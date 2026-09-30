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
    "requests": [
        {"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada",
         "amount": 1200, "note": "taxi", "status": "pending"},
        {"id": "rq_small", "requester_id": "u_bob", "payer_id": "u_ada",
         "amount": 10, "note": "gum", "status": "pending"},
    ],
}


def login(port, email, password="correct horse"):
    status, payload, _ = base.request(port, "POST", "/auth/login", body={
        "email": email, "password": password,
    })
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


def pay_request(port, auth, request_id, body=None, key="k-pay-req"):
    headers = dict(auth or {})
    headers["Idempotency-Key"] = key
    return base.request(port, "POST", f"/requests/{request_id}/pay", body=body or {}, headers=headers)


class TestPayRequest(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        assert base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_pay_happy_path_returns_payment_with_request_id(self):
        status, payload, _ = pay_request(self.port, self.ada, "rq_small", {"visibility": "private"})
        self.assertEqual(status, 201)
        self.assertEqual(set(payload.keys()), {
            "payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
            "amount", "currency", "note", "visibility", "request_id", "settlement_id",
            "authorization_id", "created_at",
        })
        self.assertEqual(payload["request_id"], "rq_small")
        self.assertEqual(payload["visibility"], "private")
        self.assertEqual(payload["to_handle"], "bob")
        request = state_module.STATE.requests["rq_small"]
        self.assertEqual(request.status, "paid")
        self.assertEqual(request.payment_id, payload["payment_id"])

    def test_pay_default_visibility_public(self):
        status, payload, _ = pay_request(self.port, self.ada, "rq_small")
        self.assertEqual(status, 201)
        self.assertEqual(payload["visibility"], "public")

    def test_replay_after_paid_200_original_payment(self):
        first = pay_request(self.port, self.ada, "rq_small", {"visibility": "private"}, key="rp")
        second = pay_request(self.port, self.ada, "rq_small", {"visibility": "private"}, key="rp")
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 10)
        self.assertEqual(state_module.STATE.users["u_ada"].balance, 9990)

    def test_same_key_different_visibility_body_409(self):
        first = pay_request(self.port, self.ada, "rq_small", {}, key="rv")
        self.assertEqual(first[0], 201)
        second = pay_request(self.port, self.ada, "rq_small", {"visibility": "public"}, key="rv")
        self.assertEqual(second[0], 409)
        self.assertEqual(second[1]["error"]["code"], "idempotency_key_reuse")

    def test_pay_non_pending_409(self):
        first = pay_request(self.port, self.ada, "rq_seed", key="np-first")
        self.assertEqual(first[0], 201)
        status, payload, _ = pay_request(self.port, self.ada, "rq_seed", key="np-second")
        self.assertEqual((status, payload["error"]["code"]), (409, "request_not_pending"))

    def test_insufficient_funds_then_money_arrives(self):
        fixture = dict(FIXTURE)
        fixture["users"] = [dict(FIXTURE["users"][0], balance=100), FIXTURE["users"][1]]
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = login(self.port, "ada@example.com")
        status, payload, _ = pay_request(self.port, ada, "rq_seed")
        self.assertEqual((status, payload["error"]["code"]), (409, "insufficient_funds"))
        self.assertEqual(state_module.STATE.requests["rq_seed"].status, "pending")
        state_module.STATE.users["u_ada"].balance += 5000
        status, payload, _ = pay_request(self.port, ada, "rq_seed", key="second-attempt")
        self.assertEqual(status, 201)

    def test_not_payer_403(self):
        status, payload, _ = pay_request(self.port, self.bob, "rq_small")
        self.assertEqual((status, payload["error"]["code"]), (403, "forbidden"))

    def test_unknown_request_404(self):
        status, payload, _ = pay_request(self.port, self.ada, "rq_nope")
        self.assertEqual((status, payload["error"]["code"]), (404, "not_found"))


if __name__ == "__main__":
    unittest.main()