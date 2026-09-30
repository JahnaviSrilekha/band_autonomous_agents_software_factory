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


def settle(port, auth, body, key="k-settle-1"):
    headers = dict(auth or {})
    headers["Idempotency-Key"] = key
    return base.request(port, "POST", "/settlements", body=body, headers=headers)


class TestSettlements(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        assert base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
        self.op = login(self.port, "op@example.com")
        self.ada = login(self.port, "ada@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_no_token_401(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}],
        })
        self.assertEqual((status, payload["error"]["code"]), (401, "unauthenticated"))

    def test_non_operator_403(self):
        status, payload, _ = settle(self.port, self.ada, {
            "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}],
        })
        self.assertEqual((status, payload["error"]["code"]), (403, "forbidden"))
        self.assertEqual(state_module.STATE.users["u_ada"].balance, 10000)

    def test_happy_path_201_shape(self):
        status, payload, _ = settle(self.port, self.op, {
            "transfers": [
                {"from_handle": "ada", "to_handle": "bob", "amount": 100},
                {"from_handle": "bob", "to_handle": "cy", "amount": 50},
            ],
        })
        self.assertEqual(status, 201)
        self.assertEqual(set(payload.keys()), {"settlement_id", "committed_at", "payments"})
        self.assertEqual(len(payload["payments"]), 2)
        first, second = payload["payments"]
        self.assertEqual(first["from_handle"], "ada")
        self.assertEqual(first["to_handle"], "bob")
        self.assertEqual(first["amount"], 100)
        self.assertEqual(first["settlement_id"], payload["settlement_id"])
        self.assertIsNone(first["request_id"])
        self.assertEqual(second["settlement_id"], payload["settlement_id"])
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertEqual(payload["committed_at"], first["created_at"])
        state = state_module.STATE
        self.assertEqual(state.users["u_ada"].balance, 9900)
        self.assertEqual(state.users["u_bob"].balance, 2550)
        self.assertEqual(state.users["u_cy"].balance, 50)

    def test_defaults_note_and_visibility(self):
        status, payload, _ = settle(self.port, self.op, {
            "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}],
        }, key="sd")
        self.assertEqual(payload["payments"][0]["note"], "")
        self.assertEqual(payload["payments"][0]["visibility"], "public")

    def test_entry_errors_in_input_order_before_funds(self):
        body = {
            "transfers": [
                {"from_handle": "ghost", "to_handle": "bob", "amount": 999999999},
                {"from_handle": "ada", "to_handle": "ada", "amount": 10},
                {"from_handle": "ada", "to_handle": "ghost2", "amount": 10},
            ],
        }
        status, payload, _ = settle(self.port, self.op, body)
        self.assertEqual((status, payload["error"]["code"]), (404, "not_found"),
                         "first entry's unknown handle wins in input order")
        body2 = {
            "transfers": [
                {"from_handle": "ada", "to_handle": "ada", "amount": 10},
                {"from_handle": "ghost", "to_handle": "bob", "amount": 10},
            ],
        }
        status, payload, _ = settle(self.port, self.op, body2, key="k2")
        self.assertEqual((status, payload["error"]["code"]), (422, "self_payment"),
                         "entry 1 self-transfer beats entry 2 unknown handle")

    def test_malformed_batch_shape_422(self):
        cases = [
            {},
            {"transfers": []},
            {"transfers": "x"},
            {"transfers": [5]},
            {"transfers": [{"to_handle": "bob", "amount": 10}]},
            {"transfers": [{"from_handle": 5, "to_handle": "bob", "amount": 10}]},
            {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": "10"}]},
            {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": True}]},
            {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 0}]},
            {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10, "note": 5}]},
            {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10, "visibility": "x"}]},
        ]
        for i, body in enumerate(cases):
            status, payload, _ = settle(self.port, self.op, body, key=f"km{i}")
            self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"), repr(body))
        thirty_three = [{"from_handle": "ada", "to_handle": "bob", "amount": 1}] * 33
        status, payload, _ = settle(self.port, self.op, {"transfers": thirty_three}, key="km-max")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))
        thirty_two = thirty_three[:32]
        status, payload, _ = settle(self.port, self.op, {"transfers": thirty_two}, key="km-ok")
        self.assertEqual(status, 201)

    def test_net_affordability_not_sequential(self):
        status, payload, _ = settle(self.port, self.op, {
            "transfers": [
                {"from_handle": "bob", "to_handle": "cy", "amount": 2500},
                {"from_handle": "ada", "to_handle": "bob", "amount": 2500},
            ],
        }, key="knet")
        self.assertEqual(status, 201,
                         "bob nets to zero: affordable even though sequential order would overdraw")
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 2500)

    def test_collective_insufficient_funds_409_all_or_nothing(self):
        status, payload, _ = settle(self.port, self.op, {
            "transfers": [
                {"from_handle": "bob", "to_handle": "cy", "amount": 3000},
                {"from_handle": "ada", "to_handle": "bob", "amount": 400},
            ],
        }, key="kins")
        self.assertEqual((status, payload["error"]["code"]), (409, "insufficient_funds"),
                         "bob nets -2600 against a 2500 balance")
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 2500)
        self.assertEqual(state_module.STATE.users["u_cy"].balance, 0)
        self.assertEqual(len(state_module.STATE.payments), 0)
        status, payload, _ = settle(self.port, self.op, {
            "transfers": [
                {"from_handle": "bob", "to_handle": "cy", "amount": 10},
            ],
        }, key="kins")
        self.assertEqual(status, 201, "failed validation leaves the key reusable")

    def test_replay_200_original_complete_response(self):
        first = settle(self.port, self.op, {
            "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}],
        }, key="krep")
        second = settle(self.port, self.op, {
            "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}],
        }, key="krep")
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 2600)

    def test_constituents_follow_feed_visibility(self):
        status, payload, _ = settle(self.port, self.op, {
            "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100,
                           "visibility": "private"}],
        }, key="kvis")
        member = payload["payments"][0]
        cy = login(self.port, "cy@example.com")
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=cy)
        self.assertNotIn(member["payment_id"], [p["payment_id"] for p in feed["payments"]])
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        self.assertIn(member["payment_id"], [p["payment_id"] for p in feed["payments"]])

    def test_operator_permission_does_not_grant_others_requests_or_private_items(self):
        status, payload, _ = base.request(self.port, "GET", "/requests", headers=self.op)
        self.assertEqual(status, 200)
        self.assertEqual(payload["requests"], [])


if __name__ == "__main__":
    unittest.main()