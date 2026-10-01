import unittest

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "settlement_operator_ids": ["u_ada"],
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 2000000000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 800},
    ],
}


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT52CorrectionExtensions(unittest.TestCase):
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

    def tearDown(self):
        base.stop_server(self.httpd)

    def correct(self, payment_id, body, headers, key):
        return base.request(self.port, "POST", f"/payments/{payment_id}/corrections",
                            body=body, headers={**headers, "Idempotency-Key": key})

    def refund(self, payment_id, amount, headers, key):
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{payment_id}/refunds",
                                          body={"amount": amount},
                                          headers={**headers, "Idempotency-Key": key})
        assert status == 201, payload
        return payload

    def test_correction_of_request_linked_payment_unchanged(self):
        status, payload, _ = base.request(self.port, "POST", "/requests", body={
            "payer_handle": "bob", "amount": 150, "note": "taxi"},
            headers={**self.cy, "Idempotency-Key": "k-req"})
        self.assertEqual(status, 201, payload)
        request_id = payload["request_id"]
        status, payload, _ = base.request(self.port, "POST",
                                          f"/requests/{request_id}/pay", body=None,
                                          headers={**self.bob, "Idempotency-Key": "k-pay-req"})
        self.assertEqual(status, 201, payload)
        request_payment_id = payload["payment_id"]
        status, payload, _ = self.correct(request_payment_id, {
            "expected_revision": 1, "amount": 100,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "adjust"},
            self.bob, "k-corr-req")
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["payment_id"], request_payment_id)
        self.assertEqual(payload["amount"], 100)

    def test_correction_of_refund_payment_422(self):
        refund = self.refund(self.payment_id, 100, self.bob, "k-refund-1")
        status, payload, _ = self.correct(refund["payment_id"], {
            "expected_revision": 1, "amount": 50,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "adjust"},
            self.bob, "k-corr-refund")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "linked_payment_immutable")

    def test_correction_of_capture_still_422(self):
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
        status, payload, _ = self.correct(capture_id, {
            "expected_revision": 1, "amount": 50,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "adjust"},
            self.ada, "k-corr-cap")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "linked_payment_immutable")

    def test_correction_of_settlement_member_still_422(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200,
                           "note": "share"}]},
            headers={**self.ada, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        member_id = payload["payments"][0]["payment_id"]
        status, payload, _ = self.correct(member_id, {
            "expected_revision": 1, "amount": 50,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "adjust"},
            self.ada, "k-corr-member")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "linked_payment_immutable")

    def test_correction_below_refunded_total_422(self):
        self.refund(self.payment_id, 400, self.bob, "k-refund-400")
        status, payload, _ = self.correct(self.payment_id, {
            "expected_revision": 1, "amount": 300,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reduce"},
            self.ada, "k-corr-below")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "refund_exceeds_payment")
        payment = next(p for p in state_module.STATE.payments if p.id == self.payment_id)
        self.assertEqual(len(payment.revisions), 1)
        status, payload, _ = self.correct(self.payment_id, {
            "expected_revision": 1, "amount": 400,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "floor"},
            self.ada, "k-corr-at-floor")
        self.assertEqual(status, 201, payload)
        status, payload, _ = self.correct(self.payment_id, {
            "expected_revision": 2, "amount": 401,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "raise"},
            self.ada, "k-corr-raise")
        self.assertEqual(status, 201, payload)

    def test_refund_floor_checked_after_staleness(self):
        self.refund(self.payment_id, 400, self.bob, "k-refund-400")
        status, payload, _ = self.correct(self.payment_id, {
            "expected_revision": 7, "amount": 300,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reduce"},
            self.ada, "k-corr-stale-floor")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "stale_revision")

    def test_refund_floor_checked_before_funds(self):
        # cy pays bob 700; bob refunds 650 (money returns to cy); bob pays the
        # rest of his money away; correcting the cy->bob payment to 40 violates
        # both the refund floor (650 > 40) and bob's current funds (0 available,
        # debit 660) — the floor check runs first.
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 700, "note": "fee", "visibility": "public"},
            headers={**self.cy, "Idempotency-Key": "k-pay-cy"})
        self.assertEqual(status, 201, payload)
        cy_payment_id = payload["payment_id"]
        self.refund(cy_payment_id, 650, self.bob, "k-refund-cy")
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "cy", "amount": 2550, "note": "sweep", "visibility": "public"},
            headers={**self.bob, "Idempotency-Key": "k-pay-sweep"})
        self.assertEqual(status, 201, payload)
        # bob still holds the setUp payment's 500 after the sweep
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 500)
        status, payload, _ = self.correct(cy_payment_id, {
            "expected_revision": 1, "amount": 40,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reduce"},
            self.cy, "k-corr-floor-funds")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "refund_exceeds_payment")
        self.assertEqual(len(next(p for p in state_module.STATE.payments
                                  if p.id == cy_payment_id).revisions), 1)

    def test_correction_funds_see_refund_balance_effect(self):
        # bob receives 500, refunds 450 back to ada, then pays 2510 away:
        # available(bob) = 40. Correcting the payment down to 450 (at the refund
        # floor, debit 50) would fail — with the pre-refund balance it would pass.
        self.refund(self.payment_id, 450, self.bob, "k-refund-450")
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "cy", "amount": 2510, "note": "sweep", "visibility": "public"},
            headers={**self.bob, "Idempotency-Key": "k-pay-sweep"})
        self.assertEqual(status, 201, payload)
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 40)
        status, payload, _ = self.correct(self.payment_id, {
            "expected_revision": 1, "amount": 450,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reduce"},
            self.ada, "k-corr-funds")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")

    def test_ordinary_correction_path_still_works_after_refund(self):
        self.refund(self.payment_id, 100, self.bob, "k-refund-100")
        status, payload, _ = self.correct(self.payment_id, {
            "expected_revision": 1, "amount": 600,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "raise"},
            self.ada, "k-corr-raise")
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["revision"], 2)
        status, payload, _ = self.correct(self.payment_id, {
            "expected_revision": 2, "amount": 500,
            "effective_at": "2026-09-20T12:00:00+00:00", "reason": "lower"},
            self.ada, "k-corr-lower")
        self.assertEqual(status, 201, payload)


if __name__ == "__main__":
    unittest.main()