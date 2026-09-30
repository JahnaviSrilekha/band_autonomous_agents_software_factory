import copy
import unittest
from datetime import datetime, timedelta, timezone

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "authorization_ttl_seconds": 600,
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


def _future(days=1):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


class TestT20Fixture(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_reset_with_authorizations_returns_204_and_seeds(self):
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        self.assertEqual(status, 204)
        state = state_module.STATE
        self.assertEqual(set(state.authorizations), {"a_1"})
        auth = state.authorizations["a_1"]
        self.assertEqual(auth.from_user_id, "u_ada")
        self.assertEqual(auth.to_user_id, "u_bob")
        self.assertEqual(auth.amount, 2000)
        self.assertEqual(auth.status, "open")
        self.assertEqual(auth.captured_amount, 0)
        self.assertEqual(auth.payment_ids, [])
        self.assertEqual(auth.expires_at, "2099-01-01T12:00:00+00:00")
        self.assertEqual(state.authorization_ttl_seconds, 600)

    def test_ttl_defaults_to_600_when_omitted(self):
        fixture = copy.deepcopy(FIXTURE)
        del fixture["authorization_ttl_seconds"]
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        self.assertEqual(state_module.STATE.authorization_ttl_seconds, 600)

    def test_zero_ttl_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorization_ttl_seconds"] = 0
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_negative_ttl_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorization_ttl_seconds"] = -5
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_non_integer_ttl_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorization_ttl_seconds"] = 1.5
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_non_number_ttl_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorization_ttl_seconds"] = "600"
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_stage1_shaped_fixture_without_authorizations_resets_cleanly(self):
        fixture = copy.deepcopy(FIXTURE)
        del fixture["authorizations"]
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        state = state_module.STATE
        self.assertEqual(state.authorizations, {})
        self.assertEqual(len(state.users), 2)
        self.assertEqual(state.users["u_ada"].balance, 10000)

    def test_open_holds_summing_above_balance_422_and_state_unchanged(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        before = state_module.STATE
        bad = copy.deepcopy(FIXTURE)
        bad["users"][1]["balance"] = 100
        bad["authorizations"].append(
            {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada",
             "amount": 5000, "status": "open", "expires_at": _future()})
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=bad)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")
        self.assertIs(state_module.STATE, before)
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 2500)
        self.assertEqual(set(state_module.STATE.authorizations), {"a_1"})

    def test_open_holds_equal_to_balance_are_accepted(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["amount"] = 10000
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)

    def test_expired_seeded_open_hold_does_not_trigger_hold_sum_error(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["users"][1]["balance"] = 100
        fixture["authorizations"].append(
            {"id": "a_2", "from_user_id": "u_bob", "to_user_id": "u_ada",
             "amount": 5000, "status": "open", "expires_at": _past()})
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)

    def test_only_open_seeded_status_holds_anything(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"] = [
            {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 1000, "status": "open", "expires_at": _future()},
            {"id": "a_captured", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 1000, "status": "captured", "expires_at": _future()},
            {"id": "a_voided", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 1000, "status": "voided", "expires_at": _future()},
            {"id": "a_expired", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 1000, "status": "expired", "expires_at": _past()},
        ]
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        state = state_module.STATE
        now = state_module.now_dt()
        from pocketful.state import effective_status, held
        self.assertEqual(held(state, "u_ada", now), 1000)
        self.assertEqual(effective_status(state.authorizations["a_captured"], now), "captured")
        self.assertEqual(effective_status(state.authorizations["a_voided"], now), "voided")
        self.assertEqual(effective_status(state.authorizations["a_expired"], now), "expired")

    def test_seeded_captured_defaults_captured_amount_to_zero(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"] = [
            {"id": "a_c", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 1000, "status": "captured", "expires_at": _future()},
        ]
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        auth = state_module.STATE.authorizations["a_c"]
        self.assertEqual(auth.captured_amount, 0)
        self.assertEqual(auth.payment_ids, [])

    def test_seeded_expired_with_future_expires_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["status"] = "expired"
        fixture["authorizations"][0]["expires_at"] = _future()
        before = state_module.STATE
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")
        self.assertIs(state_module.STATE, before)

    def test_seeded_expired_with_past_expires_stored_open_computes_expired(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["status"] = "expired"
        fixture["authorizations"][0]["expires_at"] = _past()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)
        auth = state_module.STATE.authorizations["a_1"]
        self.assertEqual(auth.status, "open")
        from pocketful.state import effective_status
        self.assertEqual(effective_status(auth, state_module.now_dt()), "expired")

    def test_seeded_from_equals_to_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["to_user_id"] = "u_ada"
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_unknown_user_in_seeded_authorization_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["to_user_id"] = "u_ghost"
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_bad_expires_at_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["expires_at"] = "not-a-time"
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_bad_seeded_status_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["status"] = "pending"
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_bad_visibility_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["visibility"] = "secret"
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_expires_at_with_z_suffix_accepted(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["expires_at"] = "2099-01-01T12:00:00Z"
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 204)

    def test_non_integer_amount_422(self):
        fixture = copy.deepcopy(FIXTURE)
        fixture["authorizations"][0]["amount"] = 1.5
        status, payload, _ = base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")


if __name__ == "__main__":
    unittest.main()