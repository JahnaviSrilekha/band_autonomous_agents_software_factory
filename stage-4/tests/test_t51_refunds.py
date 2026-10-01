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


class TestT51Refunds(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def pay(self, from_headers, key, to_handle="bob", amount=500, note="lunch",
            visibility="public"):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": to_handle, "amount": amount, "note": note,
            "visibility": visibility}, headers={**from_headers, "Idempotency-Key": key})
        assert status == 201, payload
        return payload

    def refund(self, payment_id, body=None, headers=None, key="k-refund-1"):
        return base.request(self.port, "POST", f"/payments/{payment_id}/refunds",
                            body={"amount": 200} if body is None else body,
                            headers={**(headers or self.bob), "Idempotency-Key": key})

    def get_payment_from_activity(self, payment_id):
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        assert status == 200, feed
        return next(p for p in feed["payments"] if p["payment_id"] == payment_id)

    def test_missing_idempotency_key_400(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{payment_id}/refunds",
                                          body={"amount": 200}, headers=self.bob)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_idempotency_key")

    def test_missing_token_401_before_missing_key_400(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{payment_id}/refunds",
                                          body={"amount": 200})
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "unauthenticated")
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{payment_id}/refunds",
                                          body={"amount": 200},
                                          headers={"Authorization": "Bearer bogus"})
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "unauthenticated")

    def test_empty_idempotency_key_400(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, payload, _ = self.refund(payment_id, key="")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_idempotency_key")

    def test_unknown_payment_404(self):
        status, payload, _ = self.refund("p_nope")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_non_receiver_sender_403(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, payload, _ = self.refund(payment_id, headers=self.ada, key="k-r-sender")
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_non_receiver_third_party_public_403(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, payload, _ = self.refund(payment_id, headers=self.cy, key="k-r-third")
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_invisible_private_payment_404_before_403(self):
        payment_id = self.pay(self.ada, "k-pay-priv", visibility="private")["payment_id"]
        status, payload, _ = self.refund(payment_id, headers=self.cy, key="k-r-priv")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_refund_of_refund_422(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, first, _ = self.refund(payment_id, body={"amount": 100},
                                       key="k-r-first")
        self.assertEqual(status, 201, first)
        status, payload, _ = self.refund(first["payment_id"], body={"amount": 50},
                                         headers=self.ada, key="k-r-second")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "invalid_refund_target")

    def test_amount_validation(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        huge_id = self.pay(self.ada, "k-pay-huge", amount=1000000000)["payment_id"]
        cases = [(None, 422, "validation_failed", payment_id),      # missing
                 ("500", 400, "malformed_request", payment_id),     # wrong type
                 (True, 400, "malformed_request", payment_id),      # wrong type
                 (0, 422, "validation_failed", payment_id),         # out of range
                 (-5, 422, "validation_failed", payment_id),
                 (1.5, 422, "validation_failed", payment_id),
                 (1000000001, 422, "validation_failed", payment_id),
                 (1, 201, None, payment_id),
                 (1000000000, 201, None, huge_id)]
        for value, expected_status, expected_code, target in cases:
            body = {} if value is None else {"amount": value}
            status, payload, _ = self.refund(target, body=body,
                                             key=f"k-r-amt-{expected_status}-{value!r}")
            self.assertEqual(status, expected_status, repr(value))
            if expected_code is not None:
                self.assertEqual(payload["error"]["code"], expected_code, repr(value))

    def test_refund_exceeds_payment_cumulative_422(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, _, _ = self.refund(payment_id, body={"amount": 400}, key="k-r-400")
        self.assertEqual(status, 201)
        status, payload, _ = self.refund(payment_id, body={"amount": 200},
                                         key="k-r-over")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "refund_exceeds_payment")
        status, payload, _ = self.refund(payment_id, body={"amount": 100},
                                         key="k-r-exact")
        self.assertEqual(status, 201, payload)
        payment = next(p for p in state_module.STATE.payments if p.id == payment_id)
        self.assertEqual(sum(p.amount for p in state_module.STATE.payments
                             if p.refund_of == payment_id), 500)

    def test_refund_cap_uses_current_corrected_amount(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, _, _ = base.request(self.port, "POST",
                                    f"/payments/{payment_id}/corrections",
                                    body={"expected_revision": 1, "amount": 300,
                                          "effective_at": "2026-09-20T12:00:00+00:00",
                                          "reason": "adjust"},
                                    headers={**self.ada, "Idempotency-Key": "k-corr"})
        self.assertEqual(status, 201)
        status, payload, _ = self.refund(payment_id, body={"amount": 301},
                                         key="k-r-over-corrected")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "refund_exceeds_payment")
        status, payload, _ = self.refund(payment_id, body={"amount": 300},
                                         key="k-r-under-corrected")
        self.assertEqual(status, 201, payload)

    def test_successful_refund_201_shape(self):
        payment_id = self.pay(self.ada, "k-pay-1", note="lunch",
                              visibility="private")["payment_id"]
        status, payload, _ = self.refund(payment_id, body={"amount": 200})
        self.assertEqual(status, 201)
        self.assertEqual(payload["from_user_id"], "u_bob")
        self.assertEqual(payload["to_user_id"], "u_ada")
        self.assertEqual(payload["refund_of"], payment_id)
        self.assertIsNone(payload["request_id"])
        self.assertIsNone(payload["authorization_id"])
        self.assertEqual(payload["note"], "lunch")
        self.assertEqual(payload["visibility"], "private")
        self.assertEqual(payload["amount"], 200)

    def test_replay_same_key_body_200_identical(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, first, _ = self.refund(payment_id, body={"amount": 200})
        self.assertEqual(status, 201)
        status, replay, _ = self.refund(payment_id, body={"amount": 200})
        self.assertEqual(status, 200)
        self.assertEqual(replay, first)

    def test_different_body_same_key_409(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, _, _ = self.refund(payment_id, body={"amount": 200})
        self.assertEqual(status, 201)
        status, payload, _ = self.refund(payment_id, body={"amount": 100},
                                         key="k-refund-1")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "idempotency_key_reuse")

    def test_balances_move_atomically(self):
        payment_id = self.pay(self.ada, "k-pay-1", amount=500)["payment_id"]
        bob_before = state_module.STATE.users["u_bob"].balance
        ada_before = state_module.STATE.users["u_ada"].balance
        status, _, _ = self.refund(payment_id, body={"amount": 200})
        self.assertEqual(status, 201)
        self.assertEqual(state_module.STATE.users["u_bob"].balance, bob_before - 200)
        self.assertEqual(state_module.STATE.users["u_ada"].balance, ada_before + 200)

    def test_insufficient_available_funds_409_then_recoverable(self):
        payment_id = self.pay(self.ada, "k-pay-1", amount=500)["payment_id"]
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "cy", "amount": 2800, "note": "hold"},
            headers={**self.bob, "Idempotency-Key": "k-hold"})
        self.assertEqual(status, 201, payload)
        status, payload, _ = self.refund(payment_id, body={"amount": 500},
                                         key="k-r-insufficient")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")
        record_key = ("u_bob", "POST", f"/payments/{payment_id}/refunds",
                      "k-r-insufficient")
        self.assertNotIn(record_key, state_module.STATE.idempotency)
        void_auth = next(iter(state_module.STATE.authorizations.values()))
        status, _, _ = base.request(self.port, "POST",
                                    f"/authorizations/{void_auth.id}/void",
                                    body=None, headers=self.bob)
        self.assertEqual(status, 200)
        status, payload, _ = self.refund(payment_id, body={"amount": 500},
                                         key="k-r-insufficient")
        self.assertEqual(status, 201, payload)

    def test_refund_leaves_request_and_authorization_untouched(self):
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
        status, payload, _ = self.refund(request_payment_id, body={"amount": 150},
                                         headers=self.cy, key="k-r-req")
        self.assertEqual(status, 201, payload)
        request = state_module.STATE.requests[request_id]
        self.assertEqual(request.status, "paid")
        self.assertEqual(request.payment_id, request_payment_id)

        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 300, "note": "hold"},
            headers={**self.ada, "Idempotency-Key": "k-auth"})
        self.assertEqual(status, 201, payload)
        auth_id = payload["authorization_id"]
        status, payload, _ = base.request(self.port, "POST",
                                          f"/authorizations/{auth_id}/capture",
                                          body={"amount": 100},
                                          headers={**self.bob, "Idempotency-Key": "k-cap"})
        self.assertEqual(status, 201, payload)
        capture_id = payload["payment_id"]
        auth_before = state_module.STATE.authorizations[auth_id]
        captured = (auth_before.status, auth_before.captured_amount,
                    list(auth_before.payment_ids))
        status, payload, _ = self.refund(capture_id, body={"amount": 40},
                                         key="k-r-cap")
        self.assertEqual(status, 201, payload)
        auth_after = state_module.STATE.authorizations[auth_id]
        self.assertEqual((auth_after.status, auth_after.captured_amount,
                          list(auth_after.payment_ids)), captured)
        self.assertEqual(auth_after.status, "captured")

    def test_refund_of_settlement_member_succeeds(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200,
                           "note": "share"}]},
            headers={**self.ada, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        member_id = payload["payments"][0]["payment_id"]
        status, payload, _ = self.refund(member_id, body={"amount": 200},
                                         headers=self.cy, key="k-r-settle")
        self.assertEqual(status, 201, payload)
        settlement = next(iter(state_module.STATE.settlements.values()))
        self.assertEqual(settlement.payment_ids, [member_id])
        member = next(p for p in state_module.STATE.payments if p.id == member_id)
        self.assertIsNone(member.refund_of)

    def test_refund_of_visible_on_every_representation(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        creation = self.get_payment_from_activity(payment_id)
        self.assertIsNone(creation["refund_of"])
        status, payload, _ = self.refund(payment_id, body={"amount": 200})
        self.assertEqual(status, 201)
        refund_id = payload["payment_id"]
        self.assertEqual(payload["refund_of"], payment_id)
        status, replay, _ = self.refund(payment_id, body={"amount": 200})
        self.assertEqual(status, 200)
        self.assertEqual(replay["refund_of"], payment_id)
        entry = self.get_payment_from_activity(refund_id)
        self.assertEqual(entry["refund_of"], payment_id)
        status, statement, _ = base.request(self.port, "GET", "/statement",
                                            headers=self.ada)
        self.assertEqual(status, 200)
        found = [entry for entry in statement["entries"]
                 if isinstance(entry.get("payment"), dict)
                 and entry["payment"].get("payment_id") == refund_id]
        self.assertTrue(found, statement)
        self.assertEqual(found[0]["payment"]["refund_of"], payment_id)

    def test_refund_idempotency_record_stored(self):
        payment_id = self.pay(self.ada, "k-pay-1")["payment_id"]
        status, _, _ = self.refund(payment_id, body={"amount": 200})
        self.assertEqual(status, 201)
        record_key = ("u_bob", "POST", f"/payments/{payment_id}/refunds", "k-refund-1")
        self.assertIn(record_key, state_module.STATE.idempotency)


if __name__ == "__main__":
    unittest.main()