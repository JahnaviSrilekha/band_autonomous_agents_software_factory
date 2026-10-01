"""Stage-3 money-invariant stress: conservation in every historical view
(R202), exactly-once corrections, no-5xx under 50-in-flight load, revision
consistency under fuzz (R193/R201/A33), concurrent same-revision corrections
(R231). Randomized but deterministically seeded."""
import random
import urllib.parse

from client import (
    check, eq, expect_error, expect_ok, fixture, fpayment, get_me, me_json,
    statement_ok, correct, correction_body, revisions_of, make_payment,
    create_authz, run_concurrently, fuser, parse_inst, rfc3339,
    T0, T1, T2, T3, FAR_FUTURE,
)

USERS = [fuser("u_ada", "ada", 9300), fuser("u_bob", "bob", 10100),
         fuser("u_cy", "cy", 600), fuser("u_op", "op", 10000)]
SEEDED_TOTAL = 9300 + 10100 + 600 + 10000
FAR_PAST = "1970-01-01T00:00:00+00:00"
SENDER = {"p_s1": "ada", "p_s2": "bob", "p_s3": "ada", "p_s4": "bob"}


def sfix(c):
    r = c.reset(fixture(
        users=USERS,
        payments=[
            fpayment("p_s1", "u_ada", "u_bob", 500, created_at=T1),
            fpayment("p_s2", "u_bob", "u_cy", 300, created_at=T2, note="rent",
                     visibility="private"),
            fpayment("p_s3", "u_ada", "u_cy", 200, created_at=T2),
            fpayment("p_s4", "u_bob", "u_cy", 100, created_at=T3),
        ],
        operators=["u_op"]))
    eq(r.status, 204, "reset")
    return {u["handle"]: c.token_for(u["handle"]) for u in USERS}


def historical_grid_conservation(c, toks, msg):
    for as_of in (FAR_PAST, T0, T1, T2, T3, rfc3339(0), FAR_FUTURE):
        for known_at in (T1, T2, None):
            total = sum(me_json(c, toks[h], as_of=as_of, known_at=known_at)["total"]
                        for h in ("ada", "bob", "cy", "op"))
            eq(total, SEEDED_TOTAL,
               f"{msg}: conservation at as_of={as_of} known_at={known_at} (R202)")


def no_negative_money(c, toks, msg):
    for h, t in toks.items():
        m = get_me(c, t)
        check(m["total"] >= 0 and m["available"] >= 0 and m["balance"] >= 0,
              f"{msg}: {h} money nonnegative (R2/R122): {m!r}")


def recorded_times_strictly_increasing(c, toks, pid, msg):
    revs = revisions_of(c, toks[SENDER[pid]], pid)
    rec = [parse_inst(r["recorded_at"]) for r in revs]
    check(rec == sorted(rec) and len(set(rec)) == len(rec),
          f"{msg}: recorded_at strictly increases (R193): {revs!r}")
    return len(revs)


def test_r202_conservation_after_mixed_valid_corrections(c):
    toks = sfix(c)
    rng = random.Random(20261001)
    for i, pid in enumerate(("p_s1", "p_s2", "p_s3", "p_s4")):
        sender = SENDER[pid]
        revs = len(revisions_of(c, toks[sender], pid))
        body = correction_body(revs, rng.randrange(0, 900),
                               rng.choice([T0, T1, T2, T3]), "grid")
        expect_ok(correct(c, toks[sender], pid, f"inv-{pid}", body), 201)
        recorded_times_strictly_increasing(c, toks, pid, f"correction {i}")
    historical_grid_conservation(c, toks, "after corrections")
    for h, t in toks.items():
        check(get_me(c, t)["available"] >= 0, f"{h} available nonnegative (R122)")


def test_r231_stress_concurrent_same_expected_revision(c):
    toks = sfix(c)
    for round_no in range(5):
        pay = expect_ok(make_payment(c, toks["ada"], "bob", 100 + round_no,
                                     f"r231-p{round_no}"), 201)
        pid = pay["payment_id"]

        def attempt(key, amount):
            return correct(c, toks["ada"], pid, key,
                           correction_body(1, amount, pay["created_at"], "race"))

        r1, r2 = run_concurrently([
            lambda: attempt(f"r231-{round_no}-a", 111),
            lambda: attempt(f"r231-{round_no}-b", 222),
        ])
        eq(sorted([r1.status, r2.status]), [201, 409],
           f"round {round_no}: exactly one concurrent same-revision correction "
           f"succeeds, other stale (R231)")
        ok = r1 if r1.status == 201 else r2
        eq(ok.json()["revision"], 2, "winner appended revision 2 (R231)")
        eq(len(revisions_of(c, toks["ada"], pid)), 2,
           "exactly one revision appended (R231)")


