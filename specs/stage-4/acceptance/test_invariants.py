"""Stage-4 money invariants under randomised, retried and concurrent load.

Runs waves of mixed stage-4 writes (payments, requests, splits, settlements,
authorizations/captures/voids, single corrections, refunds, correction
batches) with duplicate idempotency-key retries and concurrent identical
requests, then asserts the design's invariants over the exported state after
every wave: conservation, no negative money, exactly-once, all-or-nothing
batches, refund caps, shared batch recorded_at, monotone recorded_at per
payment, and no 5xx anywhere (R262, R278, R279, R281, R288 + carried stage-1
invariants)."""
import random

from client import (
    check, eq, expect_ok, fresh, get_me, make_payment, correct, correction_body,
    fpayment, refund, refund_body, settle, transfer, create_request,
    pay_request, split, create_authz, capture, correction_batch, batch_item,
    revisions_of, run_concurrently, parse_inst,
)

SEED = 20261001
WAVES = 10
T_EFF = "2026-09-01T09:00:00+00:00"
HANDLES = {"u_ada": "ada", "u_bob": "bob", "u_cy": "cy", "u_op": "op"}


def iter_count():
    n = 0
    while True:
        n += 1
        yield n


def test_invariants_mixed_writes_fuzz(c):
    rng = random.Random(SEED)
    seeded = [fpayment(f"fp{i}", "u_ada", "u_bob", 50 + i, created_at=T_EFF)
              for i in range(1, 9)]
    toks = fresh(c, operator=True, payments=seeded)
    declared = {"u_ada": 100000, "u_bob": 50000, "u_cy": 0, "u_op": 10000}
    seeded_ids = [f"fp{i}" for i in range(1, 9)]
    payments = [f"fp{i}" for i in range(1, 9)]
    keys = iter_count()
    seen_calls = []  # zero-arg callables safe to retry byte-identically

    def key():
        return f"fz-{next(keys)}"

    def random_amount():
        return rng.choice([1, 5, 10, 25, 100, 250])

    for wave in range(WAVES):
        responses = []
        ops = [wave_op(c, rng, toks, payments, key, random_amount, seen_calls)
               for _ in range(8)]
        # A few concurrent identical refunds per wave (R52 replay family).
        if wave % 2 == 0 and payments:
            target = rng.choice(payments)
            k = key()
            responses.extend(run_concurrently([
                lambda t=target, kk=k: refund(c, toks["bob"], t, kk,
                                              refund_body(1))
            ] * 3))
        # Duplicate retries of earlier single-attempt calls.
        tried = [w for w in seen_calls if w._first_status is not None]
        if tried and rng.random() < 0.7:
            call = tried[rng.randrange(len(tried))]
            first = call._first_status
            retry = call()
            if first == 201:
                eq(retry.status, 200, "successful write replays 200")
            else:
                # A failed (4xx) attempt frees the key, so the identical
                # retry is treated as first use and may commit.
                check(retry.status in (first, 200, 201),
                      f"retry diverged oddly: {first} -> {retry.status}")
        for op in ops:
            r = op()  # first attempt
            responses.append(r)
            if rng.random() < 0.4:  # retried identical request
                retry = op()
                if r.status == 201:
                    eq(retry.status, 200, "identical retry of success is 200")
                else:
                    check(retry.status in (r.status, 200, 201),
                          f"identical retry diverged oddly: "
                          f"{r.status} -> {retry.status}")
        for r in responses:
            check(r.status <= 499,
                  f"no 5xx allowed: got {r.status}: {r.raw[:200]!r}")
        assert_invariants(c, toks, declared, seeded_ids)


def wave_op(c, rng, toks, payments, key, random_amount, seen_calls):
    """Build one random stage-4 write as a zero-arg callable returning the
    first-attempt Response. The callable is safely re-callable (same key, same
    body)."""
    kind = rng.choice(["payment", "request", "split", "settlement", "authz",
                       "capture", "void", "correction", "refund", "batch"])
    k = key()

    def payment():
        return make_payment(c, toks["ada"], "bob", 100, k)

    def request():
        return create_request(c, toks["bob"], "ada", 40, k)

    def split_op():
        return split(c, toks["ada"], 30, ["bob", "cy"], k)

    def settlement():
        return settle(c, toks["op"], [transfer("ada", "bob", 20),
                                      transfer("bob", "cy", 5)], k)

    def authz():
        return create_authz(c, toks["ada"], "bob", 60, k)

    def capture_op():
        if "aid" not in state:
            state["aid"] = open_authz_id(c, toks["ada"])
        return capture(c, toks["bob"], state["aid"], k,
                       {"amount": 5, "final": False})

    def void():
        if "aid" not in state:
            state["aid"] = open_authz_id(c, toks["ada"])
        return c.post(f"/authorizations/{state['aid']}/void", body={},
                      token=toks["ada"], headers={"Idempotency-Key": k})

    state = {}

    def correction():
        if "body" not in state:
            pid = rng.choice(payments)
            rev = current_revision(c, toks["ada"], pid)
            state["path"] = f"/payments/{pid}/corrections"
            state["body"] = correction_body(rev, rng.choice([0, 10, 50]),
                                            T_EFF, "fuzz")
        return c.post(state["path"], body=state["body"], token=toks["ada"],
                      headers={"Idempotency-Key": k})

    def refund_op():
        if "body" not in state:
            pid = rng.choice(payments)
            state["path"] = f"/payments/{pid}/refunds"
            state["body"] = refund_body(1)
        return c.post(state["path"], body=state["body"], token=toks["bob"],
                      headers={"Idempotency-Key": k})

    def batch():
        if "body" not in state:
            items = []
            for pid in rng.sample(payments, rng.randint(1, 3)):
                rev = current_revision(c, toks["ada"], pid)
                items.append(batch_item(pid, rev, rng.choice([0, 10, 50]),
                                        T_EFF, "fuzz"))
            state["body"] = {"corrections": items}
        return c.post("/correction-batches", body=state["body"],
                      token=toks["op"], headers={"Idempotency-Key": k})

    fn = {"payment": payment, "request": request, "split": split_op,
          "settlement": settlement, "authz": authz, "capture": capture_op,
          "void": void, "correction": correction, "refund": refund_op,
          "batch": batch}[kind]

    def wrapped():
        r = fn()
        wrapped._first_status = r.status
        return r

    wrapped._first_status = None
    seen_calls.append(wrapped)
    return wrapped


