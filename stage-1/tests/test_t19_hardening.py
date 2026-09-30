import concurrent.futures
import unittest

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "settlement_operator_ids": ["u_op"],
    "users": [
        {"id": "u_op", "email": "op@example.com", "password": "correct horse",
         "display_name": "Op", "handle": "op", "balance": 0},
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 50000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 50000},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 0},
    ],
    "payments": [],
    "requests": [],
}


def login(port, email, password="correct horse"):
    status, payload, _ = base.request(port, "POST", "/auth/login", body={
        "email": email, "password": password,
    })
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestConcurrencyHardening(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        assert base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.op = login(self.port, "op@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_burst_payments_and_settlements_no_5xx_no_negative_conservation(self):
        statuses = []

        def payment_worker(i):
            src = [self.ada, self.bob][i % 2]
            for j in range(3):
                out = base.request(self.port, "POST", "/payments", body={
                    "to_handle": "cy", "amount": 7,
                }, headers={**src, "Idempotency-Key": f"burst-p-{i}-{j}"})
                statuses.append(out[0])

        def settlement_worker(i):
            out = base.request(self.port, "POST", "/settlements", body={
                "transfers": [
                    {"from_handle": "ada", "to_handle": "bob", "amount": 3},
                    {"from_handle": "bob", "to_handle": "cy", "amount": 3},
                ],
            }, headers={**self.op, "Idempotency-Key": f"burst-s-{i}"})
            statuses.append(out[0])

        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            futures = [pool.submit(payment_worker, i) for i in range(25)]
            futures += [pool.submit(settlement_worker, i) for i in range(25)]
            for f in futures:
                f.result()
        self.assertTrue(all(s < 500 for s in statuses), sorted(set(statuses)))
        balances = {u.id: u.balance for u in state_module.STATE.users.values()}
        self.assertEqual(sum(balances.values()), 100000)
        self.assertTrue(all(b >= 0 for b in balances.values()), balances)
        self.assertEqual(balances["u_ada"], 50000 - 7 * 39 - 3 * 25)
        self.assertEqual(balances["u_bob"], 50000 - 7 * 36)
        self.assertEqual(balances["u_cy"], 7 * 75 + 3 * 25)
        self.assertEqual(len(state_module.STATE.payments), 75 + 50)

    def test_concurrent_reset_and_writes_stay_consistent(self):
        statuses = []

        def churn(i):
            if i % 5 == 0:
                statuses.append(base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0])
            else:
                out = base.request(self.port, "POST", "/payments", body={
                    "to_handle": "cy", "amount": 1,
                }, headers={**self.ada, "Idempotency-Key": f"churn-{i}"})
                statuses.append(out[0])

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(churn, range(20)))
        self.assertTrue(all(s < 500 for s in statuses))
        total = sum(u.balance for u in state_module.STATE.users.values())
        self.assertEqual(total, 100000)


if __name__ == "__main__":
    unittest.main()