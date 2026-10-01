import json
import threading
import unittest
from datetime import timedelta

import base
import helpers_t2 as h


class TestT34Concurrency(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def _login_all(self):
        tokens = {}
        for email in ("ada@example.com", "bob@example.com", "carol@example.com"):
            status, payload, _ = base.request(self.port, "POST", "/auth/login",
                                              body={"email": email, "password": "correct horse"})
            tokens[email.split("@")[0]] = payload["token"]
        return tokens

    def test_mixed_burst_50_invariants(self):
        fixture = h.seeded_fixture([
            {"id": "a_seed", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 500, "status": "open", "expires_at": h.future()},
        ])
        fixture["settlement_operator_ids"] = ["u_carol"]
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        tokens = self._login_all()
        seed_total = sum(u["balance"] for u in fixture["users"])

        status, me_ada, _ = base.request(self.port, "GET", "/me",
                                         headers={"Authorization": f"Bearer {tokens['ada']}"})
        auth_id_ref = {}

        # create a second authorization to capture concurrently
        status, auth, _ = base.request(self.port, "POST", "/authorizations",
                                       body={"to_handle": "bob", "amount": 400},
                                       headers={"Authorization": f"Bearer {tokens['ada']}",
                                                "Idempotency-Key": "k-authz-burst"})
        self.assertEqual(status, 201)
        capture_id = auth["authorization_id"]

        results = []

        def record(fn):
            try:
                results.append(fn())
            except Exception as exc:  # noqa: BLE001
                results.append(("EXC", str(exc)))

        def pay(handle, to, amount, key):
            def call():
                return base.request(self.port, "POST", "/payments",
                                    body={"to_handle": to, "amount": amount},
                                    headers={"Authorization": f"Bearer {tokens[handle]}",
                                             "Idempotency-Key": key})
            return call

        def authorize(handle, to, amount, key):
            def call():
                return base.request(self.port, "POST", "/authorizations",
                                    body={"to_handle": to, "amount": amount},
                                    headers={"Authorization": f"Bearer {tokens[handle]}",
                                             "Idempotency-Key": key})
            return call

        def capture(handle, auth_id, amount, key):
            def call():
                return base.request(
                    self.port, "POST", f"/authorizations/{auth_id}/capture",
                    body={"amount": amount},
                    headers={"Authorization": f"Bearer {tokens[handle]}",
                             "Idempotency-Key": key})
            return call

        def void(handle, auth_id):
            def call():
                return base.request(self.port, "POST", f"/authorizations/{auth_id}/void",
                                    body={},
                                    headers={"Authorization": f"Bearer {tokens[handle]}"})
            return call

        def settle(handle, transfers, key):
            def call():
                return base.request(self.port, "POST", "/settlements",
                                    body={"transfers": transfers},
                                    headers={"Authorization": f"Bearer {tokens[handle]}",
                                             "Idempotency-Key": key})
            return call

        def read_me(handle):
            def call():
                return base.request(self.port, "GET", "/me",
                                    headers={"Authorization": f"Bearer {tokens[handle]}"})
            return call

        calls = []
        for i in range(10):
            calls.append(pay("ada", "bob", 100 + i, f"burst-pay-{i}"))
        for i in range(4):
            calls.append(authorize("ada", "carol", 200 + i, f"burst-authz-{i}"))
        for i in range(8):
            calls.append(capture("bob", capture_id, 30, f"burst-cap-{i}"))
        for i in range(3):
            calls.append(void("ada", capture_id))
        for i in range(2):
            calls.append(pay("bob", "carol", 50 + i, f"burst-bob-{i}"))
        calls.append(settle("carol", [{"from_handle": "ada", "to_handle": "carol",
                                       "amount": 60}], "burst-settle-1"))
        for handle in ("ada", "bob", "carol"):
            for _ in range(6):
                calls.append(read_me(handle))
        # concurrent identical-key pair on the same capture
        for _ in range(4):
            calls.append(capture("bob", capture_id, 50, "burst-cap-dup"))
        self.assertEqual(len(calls), 50)

        threads = [threading.Thread(target=record, args=(call,)) for call in calls]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for result in results:
            if isinstance(result, tuple) and result and result[0] == "EXC":
                self.fail(f"request raised: {result[1]}")
        five_xx = [r for r in results if isinstance(r, tuple) and 500 <= r[0] < 600]
        self.assertEqual(five_xx, [], "no 5xx allowed")

        created_captures = [r for r in results if r[0] == 201]
        replayed_captures = [r for r in results if r[0] == 200]
        # conservation
        finals = {}
        for handle in ("ada", "bob", "carol"):
            status, me, _ = base.request(self.port, "GET", "/me",
                                         headers={"Authorization": f"Bearer {tokens[handle]}"})
            finals[handle] = me
            self.assertGreaterEqual(me["available"], 0, f"{handle} available negative")
            self.assertGreaterEqual(me["held"], 0)
            self.assertEqual(me["balance"], me["total"])
        total_now = sum(m["total"] for m in finals.values())
        self.assertEqual(total_now, seed_total, "conservation on total")

        # captures never exceed the authorization amount
        status, auth_list, _ = base.request(
            self.port, "GET", "/authorizations",
            headers={"Authorization": f"Bearer {tokens['ada']}"})
        for record_ in auth_list["authorizations"]:
            self.assertLessEqual(record_["captured_amount"], record_["amount"])

        # the seeded hold is 500 and the burst authz is 400: ada's held fits
        status, me_ada_final, _ = finals["ada"], None, None

    def test_concurrent_identical_capture_keys_one_movement(self):
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        ada = h.login(self.port)
        bob = h.login(self.port, "bob@example.com")
        status, auth, _ = base.request(self.port, "POST", "/authorizations",
                                       body={"to_handle": "bob", "amount": 1000},
                                       headers={**ada, "Idempotency-Key": "k-c1"})
        self.assertEqual(status, 201)
        auth_id = auth["authorization_id"]
        results = []

        def fire():
            results.append(base.request(self.port, "POST", f"/authorizations/{auth_id}/capture",
                                        body={"amount": 400},
                                        headers={**bob, "Idempotency-Key": "k-dup"}))

        threads = [threading.Thread(target=fire) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        created = [r for r in results if r[0] == 201]
        replayed = [r for r in results if r[0] == 200]
        self.assertEqual(len(created) + len(replayed), 16)
        self.assertEqual(len(created), 1)
        payment_ids = {r[1]["payment_id"] for r in created + replayed}
        self.assertEqual(len(payment_ids), 1)
        status, me, _ = base.request(self.port, "GET", "/me", headers=ada)
        self.assertEqual(me["total"], 9600)
        self.assertEqual(me["held"], 0)

    def test_concurrent_payments_never_overshoot_available(self):
        fixture = h.seeded_fixture([
            {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 5000, "status": "open", "expires_at": h.future()},
        ])
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = h.login(self.port)
        # available is 5000; fire 10 concurrent 1000 payments — at most 5 succeed
        results = []

        def fire(i):
            results.append(base.request(self.port, "POST", "/payments",
                                        body={"to_handle": "bob", "amount": 1000},
                                        headers={**ada, "Idempotency-Key": f"k-ov-{i}"}))

        threads = [threading.Thread(target=fire, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        created = [r for r in results if r[0] == 201]
        refused = [r for r in results if r[0] == 409]
        self.assertEqual(len(created), 5)
        self.assertEqual(len(refused), 5)
        for r in refused:
            self.assertEqual(r[1]["error"]["code"], "insufficient_funds")
        status, me, _ = base.request(self.port, "GET", "/me", headers=ada)
        self.assertEqual(me["total"], 5000)
        self.assertEqual(me["available"], 0)
        bob_status, me_bob, _ = base.request(self.port, "GET", "/me",
                                             headers=h.login(self.port, "bob@example.com"))
        self.assertEqual(me_bob["total"], 7500)


if __name__ == "__main__":
    unittest.main()