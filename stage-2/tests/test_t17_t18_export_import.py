import copy
import unittest

import base
from pocketful import state as state_module
from pocketful.state import verify_password

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
    "payments": [
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 500, "note": "coffee", "visibility": "public"},
    ],
    "requests": [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
         "amount": 1200, "note": "taxi", "status": "pending"},
    ],
}


def login(port, email, password="correct horse"):
    status, payload, _ = base.request(port, "POST", "/auth/login", body={
        "email": email, "password": password,
    })
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


def build_busy_state(port):
    assert base.request(port, "POST", "/_test/reset", body=FIXTURE)[0] == 204
    ada = login(port, "ada@example.com")
    bob = login(port, "bob@example.com")
    op = login(port, "op@example.com")
    status, payment, _ = base.request(port, "POST", "/payments", body={
        "to_handle": "bob", "amount": 700, "note": "dinner", "visibility": "public",
    }, headers={**ada, "Idempotency-Key": "done-key"})
    assert status == 201
    status, failed, _ = base.request(port, "POST", "/payments", body={
        "to_handle": "ghost", "amount": 5,
    }, headers={**ada, "Idempotency-Key": "failed-key"})
    assert status == 404
    status, paid_payment, _ = base.request(port, "POST", "/requests/rq_1/pay", body={
        "visibility": "private",
    }, headers={**ada, "Idempotency-Key": "pay-rq"})
    assert status == 201
    status, settlement, _ = base.request(port, "POST", "/settlements", body={
        "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 100}],
    }, headers={**op, "Idempotency-Key": "settle-1"})
    assert status == 201, settlement
    return {"ada": ada, "bob": bob, "op": op, "payment": payment,
            "paid_payment": paid_payment, "settlement": settlement}


def export(port):
    status, payload, _ = base.request(port, "GET", "/_test/export")
    assert status == 200
    return payload


class TestExport(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_export_shape(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        status, payload, _ = base.request(self.port, "GET", "/_test/export")
        self.assertEqual(status, 200)
        self.assertEqual(payload["track"], "pocketful")
        self.assertEqual(payload["format_version"], 2)
        self.assertIsInstance(payload["state"], dict)

    def test_export_is_atomic_snapshot(self):
        build_busy_state(self.port)
        snapshot = export(self.port)
        self.assertEqual(len(snapshot["state"]["payments"]), 4)
        ada = login(self.port, "ada@example.com")
        status, extra, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 1,
        }, headers={**ada, "Idempotency-Key": "after-snapshot"})
        self.assertEqual(status, 201)
        snapshot_ids = [p["id"] for p in snapshot["state"]["payments"]]
        self.assertNotIn(extra["payment_id"], snapshot_ids)
        self.assertEqual(len(snapshot["state"]["payments"]), 4,
                         "subsequent writes must not change an already-taken export")


