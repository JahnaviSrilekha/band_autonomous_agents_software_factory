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
    "requests": [],
}


def login(port, email, password="correct horse"):
    status, payload, _ = base.request(port, "POST", "/auth/login", body={
        "email": email, "password": password,
    })
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


def make_requests(port):
    ada, bob, cy = login(port, "ada@example.com"), login(port, "bob@example.com"), login(port, "cy@example.com")
    created = []
    for i in range(6):
        requester = [cy, bob][i % 2]
        payer = ada
        status, payload, _ = base.request(port, "POST", "/requests", body={
            "payer_handle": "ada", "amount": 100 + i, "note": f"n{i}",
        }, headers={**requester, "Idempotency-Key": f"mk-{i}"})
        assert status == 201
        created.append(payload)
    for i, request in enumerate(created[:2]):
        status, _, _ = base.request(port, "POST", f"/requests/{request['request_id']}/pay",
                                    body={}, headers={**ada, "Idempotency-Key": f"mp-{i}"})
        assert status == 201
    status, _, _ = base.request(port, "POST", f"/requests/{created[2]['request_id']}/decline",
                                headers=ada)
    assert status == 200
    status, _, _ = base.request(port, "POST", f"/requests/{created[3]['request_id']}/cancel",
                                headers={**(bob if created[3]['requester_handle'] == 'bob' else cy)})
    assert status == 200
    return created, ada, bob, cy


class TestListRequests(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        assert base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
        self.created, self.ada, self.bob, self.cy = make_requests(self.port)

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_lists_only_own_requests_both_directions(self):
        status, payload, _ = base.request(self.port, "GET", "/requests", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(set(payload.keys()), {"requests", "has_more"})
        self.assertEqual(len(payload["requests"]), 6)
        for r in payload["requests"]:
            self.assertTrue(r["payer_handle"] == "ada" or r["requester_handle"] == "ada")

    def test_cy_sees_only_incoming_and_own(self):
        status, payload, _ = base.request(self.port, "GET", "/requests", headers=self.cy)
        self.assertEqual(len(payload["requests"]), 3)
        for r in payload["requests"]:
            self.assertEqual(r["payer_handle"], "ada")
            self.assertEqual(r["requester_handle"], "cy")

    def test_direction_filters(self):
        status, incoming, _ = base.request(self.port, "GET", "/requests?direction=incoming", headers=self.ada)
        self.assertEqual(incoming["has_more"], False)
        self.assertEqual(len(incoming["requests"]), 6)
        status, outgoing, _ = base.request(self.port, "GET", "/requests?direction=outgoing", headers=self.ada)
        self.assertEqual(len(outgoing["requests"]), 0)
        status, incoming_cy, _ = base.request(self.port, "GET", "/requests?direction=incoming", headers=self.cy)
        self.assertEqual(len(incoming_cy["requests"]), 0)
        status, outgoing_cy, _ = base.request(self.port, "GET", "/requests?direction=outgoing", headers=self.cy)
        self.assertEqual(len(outgoing_cy["requests"]), 3)

    def test_status_filters(self):
        status, paid, _ = base.request(self.port, "GET", "/requests?status=paid", headers=self.ada)
        self.assertEqual(len(paid["requests"]), 2)
        self.assertTrue(all(r["status"] == "paid" for r in paid["requests"]))
        status, declined, _ = base.request(self.port, "GET", "/requests?status=declined", headers=self.ada)
        self.assertEqual(len(declined["requests"]), 1)
        status, cancelled, _ = base.request(self.port, "GET", "/requests?status=cancelled", headers=self.ada)
        self.assertEqual(len(cancelled["requests"]), 1)
        status, pending, _ = base.request(self.port, "GET", "/requests?status=pending", headers=self.ada)
        self.assertEqual(len(pending["requests"]), 2)

    def test_newest_first_ordering(self):
        status, payload, _ = base.request(self.port, "GET", "/requests", headers=self.ada)
        amounts = [r["amount"] for r in payload["requests"]]
        self.assertEqual(amounts, [105, 104, 103, 102, 101, 100])

    def test_pagination_has_more(self):
        status, page1, _ = base.request(self.port, "GET", "/requests?limit=4", headers=self.ada)
        self.assertEqual(len(page1["requests"]), 4)
        self.assertEqual(page1["has_more"], True)
        status, page2, _ = base.request(self.port, "GET", "/requests?limit=4&offset=4", headers=self.ada)
        self.assertEqual(len(page2["requests"]), 2)
        self.assertEqual(page2["has_more"], False)
        ids1 = {r["request_id"] for r in page1["requests"]}
        ids2 = {r["request_id"] for r in page2["requests"]}
        self.assertEqual(ids1 & ids2, set())

    def test_invalid_query_values_422(self):
        cases = [
            "direction=both",
            "status=archived",
            "limit=0",
            "limit=201",
            "limit=4.0",
            "limit=+4",
            "limit=1e9",
            "limit=abc",
            "limit=",
            "offset=-1",
            "offset=1.5",
            "offset=",
        ]
        for query in cases:
            status, payload, _ = base.request(self.port, "GET", f"/requests?{query}", headers=self.ada)
            self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"), query)

    def test_boundary_limit_offset_valid(self):
        status, payload, _ = base.request(self.port, "GET", "/requests?limit=1&offset=5", headers=self.ada)
        self.assertEqual(len(payload["requests"]), 1)
        self.assertEqual(payload["has_more"], False)
        status, payload, _ = base.request(self.port, "GET", "/requests?limit=200", headers=self.ada)
        self.assertEqual(len(payload["requests"]), 6)

    def test_unknown_query_params_ignored(self):
        status, payload, _ = base.request(self.port, "GET", "/requests?zzz=1&limit=2", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["requests"]), 2)

    def test_paid_request_carries_payment_id(self):
        status, payload, _ = base.request(self.port, "GET", "/requests?status=paid", headers=self.ada)
        for r in payload["requests"]:
            self.assertIsNotNone(r["payment_id"])

    def test_requires_auth(self):
        status, payload, _ = base.request(self.port, "GET", "/requests")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()