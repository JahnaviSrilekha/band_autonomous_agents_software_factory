import unittest

import base
import helpers_t2 as h


def _setup(port, authorizations=None):
    fixture = h.seeded_fixture(authorizations or [])
    base.request(port, "POST", "/_test/reset", body=fixture)
    return h.login(port), h.login(port, "bob@example.com"), h.login(port, "carol@example.com")


class TestT23Capture(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        self.ada, self.bob, self.carol = _setup(self.port)
        self.auth_id = None

    def tearDown(self):
        base.stop_server(self.httpd)

    def _authorize(self, amount=2000, note="deposit", visibility="public", key="k-auth"):
        status, payload, _ = base.request(
            self.port, "POST", "/authorizations",
            body={"to_handle": "bob", "amount": amount, "note": note,
                  "visibility": visibility},
            headers={**self.ada, "Idempotency-Key": key})
        assert status == 201, payload
        return payload["authorization_id"]

    def _capture(self, auth_id, body, caller=None, key="k-cap"):
        return base.request(self.port, "POST", f"/authorizations/{auth_id}/capture",
                            body=body, headers={**self.bob, "Idempotency-Key": key})

    def test_default_capture_moves_money_and_releases_remainder(self):
        auth_id = self._authorize(2000)
        status, payload, _ = self._capture(auth_id, {"amount": 1500})
        self.assertEqual(status, 201)
        self.assertEqual(payload["payment_id"].startswith("p_"), True)
        self.assertEqual(payload["amount"], 1500)
        self.assertEqual(payload["authorization_id"], auth_id)
        self.assertEqual(payload["request_id"], None)
        self.assertEqual(payload["settlement_id"], None)
        self.assertEqual(payload["note"], "deposit")
        self.assertEqual(payload["visibility"], "public")
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 8500)
        self.assertEqual(me["held"], 0)
        self.assertEqual(me["available"], 8500)
        status, me_bob, _ = base.request(self.port, "GET", "/me", headers=self.bob)
        self.assertEqual(me_bob["total"], 4000)
        status, auth_list, _ = base.request(self.port, "GET", "/authorizations",
                                            headers=self.ada)
        record = auth_list["authorizations"][0]
        self.assertEqual(record["status"], "captured")
        self.assertEqual(record["captured_amount"], 1500)
        self.assertEqual(record["remaining_amount"], 0)
        self.assertEqual(record["payment_id"], payload["payment_id"])

    def test_full_capture_by_default(self):
        auth_id = self._authorize(2000)
        status, payload, _ = self._capture(auth_id, {})
        self.assertEqual(status, 201)
        self.assertEqual(payload["amount"], 2000)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 8000)
        self.assertEqual(me["held"], 0)

    def test_second_capture_after_final_409(self):
        auth_id = self._authorize(2000)
        status, _, _ = self._capture(auth_id, {"amount": 1500}, key="k-cap-1")
        self.assertEqual(status, 201)
        status, payload, _ = self._capture(auth_id, {"amount": 100}, key="k-cap-2")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "authorization_not_open")

    def test_capture_payment_appears_in_activity_by_visibility(self):
        auth_id = self._authorize(2000, visibility="public")
        status, payload, _ = self._capture(auth_id, {"amount": 1500})
        self.assertEqual(status, 201)
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.carol)
        self.assertEqual(status, 200)
        self.assertEqual(len(feed["payments"]), 1)
        self.assertEqual(feed["payments"][0]["payment_id"], payload["payment_id"])

    def test_private_capture_payment_hidden_from_third_party(self):
        auth_id = self._authorize(2000, visibility="private")
        status, payload, _ = self._capture(auth_id, {"amount": 1500})
        self.assertEqual(status, 201)
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.carol)
        self.assertEqual(feed["payments"], [])
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.bob)
        self.assertEqual(len(feed["payments"]), 1)

    def test_extended_mode_keeps_remainder_held(self):
        auth_id = self._authorize(2000)
        status, payload, _ = self._capture(auth_id, {"amount": 700, "final": False},
                                           key="k-cap-1")
        self.assertEqual(status, 201)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 9300)
        self.assertEqual(me["held"], 1300)
        self.assertEqual(me["available"], 8000)
        status, auth_list, _ = base.request(self.port, "GET", "/authorizations",
                                            headers=self.ada)
        record = auth_list["authorizations"][0]
        self.assertEqual(record["status"], "open")
        self.assertEqual(record["captured_amount"], 700)
        self.assertEqual(record["remaining_amount"], 1300)
        self.assertEqual(record["payment_id"], payload["payment_id"])

    def test_extended_mode_accumulates_captures(self):
        auth_id = self._authorize(2000)
        status, p1, _ = self._capture(auth_id, {"amount": 700, "final": False}, key="k-cap-1")
        status, p2, _ = self._capture(auth_id, {"amount": 600, "final": False}, key="k-cap-2")
        self.assertEqual(status, 201)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 8700)
        self.assertEqual(me["held"], 700)
        status, auth_list, _ = base.request(self.port, "GET", "/authorizations",
                                            headers=self.ada)
        record = auth_list["authorizations"][0]
        self.assertEqual(record["status"], "open")
        self.assertEqual(record["captured_amount"], 1300)
        self.assertEqual(record["remaining_amount"], 700)
        self.assertEqual(record["payment_id"], p2["payment_id"])

    def test_exact_remainder_capture_closes_even_with_final_false(self):
        auth_id = self._authorize(2000)
        status, _, _ = self._capture(auth_id, {"amount": 700, "final": False}, key="k-cap-1")
        status, _, _ = self._capture(auth_id, {"amount": 1300, "final": False}, key="k-cap-2")
        self.assertEqual(status, 201)
        status, auth_list, _ = base.request(self.port, "GET", "/authorizations",
                                            headers=self.ada)
        record = auth_list["authorizations"][0]
        self.assertEqual(record["status"], "captured")
        self.assertEqual(record["remaining_amount"], 0)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["held"], 0)
        self.assertEqual(me["total"], 8000)

    def test_capture_exceeds_remaining_422(self):
        auth_id = self._authorize(2000)
        status, _, _ = self._capture(auth_id, {"amount": 700, "final": False}, key="k-cap-1")
        status, payload, _ = self._capture(auth_id, {"amount": 1400}, key="k-cap-2")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "capture_exceeds_authorization")

    def test_replay_requires_identical_body(self):
        auth_id = self._authorize(2000)
        status, p1, _ = self._capture(auth_id, {}, key="k-cap")
        self.assertEqual(status, 201)
        status, payload, _ = self._capture(auth_id, {"amount": 2000}, key="k-cap")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "idempotency_key_reuse")
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 8000)

    def test_replay_same_body_returns_200_and_moves_once(self):
        auth_id = self._authorize(2000)
        status, p1, _ = self._capture(auth_id, {"amount": 1500}, key="k-cap")
        self.assertEqual(status, 201)
        status, p2, _ = self._capture(auth_id, {"amount": 1500}, key="k-cap")
        self.assertEqual(status, 200)
        self.assertEqual(p1["payment_id"], p2["payment_id"])
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 8500)
        self.assertEqual(me["held"], 0)

    def test_concurrent_identical_capture_keys_move_once(self):
        import threading

        auth_id = self._authorize(2000)
        results = []

        def fire():
            results.append(base.request(
                self.port, "POST", f"/authorizations/{auth_id}/capture",
                body={"amount": 1500},
                headers={**self.bob, "Idempotency-Key": "k-cc"}))

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        created = [r for r in results if r[0] == 201]
        replayed = [r for r in results if r[0] == 200]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(replayed), 7)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 8500)
        self.assertEqual(me["held"], 0)

    def test_case_table(self):
        auth_id = self._authorize(2000)
        status, payload, _ = self._capture(auth_id, {"amount": 0}, key="k-zero")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))
        status, payload, _ = self._capture(auth_id, {"amount": 1.5}, key="k-frac")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))
        status, payload, _ = self._capture(auth_id, {"amount": "5"}, key="k-str")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))
        status, payload, _ = self._capture(auth_id, {"amount": 3000}, key="k-over")
        self.assertEqual((status, payload["error"]["code"]),
                         (422, "capture_exceeds_authorization"))
        status, payload, _ = self._capture(auth_id, {"amount": 1500, "final": "yes"},
                                           key="k-finalbad")
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))
        status, payload, _ = base.request(self.port, "POST", f"/authorizations/{auth_id}/capture",
                                          body={"amount": 100},
                                          headers={**self.ada, "Idempotency-Key": "k-payer"})
        self.assertEqual((status, payload["error"]["code"]), (403, "forbidden"))
        status, payload, _ = base.request(self.port, "POST", f"/authorizations/{auth_id}/capture",
                                          body={"amount": 100},
                                          headers={**self.carol, "Idempotency-Key": "k-3rd"})
        self.assertEqual((status, payload["error"]["code"]), (403, "forbidden"))
        status, payload, _ = base.request(self.port, "POST", "/authorizations/a_missing/capture",
                                          body={"amount": 100},
                                          headers={**self.bob, "Idempotency-Key": "k-missing"})
        self.assertEqual((status, payload["error"]["code"]), (404, "not_found"))

    def test_expired_authorization_capture_409_expired_code(self):
        auth_id = self._authorize(2000)
        from pocketful import state as state_module
        from pocketful.state import STATE_LOCK
        with STATE_LOCK:
            record = state_module.STATE.authorizations[auth_id]
            from datetime import datetime, timedelta, timezone
            record.expires_dt = datetime.now(timezone.utc) - timedelta(seconds=5)
        status, payload, _ = self._capture(auth_id, {}, key="k-exp")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "authorization_expired")

    def test_capture_without_idempotency_key_400(self):
        auth_id = self._authorize(2000)
        status, payload, _ = base.request(self.port, "POST", f"/authorizations/{auth_id}/capture",
                                          body={"amount": 100}, headers=self.bob)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_idempotency_key")


if __name__ == "__main__":
    unittest.main()