def open_authz_id(c, token):
    r = expect_ok(c.get("/authorizations?status=open", token=token), 200)
    if r["authorizations"]:
        return r["authorizations"][0]["authorization_id"]
    return create_open_authz(c, token)


_AZ_KEY = iter_count()


def create_open_authz(c, token):
    n = next(_AZ_KEY)
    r = expect_ok(c.post("/authorizations", body={"to_handle": "bob",
                                                  "amount": 500},
                         token=token, headers={"Idempotency-Key": f"fz-az-{n}"}),
                  201)
    return r["authorization_id"]


def current_revision(c, token, pid):
    revs = revisions_of(c, token, pid)
    return revs[-1]["revision"] if revs else 1


def assert_invariants(c, toks, declared, seeded_ids):
    exp = expect_ok(c.export(), 200, "export for invariants")
    payments = exp["state"]["payments"]
    by_id = {p["id"]: p for p in payments}

    # 1. Conservation: per stage-3 R180 the fixture's declared balance is the
    # post-reset balance, and the opening absorbs the seeded payments at
    # revision 1. So for every user:
    #   balance == declared - net(seeds@rev1) + net(all payments@current)
    # — money is only ever moved, never minted or burned (R262 family).
    def net_over(payments_iter, amount_of):
        net = {}
        for p in payments_iter:
            a = amount_of(p)
            net[p["from_user_id"]] = net.get(p["from_user_id"], 0) - a
            net[p["to_user_id"]] = net.get(p["to_user_id"], 0) + a
        return net

    def rev1_amount(p):
        revs = p.get("revisions") or []
        return revs[0]["amount"] if revs else p["amount"]

    seeded = [p for p in payments if p["id"] in set(seeded_ids)]
    net_rev1 = net_over(seeded, rev1_amount)
    net_now = net_over(payments, current_amount)
    for uid, decl in declared.items():
        expected = decl - net_rev1.get(uid, 0) + net_now.get(uid, 0)
        balance = get_me(c, toks[HANDLES[uid]])["balance"]
        eq(balance, expected, f"conservation for {uid} over current revisions")

    # 2. No negative money, ever.
    for handle, t in toks.items():
        me = get_me(c, t)
        for field in ("balance", "total", "available", "held"):
            check(me[field] >= 0, f"{handle} {field} must be >= 0: {me[field]}")

    # 3. Refund cap: sum of refunds of a payment <= its current amount (R259).
    for p in payments:
        refunded = sum(q["amount"] for q in payments
                       if q.get("refund_of") == p["id"])
        current = current_amount(p)
        check(refunded <= current,
              f"refunds of {p['id']} ({refunded}) exceed current amount ({current})")

    # 4. Refund payments are well-formed opposites (R260).
    for q in payments:
        target_id = q.get("refund_of")
        if target_id is None:
            continue
        check(target_id in by_id, f"refund_of {target_id} resolves")
        target = by_id[target_id]
        eq(q["from_user_id"], target["to_user_id"], "refund from = target to")
        eq(q["to_user_id"], target["from_user_id"], "refund to = target from")
        eq(q.get("request_id"), None, "refund request_id null")
        eq(q.get("authorization_id"), None, "refund authorization_id null")
        check(current_amount(q) >= 1, "refund amount positive")

    # 5. recorded_at strictly increasing per payment; batch revisions share
    # recorded_at and carry the batch id (R281).
    for p in payments:
        revs = p.get("revisions") or []
        stamps = [parse_inst(r["recorded_at"]) for r in revs]
        check(all(a < b for a, b in zip(stamps, stamps[1:])),
              f"{p['id']} recorded_at strictly increasing")
        batch_ids = {r.get("correction_batch_id") for r in revs
                     if r.get("correction_batch_id")}
        for bid in batch_ids:
            shared = {r["recorded_at"] for r in revs
                      if r.get("correction_batch_id") == bid}
            eq(len(shared), 1, f"{p['id']} batch {bid} revisions share recorded_at")
            batched = [r["revision"] for r in revs
                       if r.get("correction_batch_id") == bid]
            eq(batched, list(range(batched[0], batched[0] + len(batched))),
               f"{p['id']} batch revisions contiguous")

    # 6. Amounts stay in the legal envelope (stage-1 R25/stage-3 R187).
    for p in payments:
        for r in p.get("revisions") or []:
            check(isinstance(r["amount"], int)
                  and 0 <= r["amount"] <= 1000000000,
                  f"{p['id']} revision amount in range: {r['amount']}")


def current_amount(p):
    revs = p.get("revisions") or []
    return revs[-1]["amount"] if revs else p["amount"]