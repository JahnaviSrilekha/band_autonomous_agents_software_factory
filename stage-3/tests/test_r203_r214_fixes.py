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
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 800},
    ],
    "payments": [
        {"id": "p_s1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 500, "created_at": "2026-09-01T10:00:00+00:00"},
    ],
}


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestR203R204OriginalRepresentation(unittest.TestCase):
    """R203/R204: a correction never changes the original payment representation —
    activity and every stored/replayed original response keep the original amount."""

    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def correct(self, amount, key):
        return base.request(self.port, "POST", "/payments/p_s1/corrections",
                            body={"expected_revision": 1, "amount": amount,
                                  "effective_at": "2026-09-01T10:00:00+00:00",
                                  "reason": "fix"},
                            headers={**self.ada, "Idempotency-Key": key})

    def test_activity_entry_keeps_original_amount(self):
        status, before, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(before["payments"][0]["amount"], 500)
        status, _, _ = self.correct(450, "k-one")
        self.assertEqual(status, 201)
        status, after, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(after["payments"][0]["amount"], 500)
        self.assertEqual(after["payments"], before["payments"])

    def test_api_created_payment_response_unchanged_by_correction(self):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 333}, headers={**self.ada, "Idempotency-Key": "k-pay"})
        self.assertEqual(status, 201)
        original = payload
        status, _, _ = base.request(
            self.port, "POST", f"/payments/{payload['payment_id']}/corrections",
            body={"expected_revision": 1, "amount": 444,
                  "effective_at": payload["created_at"], "reason": "fix"},
            headers={**self.ada, "Idempotency-Key": "k-corr"})
        self.assertEqual(status, 201)
        status, replay, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 333}, headers={**self.ada, "Idempotency-Key": "k-pay"})
        self.assertEqual(status, 200)
        self.assertEqual(replay, original)
        self.assertEqual(replay["amount"], 333)

    def test_current_me_balance_reflects_correction_but_feed_does_not(self):
        status, before, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(before["balance"], 10000)
        status, _, _ = self.correct(450, "k-one")
        self.assertEqual(status, 201)
        status, after, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(after["balance"], 10050)
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        self.assertEqual(feed["payments"][0]["amount"], 500)

    def test_statement_entry_shows_selected_amount_not_original(self):
        status, _, _ = self.correct(450, "k-one")
        self.assertEqual(status, 201)
        status, payload, _ = base.request(self.port, "GET", "/statement",
                                          headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload["entries"][0]["payment"]["amount"], 450)
        self.assertEqual(payload["entries"][0]["delta"], -450)
        self.assertEqual(payload["entries"][0]["revision"], 2)

    def test_revisions_endpoint_still_shows_full_history(self):
        status, _, _ = self.correct(450, "k-one")
        self.assertEqual(status, 201)
        status, payload, _ = base.request(self.port, "GET", "/payments/p_s1/revisions",
                                          headers=self.ada)
        self.assertEqual([r["amount"] for r in payload["revisions"]], [500, 450])


class TestR214StatementKnownAtEcho(unittest.TestCase):
    """R214: GET /statement echoes supplied known_at exactly."""

    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_statement_echoes_known_at(self):
        status, payload, _ = base.request(
            self.port, "GET",
            "/statement?known_at=2026-09-24T13%3A20%3A00%2B00%3A00",
            headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload["known_at"], "2026-09-24T13:20:00+00:00")

    def test_statement_without_known_at_has_no_echo(self):
        status, payload, _ = base.request(self.port, "GET", "/statement", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertNotIn("known_at", payload)

    def test_snapshot_page_does_not_echo(self):
        status, first, _ = base.request(self.port, "GET", "/statement", headers=self.ada)
        token = first["snapshot"]
        status, payload, _ = base.request(
            self.port, "GET", f"/statement?snapshot={token}&limit=50&offset=0",
            headers=self.ada)
        self.assertEqual(status, 200)
        self.assertNotIn("known_at", payload)


if __name__ == "__main__":
    unittest.main()