import concurrent.futures
import unittest

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
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


def pay(port, auth, body, key="k-pay-1", headers=None):
    merged = dict(auth or {})
    merged["Idempotency-Key"] = key
    if headers:
        merged.update(headers)
    return base.request(port, "POST", "/payments", body=body, headers=merged)


def balances(state):
    return {u.id: u.balance for u in state.users.values()}


class TestCreatePayment(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_payment_happy_path_201_shape_and_defaults(self):
        status, payload, _ = pay(self.port, self.ada, {"to_handle": "bob", "amount": 1500})
        self.assertEqual(status, 201)
        self.assertEqual(set(payload.keys()), {
            "payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
            "amount", "currency", "note", "visibility", "request_id", "settlement_id",
            "authorization_id", "created_at",
        })
        self.assertEqual(payload["from_handle"], "ada")
        self.assertEqual(payload["to_handle"], "bob")
        self.assertEqual(payload["amount"], 1500)
        self.assertEqual(payload["currency"], "EUR")
        self.assertEqual(payload["note"], "")
        self.assertEqual(payload["visibility"], "public")
        self.assertIsNone(payload["request_id"])
        self.assertIsNone(payload["settlement_id"])
        state = state_module.STATE
        self.assertEqual(state.users["u_ada"].balance, 8500)
        self.assertEqual(state.users["u_bob"].balance, 4000)

    def test_atomic_debit_credit_conservation(self):
        pay(self.port, self.ada, {"to_handle": "bob", "amount": 1000}, key="a")
        pay(self.port, self.bob, {"to_handle": "ada", "amount": 300}, key="b")
        total = sum(balances(state_module.STATE).values())
        self.assertEqual(total, 12500)

    def test_insufficient_funds_409_and_no_trace(self):
        status, payload, _ = pay(self.port, self.bob, {"to_handle": "ada", "amount": 3000})
        self.assertEqual((status, payload["error"]["code"]), (409, "insufficient_funds"))
        self.assertEqual(balances(state_module.STATE)["u_bob"], 2500)
        self.assertEqual(balances(state_module.STATE)["u_ada"], 10000)
        self.assertEqual(len(state_module.STATE.payments), 0)

    def test_amount_case_table_422(self):
        for amount in (0, -1, 1000000001, 1.5, "5", True, False, None):
            status, payload, _ = pay(self.port, self.ada, {"to_handle": "bob", "amount": amount}, key=f"k{amount!r}")
            self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"), repr(amount))

    def test_amount_bounds_accepted(self):
        fixture = dict(FIXTURE)
        fixture["users"] = [dict(FIXTURE["users"][0], balance=1000000000), dict(FIXTURE["users"][1], balance=0)]
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = login(self.port, "ada@example.com")
        status, payload, _ = pay(self.port, ada, {"to_handle": "bob", "amount": 1000000000}, key="max")
        self.assertEqual(status, 201)

    def test_self_payment_422(self):
        status, payload, _ = pay(self.port, self.ada, {"to_handle": "ada", "amount": 100})
        self.assertEqual((status, payload["error"]["code"]), (422, "self_payment"))

    def test_unknown_handle_404(self):
        status, payload, _ = pay(self.port, self.ada, {"to_handle": "ghost", "amount": 100})
        self.assertEqual((status, payload["error"]["code"]), (404, "not_found"))

    def test_note_round_trip_verbatim(self):
        note = "café ☕ " + "🍕" * 10 + " 🎉✓漢字"
        status, payload, _ = pay(self.port, self.ada, {"to_handle": "bob", "amount": 10, "note": note}, key="n1")
        self.assertEqual(status, 201)
        self.assertEqual(payload["note"], note)
        status, payload, _ = pay(self.port, self.ada, {"to_handle": "bob", "amount": 10, "note": note}, key="n2")
        self.assertEqual(payload["note"], note)

    def test_note_over_200_code_points_422(self):
        status, payload, _ = pay(self.port, self.ada, {
            "to_handle": "bob", "amount": 10, "note": "🎉" * 201,
        }, key="n3")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))

    def test_note_exactly_200_emoji_accepted(self):
        note = "🎉" * 200
        status, payload, _ = pay(self.port, self.ada, {
            "to_handle": "bob", "amount": 10, "note": note,
        }, key="n4")
        self.assertEqual(status, 201)
        self.assertEqual(payload["note"], note)

    def test_visibility_invalid_422(self):
        status, payload, _ = pay(self.port, self.ada, {
            "to_handle": "bob", "amount": 10, "visibility": "secret",
        }, key="v1")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))

    def test_missing_idempotency_key_400(self):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 10,
        }, headers=self.ada)
        self.assertEqual((status, payload["error"]["code"]), (400, "missing_idempotency_key"))

    def test_key_over_255_422(self):
        status, payload, _ = pay(self.port, self.ada, {"to_handle": "bob", "amount": 10}, key="k" * 256)
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))

    def test_replay_200_same_body_money_moves_once(self):
        first = pay(self.port, self.ada, {"to_handle": "bob", "amount": 500}, key="r1")
        second = pay(self.port, self.ada, {"to_handle": "bob", "amount": 500}, key="r1")
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(balances(state_module.STATE)["u_bob"], 3000)

    def test_same_key_different_body_409(self):
        pay(self.port, self.ada, {"to_handle": "bob", "amount": 500}, key="r2")
        status, payload, _ = pay(self.port, self.ada, {"to_handle": "bob", "amount": 501}, key="r2")
        self.assertEqual((status, payload["error"]["code"]), (409, "idempotency_key_reuse"))

    def test_key_reusable_after_4xx_failure(self):
        status, _, _ = pay(self.port, self.ada, {"to_handle": "ghost", "amount": 500}, key="r3")
        self.assertEqual(status, 404)
        status, payload, _ = pay(self.port, self.ada, {"to_handle": "bob", "amount": 500}, key="r3")
        self.assertEqual(status, 201)

    def test_key_scoped_to_user(self):
        pay(self.port, self.ada, {"to_handle": "bob", "amount": 100}, key="shared")
        status, payload, _ = pay(self.port, self.bob, {"to_handle": "ada", "amount": 100}, key="shared")
        self.assertEqual(status, 201)

    def test_same_body_different_key_order_and_type_forms(self):
        first = pay(self.port, self.ada, {"to_handle": "bob", "amount": 100}, key="o1")
        second = pay(self.port, self.ada, {"amount": 100.0, "to_handle": "bob"}, key="o1")
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)

    def test_concurrent_identical_requests_one_201(self):
        results = []

        def worker():
            results.append(pay(self.port, self.ada, {"to_handle": "bob", "amount": 100}, key="conc"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(lambda _: worker(), range(16)))
        created = [r for r in results if r[0] == 201]
        replayed = [r for r in results if r[0] == 200]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(replayed), 15)
        self.assertTrue(all(r[1] == created[0][1] for r in replayed))
        self.assertEqual(balances(state_module.STATE)["u_bob"], 2600)
        self.assertEqual(balances(state_module.STATE)["u_ada"], 9900)

    def test_concurrent_mixed_load_conservation_no_5xx(self):
        statuses = []

        def worker(i):
            src = [self.ada, self.bob][i % 2]
            dst = ["bob", "ada"][i % 2]
            for j in range(4):
                out = pay(self.port, src, {"to_handle": dst, "amount": 3}, key=f"load-{i}-{j}")
                statuses.append(out[0])

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(worker, range(20)))
        self.assertTrue(all(s < 500 for s in statuses), statuses)
        total = sum(balances(state_module.STATE).values())
        self.assertEqual(total, 12500)
        self.assertTrue(all(b >= 0 for b in balances(state_module.STATE).values()))


if __name__ == "__main__":
    unittest.main()