import copy
import unittest
from datetime import datetime, timedelta, timezone

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
    ],
    "authorizations": [
        {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 2000, "note": "deposit", "visibility": "public",
         "status": "open", "expires_at": "2099-01-01T12:00:00+00:00"},
    ],
}


def _login(port, email="ada@example.com"):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


def _future(days=1):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


class TestT21MeHolds(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        self.headers = _login(self.port)

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_me_shape_with_open_hold(self):
        status, payload, _ = base.request(self.port, "GET", "/me", headers=self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(payload["user_id"], "u_ada")
        self.assertEqual(payload["display_name"], "Ada")
        self.assertEqual(payload["handle"], "ada")
        self.assertEqual(payload["balance"], 10000)
        self.assertEqual(payload["total"], 10000)
        self.assertEqual(payload["held"], 2000)
        self.assertEqual(payload["available"], 8000)
        self.assertEqual(payload["currency"], "EUR")
        self.assertEqual(payload["minor_units"], 2)

    def test_balance_equals_total_always(self):
        status, payload, _ = base.request(self.port, "GET", "/me", headers=self.headers)
        self.assertEqual(payload["balance"], payload["total"])

    def test_receiver_of_a_hold_has_zero_held(self):
        status, payload, _ = base.request(
            self.port, "GET", "/me",
            headers=_login(self.port, "bob@example.com"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["held"], 0)
        self.assertEqual(payload["available"], payload["total"])

    def test_no_open_holds_all_agree(self):
        fixture = copy.deepcopy(FIXTURE)
        del fixture["authorizations"]
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        headers = _login(self.port)
        status, payload, _ = base.request(self.port, "GET", "/me", headers=headers)
        self.assertEqual(payload["balance"], payload["total"])
        self.assertEqual(payload["total"], payload["available"])
        self.assertEqual(payload["held"], 0)

    def test_seeded_hold_reflected_immediately_after_reset(self):
        status, payload, _ = base.request(self.port, "GET", "/me", headers=self.headers)
        self.assertEqual(payload["available"], 8000)
        self.assertEqual(payload["held"], 2000)

    def test_clock_expired_stored_open_hold_contributes_zero(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["expires_at"] = _past()
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        headers = _login(self.port)
        status, payload, _ = base.request(self.port, "GET", "/me", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(payload["held"], 0)
        self.assertEqual(payload["available"], payload["total"])

    def test_hold_sum_reduction_matches_captured_amount(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"] = [
            {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 2000, "status": "open", "captured_amount": 500,
             "expires_at": _future()},
            {"id": "a_2", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 1000, "status": "open", "expires_at": _future()},
        ]
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        headers = _login(self.port)
        status, payload, _ = base.request(self.port, "GET", "/me", headers=headers)
        self.assertEqual(payload["held"], 2500)
        self.assertEqual(payload["available"], 7500)

    def test_multiple_holds_sum(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"].append(
            {"id": "a_2", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 300, "status": "open", "expires_at": _future()})
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        headers = _login(self.port)
        status, payload, _ = base.request(self.port, "GET", "/me", headers=headers)
        self.assertEqual(payload["held"], 2300)
        self.assertEqual(payload["available"], 7700)

    def test_unauthenticated_still_401(self):
        status, payload, _ = base.request(self.port, "GET", "/me")
        self.assertEqual(status, 401)

    def test_conservation_total_unchanged_by_holds(self):
        status, payload, _ = base.request(self.port, "GET", "/me", headers=self.headers)
        self.assertEqual(payload["total"], 10000)
        state = state_module.STATE
        self.assertEqual(state.users["u_ada"].balance, 10000)
        self.assertEqual(state.users["u_bob"].balance, 2500)


if __name__ == "__main__":
    unittest.main()