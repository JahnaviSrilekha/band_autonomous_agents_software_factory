"""Reviewer's independent probe for the T53 batch-precedence fix (0b5a610).

Confirms stale_revision (409) is checked before refund_exceeds_payment (422)
in /correction-batches' per-item pipeline, matching the single-correction
endpoint and design.md's resolved sec6/sec7 order (staleness before floor).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "..", "stage-4", "tests"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "..", "stage-4", "src"))
import base

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f": {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


FIXTURE = {
    "currency": "EUR", "minor_units": 2,
    "settlement_operator_ids": ["u_op"],
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 100000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 100000},
        {"id": "u_op", "email": "op@example.com", "password": "correct horse",
         "display_name": "Op", "handle": "op", "balance": 100},
    ],
}
T_NOON = "2026-09-20T12:00:00+00:00"


def login(port, email):
    s, b, _ = base.request(port, "POST", "/auth/login",
                            body={"email": email, "password": "correct horse"})
    assert s == 200, b
    return {"Authorization": f"Bearer {b['token']}"}


httpd, port = base.make_server()
s, _, _ = base.request(port, "POST", "/_test/reset", FIXTURE)
assert s == 204
ada = login(port, "ada@example.com")
bob = login(port, "bob@example.com")
op = login(port, "op@example.com")

s, body, _ = base.request(port, "POST", "/payments", body={
    "to_handle": "bob", "amount": 500, "note": "x", "visibility": "public"},
    headers={**ada, "Idempotency-Key": "k-pay"})
assert s == 201, body
payment_id = body["payment_id"]

s, body, _ = base.request(port, "POST", f"/payments/{payment_id}/refunds",
                           body={"amount": 200},
                           headers={**bob, "Idempotency-Key": "k-ref"})
assert s == 201, body


def batch(item_amount, expected_revision):
    return base.request(port, "POST", "/correction-batches", body={
        "corrections": [{"payment_id": payment_id, "expected_revision": expected_revision,
                          "amount": item_amount, "effective_at": T_NOON, "reason": "x"}]},
        headers={**op, "Idempotency-Key": f"k-batch-{expected_revision}-{item_amount}"})


# stale (wrong expected_revision) AND would violate the refund floor -> 409 wins
s, body, _ = batch(100, 9)
check("stale+floor-violating -> 409 stale_revision (not 422)", s == 409 and
      body.get("error", {}).get("code") == "stale_revision", (s, body))

# fresh (correct expected_revision) but violates floor -> 422
s, body, _ = batch(100, 1)
check("fresh+floor-violating -> 422 refund_exceeds_payment", s == 422 and
      body.get("error", {}).get("code") == "refund_exceeds_payment", (s, body))

# stale but floor would be fine -> still 409 (staleness checked first)
s, body, _ = batch(300, 9)
check("stale+floor-ok -> still 409 stale_revision", s == 409 and
      body.get("error", {}).get("code") == "stale_revision", (s, body))

base.stop_server(httpd)

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL PASS")
