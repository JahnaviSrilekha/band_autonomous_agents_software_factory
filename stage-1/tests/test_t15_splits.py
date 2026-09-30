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


def split(port, auth, body, key="k-split-1"):
    headers = dict(auth or {})
    headers["Idempotency-Key"] = key
    return base.request(port, "POST", "/splits", body=body, headers=headers)


class TestSplits(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        assert base.request(self.port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_split_happy_path_shape_and_rules(self):
        status, payload, _ = split(self.port, self.ada, {
            "amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner",
        })
        self.assertEqual(status, 201)
        self.assertEqual(set(payload.keys()), {
            "split_id", "amount", "currency", "note", "shares", "requests", "created_at",
        })
        self.assertEqual(payload["shares"], [
            {"handle": "ada", "amount": 1000},
            {"handle": "bob", "amount": 1000},
            {"handle": "cy", "amount": 1000},
        ])
        self.assertEqual(len(payload["requests"]), 2, "one request per non-caller participant")
        for request in payload["requests"]:
            self.assertEqual(set(request.keys()), {
                "request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
                "amount", "currency", "note", "status", "payment_id", "created_at",
            })
            self.assertEqual(request["status"], "pending")
            self.assertEqual(request["requester_handle"], "ada")
        self.assertEqual([r["payer_handle"] for r in payload["requests"]], ["bob", "cy"])
        self.assertEqual(payload["requests"][0]["amount"], 1000)

    def test_split_remainder_follows_given_order(self):
        status, payload, _ = split(self.port, self.ada, {
            "amount": 1000, "participant_handles": ["ada", "bob", "cy"],
        }, key="s-rem")
        self.assertEqual([s["amount"] for s in payload["shares"]], [334, 333, 333])
        status, payload, _ = split(self.port, self.ada, {
            "amount": 1000, "participant_handles": ["cy", "bob", "ada"],
        }, key="s-rem2")
        self.assertEqual([s["amount"] for s in payload["shares"]], [334, 333, 333])
        self.assertEqual([s["handle"] for s in payload["shares"]], ["cy", "bob", "ada"])

    def test_split_caller_omitted_from_participants(self):
        status, payload, _ = split(self.port, self.ada, {
            "amount": 2000, "participant_handles": ["bob", "cy"],
        }, key="s-om")
        self.assertEqual(status, 201)
        self.assertEqual([s["handle"] for s in payload["shares"]], ["bob", "cy"])
        self.assertEqual([r["payer_handle"] for r in payload["requests"]], ["bob", "cy"])
        self.assertEqual(len(state_module.STATE.requests), 2)

    def test_split_caller_only_creates_zero_requests(self):
        status, payload, _ = split(self.port, self.ada, {
            "amount": 500, "participant_handles": ["ada"],
        }, key="s-only")
        self.assertEqual(status, 201)
        self.assertEqual(payload["shares"], [{"handle": "ada", "amount": 500}])
        self.assertEqual(payload["requests"], [])

    def test_zero_share_still_produces_request(self):
        status, payload, _ = split(self.port, self.ada, {
            "amount": 1, "participant_handles": ["ada", "bob", "cy"],
        }, key="s-zero")
        self.assertEqual(status, 201)
        self.assertEqual([s["amount"] for s in payload["shares"]], [1, 0, 0])
        requests = payload["requests"]
        self.assertEqual(len(requests), 2)
        self.assertEqual([r["amount"] for r in requests], [0, 0])
        self.assertEqual(len(state_module.STATE.requests), 2)

    def test_split_checks_nobody_balance(self):
        status, payload, _ = split(self.port, self.ada, {
            "amount": 1000000000, "participant_handles": ["bob", "cy"],
        }, key="s-bal")
        self.assertEqual(status, 201)
        self.assertEqual(state_module.STATE.users["u_ada"].balance, 10000)

    def test_amount_case_table_422(self):
        for amount in (0, -1, 1000000001, 1.5, "5", True, None):
            status, payload, _ = split(self.port, self.ada, {
                "amount": amount, "participant_handles": ["bob"],
            }, key=f"s{amount!r}")
            self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"), repr(amount))

    def test_participant_validation_422(self):
        for handles in ([], ["bob", "bob"], ["bob", "bob", "cy"]):
            status, payload, _ = split(self.port, self.ada, {
                "amount": 100, "participant_handles": handles,
            }, key=f"sh{handles!r}")
            self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"), repr(handles))

    def test_participant_handles_missing_422_wrong_type_400(self):
        status, payload, _ = split(self.port, self.ada, {"amount": 100}, key="s-missing")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))
        status, payload, _ = split(self.port, self.ada, {
            "amount": 100, "participant_handles": "bob",
        }, key="s-type")
        self.assertEqual((status, payload["error"]["code"]), (400, "malformed_request"))

    def test_unknown_handle_404(self):
        status, payload, _ = split(self.port, self.ada, {
            "amount": 100, "participant_handles": ["bob", "ghost"],
        }, key="s-404")
        self.assertEqual((status, payload["error"]["code"]), (404, "not_found"))
        self.assertEqual(len(state_module.STATE.requests), 0)

    def test_note_over_200_422(self):
        status, payload, _ = split(self.port, self.ada, {
            "amount": 100, "participant_handles": ["bob"], "note": "x" * 201,
        }, key="s-note")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))

    def test_missing_idempotency_key_400(self):
        status, payload, _ = base.request(self.port, "POST", "/splits", body={
            "amount": 100, "participant_handles": ["bob"],
        }, headers=self.ada)
        self.assertEqual((status, payload["error"]["code"]), (400, "missing_idempotency_key"))

    def test_replay_and_reuse(self):
        first = split(self.port, self.ada, {
            "amount": 900, "participant_handles": ["bob", "cy"],
        }, key="sr")
        second = split(self.port, self.ada, {
            "participant_handles": ["bob", "cy"], "amount": 900,
        }, key="sr")
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(len(state_module.STATE.requests), 2)
        third = split(self.port, self.ada, {
            "amount": 901, "participant_handles": ["bob", "cy"],
        }, key="sr")
        self.assertEqual((third[0], third[1]["error"]["code"]), (409, "idempotency_key_reuse"))

    def test_paid_in_full_conservation(self):
        funded = {
            "currency": "EUR",
            "minor_units": 2,
            "users": [
                {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
                 "display_name": "Ada", "handle": "ada", "balance": 10000},
                {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
                 "display_name": "Bob", "handle": "bob", "balance": 400},
                {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
                 "display_name": "Cy", "handle": "cy", "balance": 400},
            ],
            "payments": [],
            "requests": [],
        }
        assert base.request(self.port, "POST", "/_test/reset", body=funded)[0] == 204
        split(self.port, self.ada, {
            "amount": 1000, "participant_handles": ["ada", "bob", "cy"],
        }, key="s-cons")
        for request in list(state_module.STATE.requests.values()):
            payer_auth = login(self.port, f"{state_module.STATE.users[request.payer_id].handle}@example.com")
            status, _, _ = base.request(self.port, "POST", f"/requests/{request.id}/pay", body={},
                                        headers={**payer_auth, "Idempotency-Key": f"pay-{request.id}"})
            self.assertEqual(status, 201)
        total = sum(u.balance for u in state_module.STATE.users.values())
        self.assertEqual(total, 10800)


if __name__ == "__main__":
    unittest.main()