class TestImport(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        self.before = build_busy_state(self.port)
        self.exported = export(self.port)

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_round_trip_is_behavioral_noop(self):
        status, _, _ = base.request(self.port, "POST", "/_test/import", body=self.exported)
        self.assertEqual(status, 204)
        state = state_module.STATE
        self.assertEqual(state.currency, "EUR")
        self.assertEqual(state.minor_units, 2)
        self.assertEqual({u.id: u.balance for u in state.users.values()}, {
            "u_op": 0, "u_ada": 8000, "u_bob": 4400, "u_cy": 100,
        })
        self.assertEqual(len(state.payments), 4)
        self.assertEqual(state.requests["rq_1"].status, "paid")
        self.assertEqual(state.requests["rq_1"].payment_id, self.before["paid_payment"]["payment_id"])
        self.assertEqual([p.id for p in state.payments], [p["id"] for p in self.exported["state"]["payments"]])
        self.assertEqual([p.effective_at for p in state.payments],
                         [p["effective_at"] for p in self.exported["state"]["payments"]])
        self.assertEqual(state.settlement_operator_ids, {"u_op"})

    def test_old_token_still_authenticates(self):
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.before["bob"])
        self.assertEqual(status, 200)
        self.assertEqual(me["handle"], "bob")

    def test_pre_import_password_still_logs_in(self):
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        status, payload, _ = base.request(self.port, "POST", "/auth/login", body={
            "email": "ada@example.com", "password": "correct horse",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["user_id"], "u_ada")

    def test_completed_idempotency_key_still_replays(self):
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        ada = self.before["ada"]
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 700, "note": "dinner", "visibility": "public",
        }, headers={**ada, "Idempotency-Key": "done-key"})
        self.assertEqual(status, 200)
        self.assertEqual(payload, self.before["payment"])

    def test_failed_key_still_fresh_after_import(self):
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        ada = self.before["ada"]
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 33,
        }, headers={**ada, "Idempotency-Key": "failed-key"})
        self.assertEqual(status, 201, "previously-4xx key must remain a fresh first use")

    def test_import_replaces_not_merges(self):
        stranger = base.request(self.port, "POST", "/auth/signup", body={
            "email": "stranger@example.com", "password": "password1", "display_name": "S",
        })[1]
        self.assertIn(stranger["user_id"], state_module.STATE.users)
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        self.assertNotIn(stranger["user_id"], state_module.STATE.users,
                         "import removes destination users and credentials")
        status, _, _ = base.request(self.port, "GET", "/me", headers={
            "Authorization": f"Bearer {stranger['token']}",
        })
        self.assertEqual(status, 401)

    def test_repeated_import_no_duplication(self):
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        state = state_module.STATE
        self.assertEqual(len(state.payments), 4)
        self.assertEqual(len(state.users), 4)
        ada = self.before["ada"]
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 700, "note": "dinner", "visibility": "public",
        }, headers={**ada, "Idempotency-Key": "done-key"})
        self.assertEqual(status, 200)
        self.assertEqual(payload, self.before["payment"])

    def test_invalid_json_400(self):
        status, payload, _ = base.request_raw(self.port, "POST", "/_test/import", data=b"{nope")
        self.assertEqual((status, payload["error"]["code"]), (400, "malformed_request"))

    def test_wrong_track_version_missing_state_422_unchanged(self):
        before = state_module.STATE
        cases = [
            {"track": "other", "format_version": 1, "state": self.exported["state"]},
            {"track": "pocketful", "format_version": 3, "state": self.exported["state"]},
            {"track": "pocketful", "format_version": 1},
            {"track": "pocketful", "format_version": 1, "state": {"zzz": 1}},
        ]
        for i, body in enumerate(cases):
            status, payload, _ = base.request(self.port, "POST", "/_test/import", body=body)
            self.assertEqual(status, 422, repr(body))
            self.assertEqual(payload["error"]["code"], "validation_failed", repr(body))
        self.assertIs(state_module.STATE, before)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.before["ada"])
        self.assertEqual(status, 200)

    def test_invalid_state_negative_balance_422_unchanged(self):
        corrupted = copy.deepcopy(self.exported)
        for user in corrupted["state"]["users"]:
            if user["id"] == "u_ada":
                user["balance"] = -5
        before = state_module.STATE
        status, payload, _ = base.request(self.port, "POST", "/_test/import", body=corrupted)
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))
        self.assertIs(state_module.STATE, before)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.before["ada"])
        self.assertEqual(me["balance"], 8000)

    def test_reset_clears_imported_state(self):
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        self.assertEqual(status, 204)
        state = state_module.STATE
        self.assertEqual(len(state.payments), 1)
        self.assertEqual(state.requests["rq_1"].status, "pending")
        self.assertEqual(len(state.idempotency), 0)
        self.assertEqual(len(state.tokens), 0)

    def test_import_preserves_settlement_operators(self):
        base.request(self.port, "POST", "/_test/import", body=self.exported)
        op = self.before["op"]
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 10}],
        }, headers={**op, "Idempotency-Key": "post-import-settle"})
        self.assertEqual(status, 201)

    def test_non_object_body_400(self):
        status, payload, _ = base.request_raw(self.port, "POST", "/_test/import", data=b"[1]")
        self.assertEqual((status, payload["error"]["code"]), (400, "malformed_request"))


if __name__ == "__main__":
    unittest.main()