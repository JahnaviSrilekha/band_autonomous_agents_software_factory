import unittest
from datetime import datetime, timedelta, timezone

import base
import helpers_t2 as h


class TestT24Void(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        self.ada = h.login(self.port)
        self.bob = h.login(self.port, "bob@example.com")
        self.carol = h.login(self.port, "carol@example.com")
        status, payload, _ = base.request(
            self.port, "POST", "/authorizations",
            body={"to_handle": "bob", "amount": 2000, "note": "hold"},
            headers={**self.ada, "Idempotency-Key": "k-auth"})
        self.auth_id = payload["authorization_id"]

    def tearDown(self):
        base.stop_server(self.httpd)

    def _void(self, auth_id, caller, key=None):
        headers = {**caller}
        if key:
            headers["Idempotency-Key"] = key
        return base.request(self.port, "POST", f"/authorizations/{auth_id}/void",
                            body={}, headers=headers)

    def test_payer_void_returns_200_and_releases_hold(self):
        status, payload, _ = self._void(self.auth_id, self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "voided")
        self.assertEqual(payload["remaining_amount"], 0)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 10000)
        self.assertEqual(me["held"], 0)
        self.assertEqual(me["available"], 10000)

    def test_repeat_void_is_200_with_current_state(self):
        status, _, _ = self._void(self.auth_id, self.ada)
        self.assertEqual(status, 200)
        status, payload2, _ = self._void(self.auth_id, self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload2["status"], "voided")

    def test_receiver_cannot_void_403(self):
        status, payload, _ = self._void(self.auth_id, self.bob)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_third_party_cannot_void_403(self):
        status, payload, _ = self._void(self.auth_id, self.carol)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "forbidden")

    def test_unknown_authorization_404(self):
        status, payload, _ = self._void("a_missing", self.ada)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_client_supplied_idempotency_key_on_void_is_ignored(self):
        status1, payload1, _ = self._void(self.auth_id, self.ada, key="k-void-1")
        self.assertEqual(status1, 200)
        status2, payload2, _ = self._void(self.auth_id, self.ada, key="k-void-2")
        self.assertEqual(status2, 200)
        self.assertEqual(payload2["status"], "voided")

    def test_captured_authorization_void_409(self):
        status, _, _ = base.request(self.port, "POST", f"/authorizations/{self.auth_id}/capture",
                                    body={}, headers={**self.bob, "Idempotency-Key": "k-cap"})
        self.assertEqual(status, 201)
        status, payload, _ = self._void(self.auth_id, self.ada)
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "authorization_not_open")

    def test_clock_expired_authorization_void_409_not_open_code(self):
        from pocketful import state as state_module
        from pocketful.state import STATE_LOCK
        with STATE_LOCK:
            record = state_module.STATE.authorizations[self.auth_id]
            record.expires_dt = datetime.now(timezone.utc) - timedelta(seconds=5)
        status, payload, _ = self._void(self.auth_id, self.ada)
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "authorization_not_open")

    def test_void_preserves_capture_records(self):
        status, _, _ = base.request(self.port, "POST", f"/authorizations/{self.auth_id}/capture",
                                    body={"amount": 700, "final": False},
                                    headers={**self.bob, "Idempotency-Key": "k-cap-1"})
        self.assertEqual(status, 201)
        status, payload, _ = self._void(self.auth_id, self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "voided")
        self.assertEqual(payload["captured_amount"], 700)
        self.assertEqual(payload["remaining_amount"], 0)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 9300)
        self.assertEqual(me["held"], 0)
        self.assertEqual(me["available"], 9300)

    def test_seeded_expired_status_void_409(self):
        fixture = h.seeded_fixture([
            {"id": "a_exp", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 500, "status": "expired", "expires_at": h.past()}])
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = h.login(self.port)
        status, payload, _ = self._void("a_exp", ada)
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "authorization_not_open")


if __name__ == "__main__":
    unittest.main()