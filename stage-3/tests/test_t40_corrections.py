import copy
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
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 800},
    ],
}

BODY = {"expected_revision": 1, "amount": 400,
        "effective_at": "2026-09-20T12:00:00+00:00", "reason": "corrected amount"}


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT40Corrections(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500, "note": "lunch",
            "visibility": "public"}, headers={**self.ada, "Idempotency-Key": "k-pay-1"})
        assert status == 201, payload
        self.payment_id = payload["payment_id"]
        self.path = f"/payments/{self.payment_id}/corrections"

    def tearDown(self):
        base.stop_server(self.httpd)

    def latest_revision(self):
        payment = next(p for p in state_module.STATE.payments if p.id == self.payment_id)
        return len(payment.revisions)

    def correct(self, body=None, headers=None, key="k-corr-1", path=None):
        return base.request(self.port, "POST", path or self.path,
                            body=BODY if body is None else body,
                            headers={**(headers or self.ada), "Idempotency-Key": key})

    def test_missing_idempotency_key_400(self):
        status, payload, _ = base.request(self.port, "POST", self.path, body=BODY,
                                          headers=self.ada)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_idempotency_key")

    def test_empty_idempotency_key_400(self):
        status, payload, _ = base.request(self.port, "POST", self.path, body=BODY,
                                          headers={**self.ada, "Idempotency-Key": ""})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_idempotency_key")

    def test_receiver_correction_403(self):
        status, payload, _ = self.correct(headers=self.bob)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_third_party_public_payment_403(self):
        status, payload, _ = self.correct(headers=self.cy)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_third_party_private_payment_404(self):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 100, "visibility": "private"},
            headers={**self.ada, "Idempotency-Key": "k-pay-priv"})
        self.assertEqual(status, 201)
        private_id = payload["payment_id"]
        status, payload, _ = self.correct(path=f"/payments/{private_id}/corrections",
                                          headers=self.cy)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_unknown_payment_404(self):
        status, payload, _ = self.correct(path="/payments/p_nope/corrections")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_missing_field_422(self):
        for field in ("expected_revision", "amount", "effective_at", "reason"):
            body = {k: v for k, v in BODY.items() if k != field}
            status, payload, _ = self.correct(body=body, key=f"k-miss-{field}")
            self.assertEqual(status, 422, field)
            self.assertEqual(payload["error"]["code"], "validation_failed", field)

    def test_expected_revision_type_and_range(self):
        for value, expected_status in (("1", 400), (True, 400), (0, 422), (-1, 422),
                                       (1.5, 422)):
            status, payload, _ = self.correct(
                body={**BODY, "expected_revision": value,
                      "amount": 400 if isinstance(value, int) and not isinstance(value, bool) else BODY["amount"]},
                key=f"k-rev-{value!r}")
            self.assertEqual(status, expected_status, repr(value))
            if expected_status == 422:
                self.assertEqual(payload["error"]["code"], "validation_failed", repr(value))
            elif expected_status == 400:
                self.assertEqual(payload["error"]["code"], "malformed_request", repr(value))

    def test_amount_type_and_range(self):
        for value, expected_status in (("400", 400), (True, 400), (-1, 422),
                                       (1000000001, 422), (1000000000, 201), (0, 201)):
            revision = self.latest_revision()
            status, payload, _ = self.correct(
                body={**BODY, "amount": value, "expected_revision": revision},
                key=f"k-amt-{expected_status}-{value!r}")
            self.assertEqual(status, expected_status, repr(value))
            if expected_status == 422:
                self.assertEqual(payload["error"]["code"], "validation_failed", repr(value))
            elif expected_status == 400:
                self.assertEqual(payload["error"]["code"], "malformed_request", repr(value))

    def test_reason_rules(self):
        for value, expected_status in ((None, 422), ("", 422), ("x" * 201, 422),
                                       (123, 422), ("x" * 200, 201), ("ok", 201)):
            body = {**BODY, "reason": value, "expected_revision": self.latest_revision()}
            status, payload, _ = self.correct(body=body,
                                              key=f"k-rsn-{expected_status}-{len(str(value))}")
            self.assertEqual(status, expected_status, repr(value))
            if expected_status == 422:
                self.assertEqual(payload["error"]["code"], "validation_failed", repr(value))

    def test_effective_at_rules(self):
        cases = [("2026-09-20T12:00:00", 422), ("2026-09-20", 422), ("", 422),
                 ("2026-09-20T12:00:00Z", 201), (5, 422),
                 ("2099-01-01T00:00:00+00:00", 422)]
        for value, expected_status in cases:
            status, payload, _ = self.correct(
                body={**BODY, "effective_at": value,
                      "expected_revision": self.latest_revision()},
                key=f"k-eff-{expected_status}-{value!r}")
            self.assertEqual(status, expected_status, repr(value))
            if expected_status == 422:
                self.assertEqual(payload["error"]["code"], "validation_failed", repr(value))

    def test_valid_correction_201_shape(self):
        status, payload, _ = self.correct()
        self.assertEqual(status, 201)
        self.assertEqual(set(payload.keys()), {"payment_id", "revision", "amount",
                                               "effective_at", "recorded_at", "reason"})
        self.assertEqual(payload["payment_id"], self.payment_id)
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["amount"], 400)
        self.assertEqual(payload["effective_at"], "2026-09-20T12:00:00+00:00")
        self.assertEqual(payload["reason"], "corrected amount")
        self.assertIsInstance(payload["recorded_at"], str)

    def test_correction_preserves_parties_and_visibility(self):
        status, payload, _ = self.correct()
        self.assertEqual(status, 201)
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        entry = next(p for p in feed["payments"] if p["payment_id"] == self.payment_id)
        self.assertEqual(entry["from_user_id"], "u_ada")
        self.assertEqual(entry["to_user_id"], "u_bob")
        self.assertEqual(entry["visibility"], "public")
        payment = state_module.STATE.payments[0]
        self.assertEqual((payment.from_user_id, payment.to_user_id, payment.visibility),
                         ("u_ada", "u_bob", "public"))

    def test_replay_same_key_body_200(self):
        status, first, _ = self.correct()
        self.assertEqual(status, 201)
        status, replay, _ = self.correct()
        self.assertEqual(status, 200)
        self.assertEqual(replay, first)

    def test_different_body_same_key_409(self):
        status, first, _ = self.correct()
        self.assertEqual(status, 201)
        status, payload, _ = self.correct(body={**BODY, "amount": 350})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "idempotency_key_reuse")

    def test_stale_expected_revision_409(self):
        status, _, _ = self.correct(key="k-first")
        self.assertEqual(status, 201)
        status, payload, _ = self.correct(key="k-second")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "stale_revision")

    def test_settlement_member_correction_422(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200,
                           "note": "share"}]},
            headers={**self.ada, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        member_id = payload["payments"][0]["payment_id"]
        status, payload, _ = self.correct(path=f"/payments/{member_id}/corrections")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "linked_payment_immutable")

    def test_capture_correction_422(self):
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 300, "note": "hold"},
            headers={**self.ada, "Idempotency-Key": "k-auth"})
        self.assertEqual(status, 201, payload)
        auth_id = payload["authorization_id"]
        status, payload, _ = base.request(self.port, "POST",
                                          f"/authorizations/{auth_id}/capture",
                                          body={"amount": 300},
                                          headers={**self.bob, "Idempotency-Key": "k-cap"})
        self.assertEqual(status, 201, payload)
        capture_id = payload["payment_id"]
        status, payload, _ = self.correct(path=f"/payments/{capture_id}/corrections")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "linked_payment_immutable")


if __name__ == "__main__":
    unittest.main()