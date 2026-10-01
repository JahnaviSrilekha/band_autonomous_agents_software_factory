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
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 0},
    ],
    "payments": [],
    "requests": [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
         "amount": 500, "note": "taxi", "status": "pending"},
        {"id": "rq_2", "requester_id": "u_cy", "payer_id": "u_bob",
         "amount": 700, "note": "lunch", "status": "pending"},
    ],
}


def login(port, email, password="correct horse"):
    status, payload, _ = base.request(port, "POST", "/auth/login", body={
        "email": email, "password": password,
    })
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestDeclineCancel(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        assert base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_decline_happy_path_200(self):
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/decline", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "declined")
        self.assertEqual(set(payload.keys()), {
            "request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
            "amount", "currency", "note", "status", "payment_id", "created_at",
        })

    def test_decline_twice_200_current_state(self):
        base.request(self.port, "POST", "/requests/rq_1/decline", headers=self.ada)
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/decline", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "declined")

    def test_decline_paid_request_409(self):
        base.request(self.port, "POST", "/requests/rq_1/pay", body={}, headers={
            **self.ada, "Idempotency-Key": "p1",
        })
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/decline", headers=self.ada)
        self.assertEqual((status, payload["error"]["code"]), (409, "request_not_pending"))

    def test_decline_cancelled_request_409(self):
        base.request(self.port, "POST", "/requests/rq_1/cancel", headers=self.bob)
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/decline", headers=self.ada)
        self.assertEqual((status, payload["error"]["code"]), (409, "request_not_pending"))

    def test_decline_not_payer_403(self):
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/decline", headers=self.cy)
        self.assertEqual((status, payload["error"]["code"]), (403, "forbidden"))

    def test_decline_unknown_404(self):
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_x/decline", headers=self.ada)
        self.assertEqual((status, payload["error"]["code"]), (404, "not_found"))

    def test_cancel_happy_path_and_repeat(self):
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/cancel", headers=self.bob)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "cancelled")
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/cancel", headers=self.bob)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "cancelled")

    def test_cancel_declined_request_409(self):
        base.request(self.port, "POST", "/requests/rq_1/decline", headers=self.ada)
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/cancel", headers=self.bob)
        self.assertEqual((status, payload["error"]["code"]), (409, "request_not_pending"))

    def test_cancel_not_requester_403(self):
        status, payload, _ = base.request(self.port, "POST", "/requests/rq_1/cancel", headers=self.ada)
        self.assertEqual((status, payload["error"]["code"]), (403, "forbidden"))

    def test_idempotency_key_on_decline_ignored_entirely(self):
        status, _, _ = base.request(self.port, "POST", "/requests/rq_1/decline", headers={
            **self.ada, "Idempotency-Key": "shared-1",
        })
        self.assertEqual(status, 200)
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 10,
        }, headers={**self.ada, "Idempotency-Key": "shared-1"})
        self.assertEqual(status, 201, "key used on decline must still be fresh for a write path")

    def test_idempotency_key_on_cancel_ignored(self):
        status, _, _ = base.request(self.port, "POST", "/requests/rq_1/cancel", headers={
            **self.bob, "Idempotency-Key": "shared-2",
        })
        self.assertEqual(status, 200)
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 10,
        }, headers={**self.ada, "Idempotency-Key": "shared-2"})
        self.assertEqual(status, 201)


if __name__ == "__main__":
    unittest.main()