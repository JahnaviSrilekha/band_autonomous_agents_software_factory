import unittest

import base
from pocketful import state as state_module

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 800},
    ],
}

CORRECTION = {"expected_revision": 1, "amount": 400,
              "effective_at": "2026-09-20T12:00:00+00:00", "reason": "corrected amount"}


def login(port, email):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


class TestT42Revisions(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        assert status == 204
        self.ada = login(self.port, "ada@example.com")
        self.bob = login(self.port, "bob@example.com")
        self.cy = login(self.port, "cy@example.com")
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500, "note": "lunch", "visibility": "public"},
            headers={**self.ada, "Idempotency-Key": "k-pay"})
        assert status == 201, payload
        self.payment_id = payload["payment_id"]
        self.original_response = payload
        self.path = f"/payments/{self.payment_id}/revisions"

    def tearDown(self):
        base.stop_server(self.httpd)

    def correct(self, body=None, key="k-corr"):
        return base.request(self.port, "POST", f"/payments/{self.payment_id}/corrections",
                            body=CORRECTION if body is None else body,
                            headers={**self.ada, "Idempotency-Key": key})

    def test_revisions_shape_with_revision_1_empty_reason(self):
        status, payload, _ = self.correct()
        self.assertEqual(status, 201)
        status, payload, _ = base.request(self.port, "GET", self.path, headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual(set(payload.keys()), {"revisions"})
        self.assertEqual(len(payload["revisions"]), 2)
        first, second = payload["revisions"]
        self.assertEqual(set(first.keys()), {"revision", "amount", "effective_at",
                                             "recorded_at", "reason", "correction_batch_id"})
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["amount"], 500)
        self.assertEqual(first["reason"], "")
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["amount"], 400)
        self.assertEqual(second["reason"], "corrected amount")
        self.assertEqual(second["effective_at"], CORRECTION["effective_at"])
        self.assertTrue(first["recorded_at"] < second["recorded_at"])

    def test_no_token_401(self):
        status, payload, _ = base.request(self.port, "GET", self.path)
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "unauthenticated")

    def test_third_party_404_even_public(self):
        status, payload, _ = base.request(self.port, "GET", self.path, headers=self.cy)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_receiver_200(self):
        status, payload, _ = base.request(self.port, "GET", self.path, headers=self.bob)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["revisions"]), 1)

    def test_unknown_payment_404(self):
        status, payload, _ = base.request(self.port, "GET", "/payments/p_nope/revisions",
                                          headers=self.ada)
        self.assertEqual(status, 404)

    def test_activity_unchanged_by_correction(self):
        status, before, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        self.assertEqual(status, 200)
        status, _, _ = self.correct()
        self.assertEqual(status, 201)
        status, after, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        self.assertEqual(status, 200)
        self.assertEqual([p["payment_id"] for p in after["payments"]],
                         [p["payment_id"] for p in before["payments"]])
        entry = next(p for p in after["payments"] if p["payment_id"] == self.payment_id)
        self.assertEqual(entry["created_at"], self.original_response["created_at"])
        self.assertEqual(entry["from_user_id"], "u_ada")
        self.assertEqual(entry["to_user_id"], "u_bob")
        self.assertEqual(entry["visibility"], "public")

    def test_activity_ordering_retained_after_correction(self):
        self.correct()
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 50}, headers={**self.ada, "Idempotency-Key": "k-later"})
        self.assertEqual(status, 201)
        status, feed, _ = base.request(self.port, "GET", "/activity", headers=self.ada)
        created = [p["created_at"] for p in feed["payments"]]
        self.assertEqual(created, sorted(created, reverse=True))

    def test_original_idempotent_replay_unchanged_after_correction(self):
        self.correct()
        status, payload, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "bob", "amount": 500, "note": "lunch", "visibility": "public"},
            headers={**self.ada, "Idempotency-Key": "k-pay"})
        self.assertEqual(status, 200)
        self.assertEqual(payload, self.original_response)

    def test_revisions_state_matches_endpoint(self):
        self.correct(key="k-one")
        self.correct(body={**CORRECTION, "expected_revision": 2, "amount": 350,
                           "reason": "again"}, key="k-two")
        payment = next(p for p in state_module.STATE.payments if p.id == self.payment_id)
        status, payload, _ = base.request(self.port, "GET", self.path, headers=self.ada)
        self.assertEqual(payload["revisions"],
                         [r.to_json() for r in payment.revisions])
        self.assertEqual(len(payload["revisions"]), 3)


if __name__ == "__main__":
    unittest.main()