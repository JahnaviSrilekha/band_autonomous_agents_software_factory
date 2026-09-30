import copy
import unittest

import base
from pocketful import state as state_module
from pocketful.state import verify_password

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
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


class TestReset(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_reset_returns_204_and_replaces_state(self):
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        self.assertEqual(status, 204)
        self.assertIsNone(payload)
        state = state_module.STATE
        self.assertEqual(state.currency, "EUR")
        self.assertEqual(state.minor_units, 2)
        self.assertEqual(set(state.users), {"u_ada", "u_bob"})
        self.assertEqual(state.users["u_ada"].balance, 10000)
        self.assertEqual(state.users["u_bob"].balance, 2500)
        self.assertEqual(state.handles["ada"], "u_ada")
        self.assertEqual(state.emails["ada@example.com"], "u_ada")
        self.assertEqual(len(state.payments), 1)
        self.assertEqual(state.payments[0].amount, 500)
        self.assertEqual(state.requests["rq_1"].status, "pending")

    def test_balances_are_post_seeded_payment_values_not_replayed(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        state = state_module.STATE
        self.assertEqual(state.users["u_ada"].balance, 10000)
        self.assertEqual(state.users["u_bob"].balance, 2500)

    def test_repeated_reset_supported(self):
        for _ in range(2):
            status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
            self.assertEqual(status, 204)

    def test_negative_balance_fixture_422_and_state_untouched(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        before = state_module.STATE
        bad = copy.deepcopy(FIXTURE)
        bad["users"][0]["balance"] = -1
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=bad)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")
        self.assertIs(state_module.STATE, before)
        self.assertEqual(state_module.STATE.users["u_ada"].balance, 10000)

    def test_missing_currency_422(self):
        bad = copy.deepcopy(FIXTURE)
        del bad["currency"]
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=bad)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_minor_units_out_of_set_422(self):
        for value in (1, 4, -2, "2"):
            bad = copy.deepcopy(FIXTURE)
            bad["minor_units"] = value
            status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=bad)
            self.assertEqual(status, 422, f"minor_units={value!r}")
            self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_minor_units_accepted_values(self):
        for value in (0, 2, 3):
            fixture = copy.deepcopy(FIXTURE)
            fixture["minor_units"] = value
            status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
            self.assertEqual(status, 204)
            self.assertEqual(state_module.STATE.minor_units, value)

    def test_seeded_password_stored_hashed_and_verifiable(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        user = state_module.STATE.users["u_ada"]
        self.assertNotEqual(user.password_hash, "correct horse")
        self.assertNotIn("correct horse", user.password_hash)
        self.assertTrue(verify_password(user.password_hash, "correct horse"))
        self.assertFalse(verify_password(user.password_hash, "wrong password"))

    def test_unknown_fixture_fields_ignored(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["unknown_top"] = 1
        fixture["users"][0]["unknown_user_field"] = "x"
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)

    def test_duplicate_handle_422(self):
        bad = copy.deepcopy(FIXTURE)
        bad["users"][1]["handle"] = "ada"
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=bad)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_seeded_payment_unknown_user_422(self):
        bad = copy.deepcopy(FIXTURE)
        bad["payments"][0]["to_user_id"] = "u_ghost"
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=bad)
        self.assertEqual(status, 422)

    def test_reset_replaces_tokens_and_prior_fixture(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        other = {
            "currency": "JPY",
            "minor_units": 0,
            "users": [
                {"id": "u_x", "email": "x@example.com", "password": "password123",
                 "display_name": "X", "handle": "x", "balance": 100},
            ],
        }
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=other)
        self.assertEqual(status, 204)
        state = state_module.STATE
        self.assertEqual(state.currency, "JPY")
        self.assertEqual(set(state.users), {"u_x"})
        self.assertEqual(state.payments, [])
        self.assertEqual(state.requests, {})

    def test_non_object_fixture_400(self):
        status, payload, _ = base.request_raw(self.port, "POST", "/_test/reset", data=b"[1]")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "malformed_request")


class TestIdsAndTimestamps(unittest.TestCase):
    def test_new_id_format_and_length(self):
        from pocketful.state import new_id

        for prefix in ("u", "p", "rq", "sp", "st"):
            value = new_id(prefix)
            self.assertTrue(value.startswith(prefix + "_"))
            self.assertLessEqual(len(value), 64)

    def test_now_iso_has_explicit_offset(self):
        import re

        from pocketful.state import now_iso

        self.assertRegex(now_iso(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$")


if __name__ == "__main__":
    unittest.main()