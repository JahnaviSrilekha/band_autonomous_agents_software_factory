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
         "display_name": "Bob", "handle": "bob", "balance": 0},
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


def create_request(port, auth, body, key="k-req-1"):
    headers = dict(auth or {})
    headers["Idempotency-Key"] = key
    return base.request(port, "POST", "/requests", body=body, headers=headers)


class TestCreateRequest(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        assert base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_request_happy_path_201_shape(self):
        status, payload, _ = create_request(self.port, self.bob, {
            "payer_handle": "ada", "amount": 1200, "note": "taxi",
        })
        self.assertEqual(status, 201)
        self.assertEqual(set(payload.keys()), {
            "request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
            "amount", "currency", "note", "status", "payment_id", "created_at",
        })
        self.assertEqual(payload["requester_handle"], "bob")
        self.assertEqual(payload["payer_handle"], "ada")
        self.assertEqual(payload["status"], "pending")
        self.assertIsNone(payload["payment_id"])
        self.assertEqual(payload["note"], "taxi")

    def test_request_may_exceed_payer_balance_and_moves_nothing(self):
        status, payload, _ = create_request(self.port, self.bob, {
            "payer_handle": "ada", "amount": 999999,
        })
        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(state_module.STATE.users["u_ada"].balance, 10000)
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 0)

    def test_self_request_422(self):
        status, payload, _ = create_request(self.port, self.ada, {
            "payer_handle": "ada", "amount": 100,
        })
        self.assertEqual((status, payload["error"]["code"]), (422, "self_request"))

    def test_unknown_payer_404(self):
        status, payload, _ = create_request(self.port, self.bob, {
            "payer_handle": "ghost", "amount": 100,
        })
        self.assertEqual((status, payload["error"]["code"]), (404, "not_found"))

    def test_amount_case_table_422(self):
        for amount in (0, -1, 1000000001, 1.5, "5", True, None):
            status, payload, _ = create_request(self.port, self.bob, {
                "payer_handle": "ada", "amount": amount,
            }, key=f"k{amount!r}")
            self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"), repr(amount))

    def test_note_over_200_422(self):
        status, payload, _ = create_request(self.port, self.bob, {
            "payer_handle": "ada", "amount": 5, "note": "x" * 201,
        })
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))

    def test_missing_idempotency_key_400(self):
        status, payload, _ = base.request(self.port, "POST", "/requests", body={
            "payer_handle": "ada", "amount": 5,
        }, headers=self.bob)
        self.assertEqual((status, payload["error"]["code"]), (400, "missing_idempotency_key"))

    def test_replay_same_body_200_once_created(self):
        first = create_request(self.port, self.bob, {"payer_handle": "ada", "amount": 500}, key="rr")
        second = create_request(self.port, self.bob, {"amount": 500, "payer_handle": "ada"}, key="rr")
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(len(state_module.STATE.requests), 1)

    def test_same_key_different_body_409(self):
        create_request(self.port, self.bob, {"payer_handle": "ada", "amount": 500}, key="rr2")
        status, payload, _ = create_request(self.port, self.bob, {"payer_handle": "ada", "amount": 501}, key="rr2")
        self.assertEqual((status, payload["error"]["code"]), (409, "idempotency_key_reuse"))

    def test_concurrent_identical_creates_one_request(self):
        results = []

        def worker():
            results.append(create_request(self.port, self.bob, {"payer_handle": "ada", "amount": 50}, key="cc"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda _: worker(), range(12)))
        created = [r for r in results if r[0] == 201]
        replayed = [r for r in results if r[0] == 200]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(replayed), 11)
        self.assertTrue(all(r[1] == created[0][1] for r in replayed))
        self.assertEqual(len(state_module.STATE.requests), 1)

    def test_bool_never_equals_int_body(self):
        first = create_request(self.port, self.bob, {"payer_handle": "ada", "amount": 50, "x": 1}, key="bj")
        second = create_request(self.port, self.bob, {"payer_handle": "ada", "amount": 50, "x": True}, key="bj")
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 409)
        self.assertEqual(second[1]["error"]["code"], "idempotency_key_reuse")


if __name__ == "__main__":
    unittest.main()