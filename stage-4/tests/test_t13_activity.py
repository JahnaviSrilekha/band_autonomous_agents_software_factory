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
         "display_name": "Bob", "handle": "bob", "balance": 500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 300},
    ],
    "payments": [
        {"id": "p_seed_pub", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 500, "note": "coffee", "visibility": "public"},
        {"id": "p_seed_priv", "from_user_id": "u_ada", "to_user_id": "u_cy",
         "amount": 300, "note": "secret", "visibility": "private"},
    ],
    "requests": [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
         "amount": 100, "note": "never in feed", "status": "pending"},
    ],
}


def login(port, email, password="correct horse"):
    status, payload, _ = base.request(port, "POST", "/auth/login", body={
        "email": email, "password": password,
    })
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestActivity(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        assert base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def ids(self, payload):
        return [p["payment_id"] for p in payload["payments"]]

    def test_feed_contract_third_party(self):
        status, payload, _ = base.request(self.port, "GET", "/activity", headers=self.bob)
        self.assertEqual(status, 200)
        self.assertEqual(set(payload.keys()), {"payments", "has_more"})
        ids = self.ids(payload)
        self.assertIn("p_seed_pub", ids, "public payments are visible to third parties")
        self.assertNotIn("p_seed_priv", ids, "private payments hidden from third parties")
        status, payload, _ = base.request(self.port, "GET", "/activity", headers=self.cy)
        ids = self.ids(payload)
        self.assertIn("p_seed_priv", ids, "receiver always sees own private payment")
        self.assertIn("p_seed_pub", ids, "public payments visible to everyone")
        status, payload, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        ids = self.ids(payload)
        self.assertEqual(set(ids), {"p_seed_pub", "p_seed_priv"}, "sender sees both")

    def test_requests_never_in_feed(self):
        status, payload, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        for p in payload["payments"]:
            self.assertIn("payment_id", p)
            self.assertNotIn("status", p)

    def test_pay_request_visibility_lands_in_feed(self):
        status, payment, _ = base.request(self.port, "POST", "/requests/rq_1/pay", body={
            "visibility": "private",
        }, headers={**self.ada, "Idempotency-Key": "act-1"})
        self.assertEqual(status, 201)
        status, payload, _ = base.request(self.port, "GET", "/activity", headers=self.cy)
        self.assertNotIn(payment["payment_id"], self.ids(payload))
        status, payload, _ = base.request(self.port, "GET", "/activity", headers=self.bob)
        self.assertIn(payment["payment_id"], self.ids(payload), "receiver sees private payment")
        self.assertEqual(payload["payments"][0]["request_id"], "rq_1")

    def test_public_payment_from_pay_request_visible_to_all(self):
        status, payment, _ = base.request(self.port, "POST", "/requests/rq_1/pay", body={},
                                          headers={**self.ada, "Idempotency-Key": "act-2"})
        for auth in (self.ada, self.bob, self.cy):
            status, payload, _ = base.request(self.port, "GET", "/activity", headers=auth)
            self.assertIn(payment["payment_id"], self.ids(payload))

    def test_pagination_and_has_more(self):
        status, payload, _ = base.request(self.port, "GET", "/activity?limit=1", headers=self.ada)
        self.assertEqual(len(payload["payments"]), 1)
        self.assertEqual(payload["has_more"], True)
        status, payload, _ = base.request(self.port, "GET", "/activity?limit=50", headers=self.ada)
        self.assertEqual(payload["has_more"], False)

    def test_invalid_limit_offset_422(self):
        for query in ("limit=0", "limit=201", "limit=2.5", "offset=-3", "offset=4.0", "offset="):
            status, payload, _ = base.request(self.port, "GET", f"/activity?{query}", headers=self.ada)
            self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"), query)

    def test_items_share_payment_shape(self):
        status, payload, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        for p in payload["payments"]:
            self.assertEqual(set(p.keys()), {
                "payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                "amount", "currency", "note", "visibility", "request_id", "settlement_id",
                "authorization_id", "refund_of", "created_at",
            })

    def test_requires_auth(self):
        status, payload, _ = base.request(self.port, "GET", "/activity")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()