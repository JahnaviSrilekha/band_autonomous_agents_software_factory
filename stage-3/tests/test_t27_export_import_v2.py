import copy
import unittest

import base
import helpers_t2 as h


class TestT27ExportImportV2(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def _build_rich_state(self):
        fixture = h.seeded_fixture([
            {"id": "a_open", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 2000, "status": "open", "expires_at": h.future()},
            {"id": "a_part", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 1000, "status": "open", "captured_amount": 300,
             "payment_ids": [], "expires_at": h.future()},
            {"id": "a_gone", "from_user_id": "u_bob", "to_user_id": "u_carol",
             "amount": 100, "status": "voided", "expires_at": h.future()},
            {"id": "a_old", "from_user_id": "u_ada", "to_user_id": "u_carol",
             "amount": 100, "status": "expired", "expires_at": h.past()},
        ])
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        ada = h.login(self.port)
        bob = h.login(self.port, "bob@example.com")
        # capture part of a_open (final:false) so payment_ids and captured links exist
        status, list_payload, _ = base.request(self.port, "GET", "/authorizations", headers=ada)
        open_id = next(a["authorization_id"] for a in list_payload["authorizations"]
                       if a["amount"] == 2000)
        status, capture, _ = base.request(
            self.port, "POST", f"/authorizations/{open_id}/capture",
            body={"amount": 500, "final": False},
            headers={**bob, "Idempotency-Key": "k-cap-x"})
        assert status == 201, capture
        # one ordinary payment too
        status, _, _ = base.request(self.port, "POST", "/payments",
                                    body={"to_handle": "bob", "amount": 50},
                                    headers={**ada, "Idempotency-Key": "k-pay-x"})
        assert status == 201
        return ada, bob

    def _export(self):
        status, payload, _ = base.request(self.port, "GET", "/_test/export")
        assert status == 200, payload
        return payload

    def _import(self, payload):
        return base.request(self.port, "POST", "/_test/import", body=payload)

    def test_export_is_format_version_2_with_new_fields(self):
        self._build_rich_state()
        payload = self._export()
        self.assertEqual(payload["format_version"], 3)
        state = payload["state"]
        self.assertEqual(state["authorization_ttl_seconds"], 600)
        self.assertEqual(len(state["authorizations"]), 4)
        by_id = {a["id"]: a for a in state["authorizations"]}
        self.assertIn("captured_amount", by_id["a_part"])
        self.assertIn("payment_ids", by_id["a_part"])
        self.assertIn("expires_at", by_id["a_open"])
        self.assertIn("authorization_id", state["payments"][0])

    def test_v2_round_trip_is_behavioral_noop(self):
        ada, bob = self._build_rich_state()
        first = self._export()
        status, _, _ = self._import(first)
        self.assertEqual(status, 204)
        second = self._export()
        self.assertEqual(first, second)
        # behavior identical after import
        status, me, _ = base.request(self.port, "GET", "/me", headers=ada)
        self.assertEqual(me["held"], 2200)
        self.assertEqual(me["available"], me["total"] - 2200)
        status, auths, _ = base.request(self.port, "GET", "/authorizations", headers=ada)
        by_id = {a["authorization_id"]: a for a in auths["authorizations"]}
        self.assertEqual(by_id["a_old"]["status"], "expired")
        self.assertEqual(by_id["a_part"]["captured_amount"], 300)
        status, auths_bob, _ = base.request(self.port, "GET", "/authorizations", headers=bob)
        by_id_bob = {a["authorization_id"]: a for a in auths_bob["authorizations"]}
        self.assertEqual(by_id_bob["a_gone"]["status"], "voided")

    def test_v1_import_defaults_and_continuity(self):
        self._build_rich_state()
        export = self._export()
        # hand-build a stage-1-shaped export: drop the two new state keys and
        # the new payment field
        v1 = copy.deepcopy(export)
        v1["format_version"] = 1
        del v1["state"]["authorization_ttl_seconds"]
        del v1["state"]["authorizations"]
        for p in v1["state"]["payments"]:
            p.pop("authorization_id", None)
        status, _, _ = self._import(v1)
        self.assertEqual(status, 204)
        # token still valid (R116)
        ada = h.login(self.port)
        status, me, _ = base.request(self.port, "GET", "/me", headers=ada)
        self.assertEqual(status, 200)
        self.assertEqual(me["held"], 0)
        state = self._export()["state"]
        self.assertEqual(state["authorization_ttl_seconds"], 600)
        self.assertEqual(state["authorizations"], [])
        for p in state["payments"]:
            self.assertIsNone(p["authorization_id"])

    def test_v1_import_from_real_stage1_shape(self):
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        v1 = {
            "track": "pocketful",
            "format_version": 1,
            "state": {
                "currency": "EUR", "minor_units": 2, "seq": 4,
                "settlement_operator_ids": [],
                "users": [
                    {"id": "u_ada", "email": "ada@example.com",
                     "password_hash": "aa:bb", "display_name": "Ada",
                     "handle": "ada", "balance": 10000},
                ],
                "tokens": [{"token": "tok_1", "user_id": "u_ada"}],
                "payments": [], "requests": [], "splits": [],
                "settlements": [], "idempotency": [],
            },
        }
        status, _, _ = self._import(v1)
        self.assertEqual(status, 204)
        status, me, _ = base.request(self.port, "GET", "/me",
                                     headers={"Authorization": "Bearer tok_1"})
        self.assertEqual(status, 200)
        self.assertEqual(me["available"], 10000)

    def test_unknown_version_still_422(self):
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        before = self._export()
        bad = {"track": "pocketful", "format_version": 4, "state": before["state"]}
        status, payload, _ = self._import(bad)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")
        self.assertEqual(self._export(), before)

    def test_v2_import_with_partial_captures_preserves_records(self):
        self._build_rich_state()
        export = self._export()
        status, _, _ = self._import(export)
        self.assertEqual(status, 204)
        ada = h.login(self.port)
        status, auths, _ = base.request(self.port, "GET", "/authorizations", headers=ada)
        by_id = {a["authorization_id"]: a for a in auths["authorizations"]}
        open_big = next(a for a in auths["authorizations"] if a["amount"] == 2000)
        self.assertEqual(open_big["captured_amount"], 500)
        self.assertEqual(open_big["remaining_amount"], 1500)
        self.assertEqual(open_big["status"], "open")
        self.assertIsNotNone(open_big["payment_id"])

    def test_v2_bad_authorization_reference_422(self):
        self._build_rich_state()
        bad = self._export()
        bad["state"]["payments"][0]["authorization_id"] = "a_ghost"
        status, payload, _ = self._import(bad)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_v2_unknown_user_reference_422(self):
        self._build_rich_state()
        bad = self._export()
        bad["state"]["authorizations"][0]["from_user_id"] = "u_ghost"
        status, payload, _ = self._import(bad)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_v2_bad_ttl_422(self):
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        bad = self._export()
        bad["state"]["authorization_ttl_seconds"] = 0
        status, payload, _ = self._import(bad)
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")


if __name__ == "__main__":
    unittest.main()