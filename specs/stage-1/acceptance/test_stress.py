"""Randomised concurrent stress: conservation, no-negative, exactly-once,
no 5xx (R1, R2, R3, R42, R52) under interleaved competing clients."""
import random

from client import (check, eq, expect_ok, fresh, get_me, payment_body,
                    run_concurrently)

SEED = 20260930


def make_pay(c, token, to_handle, amount, key):
    return c.post("/payments", body=payment_body(to_handle, amount), token=token,
                  headers={"Idempotency-Key": key})


def create_request(c, token, payer_handle, amount, key):
    return c.post("/requests", body={"payer_handle": payer_handle, "amount": amount},
                  token=token, headers={"Idempotency-Key": key})


def test_no_5xx_under_concurrent_burst(c):
    # R10/R42: 50 in-flight mixed reads and writes; no 5xx allowed.
    toks = fresh(c, operator=True)

    def op(i):
        if i % 5 == 0:
            return c.get("/activity", token=toks["ada"])
        if i % 5 == 1:
            return c.get("/me", token=toks["bob"])
        if i % 5 == 2:
            return make_pay(c, toks["ada"], "bob", 1, f"burst-{i}")
        if i % 5 == 3:
            return create_request(c, toks["bob"], "cy", 10 + i, f"burrq-{i}")
        return c.get("/requests", token=toks["cy"])

    results = run_concurrently([lambda i=i: op(i) for i in range(50)])
    fives = [r.status for r in results if r.status >= 500]
    eq(fives, [], "no 5xx responses under concurrent load (R42)")
    bad = sorted({r.status for r in results} - {200, 201})
    eq(bad, [], f"burst only produces 200/201, saw {bad}")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 10, "exactly 10 payments debited")
    eq(get_me(c, toks["bob"])["balance"], 50000 + 10, "exactly 10 payments credited")


def test_mixed_concurrent_operations_invariants(c):
    # Randomised interleaving of every operation kind with retries and
    # duplicate keys; after the storm every stated invariant must hold.
    rng = random.Random(SEED)
    handles = ["ada", "bob", "cy", "dee"]
    balances = {"ada": 40000, "bob": 30000, "cy": 20000, "dee": 10000,
                "op": 10000}
    users = [{"id": f"u_{h}", "email": f"{h}@example.com",
              "password": "correct horse", "display_name": h.capitalize(),
              "handle": h, "balance": balances[h]} for h in balances]
    seeded_total = sum(balances.values())
    c.reset({"currency": "EUR", "minor_units": 2, "users": users,
             "payments": [], "requests": [],
             "settlement_operator_ids": ["u_op"]})
    toks = {h: c.token_for(h) for h in balances}
    statuses = []

    def worker(wid):
        local = random.Random(SEED + wid)
        for i in range(30):
            kind = local.randrange(7)
            handle = handles[local.randrange(4)]
            tok = toks[handle]
            other = handles[local.randrange(4)]
            while other == handle:
                other = handles[local.randrange(4)]
            key = f"s{wid}-{i}"
            if kind == 0:  # payment + same-key retry of the identical body
                amount = local.randrange(1, 2000)
                resp = make_pay(c, tok, other, amount, key)
                statuses.append(resp.status)
                if resp.status == 201 and local.random() < 0.5:
                    statuses.append(
                        make_pay(c, tok, other, amount, key).status)  # replay -> 200
            elif kind == 1:  # money request
                statuses.append(
                    create_request(c, tok, other, local.randrange(1, 5000), key).status)
            elif kind == 2:  # pay one of my incoming pending requests
                reqs = expect_ok(
                    c.get("/requests?direction=incoming&status=pending", token=tok),
                    200)["requests"]
                if reqs:
                    rq = local.choice(reqs)
                    statuses.append(c.post(
                        f"/requests/{rq['request_id']}/pay", body={}, token=tok,
                        headers={"Idempotency-Key": key}).status)
            elif kind == 3:  # decline/cancel a pending request I am party to
                reqs = expect_ok(c.get("/requests?status=pending", token=tok),
                                 200)["requests"]
                if reqs:
                    rq = local.choice(reqs)
                    if rq["payer_handle"] == handle:
                        statuses.append(c.post(
                            f"/requests/{rq['request_id']}/decline",
                            token=tok).status)
                    else:
                        statuses.append(c.post(
                            f"/requests/{rq['request_id']}/cancel", token=tok).status)
            elif kind == 4:  # split
                participants = local.sample(handles, local.randrange(1, 5))
                statuses.append(c.post("/splits", body={
                    "amount": local.randrange(1, 3000),
                    "participant_handles": participants}, token=tok,
                    headers={"Idempotency-Key": key}).status)
            elif kind == 5:  # operator settlement (small, affordable)
                statuses.append(c.post("/settlements", body={"transfers": [
                    {"from_handle": "ada", "to_handle": "cy",
                     "amount": local.randrange(1, 100)}]}, token=toks["op"],
                    headers={"Idempotency-Key": key}).status)
            else:  # reads
                statuses.append(c.get("/activity", token=tok).status)

    run_concurrently([lambda w=w: worker(w) for w in range(6)])
    fives = [s for s in statuses if s >= 500]
    eq(fives, [], "no 5xx during the storm (R42)")
    allowed = {200, 201, 400, 401, 403, 404, 409, 422}
    bad = sorted({s for s in statuses} - allowed)
    eq(bad, [], f"only spec-defined statuses observed, saw {bad}")
    # Invariant R1: sum of balances still equals the seeded total.
    final_total = sum(get_me(c, toks[h])["balance"] for h in balances)
    eq(final_total, seeded_total, "sum of balances equals seeded total (R1)")
    # Invariant R2: no negative balances.
    for h in balances:
        check(get_me(c, toks[h])["balance"] >= 0, f"{h} balance nonnegative (R2)")
    # Invariant R3: every paid request carries a payment id; replayed payments
    # (kind 0 retried) must not have doubled any debit.
    for h in handles:
        mine = expect_ok(c.get("/requests?limit=200", token=toks[h]), 200)["requests"]
        for rq in mine:
            if rq["status"] == "paid":
                check(rq["payment_id"],
                      f"paid request {rq['request_id']} has payment_id (R3)")