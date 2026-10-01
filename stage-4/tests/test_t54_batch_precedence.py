import unittest

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "settlement_operator_ids": ["u_op"],
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 2000000000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 800},
        {"id": "u_op", "email": "op@example.com", "password": "correct horse",
         "display_name": "Op", "handle": "op", "balance": 100},
    ],
}

T_NOON = "2026-09-20T12:00:00+00:00"
T_NOON_CEST = "2026-09-20T14:00:00+02:00"
T_SEP19 = "2026-09-19T12:00:00+00:00"
T_SEP21 = "2026-09-21T12:00:00+00:00"


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT54BatchPrecedence(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")
        self.op = login(self.port, "op@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def pay(self, from_headers, key, to_handle, amount, note="n"):
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": to_handle, "amount": amount, "note": note,
            "visibility": "public"}, headers={**from_headers, "Idempotency-Key": key})
        assert status == 201, payload
        return payload["payment_id"]

    def batch(self, items, key):
        return base.request(self.port, "POST", "/correction-batches",
                            body={"corrections": items},
                            headers={**self.op, "Idempotency-Key": key})

    def item(self, payment_id, amount, effective_at=T_NOON, expected_revision=1):
        return {"payment_id": payment_id, "expected_revision": expected_revision,
                "amount": amount, "effective_at": effective_at, "reason": "reversal"}

    def test_item_error_beats_settlement_completeness(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        member_id = payload["payments"][0]["payment_id"]
        items = [self.item("p_nope", 100), self.item(member_id, 0)]
        status, payload, _ = self.batch(items, "k-pair-item-completeness")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_item_error_beats_funds(self):
        p1 = self.pay(self.ada, "k-p1", "cy", 1000)
        p2 = self.pay(self.ada, "k-p2", "cy", 600)
        items = [self.item(p1, 0, effective_at="2099-01-01T00:00:00+00:00"),
                 self.item(p2, 0)]
        status, payload, _ = self.batch(items, "k-pair-item-funds")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_settlement_completeness_beats_current_funds(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2000},
                          {"from_handle": "cy", "to_handle": "bob", "amount": 1500}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        member_id = payload["payments"][0]["payment_id"]
        self.pay(self.cy, "k-sweep", "bob", 1300)
        self.assertEqual(state_module.STATE.users["u_cy"].balance, 0)
        items = [self.item(member_id, 0)]
        status, payload, _ = self.batch(items, "k-pair-completeness-funds")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "incomplete_settlement")

    def test_effective_consistency_beats_current_funds(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2000},
                          {"from_handle": "cy", "to_handle": "bob", "amount": 1500}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        m1, m2 = (p["payment_id"] for p in payload["payments"])
        items = [self.item(m1, 0, effective_at=T_NOON),
                 self.item(m2, 2400, effective_at=T_SEP21)]
        status, payload, _ = self.batch(items, "k-pair-consistency-funds")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_current_funds_beat_historical(self):
        p1 = self.pay(self.ada, "k-p1", "cy", 1000)
        p2 = self.pay(self.ada, "k-p2", "cy", 600)
        self.pay(self.cy, "k-q", "bob", 1800)
        items = [self.item(p1, 0), self.item(p2, 100)]
        status, payload, _ = self.batch(items, "k-pair-current-historical")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")
        payment = next(p for p in state_module.STATE.payments if p.id == p1)
        self.assertEqual(len(payment.revisions), 1)

    def test_historical_overdraft_when_current_passes(self):
        p1 = self.pay(self.ada, "k-p1", "cy", 1000)
        q = self.pay(self.cy, "k-q", "bob", 1800)
        items = [self.item(p1, 100, effective_at=T_NOON),
                 self.item(q, 900, effective_at=T_SEP19)]
        status, payload, _ = self.batch(items, "k-historical-only")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "historical_overdraft")
        cy = state_module.STATE.users["u_cy"]
        self.assertEqual(cy.balance, 0)

    def test_combined_affordability_succeeds(self):
        a = self.pay(self.ada, "k-a", "bob", 500)
        c = self.pay(self.ada, "k-c", "bob", 400)
        self.pay(self.bob, "k-sweep", "cy", 3400)
        self.assertEqual(state_module.STATE.users["u_bob"].balance, 0)
        items = [self.item(a, 300), self.item(c, 700)]
        status, payload, _ = self.batch(items, "k-combined")
        self.assertEqual(status, 201, payload)
        bob = state_module.STATE.users["u_bob"]
        self.assertEqual(bob.balance, 100)
        ada = state_module.STATE.users["u_ada"]
        self.assertEqual(ada.balance, 2000000000 - 900 - 100)

    def test_sequential_evaluation_would_fail(self):
        # the same two items corrected one-by-one against live state would fail
        # on the first (debit 200 with 0 available) — the combined check passes
        a = self.pay(self.ada, "k-a", "bob", 500)
        c = self.pay(self.ada, "k-c", "bob", 400)
        self.pay(self.bob, "k-sweep", "cy", 3400)
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{a}/corrections",
                                          body={"expected_revision": 1, "amount": 300,
                                                "effective_at": T_NOON, "reason": "solo"},
                                          headers={**self.ada, "Idempotency-Key": "k-solo"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "insufficient_funds")
        status, payload, _ = self.batch([self.item(a, 300), self.item(c, 700)],
                                        "k-combined-2")
        self.assertEqual(status, 201, payload)

    def test_all_settlement_members_together_succeed(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 2000},
                          {"from_handle": "cy", "to_handle": "bob", "amount": 1500}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        m1, m2 = (p["payment_id"] for p in payload["payments"])
        items = [self.item(m1, 1900, effective_at=T_NOON),
                 self.item(m2, 1400, effective_at=T_NOON_CEST)]
        status, payload, _ = self.batch(items, "k-all-members")
        self.assertEqual(status, 201, payload)
        settlement = next(iter(state_module.STATE.settlements.values()))
        self.assertEqual(settlement.payment_ids, [m1, m2])

    def test_offset_spellings_same_instant_accepted(self):
        status, payload, _ = base.request(self.port, "POST", "/settlements", body={
            "transfers": [{"from_handle": "ada", "to_handle": "cy", "amount": 200}]},
            headers={**self.op, "Idempotency-Key": "k-settle"})
        self.assertEqual(status, 201, payload)
        # single-member settlement: no cross-member consistency constraint
        items = [self.item(payload["payments"][0]["payment_id"], 150,
                           effective_at=T_NOON_CEST)]
        status, payload, _ = self.batch(items, "k-offset")
        self.assertEqual(status, 201, payload)

    def test_stale_revision_beats_refund_floor(self):
        # staleness (409) is checked before the refund floor (422) in batch
        # items, matching the single-correction endpoint (design sec6/sec7)
        p = self.pay(self.ada, "k-stale-floor", "bob", 500)
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{p}/refunds",
                                          body={"amount": 200},
                                          headers={**self.bob, "Idempotency-Key": "k-ref"})
        self.assertEqual(status, 201, payload)
        status, payload, _ = self.batch([self.item(p, 100, expected_revision=9)],
                                        "k-stale-floor-item")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "stale_revision")

    def test_fresh_revision_floor_violation_still_422(self):
        p = self.pay(self.ada, "k-fresh-floor", "bob", 500)
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{p}/refunds",
                                          body={"amount": 200},
                                          headers={**self.bob, "Idempotency-Key": "k-ref"})
        self.assertEqual(status, 201, payload)
        status, payload, _ = self.batch([self.item(p, 100, expected_revision=1)],
                                        "k-fresh-floor-item")
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "refund_exceeds_payment")

    def test_stale_revision_with_floor_ok_still_409(self):
        p = self.pay(self.ada, "k-stale-ok", "bob", 500)
        status, payload, _ = base.request(self.port, "POST",
                                          f"/payments/{p}/refunds",
                                          body={"amount": 200},
                                          headers={**self.bob, "Idempotency-Key": "k-ref"})
        self.assertEqual(status, 201, payload)
        status, payload, _ = self.batch([self.item(p, 300, expected_revision=9)],
                                        "k-stale-ok-item")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "stale_revision")

    def test_rejected_batch_leaves_everything_unchanged(self):
        p1 = self.pay(self.ada, "k-p1", "cy", 1000)
        before = {
            "balances": {u.id: u.balance for u in state_module.STATE.users.values()},
            "revisions": {p.id: len(p.revisions) for p in state_module.STATE.payments},
        }
        items = [self.item(p1, 0), self.item(p1, 0)]
        status, payload, _ = self.batch(items, "k-rejected")
        self.assertEqual(status, 422)
        after = {
            "balances": {u.id: u.balance for u in state_module.STATE.users.values()},
            "revisions": {p.id: len(p.revisions) for p in state_module.STATE.payments},
        }
        self.assertEqual(before, after)
        self.assertNotIn(("u_op", "POST", "/correction-batches", "k-rejected"),
                         state_module.STATE.idempotency)


if __name__ == "__main__":
    unittest.main()