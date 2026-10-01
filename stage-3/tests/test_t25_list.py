import unittest
from datetime import datetime, timedelta, timezone

import base
import helpers_t2 as h


def _make_auth(port, caller, to_handle, amount, key, note="", visibility="public"):
    status, payload, _ = base.request(
        port, "POST", "/authorizations",
        body={"to_handle": to_handle, "amount": amount, "note": note,
              "visibility": visibility},
        headers={**caller, "Idempotency-Key": f"k-{to_handle}-{amount}-{key}"})
    assert status == 201, payload
    return payload["authorization_id"]


class TestT25ListAuthorizations(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        self.ada = h.login(self.port)
        self.bob = h.login(self.port, "bob@example.com")
        self.carol = h.login(self.port, "carol@example.com")
        self.ids = [
            _make_auth(self.port, self.ada, "bob", 100, "a"),
            _make_auth(self.port, self.ada, "bob", 200, "b"),
            _make_auth(self.port, self.ada, "carol", 300, "c"),
            _make_auth(self.port, self.bob, "ada", 400, "d"),
        ]

    def tearDown(self):
        base.stop_server(self.httpd)

    def _list(self, caller, query=""):
        return base.request(self.port, "GET", f"/authorizations{query}", headers=caller)

    def test_newest_first_involving_caller_only(self):
        status, payload, _ = self._list(self.ada)
        self.assertEqual(status, 200)
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [self.ids[3], self.ids[2], self.ids[1], self.ids[0]])
        self.assertIn("has_more", payload)
        self.assertEqual(payload["has_more"], False)

    def test_carol_sees_only_her_incoming(self):
        status, payload, _ = self._list(self.carol)
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [self.ids[2]])

    def test_direction_filter(self):
        status, payload, _ = self._list(self.ada, "?direction=outgoing")
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [self.ids[2], self.ids[1], self.ids[0]])
        status, payload, _ = self._list(self.ada, "?direction=incoming")
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [self.ids[3]])

    def test_status_filter(self):
        voided_id = self.ids[0]
        status, _, _ = base.request(self.port, "POST", f"/authorizations/{voided_id}/void",
                                    body={}, headers=self.ada)
        self.assertEqual(status, 200)
        status, payload, _ = self._list(self.ada, "?status=voided")
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [voided_id])
        status, payload, _ = self._list(self.ada, "?status=open")
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [self.ids[3], self.ids[2], self.ids[1]])

    def test_clock_expired_matches_expired_never_open(self):
        from pocketful import state as state_module
        from pocketful.state import STATE_LOCK
        with STATE_LOCK:
            record = state_module.STATE.authorizations[self.ids[1]]
            record.expires_dt = datetime.now(timezone.utc) - timedelta(seconds=5)
        status, payload, _ = self._list(self.ada, "?status=expired")
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [self.ids[1]])
        status, payload, _ = self._list(self.ada, "?status=open")
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertNotIn(self.ids[1], got)
        status, payload, _ = self._list(self.ada)
        by_id = {a["authorization_id"]: a for a in payload["authorizations"]}
        self.assertEqual(by_id[self.ids[1]]["status"], "expired")

    def test_limit_offset_has_more(self):
        status, payload, _ = self._list(self.ada, "?limit=2&offset=0")
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [self.ids[3], self.ids[2]])
        self.assertEqual(payload["has_more"], True)
        status, payload, _ = self._list(self.ada, "?limit=2&offset=2")
        got = [a["authorization_id"] for a in payload["authorizations"]]
        self.assertEqual(got, [self.ids[1], self.ids[0]])
        self.assertEqual(payload["has_more"], False)

    def test_invalid_direction_422(self):
        status, payload, _ = self._list(self.ada, "?direction=sideways")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_invalid_status_422(self):
        status, payload, _ = self._list(self.ada, "?status=unknown")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_invalid_limit_422(self):
        status, payload, _ = self._list(self.ada, "?limit=0")
        self.assertEqual(status, 422)
        status, payload, _ = self._list(self.ada, "?limit=201")
        self.assertEqual(status, 422)

    def test_unauthenticated_401(self):
        status, _, _ = base.request(self.port, "GET", "/authorizations")
        self.assertEqual(status, 401)

    def test_item_shape_in_list(self):
        status, payload, _ = self._list(self.ada)
        record = payload["authorizations"][0]
        for field in ("authorization_id", "from_user_id", "from_handle", "to_user_id",
                      "to_handle", "amount", "captured_amount", "currency", "note",
                      "visibility", "status", "expires_at", "payment_id", "payment_ids",
                      "created_at", "remaining_amount"):
            self.assertIn(field, record)
        self.assertEqual(record["status"], "open")
        self.assertEqual(record["remaining_amount"], record["amount"])
        self.assertEqual(record["payment_ids"], [])


if __name__ == "__main__":
    unittest.main()