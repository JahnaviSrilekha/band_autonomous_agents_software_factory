import unittest

import base
import helpers_t2 as h


class TestT26AvailableChecks(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        self.holds = [
            {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 6000, "status": "open", "expires_at": h.future()},
        ]
        fixture = h.seeded_fixture(self.holds)
        fixture["settlement_operator_ids"] = ["u_bob"]
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.ada = h.login(self.port)
        self.bob = h.login(self.port, "bob@example.com")
        self.carol = h.login(self.port, "carol@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_payment_refused_on_available_not_total(self):
        status, payload, _ = base.request(self.port, "POST", "/payments",
                                          body={"to_handle": "bob", "amount": 5000},
                                          headers={**self.ada, "Idempotency-Key": "k-p1"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")

    def test_payment_allowed_within_available(self):
        status, payload, _ = base.request(self.port, "POST", "/payments",
                                          body={"to_handle": "bob", "amount": 4000},
                                          headers={**self.ada, "Idempotency-Key": "k-p2"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["authorization_id"], None)
        status, me, _ = base.request(self.port, "GET", "/me", headers=self.ada)
        self.assertEqual(me["total"], 6000)
        self.assertEqual(me["held"], 6000)
        self.assertEqual(me["available"], 0)

    def test_pay_request_refused_on_available(self):
        status, rq, _ = base.request(self.port, "POST", "/requests",
                                     body={"payer_handle": "ada", "amount": 5000,
                                           "note": "rent"},
                                     headers={**self.bob, "Idempotency-Key": "k-r1"})
        self.assertEqual(status, 201)
        status, payload, _ = base.request(
            self.port, "POST", f"/requests/{rq['request_id']}/pay",
            body={}, headers={**self.ada, "Idempotency-Key": "k-rp1"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")

    def test_pay_request_allowed_within_available(self):
        status, rq, _ = base.request(self.port, "POST", "/requests",
                                     body={"payer_handle": "ada", "amount": 3000,
                                           "note": "rent"},
                                     headers={**self.bob, "Idempotency-Key": "k-r2"})
        self.assertEqual(status, 201)
        status, payload, _ = base.request(
            self.port, "POST", f"/requests/{rq['request_id']}/pay",
            body={}, headers={**self.ada, "Idempotency-Key": "k-rp2"})
        self.assertEqual(status, 201)
        self.assertEqual(payload["request_id"], rq["request_id"])
        self.assertEqual(payload["authorization_id"], None)

    def test_settlement_net_debit_refused_on_available(self):
        transfers = [{"from_handle": "ada", "to_handle": "carol", "amount": 4500,
                      "note": "net"}]
        status, payload, _ = base.request(self.port, "POST", "/settlements",
                                          body={"transfers": transfers},
                                          headers={**self.bob, "Idempotency-Key": "k-s1"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")

    def test_settlement_net_debit_allowed_within_available(self):
        transfers = [{"from_handle": "ada", "to_handle": "carol", "amount": 3500,
                      "note": "net"}]
        status, payload, _ = base.request(self.port, "POST", "/settlements",
                                          body={"transfers": transfers},
                                          headers={**self.bob, "Idempotency-Key": "k-s2"})
        self.assertEqual(status, 201)
        for payment in payload["payments"]:
            self.assertEqual(payment["authorization_id"], None)

    def test_split_unchanged_no_balance_check(self):
        status, payload, _ = base.request(self.port, "POST", "/splits",
                                          body={"participant_handles": ["ada", "bob", "carol"],
                                                "amount": 100, "note": "lunch"},
                                          headers={**self.carol, "Idempotency-Key": "k-sp1"})
        self.assertEqual(status, 201)
        self.assertEqual(sum(share["amount"] for share in payload["shares"]), 100)

    def test_zero_holds_matches_stage1_behavior(self):
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        ada = h.login(self.port)
        status, me, _ = base.request(self.port, "GET", "/me", headers=ada)
        self.assertEqual(me["balance"], me["total"])
        self.assertEqual(me["total"], me["available"])
        self.assertEqual(me["held"], 0)
        status, payload, _ = base.request(self.port, "POST", "/payments",
                                          body={"to_handle": "bob", "amount": 10000},
                                          headers={**ada, "Idempotency-Key": "k-exact"})
        self.assertEqual(status, 201)
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        ada = h.login(self.port)
        status, payload, _ = base.request(self.port, "POST", "/payments",
                                          body={"to_handle": "bob", "amount": 10001},
                                          headers={**ada, "Idempotency-Key": "k-over"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")

    def test_payments_shape_gains_authorization_id_null(self):
        status, payload, _ = base.request(self.port, "POST", "/payments",
                                          body={"to_handle": "bob", "amount": 100},
                                          headers={**self.ada, "Idempotency-Key": "k-shape"})
        self.assertEqual(status, 201)
        self.assertIn("authorization_id", payload)
        self.assertIsNone(payload["authorization_id"])
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        self.assertIsNone(feed["payments"][0]["authorization_id"])


if __name__ == "__main__":
    unittest.main()