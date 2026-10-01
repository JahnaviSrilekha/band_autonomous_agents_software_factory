import copy
import json
import unittest

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "settlement_operator_ids": ["u_ada"],
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 4000},
    ],
    "payments": [
        {"id": "p_a1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 3000, "created_at": "2026-08-10T09:00:00+00:00"},
    ],
    "authorizations": [
        {"id": "a_hold", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 2000, "status": "open",
         "created_at": "2026-08-01T09:00:00+00:00",
         "expires_at": "2099-01-01T00:00:00+00:00"},
    ],
}


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


def build_rich_state(port):
    status, _, _ = base.request(port, "POST", "/_test/reset", body=FIXTURE)
    assert status == 204
    ada = login(port, "ada@example.com")
    bob = login(port, "bob@example.com")
    status, payload, _ = base.request(port, "POST", "/payments", body={
        "to_handle": "bob", "amount": 500}, headers={**ada, "Idempotency-Key": "k-pay"})
    assert status == 201, payload
    status, _, _ = base.request(port, "POST", "/payments/p_a1/corrections", body={
        "expected_revision": 1, "amount": 2500,
        "effective_at": "2026-08-10T09:00:00+00:00", "reason": "fix"},
        headers={**ada, "Idempotency-Key": "k-fix"})
    assert status == 201
    status, auth, _ = base.request(port, "POST", "/authorizations", body={
        "to_handle": "bob", "amount": 800}, headers={**ada, "Idempotency-Key": "k-auth"})
    assert status == 201
    status, capture, _ = base.request(port, "POST",
                                      f"/authorizations/{auth['authorization_id']}/capture",
                                      body={"amount": 800},
                                      headers={**bob, "Idempotency-Key": "k-cap"})
    assert status == 201, capture
    return ada, bob, capture["payment_id"]


