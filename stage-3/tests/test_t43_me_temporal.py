import copy
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
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 3000, "created_at": "2026-08-10T09:00:00+00:00"},
        {"id": "p_2", "from_user_id": "u_bob", "to_user_id": "u_ada",
         "amount": 1000, "created_at": "2026-08-11T09:00:00+00:00"},
    ],
}

P1_AT = "2026-08-10T09:00:00+00:00"


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT43MeTemporal(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def me(self, query="", headers=None):
        return base.request(self.port, "GET", f"/me{query}", headers=headers or self.ada)

    def test_as_of_format_validation(self):
        for bad in ("?as_of=2026-08-10T09:00:00", "?as_of=2026-08-10", "?as_of=",
                    "?as_of=nonsense", "?as_of=5"):
            status, payload, _ = self.me(bad)
            self.assertEqual(status, 422, bad)
            self.assertEqual(payload["error"]["code"], "validation_failed", bad)

    def test_known_at_format_validation(self):
        for bad in ("?known_at=2026-08-10T09:00:00", "?known_at=2026-08-10", "?known_at="):
            status, payload, _ = self.me(bad)
            self.assertEqual(status, 422, bad)
            self.assertEqual(payload["error"]["code"], "validation_failed", bad)

    def test_plain_me_reports_current_corrected_values_without_temporal_keys(self):
        status, payload, _ = self.me()
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 10000)
        self.assertNotIn("as_of", payload)
        self.assertNotIn("known_at", payload)
        self.assertEqual(set(payload.keys()), {"user_id", "display_name", "handle",
                                               "balance", "total", "available", "held",
                                               "currency", "minor_units"})

    def test_as_of_at_or_after_latest_payment_returns_current_balance(self):
        status, payload, _ = self.me("?as_of=2026-09-24T13:20:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 10000)
        self.assertEqual(payload["as_of"], "2026-09-24T13:20:00+00:00")

    def test_as_of_between_payments(self):
        status, payload, _ = self.me("?as_of=2026-08-10T12:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 9000)
        status, payload, _ = self.me(f"?as_of=2026-08-10T09:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 9000)

    def test_as_of_before_earliest_payment_returns_opening_balance(self):
        status, payload, _ = self.me("?as_of=2026-08-01T00:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 12000)
        status, payload, _ = self.me("?as_of=2026-08-01T00:00:00%2B00:00", headers=self.bob)
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 500)

    def test_as_of_exactly_on_payment_counts_it(self):
        status, payload, _ = self.me("?as_of=2026-08-11T09:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 10000)

    def test_correction_shifts_effective_time(self):
        status, payload, _ = base.request(
            self.port, "POST", "/payments/p_1/corrections",
            body={"expected_revision": 1, "amount": 500,
                  "effective_at": "2026-08-09T09:00:00+00:00", "reason": "recompute"},
            headers={**self.ada, "Idempotency-Key": "k-shift"})
        self.assertEqual(status, 201, payload)
        status, payload, _ = self.me()
        self.assertEqual(payload["balance"], 12500)
        status, payload, _ = self.me("?as_of=2026-08-10T12:00:00%2B00:00")
        self.assertEqual(payload["balance"], 11500)
        status, payload, _ = self.me("?as_of=2026-08-09T00:00:00%2B00:00")
        self.assertEqual(payload["balance"], 12000)

    def test_known_at_selects_revision_recorded_at_or_before(self):
        status, payload, _ = base.request(
            self.port, "POST", "/payments/p_1/corrections",
            body={"expected_revision": 1, "amount": 500,
                  "effective_at": P1_AT, "reason": "fix"},
            headers={**self.ada, "Idempotency-Key": "k-fix"})
        self.assertEqual(status, 201, payload)
        status, payload, _ = self.me("?known_at=2020-01-01T00:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["known_at"], "2020-01-01T00:00:00+00:00")
        self.assertEqual(payload["balance"], 12000)
        status, payload, _ = self.me("?known_at=2026-09-30T00:00:00%2B00:00")
        self.assertEqual(payload["balance"], 10000)
        status, payload, _ = self.me("?known_at=2099-01-01T00:00:00%2B00:00")
        self.assertEqual(payload["balance"], 12500)

    def test_known_at_before_earliest_payment_excludes_everything(self):
        status, payload, _ = self.me("?known_at=2020-01-01T00:00:00%2B00:00")
        self.assertEqual(payload["balance"], 12000)

    def test_historical_conservation_across_views(self):
        seeded_total = sum(u["balance"] for u in FIXTURE["users"])
        views = ["", "?as_of=2026-08-10T12:00:00%2B00:00",
                 "?as_of=2026-09-24T13:20:00%2B00:00",
                 "?known_at=2020-01-01T00:00:00%2B00:00",
                 "?known_at=2026-09-30T00:00:00%2B00:00",
                 "?as_of=2026-08-10T12:00:00%2B00:00&known_at=2020-01-01T00:00:00%2B00:00",
                 "?as_of=2026-08-10T12:00:00%2B00:00&known_at=2099-01-01T00:00:00%2B00:00"]
        for view in views:
            total = 0
            for email in ("ada@example.com", "bob@example.com", "cy@example.com"):
                status, payload, _ = self.me(view, headers=login(self.port, email))
                self.assertEqual(status, 200, view)
                total += payload["total"]
            self.assertEqual(total, seeded_total, view)

    def test_correction_with_known_at_conserves_money(self):
        base.request(self.port, "POST", "/payments/p_1/corrections",
                     body={"expected_revision": 1, "amount": 500,
                           "effective_at": "2026-08-09T09:00:00+00:00", "reason": "fix"},
                     headers={**self.ada, "Idempotency-Key": "k-fix"})
        seeded_total = sum(u["balance"] for u in FIXTURE["users"])
        for view in ("?as_of=2026-08-09T00:00:00%2B00:00",
                     "?as_of=2026-08-10T12:00:00%2B00:00",
                     "?known_at=2020-01-01T00:00:00%2B00:00",
                     "?as_of=2026-08-10T12:00:00%2B00:00&known_at=2099-01-01T00:00:00%2B00:00"):
            total = 0
            for email in ("ada@example.com", "bob@example.com", "cy@example.com"):
                status, payload, _ = self.me(view, headers=login(self.port, email))
                total += payload["total"]
            self.assertEqual(total, seeded_total, view)

    def test_future_instants_accepted(self):
        status, payload, _ = self.me("?as_of=2099-06-01T00:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["balance"], 10000)
        status, payload, _ = self.me("?known_at=2099-06-01T00:00:00%2B00:00")
        self.assertEqual(status, 200)

    def test_uncorrected_no_known_at_matches_live_state(self):
        status, plain, _ = self.me()
        status, future, _ = self.me("?as_of=2099-01-01T00:00:00%2B00:00")
        self.assertEqual(future["balance"], plain["balance"])


if __name__ == "__main__":
    unittest.main()