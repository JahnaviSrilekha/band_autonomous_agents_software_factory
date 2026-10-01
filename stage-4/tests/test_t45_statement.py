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
         "display_name": "Bob", "handle": "bob", "balance": 4000},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 900},
    ],
    "payments": [
        {"id": "p_a1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 3000, "note": "first", "created_at": "2026-08-10T09:00:00+00:00"},
        {"id": "p_a2", "from_user_id": "u_bob", "to_user_id": "u_ada",
         "amount": 1200, "note": "second", "visibility": "public",
         "created_at": "2026-08-11T09:00:00+00:00"},
        {"id": "p_c1", "from_user_id": "u_cy", "to_user_id": "u_bob",
         "amount": 400, "note": "third party", "visibility": "public",
         "created_at": "2026-08-11T09:00:00+00:00"},
    ],
}


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT45Statement(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def stmt(self, query="", headers=None):
        return base.request(self.port, "GET", f"/statement{query}",
                            headers=headers or self.ada)

    def test_shape_and_full_window(self):
        status, payload, _ = self.stmt()
        self.assertEqual(status, 200)
        self.assertEqual(set(payload.keys()), {"opening_balance", "entries",
                                               "closing_balance", "has_more",
                                               "snapshot"})
        self.assertEqual(payload["opening_balance"], 11800)
        self.assertEqual(payload["closing_balance"], 10000)
        self.assertEqual(payload["has_more"], False)
        deltas = [entry["delta"] for entry in payload["entries"]]
        self.assertEqual(deltas, [-3000, 1200])
        self.assertEqual(payload["opening_balance"] + sum(deltas), payload["closing_balance"])
        balances = [entry["balance_after"] for entry in payload["entries"]]
        self.assertEqual(balances, [8800, 10000])

    def test_entries_oldest_first_ordered_by_created_at_then_id(self):
        status, payload, _ = self.stmt(headers=self.bob)
        self.assertEqual(status, 200)
        ids = [entry["payment"]["payment_id"] for entry in payload["entries"]]
        self.assertEqual(ids, ["p_a1", "p_a2", "p_c1"])
        self.assertEqual([entry["delta"] for entry in payload["entries"]],
                         [3000, -1200, 400])
        self.assertEqual([entry["balance_after"] for entry in payload["entries"]],
                         [4800, 3600, 4000])

    def test_opening_closing_are_immediately_before_bounds(self):
        status, payload, _ = self.stmt(
            "?from=2026-08-10T09:00:00%2B00:00&to=2026-08-11T09:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["opening_balance"], 11800)
        self.assertEqual(payload["closing_balance"], 8800)
        self.assertEqual([entry["payment"]["payment_id"] for entry in payload["entries"]],
                         ["p_a1"])
        status, payload, _ = self.stmt("?from=2026-08-11T09:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["opening_balance"], 8800)
        self.assertEqual([entry["payment"]["payment_id"] for entry in payload["entries"]],
                         ["p_a2"])
        self.assertEqual(payload["closing_balance"], 10000)

    def test_pagination_preserves_full_window_values(self):
        status, page1, _ = self.stmt("?limit=1&offset=0")
        status, page2, _ = self.stmt("?limit=1&offset=1")
        status, page3, _ = self.stmt("?limit=1&offset=2")
        for page in (page1, page2, page3):
            self.assertEqual(page["opening_balance"], 11800)
            self.assertEqual(page["closing_balance"], 10000)
        self.assertEqual(page1["has_more"], True)
        self.assertEqual(page2["has_more"], False)
        self.assertEqual(page3["has_more"], False)
        self.assertEqual(page2["entries"][0]["balance_after"], 10000)

    def test_pagination_beyond_end(self):
        status, payload, _ = self.stmt("?offset=9")
        self.assertEqual(status, 200)
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["has_more"], False)
        self.assertEqual(payload["opening_balance"], 11800)
        self.assertEqual(payload["closing_balance"], 10000)

    def test_only_own_payments_regardless_of_visibility(self):
        status, payload, _ = self.stmt(headers=self.ada)
        ids = [entry["payment"]["payment_id"] for entry in payload["entries"]]
        self.assertEqual(ids, ["p_a1", "p_a2"])

    def test_full_payment_representation_with_selected_amount(self):
        status, payload, _ = self.stmt()
        entry = payload["entries"][0]
        payment = entry["payment"]
        self.assertEqual(set(payment.keys()), {"payment_id", "from_user_id", "from_handle",
                                               "to_user_id", "to_handle", "amount",
                                               "currency", "note", "visibility",
                                               "request_id", "settlement_id",
                                               "authorization_id", "refund_of", "created_at"})
        self.assertEqual(payment["amount"], 3000)
        self.assertEqual(entry["revision"], 1)
        self.assertEqual(entry["effective_at"], "2026-08-10T09:00:00+00:00")
        self.assertEqual(entry["recorded_at"], "2026-08-10T09:00:00+00:00")

    def test_limits_match_requests_rules(self):
        status, payload, _ = self.stmt("?limit=0")
        self.assertEqual(status, 422)
        status, payload, _ = self.stmt("?limit=201")
        self.assertEqual(status, 422)
        status, payload, _ = self.stmt("?limit=200")
        self.assertEqual(status, 200)
        status, payload, _ = self.stmt("?offset=-1")
        self.assertEqual(status, 422)

    def test_malformed_bounds_422(self):
        for query in ("?from=2026-08-10T09:00:00", "?to=2026-08-10", "?from=",
                      "?known_at=2026-08-10T09:00:00", "?known_at="):
            status, payload, _ = self.stmt(query)
            self.assertEqual(status, 422, query)
            self.assertEqual(payload["error"]["code"], "validation_failed", query)

    def test_as_of_param_is_ignored_on_statement(self):
        status, payload, _ = self.stmt("?as_of=2020-01-01T00:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual([entry["payment"]["payment_id"] for entry in payload["entries"]],
                         ["p_a1", "p_a2"])

    def test_known_at_selects_revision_for_statements(self):
        status, _, _ = base.request(
            self.port, "POST", "/payments/p_a1/corrections",
            body={"expected_revision": 1, "amount": 500,
                  "effective_at": "2026-08-10T09:00:00+00:00", "reason": "fix"},
            headers={**self.ada, "Idempotency-Key": "k-fix"})
        self.assertEqual(status, 201)
        status, payload, _ = self.stmt("?known_at=2020-01-01T00:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["opening_balance"], 11800)
        self.assertEqual(payload["closing_balance"], 11800)
        status, payload, _ = self.stmt("?known_at=2020-01-01T00:00:00%2B00:00",
                                       headers=self.bob)
        self.assertEqual(payload["closing_balance"], 1800)
        status, payload, _ = self.stmt("?known_at=2099-01-01T00:00:00%2B00:00")
        self.assertEqual(status, 200)
        self.assertEqual([entry["delta"] for entry in payload["entries"]], [-500, 1200])
        self.assertEqual([entry["revision"] for entry in payload["entries"]], [2, 1])
        self.assertEqual(payload["entries"][0]["payment"]["amount"], 500)
        self.assertEqual(payload["opening_balance"], 11800)
        self.assertEqual(payload["closing_balance"], 12500)

    def test_zero_amount_revision_still_appears_with_zero_delta(self):
        status, _, _ = base.request(
            self.port, "POST", "/payments/p_c1/corrections",
            body={"expected_revision": 1, "amount": 0,
                  "effective_at": "2026-08-10T09:00:00+00:00", "reason": "reversal"},
            headers={**self.cy, "Idempotency-Key": "k-zero"})
        self.assertEqual(status, 201)
        status, payload, _ = self.stmt(
            "?from=2026-08-10T09:00:00%2B00:00&to=2026-08-11T09:00:00%2B00:00",
            headers=self.cy)
        ids = [entry["payment"]["payment_id"] for entry in payload["entries"]]
        self.assertEqual(ids, ["p_c1"])
        self.assertEqual(payload["entries"][0]["delta"], 0)
        self.assertEqual(payload["entries"][0]["payment"]["amount"], 0)
        self.assertEqual(payload["entries"][0]["balance_after"], 1300)

    def test_statement_never_shows_others_private_payments(self):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 100, "visibility": "private"},
            headers={**self.ada, "Idempotency-Key": "k-priv"})
        self.assertEqual(status, 201)
        private_id = payload["payment_id"]
        status, payload, _ = self.stmt(headers=self.cy)
        ids = [entry["payment"]["payment_id"] for entry in payload["entries"]]
        self.assertEqual(ids, ["p_c1"])
        self.assertNotIn(private_id, ids)
        status, payload, _ = self.stmt(headers=self.bob)
        ids = [entry["payment"]["payment_id"] for entry in payload["entries"]]
        self.assertIn(private_id, ids)

    def test_invariant_holds_across_arbitrary_windows(self):
        for bounds in ("", "?from=2026-08-10T09:00:00%2B00:00",
                       "?from=2026-08-10T09:00:00%2B00:00&to=2026-08-11T09:00:00%2B00:00",
                       "?from=2020-01-01T00:00:00%2B00:00&to=2099-01-01T00:00:00%2B00:00",
                       "?to=2026-08-11T09:00:00%2B00:00"):
            status, payload, _ = self.stmt(bounds)
            self.assertEqual(status, 200, bounds)
            total = payload["opening_balance"] + sum(e["delta"] for e in payload["entries"])
            self.assertEqual(total, payload["closing_balance"], bounds)


if __name__ == "__main__":
    unittest.main()