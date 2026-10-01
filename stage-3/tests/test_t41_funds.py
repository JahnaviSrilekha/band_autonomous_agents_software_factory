import threading
import unittest

import base
from pocketful import state as state_module
from pocketful.state import as_dt

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
    ],
}

COMBINED_FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 7000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 10000},
    ],
    "payments": [
        {"id": "p_in", "from_user_id": "u_bob", "to_user_id": "u_ada",
         "amount": 12000, "created_at": "2026-08-01T09:00:00+00:00"},
        {"id": "p_out", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 6000, "created_at": "2026-08-01T09:00:00+00:00"},
    ],
}

T1 = "2026-08-01T09:00:00+00:00"


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


def balances():
    return {uid: u.balance for uid, u in state_module.STATE.users.items()}


class TestT41Funds(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500}, headers={**self.ada, "Idempotency-Key": "k-pay"})
        assert status == 201, payload
        self.payment_id = payload["payment_id"]
        self.path = f"/payments/{self.payment_id}/corrections"

    def tearDown(self):
        base.stop_server(self.httpd)

    def correct(self, body, headers=None, key="k-corr"):
        return base.request(self.port, "POST", self.path, body=body,
                            headers={**(headers or self.ada), "Idempotency-Key": key})

    def test_current_unaffordable_debit_409_state_unchanged(self):
        before = balances()
        status, payload, _ = self.correct({"expected_revision": 1, "amount": 20000,
                                           "effective_at": "2026-09-20T12:00:00+00:00",
                                           "reason": "too much"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")
        self.assertEqual(balances(), before)
        payment = next(p for p in state_module.STATE.payments if p.id == self.payment_id)
        self.assertEqual(len(payment.revisions), 1)

    def test_insufficient_funds_counts_held_not_just_balance(self):
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 8000}, headers={**self.ada, "Idempotency-Key": "k-hold"})
        self.assertEqual(status, 201, payload)
        status, payload, _ = self.correct({"expected_revision": 1, "amount": 11000,
                                           "effective_at": "2026-09-20T12:00:00+00:00",
                                           "reason": "over available"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")

    def test_failed_correction_frees_idempotency_key(self):
        status, _, _ = self.correct({"expected_revision": 1, "amount": 20000,
                                     "effective_at": "2026-09-20T12:00:00+00:00",
                                     "reason": "declined"})
        self.assertEqual(status, 409)
        status, payload, _ = self.correct({"expected_revision": 1, "amount": 600,
                                           "effective_at": "2026-09-20T12:00:00+00:00",
                                           "reason": "accepted"}, key="k-corr")
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["revision"], 2)

    def test_amount_increase_debits_sender(self):
        before = balances()
        status, payload, _ = self.correct({"expected_revision": 1, "amount": 600,
                                           "effective_at": "2026-09-20T12:00:00+00:00",
                                           "reason": "tip"})
        self.assertEqual(status, 201)
        after = balances()
        self.assertEqual(after["u_ada"], before["u_ada"] - 100)
        self.assertEqual(after["u_bob"], before["u_bob"] + 100)

    def test_amount_decrease_debits_receiver(self):
        before = balances()
        status, payload, _ = self.correct({"expected_revision": 1, "amount": 300,
                                           "effective_at": "2026-09-20T12:00:00+00:00",
                                           "reason": "partial refund"})
        self.assertEqual(status, 201)
        after = balances()
        self.assertEqual(after["u_bob"], before["u_bob"] - 200)
        self.assertEqual(after["u_ada"], before["u_ada"] + 200)

    def test_zero_amount_reverses_entire_payment(self):
        before = balances()
        status, payload, _ = self.correct({"expected_revision": 1, "amount": 0,
                                           "effective_at": "2026-09-20T12:00:00+00:00",
                                           "reason": "reversal"})
        self.assertEqual(status, 201)
        after = balances()
        self.assertEqual(after["u_bob"], before["u_bob"] - 500)
        self.assertEqual(after["u_ada"], before["u_ada"] + 500)

    def test_replay_returns_original_revision_after_newer_revisions(self):
        status, first, _ = self.correct({"expected_revision": 1, "amount": 400,
                                         "effective_at": "2026-09-20T12:00:00+00:00",
                                         "reason": "first"}, key="k-one")
        self.assertEqual(status, 201)
        status, second, _ = self.correct({"expected_revision": 2, "amount": 450,
                                          "effective_at": "2026-09-20T12:00:00+00:00",
                                          "reason": "second"}, key="k-two")
        self.assertEqual(status, 201)
        status, replay, _ = self.correct({"expected_revision": 1, "amount": 400,
                                          "effective_at": "2026-09-20T12:00:00+00:00",
                                          "reason": "first"}, key="k-one")
        self.assertEqual(status, 200)
        self.assertEqual(replay, first)
        self.assertEqual(replay["revision"], 2)

    def test_recorded_times_strictly_increase(self):
        stamps = []
        for index in range(3):
            status, payload, _ = self.correct(
                {"expected_revision": index + 1, "amount": 400 + index,
                 "effective_at": "2026-09-20T12:00:00+00:00", "reason": f"r{index}"},
                key=f"k-seq-{index}")
            self.assertEqual(status, 201, payload)
            stamps.append(as_dt(payload["recorded_at"]))
        self.assertLess(stamps[0], stamps[1])
        self.assertLess(stamps[1], stamps[2])

    def test_payment_correctable_many_times_no_cap(self):
        for index in range(5):
            status, payload, _ = self.correct(
                {"expected_revision": index + 1, "amount": 500 - index,
                 "effective_at": "2026-09-20T12:00:00+00:00", "reason": f"r{index}"},
                key=f"k-many-{index}")
            self.assertEqual(status, 201, payload)
            self.assertEqual(payload["revision"], index + 2)
        payment = next(p for p in state_module.STATE.payments if p.id == self.payment_id)
        self.assertEqual(len(payment.revisions), 6)

    def test_concurrent_same_expected_revision_exactly_one_success(self):
        barrier = threading.Barrier(4)
        results = []

        def attempt(index):
            barrier.wait()
            status, payload, _ = self.correct(
                {"expected_revision": 1, "amount": 100 + index,
                 "effective_at": "2026-09-20T12:00:00+00:00", "reason": f"c{index}"},
                key=f"k-race-{index}")
            results.append((status, payload.get("error", {}).get("code")
                            if isinstance(payload, dict) and "error" in payload else None))

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        successes = [r for r in results if r[0] == 201]
        self.assertEqual(len(successes), 1, results)
        for status, code in results:
            if status != 201:
                self.assertEqual((status, code), (409, "stale_revision"))


class TestT41HistoricalOverdraft(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def login(self, email):
        status, payload, _ = base.request(self.port, "POST", "/auth/login",
                                          body={"email": email, "password": "correct horse"})
        assert status == 200, payload
        return {"Authorization": f"Bearer {payload['token']}"}

    def test_same_instant_movements_combined_before_zero_check_at_seed(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=COMBINED_FIXTURE)
        self.assertEqual(status, 204)

    def test_correction_making_past_total_negative_409(self):
        fixture = {
            "currency": "EUR", "minor_units": 2,
            "users": [
                {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
                 "display_name": "Ada", "handle": "ada", "balance": 10000},
                {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
                 "display_name": "Bob", "handle": "bob", "balance": 10000},
            ],
            "payments": [
                {"id": "p_old", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 9000, "created_at": "2026-08-01T09:00:00+00:00"},
                {"id": "p_back", "from_user_id": "u_bob", "to_user_id": "u_ada",
                 "amount": 8000, "created_at": "2026-08-02T09:00:00+00:00"},
            ],
        }
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        ada = self.login("ada@example.com")
        before = balances()
        status, payload, _ = base.request(
            self.port, "POST", "/payments/p_old/corrections",
            body={"expected_revision": 1, "amount": 18000,
                  "effective_at": "2026-08-01T09:00:00+00:00", "reason": "recompute"},
            headers={**ada, "Idempotency-Key": "k-hist"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "historical_overdraft")
        self.assertEqual(balances(), before)
        payment = next(p for p in state_module.STATE.payments if p.id == "p_old")
        self.assertEqual(len(payment.revisions), 1)

    def test_correction_scan_ignores_payments_without_both_parties(self):
        fixture = {
            "currency": "EUR", "minor_units": 2,
            "users": [
                {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
                 "display_name": "Ada", "handle": "ada", "balance": 10000},
                {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
                 "display_name": "Bob", "handle": "bob", "balance": 10000},
                {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
                 "display_name": "Cy", "handle": "cy", "balance": 10000},
            ],
            "payments": [
                {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 1000, "created_at": "2026-08-01T09:00:00+00:00"},
                {"id": "p_2", "from_user_id": "u_cy", "to_user_id": "u_bob",
                 "amount": 500, "created_at": "2026-08-02T09:00:00+00:00"},
            ],
        }
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        ada = self.login("ada@example.com")
        status, payload, _ = base.request(
            self.port, "POST", "/payments/p_1/corrections",
            body={"expected_revision": 1, "amount": 1500,
                  "effective_at": "2026-08-01T09:00:00+00:00", "reason": "bump"},
            headers={**ada, "Idempotency-Key": "k-third"})
        self.assertEqual(status, 201, payload)

    def test_same_instant_correction_combined_not_isolated(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=COMBINED_FIXTURE)
        self.assertEqual(status, 204)
        ada = self.login("ada@example.com")
        status, payload, _ = base.request(
            self.port, "POST", "/payments/p_out/corrections",
            body={"expected_revision": 1, "amount": 12000,
                  "effective_at": T1, "reason": "same-instant"},
            headers={**ada, "Idempotency-Key": "k-combined"})
        self.assertEqual(status, 201, payload)
        self.assertEqual(balances()["u_ada"], 7000 - 6000)
        self.assertEqual(balances()["u_bob"], 10000 + 6000)

    def test_effective_time_shift_zero_delta_still_scanned(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=COMBINED_FIXTURE)
        self.assertEqual(status, 204)
        ada = self.login("ada@example.com")
        status, payload, _ = base.request(
            self.port, "POST", "/payments/p_out/corrections",
            body={"expected_revision": 1, "amount": 6000,
                  "effective_at": "2026-08-03T09:00:00+00:00", "reason": "move later"},
            headers={**ada, "Idempotency-Key": "k-shift"})
        self.assertEqual(status, 201, payload)
        self.assertEqual(balances()["u_ada"], 7000)


if __name__ == "__main__":
    unittest.main()