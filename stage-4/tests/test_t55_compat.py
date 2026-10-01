import threading
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


class TestT55CompatReplay(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")
        self.op = login(self.port, "op@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def batch(self, items, key):
        return base.request(self.port, "POST", "/correction-batches",
                            body={"corrections": items},
                            headers={**self.op, "Idempotency-Key": key})

    def item(self, payment_id, amount, expected_revision=1, effective_at=T_NOON):
        return {"payment_id": payment_id, "expected_revision": expected_revision,
                "amount": amount, "effective_at": effective_at, "reason": "reversal"}

    def pay(self, from_headers, key, to_handle, amount, note="n"):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": to_handle, "amount": amount, "note": note,
            "visibility": "public"}, headers={**from_headers, "Idempotency-Key": key})
        assert status == 201, payload
        return payload["payment_id"]

    def test_creation_receipt_shows_original_amount_after_batch(self):
        status, creation, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500, "note": "lunch", "visibility": "public"},
            headers={**self.ada, "Idempotency-Key": "k-pay"})
        self.assertEqual(status, 201, creation)
        payment_id = creation["payment_id"]
        status, payload, _ = self.batch([self.item(payment_id, 300)], "k-corr")
        self.assertEqual(status, 201, payload)
        payment = next(p for p in state_module.STATE.payments if p.id == payment_id)
        self.assertEqual(len(payment.revisions), 2)
        self.assertEqual(payment.revisions[0].amount, 500)
        self.assertEqual(creation["amount"], 500)
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        entry = next(p for p in feed["payments"] if p["payment_id"] == payment_id)
        self.assertEqual(entry["amount"], 500)
        status, statement, _ = base.request(self.port, "GET", "/statement",
                                            headers=self.ada)
        entry = next(e for e in statement["entries"]
                     if e["payment"]["payment_id"] == payment_id)
        self.assertEqual(entry["payment"]["amount"], 300)
        self.assertEqual(entry["revision"], 2)

    def test_original_write_replays_return_original_bodies(self):
        status, pay_body, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500, "note": "lunch", "visibility": "public"},
            headers={**self.ada, "Idempotency-Key": "k-pay"})
        self.assertEqual(status, 201, pay_body)
        payment_id = pay_body["payment_id"]

        status, req_body, _ = base.request(self.port, "POST", "/requests", body={
            "payer_handle": "bob", "amount": 150, "note": "taxi"},
            headers={**self.cy, "Idempotency-Key": "k-req"})
        self.assertEqual(status, 201, req_body)
        request_id = req_body["request_id"]
        status, payreq_body, _ = base.request(self.port, "POST",
                                              f"/requests/{request_id}/pay", body=None,
                                              headers={**self.bob,
                                                       "Idempotency-Key": "k-pay-req"})
        self.assertEqual(status, 201, payreq_body)
        request_payment_id = payreq_body["payment_id"]

        status, split_body, _ = base.request(self.port, "POST", "/splits", body={
            "amount": 90, "note": "dinner", "participant_handles": ["ada", "bob", "cy"]},
            headers={**self.ada, "Idempotency-Key": "k-split"})
        self.assertEqual(status, 201, split_body)
        split_request_id = split_body["requests"][0]["request_id"]
        status, splitpay_body, _ = base.request(self.port, "POST",
                                                f"/requests/{split_request_id}/pay",
                                                body=None,
                                                headers={**self.bob,
                                                         "Idempotency-Key": "k-split-pay"})
        self.assertEqual(status, 201, splitpay_body)
        split_payment_id = splitpay_body["payment_id"]

        status, settle_body, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, settle_body)
        settle_member = settle_body["payments"][0]["payment_id"]

        targets = [payment_id, request_payment_id, split_payment_id, settle_member]
        status, payload, _ = self.batch(
            [self.item(t, expected_revision=1, amount=100) for t in targets], "k-corr")
        self.assertEqual(status, 201, payload)

        status, replay, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500, "note": "lunch", "visibility": "public"},
            headers={**self.ada, "Idempotency-Key": "k-pay"})
        self.assertEqual(status, 200)
        self.assertEqual(replay, pay_body)
        status, replay, _ = base.request(self.port, "POST",
                                         f"/requests/{request_id}/pay", body=None,
                                         headers={**self.bob,
                                                  "Idempotency-Key": "k-pay-req"})
        self.assertEqual(status, 200)
        self.assertEqual(replay, payreq_body)
        status, replay, _ = base.request(self.port, "POST", "/splits", body={
            "amount": 90, "note": "dinner", "participant_handles": ["ada", "bob", "cy"]},
            headers={**self.ada, "Idempotency-Key": "k-split"})
        self.assertEqual(status, 200)
        self.assertEqual(replay, split_body)
        status, replay, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 200)
        self.assertEqual(replay, settle_body)

    def test_statement_frozen_snapshot_vs_new_revisions(self):
        payment_id = self.pay(self.ada, "k-pay", "bob", 500)
        status, before, _ = base.request(self.port, "GET", "/statement?limit=200",
                                         headers=self.bob)
        self.assertEqual(status, 200, before)
        token = before["snapshot"]
        status, payload, _ = self.batch([self.item(payment_id, 300)], "k-corr")
        self.assertEqual(status, 201, payload)
        status, page1, _ = base.request(self.port, "GET",
                                        f"/statement?snapshot={token}&limit=200",
                                        headers=self.bob)
        self.assertEqual(status, 200, page1)
        self.assertEqual(page1["entries"], before["entries"])
        self.assertEqual(page1["opening_balance"], before["opening_balance"])
        self.assertEqual(page1["closing_balance"], before["closing_balance"])
        status, after, _ = base.request(self.port, "GET", "/statement?limit=200",
                                        headers=self.bob)
        self.assertEqual(status, 200)
        self.assertNotEqual(after["entries"], before["entries"])
        entry = next(e for e in after["entries"]
                     if e["payment"]["payment_id"] == payment_id)
        self.assertEqual((entry["payment"]["amount"], entry["revision"]), (300, 2))

    def test_batch_replay_after_export_import_round_trip(self):
        payment_id = self.pay(self.ada, "k-pay", "bob", 500)
        body = {"corrections": [self.item(payment_id, 300)]}
        status, first, _ = base.request(self.port, "POST", "/correction-batches",
                                        body=body,
                                        headers={**self.op, "Idempotency-Key": "k-corr"})
        self.assertEqual(status, 201, first)
        status, replay, _ = base.request(self.port, "POST", "/correction-batches",
                                         body=body,
                                         headers={**self.op, "Idempotency-Key": "k-corr"})
        self.assertEqual(status, 200)
        self.assertEqual(replay, first)

        status, exported, _ = base.request(self.port, "GET", "/_test/export",
                                           headers=self.ada)
        self.assertEqual(status, 200)
        status, _, _ = base.request(self.port, "POST", "/_test/import",
                                    body=exported, headers=self.ada)
        self.assertEqual(status, 204)
        status, replay, _ = base.request(self.port, "POST", "/correction-batches",
                                         body=body,
                                         headers={**self.op, "Idempotency-Key": "k-corr"})
        self.assertEqual(status, 200)
        self.assertEqual(replay, first)

    def test_refund_of_settlement_member_leaves_settlement_untouched(self):
        status, settle_body, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200,
                           "note": "share"}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, settle_body)
        member_id = settle_body["payments"][0]["payment_id"]
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{member_id}/refunds",
                                          body={"amount": 120},
                                          headers={**self.cy,
                                                   "Idempotency-Key": "k-refund"})
        self.assertEqual(status, 201, payload)
        settlement = next(iter(state_module.STATE.settlements.values()))
        self.assertEqual(settlement.payment_ids, [member_id])
        self.assertEqual(settlement.transfers,
                         [{"from_handle": "ada", "to_handle": "cy", "amount": 200,
                           "note": "share"}])
        member = next(p for p in state_module.STATE.payments if p.id == member_id)
        self.assertEqual(len(member.revisions), 1)

    def test_concurrent_same_revision_single_vs_batch(self):
        payment_id = self.pay(self.ada, "k-pay", "bob", 500)
        barrier = threading.Barrier(2)
        results = []

        def single():
            barrier.wait()
            status, payload, _ = base.request(
                self.port, "POST", f"/payments/{payment_id}/corrections",
                body={"expected_revision": 1, "amount": 400, "effective_at": T_NOON,
                      "reason": "single"},
                headers={**self.ada, "Idempotency-Key": "k-race-single"})
            results.append(status)

        def batched():
            barrier.wait()
            status, payload, _ = self.batch([self.item(payment_id, 300)], "k-race-batch")
            results.append(status)

        threads = [threading.Thread(target=single), threading.Thread(target=batched)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), [201, 409])
        payment = next(p for p in state_module.STATE.payments if p.id == payment_id)
        self.assertEqual(len(payment.revisions), 2)

    def test_concurrent_two_batches_same_revision(self):
        p1 = self.pay(self.ada, "k-p1", "bob", 500)
        p2 = self.pay(self.ada, "k-p2", "bob", 400)
        barrier = threading.Barrier(2)
        results = []

        def batched(key, amount):
            barrier.wait()
            status, payload, _ = self.batch(
                [self.item(p1, amount), self.item(p2, amount)], key)
            results.append(status)

        threads = [threading.Thread(target=batched, args=("k-batch-a", 300)),
                   threading.Thread(target=batched, args=("k-batch-b", 200))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), [201, 409])
        payment = next(p for p in state_module.STATE.payments if p.id == p1)
        self.assertEqual(len(payment.revisions), 2)


if __name__ == "__main__":
    unittest.main()