import copy
import unittest

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
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
}


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT46Snapshots(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def first_read(self, query="", headers=None):
        status, payload, _ = base.request(self.port, "GET", f"/statement{query}",
                                          headers=headers or self.ada)
        self.assertEqual(status, 200, payload)
        self.assertIn("snapshot", payload)
        return payload, payload["snapshot"]

    def page(self, token, query="", headers=None):
        sep = "&" if query else ""
        return base.request(self.port, "GET",
                            f"/statement?snapshot={token}{sep}{query}",
                            headers=headers or self.ada)

    def test_first_read_returns_token_and_pages_frozen_result(self):
        payload, token = self.first_read("?from=2026-08-01T00:00:00%2B00:00")
        self.assertEqual([entry["payment"]["payment_id"] for entry in payload["entries"]],
                         ["p_a1"])
        status, paged, _ = self.page(token, "limit=50&offset=0")
        self.assertEqual(status, 200)
        self.assertNotIn("snapshot", paged)
        self.assertEqual(paged["entries"], payload["entries"])
        self.assertEqual(paged["opening_balance"], payload["opening_balance"])
        self.assertEqual(paged["closing_balance"], payload["closing_balance"])

    def test_snapshot_frozen_after_payments_and_corrections(self):
        payload, token = self.first_read()
        status, _, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 700},
            headers={**self.ada, "Idempotency-Key": "k-after"})
        self.assertEqual(status, 201)
        status, _, _ = base.request(
            self.port, "POST", "/payments/p_a1/corrections",
            body={"expected_revision": 1, "amount": 100,
                  "effective_at": "2026-08-05T00:00:00+00:00", "reason": "later fix"},
            headers={**self.ada, "Idempotency-Key": "k-corr"})
        self.assertEqual(status, 201)
        status, paged, _ = self.page(token)
        self.assertEqual(status, 200)
        self.assertEqual(paged["entries"], payload["entries"])
        self.assertEqual(paged["closing_balance"], payload["closing_balance"])
        self.assertEqual(paged["opening_balance"], payload["opening_balance"])

    def test_live_window_reflects_correction_after_snapshot(self):
        payload, _token = self.first_read("?from=2026-08-10T09:00:00%2B00:00")
        self.assertEqual([entry["payment"]["payment_id"] for entry in payload["entries"]],
                         ["p_a1"])
        status, _, _ = base.request(
            self.port, "POST", "/payments/p_a1/corrections",
            body={"expected_revision": 1, "amount": 100,
                  "effective_at": "2026-08-05T00:00:00+00:00", "reason": "backdate"},
            headers={**self.ada, "Idempotency-Key": "k-back"})
        self.assertEqual(status, 201)
        status, live, _ = base.request(
            self.port, "GET", "/statement?from=2026-08-10T09:00:00%2B00:00",
            headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(live["entries"], [])
        self.assertEqual(live["opening_balance"], 12900)
        self.assertEqual(live["closing_balance"], 12900)

    def test_snapshot_with_from_to_known_at_422(self):
        _payload, token = self.first_read()
        for extra in ("from=2026-08-01T00:00:00%2B00:00", "to=2099-01-01T00:00:00%2B00:00",
                      "known_at=2099-01-01T00:00:00%2B00:00"):
            status, payload, _ = self.page(token, extra)
            self.assertEqual(status, 422, extra)
            self.assertEqual(payload["error"]["code"], "validation_failed", extra)

    def test_snapshot_with_as_of_is_ignored_not_422(self):
        _payload, token = self.first_read()
        status, payload, _ = self.page(token, "as_of=2020-01-01T00:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["entries"]), 1)

    def test_unknown_other_user_token_404(self):
        _payload, token = self.first_read()
        status, payload, _ = self.page("snap_nope")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")
        status, payload, _ = self.page(token, headers=self.bob)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_token_from_before_reset_404(self):
        _payload, token = self.first_read()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        self.assertEqual(status, 204)
        ada = login(self.port, "ada@example.com")
        status, payload, _ = self.page(token, headers=ada)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_paging_beyond_end_and_final_partial_page(self):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 50},
            headers={**self.ada, "Idempotency-Key": "k-two"})
        self.assertEqual(status, 201)
        payload, token = self.first_read("?from=2020-01-01T00:00:00%2B00:00&limit=1")
        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(payload["has_more"], True)
        status, page2, _ = self.page(token, "limit=1&offset=1")
        self.assertEqual(len(page2["entries"]), 1)
        self.assertEqual(page2["has_more"], False)
        status, page3, _ = self.page(token, "limit=1&offset=2")
        self.assertEqual(page3["entries"], [])
        self.assertEqual(page3["has_more"], False)
        self.assertEqual(page3["opening_balance"], payload["opening_balance"])
        self.assertEqual(page3["closing_balance"], payload["closing_balance"])

    def test_paging_does_not_mutate_state(self):
        balances_before = {uid: u.balance for uid, u in state_module.STATE.users.items()}
        payload, token = self.first_read()
        for offset in (0, 1, 5):
            self.page(token, f"limit=1&offset={offset}")
        balances_after = {uid: u.balance for uid, u in state_module.STATE.users.items()}
        self.assertEqual(balances_after, balances_before)
        status, again, _ = self.page(token)
        self.assertEqual(again["entries"], payload["entries"])

    def test_snapshot_frozen_after_authorization_lifecycle(self):
        payload, token = self.first_read()
        status, auth, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 200},
            headers={**self.ada, "Idempotency-Key": "k-auth"})
        self.assertEqual(status, 201)
        status, _, _ = base.request(self.port, "POST",
                                    f"/authorizations/{auth['authorization_id']}/void",
                                    headers=self.ada)
        self.assertEqual(status, 200)
        status, paged, _ = self.page(token)
        self.assertEqual(paged["entries"], payload["entries"])
        self.assertEqual(paged["closing_balance"], payload["closing_balance"])

    def test_statement_has_no_hold_only_events(self):
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 200},
            headers={**self.ada, "Idempotency-Key": "k-auth"})
        auth_id = payload["authorization_id"]
        base.request(self.port, "POST", f"/authorizations/{auth_id}/void",
                     headers=self.ada)
        status, live, _ = base.request(self.port, "GET", "/statement", headers=self.ada)
        ids = [entry["payment"]["payment_id"] for entry in live["entries"]]
        self.assertEqual(ids, ["p_a1"])

    def test_capture_appears_exactly_once_with_link(self):
        status, auth, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 200},
            headers={**self.ada, "Idempotency-Key": "k-auth"})
        auth_id = auth["authorization_id"]
        status, capture, _ = base.request(self.port, "POST",
                                          f"/authorizations/{auth_id}/capture",
                                          body={"amount": 200},
                                          headers={**self.bob, "Idempotency-Key": "k-cap"})
        self.assertEqual(status, 201)
        capture_id = capture["payment_id"]
        status, live, _ = base.request(self.port, "GET", "/statement?from=2020-01-01T00:00:00%2B00:00",
                                       headers=self.ada)
        matches = [entry for entry in live["entries"]
                   if entry["payment"]["payment_id"] == capture_id]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["payment"]["authorization_id"], auth_id)
        self.assertEqual(matches[0]["delta"], -200)


if __name__ == "__main__":
    unittest.main()