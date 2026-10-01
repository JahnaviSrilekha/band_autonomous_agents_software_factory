import unittest

import base
import helpers_t2 as h


class TestT33UpgradeContinuity(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def _export(self):
        status, payload, _ = base.request(self.port, "GET", "/_test/export")
        assert status == 200
        return payload

    def test_token_survives_import(self):
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        status, login, _ = base.request(self.port, "POST", "/auth/login",
                                        body={"email": "ada@example.com",
                                              "password": "correct horse"})
        token = login["token"]
        export = self._export()
        status, _, _ = base.request(self.port, "POST", "/_test/import", body=export)
        self.assertEqual(status, 204)
        status, me, _ = base.request(self.port, "GET", "/me",
                                     headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(status, 200)
        self.assertEqual(me["handle"], "ada")

    def test_pending_request_payable_across_import(self):
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        ada = h.login(self.port)
        bob = h.login(self.port, "bob@example.com")
        status, rq, _ = base.request(self.port, "POST", "/requests",
                                     body={"payer_handle": "ada", "amount": 500,
                                           "note": "bus"},
                                     headers={**bob, "Idempotency-Key": "k-rq"})
        self.assertEqual(status, 201)
        export = self._export()
        base.request(self.port, "POST", "/_test/import", body=export)
        ada = h.login(self.port)
        status, payment, _ = base.request(
            self.port, "POST", f"/requests/{rq['request_id']}/pay", body={},
            headers={**ada, "Idempotency-Key": "k-pay"})
        self.assertEqual(status, 201)
        self.assertEqual(payment["request_id"], rq["request_id"])

    def test_lost_response_payment_replay_recovers_original(self):
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        ada = h.login(self.port)
        body = {"to_handle": "bob", "amount": 700, "note": "lost", "visibility": "public"}
        key = "k-lost"
        status, first, _ = base.request(self.port, "POST", "/payments", body=body,
                                        headers={**ada, "Idempotency-Key": key})
        self.assertEqual(status, 201)
        export = self._export()
        status, _, _ = base.request(self.port, "POST", "/_test/import", body=export)
        self.assertEqual(status, 204)
        ada = h.login(self.port)
        status, replay, _ = base.request(self.port, "POST", "/payments", body=body,
                                         headers={**ada, "Idempotency-Key": key})
        self.assertEqual(status, 200)
        self.assertEqual(replay["payment_id"], first["payment_id"])
        status, me, _ = base.request(self.port, "GET", "/me", headers=ada)
        self.assertEqual(me["total"], 9300)

    def test_import_with_seeded_holds_keeps_pending_requests_payable(self):
        fixture = h.seeded_fixture([
            {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 2000, "status": "open", "expires_at": h.future()},
        ])
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        bob = h.login(self.port, "bob@example.com")
        status, rq, _ = base.request(self.port, "POST", "/requests",
                                     body={"payer_handle": "ada", "amount": 500,
                                           "note": "rent"},
                                     headers={**bob, "Idempotency-Key": "k-rq2"})
        self.assertEqual(status, 201)
        export = self._export()
        base.request(self.port, "POST", "/_test/import", body=export)
        ada = h.login(self.port)
        status, me, _ = base.request(self.port, "GET", "/me", headers=ada)
        self.assertEqual(me["held"], 2000)
        self.assertEqual(me["available"], 8000)
        status, payment, _ = base.request(
            self.port, "POST", f"/requests/{rq['request_id']}/pay", body={},
            headers={**ada, "Idempotency-Key": "k-pay2"})
        self.assertEqual(status, 201)
        status, me, _ = base.request(self.port, "GET", "/me", headers=ada)
        self.assertEqual(me["available"], 7500)


if __name__ == "__main__":
    unittest.main()