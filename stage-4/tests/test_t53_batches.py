import unittest

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "settlement_operator_ids": ["u_op"],
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 2000000000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 800},
        {"id": "u_op", "email": "op@example.com", "password": "correct horse",
         "display_name": "Op", "handle": "op", "balance": 100},
    ],
}

ITEM = {"payment_id": None, "expected_revision": 1, "amount": 0,
        "effective_at": "2026-09-20T12:00:00+00:00", "reason": "reversal"}


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT53CorrectionBatches(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")
        self.op = login(self.port, "op@example.com")
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500, "note": "lunch",
            "visibility": "public"}, headers={**self.ada, "Idempotency-Key": "k-pay-1"})
        assert status == 201, payload
        self.payment_id = payload["payment_id"]
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "cy", "amount": 300, "note": "fee",
            "visibility": "public"}, headers={**self.ada, "Idempotency-Key": "k-pay-2"})
        assert status == 201, payload
        self.payment_id_2 = payload["payment_id"]

    def tearDown(self):
        base.stop_server(self.httpd)

    def batch(self, body, headers=None, key="k-batch-1"):
        return base.request(self.port, "POST", "/correction-batches", body=body,
                            headers={**(headers or self.op), "Idempotency-Key": key})

    def item(self, payment_id, **overrides):
        item = {**ITEM, "payment_id": payment_id, **overrides}
        if item["amount"] is None and "amount" not in overrides:
            del item["amount"]
        return item

    def test_missing_idempotency_key_400(self):
        status, payload, _ = base.request(self.port, "POST", "/correction-batches",
                                          body={"corrections": []}, headers=self.op)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_idempotency_key")

    def test_no_token_401(self):
        status, payload, _ = base.request(self.port, "POST", "/correction-batches",
                                          body={"corrections": []},
                                          headers={"Idempotency-Key": "k-x"})
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "unauthenticated")

    def test_non_operator_403_before_body_validation(self):
        status, payload, _ = self.batch({"corrections": "not-an-array"},
                                        headers=self.ada, key="k-nonop")
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_non_array_corrections_422(self):
        for value in (None, "x", {}, 5):
            body = {} if value is None else {"corrections": value}
            status, payload, _ = self.batch(body, key=f"k-shape-{type(value).__name__}")
            self.assertEqual(status, 422, repr(value))
            self.assertEqual(payload["error"]["code"], "validation_failed", repr(value))

    def test_item_count_bounds_422(self):
        status, payload, _ = self.batch({"corrections": []}, key="k-count-0")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")
        items = [self.item(self.payment_id, amount=100) for _ in range(33)]
        status, payload, _ = self.batch({"corrections": items}, key="k-count-33")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_duplicate_payment_ids_422(self):
        items = [self.item(self.payment_id, amount=100),
                 self.item(self.payment_id, amount=200)]
        status, payload, _ = self.batch({"corrections": items}, key="k-dup")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_duplicate_wins_over_later_item_field_errors(self):
        items = [self.item(self.payment_id, amount=100),
                 self.item(self.payment_id, expected_revision=9)]
        status, payload, _ = self.batch({"corrections": items}, key="k-dup-first")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_per_item_field_errors_first_item_in_input_order(self):
        bad = self.item(self.payment_id_2, expected_revision=0)
        good = self.item(self.payment_id, amount=100)
        status, payload, _ = self.batch({"corrections": [bad, good]}, key="k-order-1")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")
        status, payload, _ = self.batch({"corrections": [good, bad]}, key="k-order-2")
        self.assertEqual(status, 422)

    def test_unknown_payment_404_first_offender(self):
        good = self.item(self.payment_id, amount=100)
        unknown = self.item("p_nope", amount=100)
        status, payload, _ = self.batch({"corrections": [good, unknown]},
                                        key="k-404-1")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")
        status, payload, _ = self.batch({"corrections": [unknown, good]},
                                        key="k-404-2")
        self.assertEqual(status, 404)

    def test_stale_revision_409_first_offender(self):
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{self.payment_id}/corrections",
                                          body={"expected_revision": 1, "amount": 400,
                                                "effective_at": "2026-09-20T12:00:00+00:00",
                                                "reason": "first"},
                                          headers={**self.ada, "Idempotency-Key": "k-pre"})
        self.assertEqual(status, 201, payload)
        good = self.item(self.payment_id, expected_revision=2, amount=450)
        stale = self.item(self.payment_id_2, expected_revision=9, amount=100)
        status, payload, _ = self.batch({"corrections": [good, stale]},
                                        key="k-stale-1")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "stale_revision")
        status, payload, _ = self.batch({"corrections": [stale, good]},
                                        key="k-stale-2")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "stale_revision")

    def test_field_shape_errors(self):
        cases = [
            ({"expected_revision": True}, 400, "malformed_request"),
            ({"amount": "0"}, 400, "malformed_request"),
            ({"amount": -1}, 422, "validation_failed"),
            ({"effective_at": "2026-09-20"}, 422, "validation_failed"),
            ({"reason": ""}, 422, "validation_failed"),
        ]
        for overrides, expected_status, expected_code in cases:
            item = self.item(self.payment_id, **overrides)
            status, payload, _ = self.batch({"corrections": [item]},
                                            key=f"k-field-{overrides}")
            self.assertEqual(status, expected_status, repr(overrides))
            self.assertEqual(payload["error"]["code"], expected_code, repr(overrides))

    def test_missing_item_fields_422(self):
        for field in ("expected_revision", "amount", "effective_at", "reason"):
            item = self.item(self.payment_id)
            del item[field]
            status, payload, _ = self.batch({"corrections": [item]},
                                            key=f"k-miss-{field}")
            self.assertEqual(status, 422, field)
            self.assertEqual(payload["error"]["code"], "validation_failed", field)

    def test_operator_can_correct_non_sender_payments(self):
        # op is neither party of either payment; both a plain payment and a
        # settlement member are correctable through the batch endpoint
        status, payload, _ = self.batch({"corrections": [
            self.item(self.payment_id, amount=450),
            self.item(self.payment_id_2, amount=250)]}, key="k-nonsender")
        self.assertEqual(status, 201, payload)
        self.assertEqual([r["amount"] for r in payload["revisions"]], [450, 250])

    def test_batch_can_correct_settlement_member(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200,
                           "note": "share"}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        member_id = payload["payments"][0]["payment_id"]
        status, payload, _ = self.batch({"corrections": [
            self.item(member_id, amount=150)]}, key="k-member")
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["revisions"][0]["amount"], 150)

    def test_batch_cannot_correct_capture_or_refund(self):
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
        status, payload, _ = self.batch({"corrections": [
            self.item(capture_id, amount=100)]}, key="k-immutable-capture")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "linked_payment_immutable")

        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{self.payment_id}/refunds",
                                          body={"amount": 100},
                                          headers={**self.bob, "Idempotency-Key": "k-ref"})
        self.assertEqual(status, 201, payload)
        refund_id = payload["payment_id"]
        status, payload, _ = self.batch({"corrections": [
            self.item(refund_id, amount=50)]}, key="k-immutable-refund")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "linked_payment_immutable")

    def test_unknown_item_fields_ignored(self):
        item = {**self.item(self.payment_id, amount=400),
                "unexpected": "value", "note": "nope"}
        body = {"corrections": [item], "unexpected_top": True}
        status, payload, _ = self.batch(body, key="k-unknown-fields")
        self.assertEqual(status, 201, payload)

    def test_successful_batch_201_shape(self):
        status, payload, _ = self.batch({"corrections": [
            self.item(self.payment_id, amount=450, reason="reversal"),
            self.item(self.payment_id_2, amount=250)]}, key="k-ok")
        self.assertEqual(status, 201)
        self.assertEqual(set(payload.keys()),
                         {"correction_batch_id", "recorded_at", "revisions"})
        self.assertIsInstance(payload["correction_batch_id"], str)
        self.assertTrue(payload["correction_batch_id"].startswith("cb_"))
        self.assertEqual(len(payload["revisions"]), 2)
        self.assertEqual([r["payment_id"] for r in payload["revisions"]],
                         [self.payment_id, self.payment_id_2])
        for revision in payload["revisions"]:
            self.assertEqual(set(revision.keys()),
                             {"payment_id", "revision", "amount", "effective_at",
                              "recorded_at", "reason", "correction_batch_id"})
            self.assertEqual(revision["correction_batch_id"],
                             payload["correction_batch_id"])
        self.assertEqual([r["reason"] for r in payload["revisions"]],
                         ["reversal", "reversal"])

    def test_shared_recorded_at_strictly_later(self):
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{self.payment_id}/corrections",
                                          body={"expected_revision": 1, "amount": 400,
                                                "effective_at": "2026-09-20T12:00:00+00:00",
                                                "reason": "pre"},
                                          headers={**self.ada, "Idempotency-Key": "k-pre"})
        self.assertEqual(status, 201, payload)
        prior = payload["recorded_at"]
        status, payload, _ = self.batch({"corrections": [
            self.item(self.payment_id, expected_revision=2, amount=450),
            self.item(self.payment_id_2, amount=250)]}, key="k-shared")
        self.assertEqual(status, 201, payload)
        recorded = [r["recorded_at"] for r in payload["revisions"]]
        self.assertEqual(len(set(recorded)), 1)
        self.assertEqual(recorded[0], payload["recorded_at"])
        self.assertGreater(payload["recorded_at"], prior)
        for payment_id in (self.payment_id, self.payment_id_2):
            payment = next(p for p in state_module.STATE.payments if p.id == payment_id)
            latest = payment.revisions[-1]
            self.assertEqual(latest.recorded_at, payload["recorded_at"])
            self.assertIsNotNone(latest.correction_batch_id)
        first = next(p for p in state_module.STATE.payments if p.id == self.payment_id)
        self.assertIsNone(first.revisions[0].correction_batch_id)
        self.assertIsNone(first.revisions[1].correction_batch_id)

    def test_future_effective_at_422(self):
        item = self.item(self.payment_id, amount=100,
                         effective_at="2099-01-01T00:00:00+00:00")
        status, payload, _ = self.batch({"corrections": [item]}, key="k-future")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_replay_same_key_body_200(self):
        body = {"corrections": [self.item(self.payment_id, amount=450)]}
        status, first, _ = self.batch(body, key="k-replay")
        self.assertEqual(status, 201)
        status, replay, _ = self.batch(body, key="k-replay")
        self.assertEqual(status, 200)
        self.assertEqual(replay, first)

    def test_rejected_batch_leaves_state_untouched(self):
        before_bob = state_module.STATE.users["u_bob"].balance
        before_cy = state_module.STATE.users["u_cy"].balance
        item = self.item(self.payment_id, amount=100,
                         effective_at="2099-01-01T00:00:00+00:00")
        status, payload, _ = self.batch({"corrections": [item]}, key="k-rejected")
        self.assertEqual(status, 422)
        self.assertEqual(state_module.STATE.users["u_bob"].balance, before_bob)
        self.assertEqual(state_module.STATE.users["u_cy"].balance, before_cy)
        payment = next(p for p in state_module.STATE.payments if p.id == self.payment_id)
        self.assertEqual(len(payment.revisions), 1)
        self.assertNotIn(("u_op", "POST", "/correction-batches", "k-rejected"),
                         state_module.STATE.idempotency)


if __name__ == "__main__":
    unittest.main()