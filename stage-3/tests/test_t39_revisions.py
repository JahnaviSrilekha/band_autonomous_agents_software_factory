import copy
import unittest
from datetime import datetime, timedelta, timezone

import base
from pocketful import state as state_module
from pocketful.state import as_dt

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
    ],
}

STAMP = "2026-09-01T10:00:00+00:00"


def seeded(payment_entries, balances=None):
    fixture = copy.deepcopy(FIXTURE)
    fixture["payments"] = payment_entries
    if balances:
        for entry in fixture["users"]:
            if entry["id"] in balances:
                entry["balance"] = balances[entry["id"]]
    return fixture


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT39SeededTimestamps(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_seeded_created_at_becomes_revision_1(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 500, "note": "lunch", "created_at": STAMP},
        ]))
        self.assertEqual(status, 204)
        payment = state_module.STATE.payments[0]
        self.assertEqual(len(payment.revisions), 1)
        revision = payment.revisions[0]
        self.assertEqual(revision.revision, 1)
        self.assertEqual(revision.amount, 500)
        self.assertEqual(revision.effective_at, STAMP)
        self.assertEqual(revision.recorded_at, STAMP)
        self.assertEqual(revision.reason, "")

    def test_seeded_created_at_echoed_by_activity(self):
        base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 500, "created_at": STAMP},
        ]))
        status, payload, _ = base.request(self.port, "GET", "/activity",
                                          headers=login(self.port, "ada@example.com"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["payments"][0]["created_at"], STAMP)

    def test_omitted_created_at_uses_reset_instant_before_api_payments(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100},
        ]))
        self.assertEqual(status, 204)
        seeded_created = state_module.STATE.payments[0].effective_at
        headers = login(self.port, "ada@example.com")
        headers["Idempotency-Key"] = "k-after-reset"
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 200, "note": "after reset"}, headers=headers)
        self.assertEqual(status, 201)
        api_created = payload["created_at"]
        self.assertLess(as_dt(seeded_created), as_dt(api_created))

    def test_api_created_payment_gets_revision_1(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        headers = login(self.port, "ada@example.com")
        headers["Idempotency-Key"] = "k-rev1"
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 300}, headers=headers)
        self.assertEqual(status, 201)
        payment = next(p for p in state_module.STATE.payments if p.id == payload["payment_id"])
        self.assertEqual(len(payment.revisions), 1)
        self.assertEqual(payment.revisions[0].amount, 300)
        self.assertEqual(payment.revisions[0].reason, "")
        self.assertEqual(payment.revisions[0].effective_at, payment.effective_at)
        self.assertEqual(payment.revisions[0].recorded_at, payment.recorded_at)

    def test_future_seeded_created_at_422_no_state_change(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 100},
        ]))
        self.assertEqual(status, 204)
        payments_before = list(state_module.STATE.payments)
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_x", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 100, "created_at": future},
        ]))
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")
        self.assertEqual([p.id for p in state_module.STATE.payments],
                         [p.id for p in payments_before])

    def test_naive_seeded_created_at_422(self):
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_x", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 100, "created_at": "2026-09-01T10:00:00"},
        ]))
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_bare_date_seeded_created_at_422(self):
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_x", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 100, "created_at": "2026-09-01"},
        ]))
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")


class TestT39OpeningBalancesAndHistory(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_fixture_balance_unchanged_by_seeded_payments(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 700},
            {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 200},
        ]))
        self.assertEqual(status, 204)
        status, payload, _ = base.request(self.port, "GET", "/me",
                                          headers=login(self.port, "ada@example.com"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 10000)
        self.assertEqual(state_module.STATE.users["u_ada"].balance, 10000)

    def test_opening_balances_derived_from_seeded_net(self):
        base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 300},
            {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 100},
        ]))
        state = state_module.STATE
        self.assertEqual(state.users["u_ada"].opening_balance, 10000 + 200)
        self.assertEqual(state.users["u_bob"].opening_balance, 2500 - 200)

    def test_signup_opening_balance_zero(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        status, payload, _ = base.request(self.port, "POST", "/auth/signup", body={
            "email": "carol@example.com", "password": "correct horse",
            "display_name": "Carol"})
        self.assertEqual(status, 201)
        user = state_module.STATE.users[payload["user_id"]]
        self.assertEqual(user.opening_balance, 0)
        self.assertEqual(user.balance, 0)

    def test_overdrawing_seeded_history_422_no_state_change(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        self.assertEqual(status, 204)
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=seeded([
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 20000},
        ]))
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")
        self.assertEqual(state_module.STATE.users["u_ada"].id, "u_ada")
        self.assertEqual(state_module.STATE.payments, [])

    def test_history_negative_at_later_boundary_422(self):
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=seeded(
            [
                {"id": "p_1", "from_user_id": "u_bob", "to_user_id": "u_ada",
                 "amount": 500, "created_at": "2026-08-01T09:00:00+00:00"},
                {"id": "p_2", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 9000, "created_at": "2026-08-02T09:00:00+00:00"},
                {"id": "p_3", "from_user_id": "u_bob", "to_user_id": "u_ada",
                 "amount": 9000, "created_at": "2026-08-03T09:00:00+00:00"},
            ],
            balances={"u_ada": 500, "u_bob": 2000}))
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_zero_net_history_accepted(self):
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=seeded(
            [
                {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 9000, "created_at": "2026-08-01T09:00:00+00:00"},
                {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada",
                 "amount": 9000, "created_at": "2026-08-02T09:00:00+00:00"},
            ],
            balances={"u_ada": 10000, "u_bob": 2500}))
        self.assertEqual(status, 204)
        state = state_module.STATE
        self.assertEqual(state.users["u_ada"].opening_balance, 10000)
        self.assertEqual(state.users["u_bob"].opening_balance, 2500)


class TestT39RevisionAppend(unittest.TestCase):
    def test_append_revision_records_strictly_increasing(self):
        from pocketful.state import Payment

        payment = Payment("p_1", "u_ada", "u_bob", 500, "", "public", None, None,
                          STAMP, STAMP, 1)
        first = payment.append_revision(400, STAMP, STAMP, "fix")
        self.assertEqual(first.revision, 2)
        self.assertGreater(as_dt(first.recorded_at), as_dt(STAMP))
        again = payment.append_revision(300, STAMP, first.recorded_at, "again")
        self.assertGreater(as_dt(again.recorded_at), as_dt(first.recorded_at))
        self.assertEqual(again.revision, 3)
        self.assertEqual(payment.amount, 300)

    def test_append_revision_future_recorded_kept_as_given(self):
        from pocketful.state import Payment

        payment = Payment("p_1", "u_ada", "u_bob", 500, "", "public", None, None,
                          STAMP, STAMP, 1)
        later = "2026-09-02T10:00:00+00:00"
        revision = payment.append_revision(400, later, later, "fix")
        self.assertEqual(revision.recorded_at, later)
        self.assertEqual(payment.amount, 400)


if __name__ == "__main__":
    unittest.main()