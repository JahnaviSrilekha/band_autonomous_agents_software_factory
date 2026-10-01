import random
import threading
import urllib.parse
import unittest
from datetime import datetime, timedelta, timezone

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "settlement_operator_ids": ["u_op"],
    "users": [
        {"id": "u_op", "email": "op@example.com", "password": "correct horse",
         "display_name": "Op", "handle": "op", "balance": 10000},
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 40000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 40000},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 40000},
    ],
    "payments": [
        {"id": "p_seed_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 3000, "created_at": "2026-08-10T09:00:00+00:00"},
        {"id": "p_seed_2", "from_user_id": "u_bob", "to_user_id": "u_cy",
         "amount": 2000, "created_at": "2026-08-11T09:00:00+00:00"},
    ],
    "authorizations": [
        {"id": "a_seed", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 5000, "status": "open",
         "created_at": "2026-08-05T09:00:00+00:00",
         "expires_at": "2099-01-01T00:00:00+00:00"},
    ],
}

SEED_TOTAL = 130000


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


HANDLES = {"u_op": "op", "u_ada": "ada", "u_bob": "bob", "u_cy": "cy"}
SENDERS = ["u_ada", "u_bob", "u_cy"]


class TestT48ConcurrentBurst(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.tokens = {uid: login(self.port, email) for uid, email in (
            ("u_op", "op@example.com"), ("u_ada", "ada@example.com"),
            ("u_bob", "bob@example.com"), ("u_cy", "cy@example.com"))}

    def tearDown(self):
        base.stop_server(self.httpd)

    def race_same_expected_revision(self, target):
        barrier = threading.Barrier(4)
        results = []

        def attempt(index):
            barrier.wait()
            status, payload, _ = base.request(
                self.port, "POST", f"/payments/{target}/corrections",
                body={"expected_revision": 1, "amount": 3000 + index,
                      "effective_at": "2026-08-10T09:00:00+00:00",
                      "reason": f"race{index}"},
                headers={**self.tokens["u_ada"], "Idempotency-Key": f"k-race-{index}"})
            results.append((status, payload))

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        successes = [status for status, _ in results if status == 201]
        stale = [status for status, _ in results if status == 409]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(stale), 3, results)
        self.assertTrue(all(status < 500 for status, _ in results))

    def test_mixed_burst_50_in_flight_no_5xx_conservation_everywhere(self):
        self.race_same_expected_revision("p_seed_1")
        statuses = []
        lock = threading.Lock()
        payment_counter = [0]
        seeded_payment_ids = ["p_seed_1", "p_seed_2"]

        def record(status):
            with lock:
                statuses.append(status)

        def worker(index):
            rng = random.Random(index)
            sender = SENDERS[index % len(SENDERS)]
            receiver = [u for u in SENDERS if u != sender][index % (len(SENDERS) - 1)]
            for step in range(4):
                kind = (index + step) % 4
                with lock:
                    payment_counter[0] += 1
                    key = f"k-burst-{payment_counter[0]}"
                if kind == 0:
                    status, _, _ = base.request(self.port, "POST", "/payments", body={
                        "to_handle": HANDLES[receiver], "amount": 10 + rng.randint(10, 50)},
                        headers={**self.tokens[sender], "Idempotency-Key": key})
                    record(status)
                elif kind == 1:
                    status, payload, _ = base.request(self.port, "POST", "/authorizations",
                                                      body={"to_handle": HANDLES[receiver],
                                                            "amount": 100},
                                                      headers={**self.tokens[sender],
                                                               "Idempotency-Key": key})
                    record(status)
                    if status == 201:
                        status, _, _ = base.request(
                            self.port, "POST",
                            f"/authorizations/{payload['authorization_id']}/capture",
                            body={"amount": 100},
                            headers={**self.tokens[receiver], "Idempotency-Key": key + "-c"})
                        record(status)
                elif kind == 2:
                    status, _, _ = base.request(self.port, "GET", "/statement?limit=10",
                                                headers=self.tokens[sender])
                    record(status)
                    as_of = (datetime.now(timezone.utc)
                             - timedelta(days=rng(30))).isoformat()
                    status, _, _ = base.request(
                        self.port, "GET",
                        f"/me?as_of={urllib.parse.quote(as_of, safe='')}"
                        f"&known_at={urllib.parse.quote(as_of, safe='')}",
                        headers=self.tokens[sender])
                    record(status)
                else:
                    status, _, _ = base.request(self.port, "GET", "/activity?limit=5",
                                                headers=self.tokens[sender])
                    record(status)
                    target = seeded_payment_ids[index % len(seeded_payment_ids)]
                    status, payload, _ = base.request(
                        self.port, "POST", f"/payments/{target}/corrections",
                        body={"expected_revision": 1, "amount": 2999,
                              "effective_at": "2026-08-10T09:00:00+00:00",
                              "reason": "expected stale or forbidden"},
                        headers={**self.tokens["u_ada"], "Idempotency-Key": key})
                    record(status)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(13)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(statuses)
        five_hundreds = [status for status in statuses if status >= 500]
        self.assertEqual(five_hundreds, [])

        views = ["?as_of=2026-08-09T00:00:00%2B00:00",
                 "?as_of=2026-08-10T12:00:00%2B00:00",
                 "?as_of=2026-08-11T12:00:00%2B00:00",
                 "?known_at=2020-01-01T00:00:00%2B00:00",
                 "?as_of=2026-08-10T12:00:00%2B00:00&known_at=2020-01-01T00:00:00%2B00:00",
                 ""]
        for view in views:
            total = 0
            for uid in ("u_op", "u_ada", "u_bob", "u_cy"):
                status, payload, _ = base.request(self.port, "GET", f"/me{view}",
                                                  headers=self.tokens[uid])
                self.assertEqual(status, 200, view)
                self.assertGreaterEqual(payload["total"], 0, (view, uid))
                self.assertGreaterEqual(payload["available"], 0, (view, uid))
                total += payload["total"]
            self.assertEqual(total, SEED_TOTAL, view)

    def test_concurrent_same_expected_revision_stress(self):
        for round_index in range(3):
            status, payload, _ = base.request(self.port, "POST", "/payments", body={
                "to_handle": "bob", "amount": 100},
                headers={**self.tokens["u_ada"],
                         "Idempotency-Key": f"k-stress-pay-{round_index}"})
            self.assertEqual(status, 201)
            target = payload["payment_id"]
            barrier = threading.Barrier(6)
            results = []

            def attempt(i):
                barrier.wait()
                status, payload, _ = base.request(
                    self.port, "POST", f"/payments/{target}/corrections",
                    body={"expected_revision": 1, "amount": 90 + i,
                          "effective_at": "2026-08-10T09:00:00+00:00",
                          "reason": f"r{round_index}-{i}"},
                    headers={**self.tokens["u_ada"],
                             "Idempotency-Key": f"k-stress-{round_index}-{i}"})
                results.append((status, payload))

            threads = [threading.Thread(target=attempt, args=(i,)) for i in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(sorted(status for status, _ in results),
                             [201] + [409] * 5, results)
            self.assertTrue(all(status != 500 for status, _ in results))


if __name__ == "__main__":
    unittest.main()