def test_exactly_once_concurrent_identical_corrections(c):
    toks = sfix(c)
    pay = expect_ok(make_payment(c, toks["ada"], "bob", 500, "eo-pay"), 201)
    pid = pay["payment_id"]
    body = correction_body(1, 300, pay["created_at"], "once")
    results = run_concurrently([lambda: correct(c, toks["ada"], pid, "eo-key", body)
                                for _ in range(8)])
    created = [r for r in results if r.status == 201]
    replays = [r for r in results if r.status == 200]
    eq((len(created), len(replays)), (1, 7),
       "exactly one 201, rest 200, concurrent identical corrections (stage-1 R52)")
    eq({r.json()["revision"] for r in created + replays}, {2},
       "every response carries the single new revision (R52)")
    eq(len(revisions_of(c, toks["ada"], pid)), 2, "one revision appended once (R3)")
    eq(get_me(c, toks["ada"])["balance"], 9300 - 500 + 200,
       "money moved exactly once: the payment's own debit, then the 200 refund (R3)")


def test_no_5xx_under_mixed_concurrent_load(c):
    toks = sfix(c)
    q = urllib.parse.quote

    def op(i):
        h = ("ada", "bob", "cy")[i % 3]
        kind = i % 8
        if kind == 0:
            return make_payment(c, toks["ada"], "bob", 10 + i, f"load-p{i}")
        if kind == 1:
            return create_authz(c, toks["bob"], "cy", 50 + i, f"load-a{i}")
        if kind == 2:
            return correct(c, toks["ada"], "p_s1", f"load-c{i}",
                           correction_body(1, 400 + (i % 50), T1, "load"))
        if kind == 3:
            return c.get(f"/statement?known_at={q(T2)}&limit=5", token=toks[h])
        if kind == 4:
            return c.get(f"/me?as_of={q(T2)}&known_at={q(T1)}", token=toks[h])
        if kind == 5:
            return c.get("/activity", token=toks[h])
        if kind == 6:
            return c.post("/settlements", body={"transfers": [
                {"from_handle": "ada", "to_handle": "cy", "amount": 5}]},
                token=toks["op"], headers={"Idempotency-Key": f"load-s{i}"})
        return c.get("/health")

    results = run_concurrently([lambda i=i: op(i) for i in range(50)])
    bad = [getattr(r, "status", 0) for r in results if getattr(r, "status", 0) >= 500]
    eq(bad, [], f"no 5xx under 50-in-flight mixed load (R42/R157): {bad}")
    historical_grid_conservation(c, toks, "after mixed load")
    no_negative_money(c, toks, "after mixed load")


def test_r201_fuzz_corrections_state_stays_consistent(c):
    toks = sfix(c)
    rng = random.Random(31337)
    applied = 0
    for i in range(12):
        amount = rng.choice([-1, 1000000001, 0, 5, 900])
        eff = rng.choice([T0, T2, T3])
        body = {"expected_revision": 1 + applied, "amount": amount,
                "effective_at": eff, "reason": f"fuzz {i}"}
        if amount in (-1, 1000000001):
            expect_error(correct(c, toks["ada"], "p_s1", f"fz-{i}", body),
                         422, "validation_failed", f"amount {amount} rejected (R187)")
        else:
            r = correct(c, toks["ada"], "p_s1", f"fz-{i}", body)
            check(r.status in (201, 409),
                  f"fuzz step {i}: unexpected HTTP {r.status}: {r.raw[:200]!r}")
            applied += r.status == 201
        eq(len(revisions_of(c, toks["ada"], "p_s1")), 1 + applied,
           f"revision count == successes after fuzz step {i} (R201/A33)")
        recorded_times_strictly_increasing(c, toks, "p_s1", f"fuzz step {i}")
        historical_grid_conservation(c, toks, f"fuzz step {i}")
        no_negative_money(c, toks, f"fuzz step {i}")
    after = statement_ok(c, toks["ada"])
    eq(after["closing_balance"] - after["opening_balance"],
       sum(e["delta"] for e in after["entries"]),
       "statement window invariant after fuzz (R175)")