import time
import unittest
import urllib.parse

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "authorization_ttl_seconds": 600,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 12000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 4000},
    ],
    "payments": [
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 3000, "created_at": "2026-08-10T09:00:00+00:00"},
        {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada",
         "amount": 4000, "created_at": "2026-08-12T09:00:00+00:00"},
    ],
    "authorizations": [
        {"id": "a_hold", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 6000, "status": "open",
         "created_at": "2026-08-05T09:00:00+00:00",
         "expires_at": "2099-01-01T00:00:00+00:00"},
    ],
}


def q(value):
    return urllib.parse.quote(value, safe="")


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT44HistoricalHolds(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def me(self, query="", headers=None):
        return base.request(self.port, "GET", f"/me{query}", headers=headers or self.ada)

    def test_all_four_money_fields_one_consistent_view(self):
        status, payload, _ = self.me("?as_of=2026-08-10T12:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], payload["total"])
        self.assertEqual(payload["available"], payload["total"] - payload["held"])
        self.assertEqual(payload["total"], 8000)
        self.assertEqual(payload["held"], 6000)
        self.assertEqual(payload["available"], 2000)

    def test_seeded_open_hold_held_from_its_created_at(self):
        status, payload, _ = self.me("?as_of=2026-08-04T09:00:00%2B00:00")
        self.assertEqual(payload["held"], 0)
        self.assertEqual(payload["total"], 11000)
        status, payload, _ = self.me("?as_of=2026-08-05T09:00:00%2B00:00")
        self.assertEqual(payload["held"], 6000)

    def test_seeded_open_hold_without_created_at_assumed_created_at_reset(self):
        fixture = {
            "currency": "EUR", "minor_units": 2,
            "users": FIXTURE["users"],
            "authorizations": [
                {"id": "a_reset", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 2000, "status": "open",
                 "expires_at": "2099-01-01T00:00:00+00:00"},
            ],
        }
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        ada = login(self.port, "ada@example.com")
        status, payload, _ = self.me("?as_of=2020-01-01T00:00:00%2B00:00", headers=ada)
        self.assertEqual(payload["held"], 0)
        status, payload, _ = self.me(headers=ada)
        self.assertEqual(payload["held"], 2000)

    def test_nonfinal_capture_reduces_held_at_capture_time(self):
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 4000, "note": "metered"},
            headers={**self.ada, "Idempotency-Key": "k-auth"})
        self.assertEqual(status, 201, payload)
        auth_id = payload["authorization_id"]
        before = payload["created_at"]
        status, capture, _ = base.request(self.port, "POST",
                                          f"/authorizations/{auth_id}/capture",
                                          body={"amount": 1500, "final": False},
                                          headers={**self.bob, "Idempotency-Key": "k-cap1"})
        self.assertEqual(status, 201, capture)
        capture_at = capture["created_at"]
        status, payload, _ = self.me(f"?as_of={q(before)}")
        self.assertEqual(payload["held"], 6000 + 4000)
        status, payload, _ = self.me(f"?as_of={q(capture_at)}")
        self.assertEqual(payload["held"], 6000 + 2500)

    def test_closed_at_null_while_open(self):
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 500}, headers={**self.ada, "Idempotency-Key": "k-a"})
        self.assertEqual(status, 201)
        self.assertIsNone(payload["closed_at"])
        status, payload, _ = base.request(self.port, "GET", "/authorizations",
                                          headers=self.ada)
        entries = {a["authorization_id"]: a for a in payload["authorizations"]}
        self.assertIsNone(entries["a_hold"]["closed_at"])

    def test_closed_at_event_time_once_captured(self):
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 500}, headers={**self.ada, "Idempotency-Key": "k-a"})
        auth_id = payload["authorization_id"]
        status, capture, _ = base.request(self.port, "POST",
                                          f"/authorizations/{auth_id}/capture",
                                          body={"amount": 500},
                                          headers={**self.bob, "Idempotency-Key": "k-c"})
        self.assertEqual(status, 201, capture)
        status, payload, _ = base.request(self.port, "GET", "/authorizations",
                                          headers=self.ada)
        entry = next(a for a in payload["authorizations"]
                     if a["authorization_id"] == auth_id)
        self.assertEqual(entry["closed_at"], capture["created_at"])
        self.assertEqual(entry["status"], "captured")

    def test_closed_at_event_time_once_voided(self):
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 500}, headers={**self.ada, "Idempotency-Key": "k-a"})
        auth_id = payload["authorization_id"]
        status, void, _ = base.request(self.port, "POST",
                                       f"/authorizations/{auth_id}/void",
                                       headers=self.ada)
        self.assertEqual(status, 200, void)
        self.assertIsNotNone(void["closed_at"])
        status, payload, _ = self.me(f"?as_of={q(void['closed_at'])}")
        self.assertEqual(payload["held"], 6000)

    def test_clock_expiry_takes_effect_at_expires_at_even_for_future_as_of(self):
        fixture = {
            "currency": "EUR", "minor_units": 2, "authorization_ttl_seconds": 1,
            "users": FIXTURE["users"],
        }
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        ada = login(self.port, "ada@example.com")
        status, payload, _ = base.request(self.port, "POST", "/authorizations", body={
            "to_handle": "bob", "amount": 500}, headers={**ada, "Idempotency-Key": "k-a"})
        auth_id = payload["authorization_id"]
        expires_at = payload["expires_at"]
        status, payload, _ = self.me(headers=ada)
        self.assertEqual(payload["held"], 500)
        time.sleep(1.3)
        status, payload, _ = self.me(headers=ada)
        self.assertEqual(payload["held"], 0)
        status, payload, _ = base.request(self.port, "GET", "/authorizations",
                                          headers=ada)
        entry = next(a for a in payload["authorizations"]
                     if a["authorization_id"] == auth_id)
        self.assertEqual(entry["status"], "expired")
        self.assertEqual(entry["closed_at"], expires_at)
        status, payload, _ = self.me("?as_of=2099-01-01T00:00:00%2B00:00", headers=ada)
        self.assertEqual(payload["held"], 0)
        status, payload, _ = self.me("?as_of=2099-01-01T00:00:00%2B00:00",
                                     headers=login(self.port, "bob@example.com"))
        self.assertEqual(payload["held"], 0)

    def test_seeded_closed_hold_no_prior_lifecycle(self):
        fixture = {
            "currency": "EUR", "minor_units": 2,
            "users": FIXTURE["users"],
            "payments": [
                {"id": "p_cap", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 1000, "created_at": "2026-08-06T09:00:00+00:00"},
            ],
            "authorizations": [
                {"id": "a_closed", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 3000, "status": "captured", "captured_amount": 3000,
                 "payment_ids": ["p_cap"],
                 "created_at": "2026-08-05T09:00:00+00:00",
                 "expires_at": "2099-01-01T00:00:00+00:00"},
            ],
        }
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        ada = login(self.port, "ada@example.com")
        for view in ("?as_of=2020-01-01T00:00:00%2B00:00",
                     "?as_of=2026-08-05T12:00:00%2B00:00",
                     "?as_of=2099-01-01T00:00:00%2B00:00"):
            status, payload, _ = self.me(view, headers=ada)
            self.assertEqual(payload["held"], 0, view)
        status, payload, _ = base.request(self.port, "GET", "/authorizations",
                                          headers=ada)
        entry = next(a for a in payload["authorizations"]
                     if a["authorization_id"] == "a_closed")
        self.assertIsNotNone(entry["closed_at"])

    def test_correction_breaking_historical_availability_409(self):
        fixture = {
            "currency": "EUR", "minor_units": 2,
            "users": [
                {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
                 "display_name": "Ada", "handle": "ada", "balance": 16000},
                {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
                 "display_name": "Bob", "handle": "bob", "balance": 5000},
            ],
            "payments": [
                {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 8000, "created_at": "2026-08-01T09:00:00+00:00"},
                {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada",
                 "amount": 4000, "created_at": "2026-08-20T09:00:00+00:00"},
            ],
            "authorizations": [
                {"id": "a_mid", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 6000, "status": "open",
                 "created_at": "2026-08-10T09:00:00+00:00",
                 "expires_at": "2099-01-01T00:00:00+00:00"},
            ],
        }
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        ada = login(self.port, "ada@example.com")
        status, payload, _ = base.request(
            self.port, "POST", "/payments/p_1/corrections",
            body={"expected_revision": 1, "amount": 15000,
                  "effective_at": "2026-08-01T09:00:00+00:00", "reason": "recompute"},
            headers={**ada, "Idempotency-Key": "k-hold-break"})
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "historical_overdraft")
        status, payload, _ = base.request(
            self.port, "POST", "/payments/p_1/corrections",
            body={"expected_revision": 1, "amount": 19000,
                  "effective_at": "2026-08-01T09:00:00+00:00", "reason": "bigger"},
            headers={**ada, "Idempotency-Key": "k-current-break"})
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")


if __name__ == "__main__":
    unittest.main()