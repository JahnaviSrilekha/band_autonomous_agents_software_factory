"""Reviewer's independent batch-3/batch-4 probe (stage-4, T55-T59).

In-process (no container), mirrors stage-4/tests/base.py's harness style.
Targets the amended-requirement edges from coordinator-docs-stage4
(R253 auth-before-idempotency-key ordering, R262/R267/R288 concurrency
serialization) plus R289/R290 (export v4 referential integrity) and R287
(refund of a settlement member leaves Settlement untouched).
"""
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "..", "stage-4", "tests"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "..", "stage-4", "src"))
import base
from pocketful import state as state_module

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
    "to_handle": "bob", "amount": 1000, "note": "x", "visibility": "public"},
    headers={**ada, "Idempotency-Key": "k-pay-1"})
assert s == 201, body
payment_id = body["payment_id"]

# --- R253: auth gate (401) must be checked before idempotency-key (400) ---
s, body, _ = base.request(port, "POST", f"/payments/{payment_id}/refunds",
                           body={"amount": 100})
check("R253 missing token -> 401 unauthenticated (not 400)", s == 401 and
      body.get("error", {}).get("code") == "unauthenticated", (s, body))

s, body, _ = base.request(port, "POST", f"/payments/{payment_id}/refunds",
                           body={"amount": 100},
                           headers={"Authorization": "Bearer garbage"})
check("R253 invalid token -> 401 before idem-key check", s == 401 and
      body.get("error", {}).get("code") == "unauthenticated", (s, body))

# --- R289/R290: export v4 referential integrity on refund_of ---
s, body, _ = base.request(port, "GET", "/_test/export", headers=ada)
assert s == 200, body
check("R290 export format_version is 4", body["format_version"] == 4, body["format_version"])
exported = body

bad = {**exported, "state": dict(exported["state"])}
bad["state"]["payments"] = list(exported["state"]["payments"]) + [{
    "id": "p_forged_refund", "from_user_id": "u_bob", "to_user_id": "u_ada",
    "amount": 50, "note": "", "visibility": "private", "request_id": None,
    "settlement_id": None, "effective_at": T_NOON, "recorded_at": T_NOON,
    "authorization_id": None, "refund_of": "p_does_not_exist",
    "revisions": [],
}]
s, body, _ = base.request(port, "POST", "/_test/import", body=bad, headers=ada)
check("R289/R290 import rejects refund_of referencing unknown payment", s == 422 and
      body.get("error", {}).get("code") == "validation_failed", (s, body))

self_ref = {**exported, "state": dict(exported["state"])}
self_ref["state"]["payments"] = list(exported["state"]["payments"]) + [{
    "id": "p_self_ref", "from_user_id": "u_bob", "to_user_id": "u_ada",
    "amount": 50, "note": "", "visibility": "private", "request_id": None,
    "settlement_id": None, "effective_at": T_NOON, "recorded_at": T_NOON,
    "authorization_id": None, "refund_of": "p_self_ref",
    "revisions": [],
}]
s, body, _ = base.request(port, "POST", "/_test/import", body=self_ref, headers=ada)
check("R289/R290 import rejects self-referencing refund_of", s == 422 and
      body.get("error", {}).get("code") == "validation_failed", (s, body))

# --- R262/R288: concurrent refunds against one target commit only the fitting subset ---
s, body, _ = base.request(port, "POST", "/payments", body={
    "to_handle": "bob", "amount": 500, "note": "cap-target", "visibility": "public"},
    headers={**ada, "Idempotency-Key": "k-pay-cap"})
assert s == 201, body
cap_target = body["payment_id"]
barrier = threading.Barrier(5)
results = []


def do_refund(i):
    barrier.wait()
    st, pl, _ = base.request(port, "POST", f"/payments/{cap_target}/refunds",
                              body={"amount": 150},
                              headers={**bob, "Idempotency-Key": f"probe-cap-{i}"})
    results.append((st, pl))


threads = [threading.Thread(target=do_refund, args=(i,)) for i in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()
created = [s for s, _ in results if s == 201]
capped = [s for s, _ in results if s == 422]
check("R262/R288 concurrent over-cap refunds: exactly 3 commit, 2 capped",
      len(created) == 3 and len(capped) == 2, results)
refunded_total = sum(p.amount for p in state_module.STATE.payments if p.refund_of == cap_target)
check("R262 refunded total stops at fitting subset (450)", refunded_total == 450, refunded_total)

# --- R287: refunding a settlement member leaves Settlement untouched ---
s, body, _ = base.request(port, "POST", "/settlements", body={
    "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 200}]},
    headers={**op, "Idempotency-Key": "k-settle-1"})
assert s == 201, body
settlement_id = body["settlement_id"]
member_id = body["payments"][0]["payment_id"]
before_payment_ids = list(state_module.STATE.settlements[settlement_id].payment_ids)
before_transfers = list(state_module.STATE.settlements[settlement_id].transfers)
s, body, _ = base.request(port, "POST", f"/payments/{member_id}/refunds",
                           body={"amount": 200},
                           headers={**bob, "Idempotency-Key": "k-settle-refund"})
check("R287 refunding settlement member succeeds (201)", s == 201, (s, body))
after = state_module.STATE.settlements[settlement_id]
check("R287 Settlement.payment_ids untouched", list(after.payment_ids) == before_payment_ids)
check("R287 Settlement.transfers untouched", list(after.transfers) == before_transfers)

base.stop_server(httpd)

print()
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("ALL PASS")
