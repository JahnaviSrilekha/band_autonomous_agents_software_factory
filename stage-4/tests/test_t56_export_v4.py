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

T_NOON = "2026-09-20T12:00:00+00:00"


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT56ExportV4(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")
        self.op = login(self.port, "op@example.com")
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500, "note": "lunch", "visibility": "public"},
            headers={**self.ada, "Idempotency-Key": "k-pay"})
        assert status == 201, payload
        self.payment_id = payload["payment_id"]

    def tearDown(self):
        base.stop_server(self.httpd)

    def export(self):
        status, payload, _ = base.request(self.port, "GET", "/_test/export",
                                          headers=self.ada)
        assert status == 200, payload
        return payload

    def import_payload(self, payload):
        return base.request(self.port, "POST", "/_test/import", body=payload,
                            headers=self.ada)

    def refund(self, payment_id, amount, headers, key):
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{payment_id}/refunds",
                                          body={"amount": amount},
                                          headers={**headers, "Idempotency-Key": key})
        assert status == 201, payload
        return payload

    def batch(self, items, key):
        status, payload, _ = base.request(self.port, "POST", "/correction-batches",
                                          body={"corrections": items},
                                          headers={**self.op, "Idempotency-Key": key})
        assert status == 201, payload
        return payload

    def item(self, payment_id, amount, expected_revision=1, effective_at=T_NOON):
        return {"payment_id": payment_id, "expected_revision": expected_revision,
                "amount": amount, "effective_at": effective_at, "reason": "reversal"}

    def test_export_is_v4_with_new_fields(self):
        self.refund(self.payment_id, 200, self.bob, "k-refund")
        refund_id = state_module.STATE.payments[-1].id
        batch = self.batch([self.item(self.payment_id, 400)], "k-corr")
        exported = self.export()
        self.assertEqual(exported["format_version"], 4)
        payments = {p["id"]: p for p in exported["state"]["payments"]}
        self.assertEqual(payments[self.payment_id]["refund_of"], None)
        self.assertEqual(payments[refund_id]["refund_of"], self.payment_id)
        self.assertEqual(payments[self.payment_id]["revisions"][-1]["correction_batch_id"],
                         batch["correction_batch_id"])
        self.assertEqual(payments[self.payment_id]["revisions"][0]["correction_batch_id"],
                         None)
        self.assertEqual(payments[refund_id]["revisions"][0]["correction_batch_id"], None)

    def test_v4_round_trip_preserves_refunds_and_batches(self):
        self.refund(self.payment_id, 200, self.bob, "k-refund")
        batch = self.batch([self.item(self.payment_id, 400)], "k-corr")
        status, settle_body, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 300}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, settle_body)
        member_id = settle_body["payments"][0]["payment_id"]
        self.batch([self.item(member_id, 250)], "k-corr-2")
        before_balances = {u.id: u.balance for u in state_module.STATE.users.values()}
        before_revisions = {p.id: [(r.revision, r.amount, r.effective_at, r.recorded_at,
                                    r.reason, r.correction_batch_id)
                                   for r in p.revisions]
                            for p in state_module.STATE.payments}
        exported = self.export()
        status, _, _ = self.import_payload(exported)
        self.assertEqual(status, 204)
        after_balances = {u.id: u.balance for u in state_module.STATE.users.values()}
        after_revisions = {p.id: [(r.revision, r.amount, r.recorded_at, r.reason,
                                   r.correction_batch_id)
                                  for r in p.revisions]
                           for p in state_module.STATE.payments}
        self.assertEqual(before_balances, after_balances)
        self.assertEqual(
            {pid: [(rev, amt, rec, rsn, cb) for (rev, amt, _eff, rec, rsn, cb) in revs]
             for pid, revs in before_revisions.items()},
            after_revisions)
        payments = {p.id: p for p in state_module.STATE.payments}
        refund = next(p for p in state_module.STATE.payments
                      if p.refund_of == self.payment_id)
        self.assertIsNotNone(refund)
        corrected = payments[self.payment_id]
        self.assertEqual(corrected.revisions[-1].correction_batch_id,
                         batch["correction_batch_id"])
        settlement = next(iter(state_module.STATE.settlements.values()))
        self.assertIn(member_id, settlement.payment_ids)
        member = payments[member_id]
        self.assertEqual(member.settlement_id, settlement.id)
        # replays still work after the round trip
        status, replay, _ = base.request(self.port, "POST", "/correction-batches",
                                         body={"corrections": [
                                             self.item(self.payment_id, 400)]},
                                         headers={**self.op, "Idempotency-Key": "k-corr"})
        self.assertEqual(status, 200)
        self.assertEqual(replay["correction_batch_id"], batch["correction_batch_id"])
        # corrections/refunds still work on the imported state
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{self.payment_id}/refunds",
                                          body={"amount": 100},
                                          headers={**self.bob,
                                                   "Idempotency-Key": "k-refund-2"})
        self.assertEqual(status, 201, payload)

    def test_import_v1_v2_v3_default_null_fields(self):
        import copy

        exported = self.export()
        for version in (1, 2, 3):
            payload = {"track": "pocketful", "format_version": version,
                       "state": copy.deepcopy(exported["state"])}
            if version < 3:
                payload["state"] = {k: v for k, v in payload["state"].items()
                                    if k != "authorizations"}
            for payment in payload["state"]["payments"]:
                if version < 3:
                    payment.pop("revisions", None)
                else:
                    for revision in payment["revisions"]:
                        revision.pop("correction_batch_id", None)
                payment.pop("refund_of", None)
            status, response, _ = self.import_payload(payload)
            self.assertEqual(status, 204, (version, response))
            payment = next(p for p in state_module.STATE.payments)
            self.assertIsNone(payment.refund_of)
            for revision in payment.revisions:
                self.assertIsNone(revision.correction_batch_id)

    def test_import_v3_keeps_revisions_with_null_batch_ids(self):
        self.batch([self.item(self.payment_id, 400)], "k-corr")
        exported = self.export()
        for payment in exported["state"]["payments"]:
            for revision in payment["revisions"]:
                revision.pop("correction_batch_id", None)
            payment.pop("refund_of", None)
        exported["format_version"] = 3
        status, _, _ = self.import_payload(exported)
        self.assertEqual(status, 204)
        payment = next(p for p in state_module.STATE.payments
                       if p.id == self.payment_id)
        self.assertEqual(len(payment.revisions), 2)
        self.assertIsNone(payment.revisions[1].correction_batch_id)
        self.assertIsNone(payment.refund_of)

    def test_import_unknown_refund_of_422(self):
        exported = self.export()
        state_payload = exported["state"]
        target = next(p for p in state_payload["payments"] if p["id"] == self.payment_id)
        ghost = dict(target)
        ghost["id"] = "p_ghost"
        ghost["refund_of"] = "p_missing"
        state_payload["payments"].append(ghost)
        status, response, _ = self.import_payload(exported)
        self.assertEqual(status, 422)
        self.assertEqual(response["error"]["code"], "validation_failed")

    def test_import_forward_refund_reference_422(self):
        self.refund(self.payment_id, 200, self.bob, "k-refund")
        exported = self.export()
        payments = exported["state"]["payments"]
        payments.reverse()
        status, response, _ = self.import_payload(exported)
        self.assertEqual(status, 422)
        self.assertEqual(response["error"]["code"], "validation_failed")


if __name__ == "__main__":
    unittest.main()