class TestT47ExportV3(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def export(self):
        status, payload, _ = base.request(self.port, "GET", "/_test/export")
        assert status == 200
        return payload

    def import_payload(self, payload):
        return base.request(self.port, "POST", "/_test/import", body=payload)

    def test_export_is_v3_with_revisions(self):
        build_rich_state(self.port)
        exported = self.export()
        self.assertEqual(exported["format_version"], 3)
        payments = {p["id"]: p for p in exported["state"]["payments"]}
        self.assertEqual(payments["p_a1"]["revisions"][:1],
                         [{"revision": 1, "amount": 3000,
                           "effective_at": "2026-08-10T09:00:00+00:00",
                           "recorded_at": "2026-08-10T09:00:00+00:00", "reason": ""}])
        second = payments["p_a1"]["revisions"][1]
        self.assertEqual((second["revision"], second["amount"], second["reason"]),
                         (2, 2500, "fix"))
        self.assertEqual(second["effective_at"], "2026-08-10T09:00:00+00:00")
        self.assertGreater(second["recorded_at"], second["effective_at"])
        self.assertTrue(all("revisions" in p for p in exported["state"]["payments"]))
        self.assertNotIn("statement_snapshots", exported["state"])

    def test_v3_round_trip_is_behavioral_no_op(self):
        ada, bob, capture_id = build_rich_state(self.port)
        statements = {}
        for email in ("ada@example.com", "bob@example.com"):
            status, payload, _ = base.request(
                self.port, "GET",
                "/statement?from=2020-01-01T00:00:00%2B00:00&to=2099-01-01T00:00:00%2B00:00",
                headers=login(self.port, email))
            statements[email] = {k: v for k, v in payload.items() if k != "snapshot"}
        status, revisions_before, _ = base.request(
            self.port, "GET", "/payments/p_a1/revisions", headers=ada)
        status, me_before, _ = base.request(self.port, "GET", "/me", headers=ada)
        exported = self.export()
        status, _, _ = self.import_payload(exported)
        self.assertEqual(status, 204)
        for email, before in statements.items():
            status, payload, _ = base.request(
                self.port, "GET",
                "/statement?from=2020-01-01T00:00:00%2B00:00&to=2099-01-01T00:00:00%2B00:00",
                headers=login(self.port, email))
            after = {k: v for k, v in payload.items() if k != "snapshot"}
            self.assertEqual(after, before, email)
        status, revisions_after, _ = base.request(
            self.port, "GET", "/payments/p_a1/revisions",
            headers=login(self.port, "ada@example.com"))
        self.assertEqual(revisions_after, revisions_before)
        status, me_after, _ = base.request(self.port, "GET", "/me",
                                           headers=login(self.port, "ada@example.com"))
        self.assertEqual({k: v for k, v in me_after.items() if k not in ("user_id",)},
                         {k: v for k, v in me_before.items() if k not in ("user_id",)})
        status, capture_now, _ = base.request(
            self.port, "POST", f"/payments/{capture_id}/corrections",
            body={"expected_revision": 1, "amount": 1,
                  "effective_at": "2026-08-10T09:00:00+00:00", "reason": "x"},
            headers={**login(self.port, "ada@example.com"), "Idempotency-Key": "k-cap-corr"})
        self.assertEqual(status, 422)
        self.assertEqual(capture_now["error"]["code"], "linked_payment_immutable")

    def test_v1_and_v2_imports_synthesize_revision_1(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        self.assertEqual(status, 204)
        ada = login(self.port, "ada@example.com")
        status, _, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500}, headers={**ada, "Idempotency-Key": "k-pay"})
        self.assertEqual(status, 201)
        import urllib.request

        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/_test/export")
        with urllib.request.urlopen(req) as resp:
            exported = json.loads(resp.read())
        v2 = copy.deepcopy(exported)
        v2["format_version"] = 2
        for payment in v2["state"]["payments"]:
            payment.pop("revisions", None)
        for authorization in v2["state"]["authorizations"]:
            authorization.pop("closed_event_at", None)
        status, _, _ = self.import_payload(v2)
        self.assertEqual(status, 204)
        status, payload, _ = base.request(self.port, "GET", "/payments/p_a1/revisions",
                                          headers=ada)
        self.assertEqual(len(payload["revisions"]), 1)
        self.assertEqual(payload["revisions"][0]["revision"], 1)
        self.assertEqual(payload["revisions"][0]["amount"], 3000)
        self.assertEqual(payload["revisions"][0]["effective_at"],
                         "2026-08-10T09:00:00+00:00")
        api_payment_id = next(p["id"] for p in v2["state"]["payments"]
                              if p["authorization_id"] is None and p["id"] != "p_a1")
        status, payload, _ = base.request(self.port,
                                          "GET", f"/payments/{api_payment_id}/revisions",
                                          headers=ada)
        self.assertEqual(payload["revisions"][0]["amount"], 500)
        v1 = copy.deepcopy(v2)
        v1["format_version"] = 1
        v1["state"].pop("authorization_ttl_seconds", None)
        status, _, _ = self.import_payload(v1)
        self.assertEqual(status, 204)
        status, payload, _ = base.request(self.port, "GET", "/payments/p_a1/revisions",
                                          headers=ada)
        self.assertEqual(len(payload["revisions"]), 1)

    def test_imported_payments_support_corrections_and_historical_views(self):
        build_rich_state(self.port)
        exported = self.export()
        status, _, _ = self.import_payload(exported)
        self.assertEqual(status, 204)
        ada = login(self.port, "ada@example.com")
        status, payload, _ = base.request(self.port, "GET",
                                          "/me?as_of=2026-08-09T00:00:00%2B00:00",
                                          headers=ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 13000)
        status, payload, _ = base.request(self.port, "POST", "/payments/p_a1/corrections",
                                          body={"expected_revision": 2, "amount": 2400,
                                                "effective_at": "2026-08-10T09:00:00+00:00",
                                                "reason": "again"},
                                          headers={**ada, "Idempotency-Key": "k-again"})
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["revision"], 3)

    def test_import_invalidates_snapshot_tokens(self):
        build_rich_state(self.port)
        ada = login(self.port, "ada@example.com")
        status, statement, _ = base.request(self.port, "GET", "/statement", headers=ada)
        token = statement["snapshot"]
        exported = self.export()
        status, _, _ = self.import_payload(exported)
        self.assertEqual(status, 204)
        status, payload, _ = base.request(
            self.port, "GET", f"/statement?snapshot={token}&limit=50&offset=0",
            headers=login(self.port, "ada@example.com"))
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_unknown_format_version_422(self):
        build_rich_state(self.port)
        exported = self.export()
        for version in (0, 4, "3"):
            payload = copy.deepcopy(exported)
            payload["format_version"] = version
            status, response, _ = self.import_payload(payload)
            self.assertEqual(status, 422, version)
            self.assertEqual(response["error"]["code"], "validation_failed", version)

    def test_settlement_member_revision_uses_committed_at(self):
        build_rich_state(self.port)
        ada = login(self.port, "ada@example.com")
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100,
                           "note": "share"}]},
            headers={**ada, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        committed_at = payload["committed_at"]
        member_id = payload["payments"][0]["payment_id"]
        status, payload, _ = base.request(self.port, "GET",
                                          f"/payments/{member_id}/revisions",
                                          headers=ada)
        first = payload["revisions"][0]
        self.assertEqual(first["effective_at"], committed_at)
        self.assertEqual(first["recorded_at"], committed_at)
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{member_id}/corrections",
                                          body={"expected_revision": 1, "amount": 50,
                                                "effective_at": committed_at,
                                                "reason": "nope"},
                                          headers={**ada, "Idempotency-Key": "k-mem"})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "linked_payment_immutable")


if __name__ == "__main__":
    unittest.main()