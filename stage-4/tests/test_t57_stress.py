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

SEEDED_TOTAL = sum(u["balance"] for u in FIXTURE["users"])
T_NOON = "2026-09-20T12:00:00+00:00"


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT57ConcurrencyHardening(unittest.TestCase):
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

    def pay(self, from_headers, key, to_handle, amount):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": to_handle, "amount": amount, "note": "burst",
            "visibility": "public"}, headers={**from_headers, "Idempotency-Key": key})
        assert status == 201, payload
        return payload["payment_id"]

    def batch(self, items, key):
        return base.request(self.port, "POST", "/correction-batches",
                            body={"corrections": items},
                            headers={**self.op, "Idempotency-Key": key})

    def item(self, payment_id, amount, expected_revision=1):
        return {"payment_id": payment_id, "expected_revision": expected_revision,
                "amount": amount, "effective_at": T_NOON, "reason": "reversal"}

    def historical_totals(self, as_of):
        from pocketful.state import as_dt, historical_balance

        as_of = as_dt(as_of)
        return sum(historical_balance(state_module.STATE, user_id, as_of, None)
                   for user_id in state_module.STATE.users)

    def test_fifty_in_flight_mixed_burst(self):
        # phase 1: sequential setup the burst operates on
        p_a1 = self.pay(self.ada, "k-a1", "bob", 100)
        p_a2 = self.pay(self.ada, "k-a2", "cy", 150)
        p_a3 = self.pay(self.ada, "k-a3", "bob", 200)
        p_a4 = self.pay(self.bob, "k-a4", "cy", 120)
        p_a5 = self.pay(self.cy, "k-a5", "bob", 80)
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 500}, headers={**self.ada,
                                                         "Idempotency-Key": "k-auth"})
        self.assertEqual(status, 201, payload)
        auth_id = payload["authorization_id"]
        status, payload, _ = base.request(self.port, "POST",
                                          f"/authorizations/{auth_id}/capture",
                                          body={"amount": 200},
                                          headers={**self.bob, "Idempotency-Key": "k-cap"})
        self.assertEqual(status, 201, payload)
        capture_id = payload["payment_id"]
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 100}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        p_s1 = payload["payments"][0]["payment_id"]

        barrier = threading.Barrier(50)
        results = []

        def record(status):
            results.append(status)

        def new_payment(index):
            barrier.wait()
            status, payload, _ = base.request(self.port, "POST", "/payments", body={
                "to_handle": "bob" if index % 2 == 0 else "cy", "amount": 30 + index,
                "note": "burst", "visibility": "public"},
                headers={**self.ada, "Idempotency-Key": f"b-pay-{index}"})
            record(status)

        def new_authorization(index):
            barrier.wait()
            status, payload, _ = base.request(self.port, "POST", "/authorizations",
                                              body={"to_handle": "bob", "amount": 100},
                                              headers={**self.ada,
                                                       "Idempotency-Key": f"b-auth-{index}"})
            record(status)

        def capture(index):
            barrier.wait()
            status, payload, _ = base.request(self.port, "POST",
                                              f"/authorizations/{auth_id}/capture",
                                              body={"amount": 50},
                                              headers={**self.bob,
                                                       "Idempotency-Key": f"b-cap-{index}"})
            record(status)

        def settlement(index):
            barrier.wait()
            status, payload, _ = base.request(self.port, "POST", "/settlements", body={
                "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 25}]},
                headers={**self.op, "Idempotency-Key": f"b-settle-{index}"})
            record(status)

        def correction(payment_id, amount, user, index):
            barrier.wait()
            status, payload, _ = base.request(
                self.port, "POST", f"/payments/{payment_id}/corrections",
                body={"expected_revision": 1, "amount": amount,
                      "effective_at": T_NOON, "reason": "burst"},
                headers={**user, "Idempotency-Key": f"b-corr-{index}"})
            record(status)

        def refund(payment_id, amount, user, key):
            barrier.wait()
            status, payload, _ = base.request(
                self.port, "POST", f"/payments/{payment_id}/refunds",
                body={"amount": amount},
                headers={**user, "Idempotency-Key": key})
            record(status)

        def batch(payment_id, amount, expected_revision, key):
            barrier.wait()
            status, payload, _ = self.batch(
                [self.item(payment_id, amount, expected_revision)], key)
            record(status)

        def batch_replay_group():
            barrier.wait()
            status, payload, _ = self.batch([self.item(p_a4, 90)], "b-batch-replay")
            record(status)

        def refund_replay_group():
            barrier.wait()
            status, payload, _ = base.request(
                self.port, "POST", f"/payments/{p_a1}/refunds", body={"amount": 20},
                headers={**self.bob, "Idempotency-Key": "b-refund-replay"})
            record(status)

        def statement(index):
            barrier.wait()
            status, payload, _ = base.request(
                self.port, "GET", "/statement?limit=200",
                headers=self.bob if index % 2 == 0 else self.cy)
            record(status)

        def revisions(payment_id):
            barrier.wait()
            status, payload, _ = base.request(
                self.port, "GET", f"/payments/{payment_id}/revisions",
                headers=self.ada)
            record(status)

        def activity():
            barrier.wait()
            status, payload, _ = base.request(self.port, "GET", "/activity",
                                              headers=self.ada)
            record(status)

        def me():
            barrier.wait()
            status, payload, _ = base.request(self.port, "GET", "/me", headers=self.cy)
            record(status)

        workers = []
        for index in range(8):
            workers.append((new_payment, (index,)))
        for index in range(4):
            workers.append((new_authorization, (index,)))
        for index in range(2):
            workers.append((capture, (index,)))
        for index in range(4):
            workers.append((settlement, (index,)))
        workers.append((correction, (p_a1, 80, self.ada, 10)))
        workers.append((correction, (p_a3, 180, self.ada, 11)))
        workers.append((correction, (p_a2, 120, self.ada, 12)))
        workers.append((correction, (p_s1, 60, self.ada, 13)))
        workers.append((correction, (p_a1, 80, self.ada, 14)))
        workers.append((correction, (p_a5, 60, self.cy, 15)))
        workers.append((refund, (p_a3, 30, self.bob, "b-refund-1")))
        workers.append((refund, (p_a2, 40, self.cy, "b-refund-2")))
        workers.append((refund, (capture_id, 10, self.bob, "b-refund-3")))
        workers.append((refund, (p_s1, 15, self.cy, "b-refund-4")))
        for _ in range(5):
            workers.append((refund_replay_group, ()))
        workers.append((batch, (p_a2, 90, 1, "b-batch-1")))
        workers.append((batch, (p_a3, 150, 1, "b-batch-2")))
        workers.append((batch, (p_s1, 50, 1, "b-batch-3")))
        for _ in range(5):
            workers.append((batch_replay_group, ()))
        for index in range(5):
            workers.append((statement, (index,)))
        workers.append((revisions, (p_a1,)))
        workers.append((revisions, (capture_id,)))
        workers.append((activity, ()))
        workers.append((me, ()))

        self.assertEqual(len(workers), 50, len(workers))
        threads = [threading.Thread(target=fn, args=args) for fn, args in workers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # zero 5xx anywhere in the burst
        fivehundreds = [status for status in results if status >= 500]
        self.assertEqual(fivehundreds, [])

        # identical concurrent refund under one key moved money exactly once
        one_refund = [p for p in state_module.STATE.payments if p.refund_of == p_a1]
        self.assertEqual(len(one_refund), 1)
        self.assertEqual(one_refund[0].amount, 20)

        # identical concurrent batch under one key appended exactly one revision
        p4 = next(p for p in state_module.STATE.payments if p.id == p_a4)
        batch_revisions = [r for r in p4.revisions if r.correction_batch_id is not None]
        self.assertEqual(len(batch_revisions), 1)

        # money invariants: conservation, non-negative totals and availability
        self.assertEqual(sum(u.balance for u in state_module.STATE.users.values()),
                         SEEDED_TOTAL)
        now = state_module.now_dt()
        from pocketful.state import available, held

        for user in state_module.STATE.users.values():
            self.assertGreaterEqual(user.balance, 0)
            self.assertGreaterEqual(available(state_module.STATE, user.id, now), 0)
            self.assertGreaterEqual(held(state_module.STATE, user.id, now), 0)

        # refund cap holds for every refunded target
        from pocketful.state import refunded_total

        for payment in state_module.STATE.payments:
            self.assertLessEqual(refunded_total(state_module.STATE, payment.id),
                                 payment.revisions[-1].amount)

        # historical conservation across several views (R202-style)
        for as_of in ("2026-01-01T00:00:00+00:00", "2026-09-20T12:00:00+00:00", now):
            self.assertEqual(self.historical_totals(as_of), SEEDED_TOTAL)

    def test_replays_survive_the_burst(self):
        p_a1 = self.pay(self.ada, "k-a1", "bob", 100)
        # fire a mixed mini-burst, then replay pre-batch keys
        barrier = threading.Barrier(10)

        def churn(index):
            barrier.wait()
            base.request(self.port, "POST", "/payments", body={
                "to_handle": "bob", "amount": 10 + index},
                headers={**self.ada, "Idempotency-Key": f"c-pay-{index}"})

        threads = [threading.Thread(target=churn, args=(i,)) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        status, first, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 55}, headers={**self.ada,
                                                        "Idempotency-Key": "k-pre"})
        self.assertEqual(status, 201, first)
        status, replay, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 55}, headers={**self.ada,
                                                        "Idempotency-Key": "k-pre"})
        self.assertEqual(status, 200)
        self.assertEqual(replay, first)


if __name__ == "__main__":
    unittest.main()