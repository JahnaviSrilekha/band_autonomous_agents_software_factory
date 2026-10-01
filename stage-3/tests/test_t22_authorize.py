import copy
import unittest
from datetime import timedelta

import base
import helpers_t2 as h


class TestT22CreateAuthorization(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        self.ada = h.login(self.port)
        self.bob = h.login(self.port, "bob@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def _create(self, headers, body, key="k-auth-1"):
        return base.request(self.port, "POST", "/authorizations", body=body,
                            headers={**headers, "Idempotency-Key": key})

    def test_create_returns_201_with_exact_shape(self):
        status, payload, _ = self._create(self.ada, {
            "to_handle": "bob", "amount": 2000, "note": "deposit",
            "visibility": "private"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["authorization_id"].startswith("a_"), True)
        self.assertEqual(payload["from_user_id"], "u_ada")
        self.assertEqual(payload["from_handle"], "ada")
        self.assertEqual(payload["to_user_id"], "u_bob")
        self.assertEqual(payload["to_handle"], "bob")
        self.assertEqual(payload["amount"], 2000)
        self.assertEqual(payload["captured_amount"], 0)
        self.assertEqual(payload["currency"], "EUR")
        self.assertEqual(payload["note"], "deposit")
        self.assertEqual(payload["visibility"], "private")
        self.assertEqual(payload["status"], "open")
        self.assertEqual(payload["payment_id"], None)
        self.assertEqual(payload["remaining_amount"], 2000)
        self.assertIn("created_at", payload)
        self.assertIn("expires_at", payload)

    def test_expires_at_is_created_at_plus_ttl(self):
        status, payload, _ = self._create(self.ada, {"to_handle": "bob", "amount": 100})
        self.assertEqual(status, 201)
        from pocketful.state import parse_rfc3339
        created = parse_rfc3339(payload["created_at"])
        expires = parse_rfc3339(payload["expires_at"])
        self.assertEqual(expires - created, timedelta(seconds=600))

    def test_ttl_from_fixture_is_applied(self):
        fixture = {**h.BASE_FIXTURE, "authorization_ttl_seconds": 30}
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = h.login(self.port)
        status, payload, _ = self._create(ada, {"to_handle": "bob", "amount": 100})
        from pocketful.state import parse_rfc3339
        created = parse_rfc3339(payload["created_at"])
        expires = parse_rfc3339(payload["expires_at"])
        self.assertEqual(expires - created, timedelta(seconds=30))

    def test_note_and_visibility_defaults(self):
        status, payload, _ = self._create(self.ada, {"to_handle": "bob", "amount": 100})
        self.assertEqual(status, 201)
        self.assertEqual(payload["note"], "")
        self.assertEqual(payload["visibility"], "public")

    def test_hold_reserves_without_moving_money(self):
        status, _, _ = self._create(self.ada, {"to_handle": "bob", "amount": 2000})
        self.assertEqual(status, 201)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 10000)
        self.assertEqual(me["balance"], 10000)
        self.assertEqual(me["held"], 2000)
        self.assertEqual(me["available"], 8000)
        status, me_bob, _ = base.request(self.port, "GET", "/me", headers=self.bob)
        self.assertEqual(me_bob["total"], 2500)
        self.assertEqual(me_bob["held"], 0)

    def test_insufficient_available_409(self):
        fixture = {**h.BASE_FIXTURE, "authorizations": [
            {"id": "a_seed", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 6000, "status": "open", "expires_at": h.future()}]}
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = h.login(self.port)
        status, payload, _ = self._create(ada, {"to_handle": "bob", "amount": 5000})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")

    def test_available_below_amount_but_total_above_409(self):
        fixture = {**h.BASE_FIXTURE, "authorizations": [
            {"id": "a_seed", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 9999, "status": "open", "expires_at": h.future()}]}
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = h.login(self.port)
        status, payload, _ = self._create(ada, {"to_handle": "bob", "amount": 2})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")

    def test_amount_validation_422(self):
        cases = [0, -1, 1000000001, 1.5, "10", None, True]
        for amount in cases:
            status, payload, _ = self._create(self.ada, {"to_handle": "bob", "amount": amount},
                                              key=f"k-{amount!r}")
            self.assertEqual(status, 422, f"amount {amount!r}")
            self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_amount_boundaries_accepted(self):
        status, _, _ = self._create(self.ada, {"to_handle": "bob", "amount": 1}, key="k-min")
        self.assertEqual(status, 201)
        fixture = copy.deepcopy(h.BASE_FIXTURE)
        fixture["users"][0]["balance"] = 1000000000
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = h.login(self.port)
        status, _, _ = self._create(ada, {"to_handle": "bob", "amount": 1000000000}, key="k-max")
        self.assertEqual(status, 201)

    def test_self_payment_422(self):
        status, payload, _ = self._create(self.ada, {"to_handle": "ada", "amount": 100})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "self_payment")

    def test_note_over_200_422(self):
        status, payload, _ = self._create(self.ada, {
            "to_handle": "bob", "amount": 100, "note": "x" * 201})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_bad_visibility_422(self):
        status, payload, _ = self._create(self.ada, {
            "to_handle": "bob", "amount": 100, "visibility": "secret"})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_unknown_handle_404(self):
        status, payload, _ = self._create(self.ada, {"to_handle": "ghost", "amount": 100})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_self_payment_precedes_funds_check(self):
        fixture = {**h.BASE_FIXTURE, "authorizations": [
            {"id": "a_seed", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 9999, "status": "open", "expires_at": h.future()}]}
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = h.login(self.port)
        status, payload, _ = self._create(ada, {"to_handle": "ada", "amount": 5000})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "self_payment")

    def test_missing_idempotency_key_400(self):
        status, payload, _ = base.request(self.port, "POST", "/authorizations",
                                          body={"to_handle": "bob", "amount": 100},
                                          headers=self.ada)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "missing_idempotency_key")

    def test_replay_same_key_same_body_returns_200_original(self):
        body = {"to_handle": "bob", "amount": 500}
        status1, payload1, _ = self._create(self.ada, body, key="k-replay")
        status2, payload2, _ = self._create(self.ada, body, key="k-replay")
        self.assertEqual(status1, 201)
        self.assertEqual(status2, 200)
        self.assertEqual(payload1["authorization_id"], payload2["authorization_id"])

    def test_replay_same_key_different_body_409(self):
        status, payload, _ = self._create(self.ada, {"to_handle": "bob", "amount": 500},
                                          key="k-reuse")
        self.assertEqual(status, 201)
        status, payload, _ = self._create(self.ada, {"to_handle": "bob", "amount": 501},
                                          key="k-reuse")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "idempotency_key_reuse")

    def test_keys_independent_across_paths(self):
        status, _, _ = self._create(self.ada, {"to_handle": "bob", "amount": 500}, key="k-shared")
        self.assertEqual(status, 201)
        status, _, _ = base.request(self.port, "POST", "/payments",
                                    body={"to_handle": "bob", "amount": 100},
                                    headers={**self.ada, "Idempotency-Key": "k-shared"})
        self.assertEqual(status, 201)

    def test_key_scoped_per_user(self):
        status, _, _ = self._create(self.ada, {"to_handle": "bob", "amount": 500}, key="k-scoped")
        self.assertEqual(status, 201)
        status, _, _ = self._create(self.bob, {"to_handle": "ada", "amount": 100}, key="k-scoped")
        self.assertEqual(status, 201)

    def test_non_object_body_400(self):
        status, payload, _ = base.request_raw(self.port, "POST", "/authorizations",
                                              data=b"[1,2]",
                                              headers={**self.ada, "Idempotency-Key": "k-arr"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "malformed_request")

    def test_authorization_never_appears_in_activity(self):
        status, _, _ = self._create(self.ada, {"to_handle": "bob", "amount": 2000})
        self.assertEqual(status, 201)
        status, payload, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(payload["payments"], [])

    def test_concurrent_identical_keys_move_money_once(self):
        import threading

        results = []

        def fire():
            results.append(self._create(self.ada, {"to_handle": "bob", "amount": 700},
                                        key="k-concurrent"))

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
        self.assertEqual(me["held"], 700)
        self.assertEqual(me["total"], 10000)


if __name__ == "__main__":
    unittest.main()