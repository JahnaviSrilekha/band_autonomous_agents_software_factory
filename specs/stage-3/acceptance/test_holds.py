"""Stage-3 historical holds (R238-R248, A35) and statement money-movements-only
(R249/R250)."""
from client import (
    check, eq, expect_error, expect_ok, afresh, fauthz, get_me, me_json,
    statement_ok, correct, correction_body, create_authz, capture, void_authz,
    list_authz, fuser, make_payment, fpayment, fixture, RFC3339, parse_inst,
    shift, mid, T0, T1, T2, T3, FAR_PAST, FAR_FUTURE,
)

EXPIRES_FUTURE = "2026-10-05T00:00:00+00:00"
EXPIRES_PAST = "2026-09-02T00:00:00+00:00"


def hold_fix(c, extra_authz=None):
    users = [fuser("u_ada", "ada", 400), fuser("u_bob", "bob", 100),
             fuser("u_cy", "cy", 700)]
    payments = [fpayment("p_h1", "u_ada", "u_bob", 100, created_at=T2),
                fpayment("p_h2", "u_bob", "u_cy", 100, created_at=T3)]
    authz = [fauthz("a_1", "u_ada", "u_bob", 400, status="open",
                    created_at=T1, expires_at=EXPIRES_FUTURE)]
    if extra_authz:
        authz.extend(extra_authz)
    r = c.reset(afresh_fixture(users, payments, authz))
    eq(r.status, 204, "reset")
    return {u["handle"]: c.token_for(u["handle"]) for u in users}


def afresh_fixture(users, payments, authz):
    f = fixture(users=users, payments=payments)
    f["authorizations"] = authz
    return f


def test_r238_all_four_money_fields_one_view(c):
    toks = hold_fix(c)
    views = [
        # (as_of, known_at, expected total, expected held)
        (T0, None, 500, 0),      # before hold creation and payment
        (T1, None, 500, 400),    # hold active from its created_at (inclusive)
        (T2, None, 400, 400),    # payment took effect
        ("2026-10-04T00:00:00+00:00", None, 400, 400),  # beyond now, before deadline (R242)
        (T2, T0, 500, 0),        # known_at before both events: nothing known
        (T2, mid(T1, T2), 500, 400),  # hold known, payment not yet recorded
        (T2, FAR_FUTURE, 400, 400),
    ]
    for as_of, known_at, total, held in views:
        m = me_json(c, toks["ada"], as_of=as_of, known_at=known_at)
        eq(m["total"], total, f"historical total at as_of={as_of} known_at={known_at} (R245)")
        eq(m["held"], held, f"historical held at as_of={as_of} known_at={known_at} (R239)")
        eq(m["balance"], m["total"], f"balance == total (R238) at {as_of}/{known_at}")
        eq(m["available"], m["total"] - m["held"], f"available == total - held (R238)")
        check(m["available"] >= 0, "available never negative (R122)")


def test_r239_capture_timeline_nonfinal(c):
    toks = hold_fix(c)
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 400, "h239-a"), 201)
    created = authz["created_at"]
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "h239-cap",
                            {"amount": 150, "final": False}), 201)
    cap_time = cap["created_at"]
    between = mid(created, cap_time)
    eq(me_json(c, toks["ada"], as_of=FAR_PAST)["held"], 0,
       "no hold before authorization creation (R239)")
    eq(me_json(c, toks["ada"], as_of=between)["held"], 400,
       "full hold between creation and capture (R239)")
    eq(me_json(c, toks["ada"], as_of=between, known_at=mid(between, cap_time))["held"], 400,
       "hold fully held when capture not yet known (R241)")
    m = me_json(c, toks["ada"])  # now, everything known
    eq(m["held"], 250, "nonfinal capture reduces the hold at capture time (R239)")
    eq(me_json(c, toks["ada"], as_of=between, known_at=FAR_FUTURE)["held"], 400,
       "historical held at pre-capture instant unaffected by later capture (R239)")


def test_r239_final_capture_and_void_release_at_event_time(c):
    toks = hold_fix(c)
    a1 = expect_ok(create_authz(c, toks["ada"], "bob", 300, "h239-f"), 201)
    expect_ok(capture(c, toks["bob"], a1["authorization_id"], "h239-fcap", {}), 201)
    eq(me_json(c, toks["ada"])["held"], 0, "final capture releases everything (R239)")
    a2 = expect_ok(create_authz(c, toks["ada"], "bob", 300, "h239-v"), 201)
    v = expect_ok(void_authz(c, toks["ada"], a2["authorization_id"]), 200)
    eq(me_json(c, toks["ada"])["held"], 0, "void releases the hold (R239)")
    check(v["closed_at"] is not None and RFC3339.match(v["closed_at"]),
          f"void sets closed_at (R244): {v!r}")


def test_r240_expiry_at_expires_at(c):
    toks = hold_fix(c, extra_authz=[
        fauthz("a_exp", "u_ada", "u_bob", 150, status="open",
               created_at=T1, expires_at=EXPIRES_PAST)])
    eq(me_json(c, toks["ada"])["held"], 400,
       "clock-expired seeded hold holds nothing now (R240/stage-2 R136)")
    eq(me_json(c, toks["ada"], as_of="2026-09-01T15:00:00+00:00")["held"], 550,
       "before its expires_at the hold was active (R240)")
    eq(me_json(c, toks["ada"], as_of="2026-09-02T01:00:00+00:00")["held"], 400,
       "released exactly at expires_at (R240)")
    lst = expect_ok(list_authz(c, toks["ada"], status="expired"), 200).json()
    check(any(a["authorization_id"] == "a_exp" for a in lst["authorizations"]),
          "clock-expired authorization reports status expired (stage-2 R136)")


def test_r241_r242_future_expiry_known_at_creation(c):
    toks = hold_fix(c)  # a_1: created T1 (past), expires 2026-10-05 (future of now)
    eq(me_json(c, toks["ada"], as_of="2026-10-04T00:00:00+00:00")["held"], 400,
       "beyond now but before deadline: still held (R242)")
    eq(me_json(c, toks["ada"], as_of="2026-10-05T01:00:00+00:00")["held"], 0,
       "open hold expires at its deadline for queries beyond now (R242)")
    eq(me_json(c, toks["ada"], as_of="2026-10-05T01:00:00+00:00",
               known_at=mid(T1, "2026-10-01T00:00:00+00:00"))["held"], 0,
       "expiry deadline known as soon as creation is known (R241)")
    eq(me_json(c, toks["ada"], as_of="2026-10-05T01:00:00+00:00",
               known_at=T0)["held"], 0,
       "creation itself unknown at early known_at: hold contributes nothing (R241)")


def test_r243_without_as_of_uses_request_start(c):
    toks = hold_fix(c)
    m1 = get_me(c, toks["ada"])
    m2 = me_json(c, toks["ada"], as_of=me_view_now())
    eq((m2["total"], m2["held"], m2["available"]), (m1["total"], m1["held"], m1["available"]),
       "current view == as_of(request start) (R243)")


def me_view_now():
    from client import rfc3339
    return rfc3339(0)


def test_r244_closed_at(c):
    toks = hold_fix(c)
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 200, "h244-a"), 201)
    check(authz["closed_at"] is None, "closed_at null while open (R244)")
    lst = expect_ok(list_authz(c, toks["ada"]), 200).json()["authorizations"]
    mine = [a for a in lst if a["authorization_id"] == authz["authorization_id"]][0]
    check(mine["closed_at"] is None, "list representation closed_at null (R244)")
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "h244-cap", {}),
                    201)
    mine = [a for a in expect_ok(list_authz(c, toks["ada"]), 200).json()["authorizations"]
            if a["authorization_id"] == authz["authorization_id"]][0]
    eq(mine["status"], "captured", "captured after final capture")
    eq(mine["closed_at"], cap["created_at"],
       "closed_at == capture event time (R244)")
    v = expect_ok(void_authz(c, toks["ada"], "a_1"), 200)
    check(v["closed_at"] is not None and RFC3339.match(v["closed_at"]),
          "void sets closed_at (R244)")
    # Seeded clock-expired hold: closed_at == expires_at (R240/R244).
    toks2 = hold_fix(c, extra_authz=[
        fauthz("a_exp", "u_ada", "u_bob", 150, status="open",
               created_at=T1, expires_at=EXPIRES_PAST)])
    mine2 = [a for a in expect_ok(list_authz(c, toks2["ada"]), 200).json()["authorizations"]
             if a["authorization_id"] == "a_exp"][0]
    eq(mine2["closed_at"], EXPIRES_PAST, "clock expiry closes at expires_at (R244)")
    # Seeded captured/voided holds: closed_at non-null (value may be as-given).
    toks3 = hold_fix(c, extra_authz=[
        fauthz("a_cap", "u_ada", "u_bob", 150, status="captured",
               created_at=T1, expires_at=EXPIRES_FUTURE),
        fauthz("a_void", "u_bob", "u_cy", 50, status="voided",
               created_at=T1, expires_at=EXPIRES_FUTURE)])
    got = {a["authorization_id"]: a for a in
           expect_ok(list_authz(c, toks3["ada"]), 200).json()["authorizations"]}
    check(RFC3339.match(got["a_cap"]["closed_at"] or ""), "seeded captured closed_at set (R244)")
    check(got["a_void"]["closed_at"] is None or RFC3339.match(got["a_void"]["closed_at"]),
          "seeded voided closed_at present or null-as-given (R248: no lifecycle reconstruction)")


def test_r246_historical_overdraft_via_available(c):
    users = [fuser("u_ada", "ada", 500), fuser("u_bob", "bob", 0)]
    payments = [fpayment("p_x", "u_ada", "u_bob", 100, created_at=T2),
                fpayment("p_y", "u_bob", "u_ada", 100, created_at=T3)]
    authz = [fauthz("a_h", "u_ada", "u_bob", 400, status="open",
                    created_at=T1, expires_at=EXPIRES_FUTURE)]
    r = c.reset(afresh_fixture(users, payments, authz))
    eq(r.status, 204, "reset")
    toks = {u["handle"]: c.token_for(u["handle"]) for u in users}
    # Current check passes: ada's available is exactly 100 and the delta is 100.
    # Historical: at T2 ada's total is 300 against a 400 hold -> available -100.
    expect_error(correct(c, toks["ada"], "p_x", "r246-k",
                         correction_body(1, 200, T2, "past")), 409,
                 "historical_overdraft",
                 "available would go negative at a past boundary (R246); total stays >= 0")


def test_r247_insufficient_funds_precedence(c):
    users = [fuser("u_ada", "ada", 500), fuser("u_bob", "bob", 0)]
    payments = [fpayment("p_x", "u_ada", "u_bob", 100, created_at=T2)]
    authz = [fauthz("a_h", "u_ada", "u_bob", 400, status="open",
                    created_at=T1, expires_at=EXPIRES_FUTURE)]
    r = c.reset(afresh_fixture(users, payments, authz))
    eq(r.status, 204, "reset")
    toks = {u["handle"]: c.token_for(u["handle"]) for u in users}
    expect_error(correct(c, toks["ada"], "p_x", "r247-k",
                         correction_body(1, 700, T2, "big")), 409, "insufficient_funds",
                 "current unaffordable debit takes precedence (R247)")


def test_r248_seeded_open_hold_created_at(c):
    toks = hold_fix(c, extra_authz=[
        fauthz("a_def", "u_bob", "u_cy", 50, status="open", expires_at=EXPIRES_FUTURE)])
    # a_def has no created_at: assumed created at the reset instant (R248).
    eq(me_json(c, toks["bob"], as_of=FAR_PAST)["held"], 0,
       "no hold before the assumed creation (R248)")
    eq(me_json(c, toks["bob"])["held"], 50, "held now (R248)")
    # a_1 has supplied created_at T1: active from T1, not before.
    eq(me_json(c, toks["ada"], as_of=shift(T1, -1))["held"], 0,
       "supplied created_at governs the hold's start (R248)")
    eq(me_json(c, toks["ada"], as_of=T1)["held"], 400, "active at created_at (R239/R248)")


def test_a35_seeded_authz_created_at_validation_and_ordering(c):
    users = [fuser("u_ada", "ada", 400), fuser("u_bob", "bob", 100),
             fuser("u_cy", "cy", 700)]
    payments = [fpayment("p_h1", "u_ada", "u_bob", 100, created_at=T2)]
    ok_authz = [fauthz("a_1", "u_ada", "u_bob", 400, status="open",
                       created_at=T1, expires_at=EXPIRES_FUTURE)]
    r = c.reset(afresh_fixture(users, payments, ok_authz))
    eq(r.status, 204, "reset")
    toks = {u["handle"]: c.token_for(u["handle"]) for u in users}
    eq(get_me(c, toks["ada"])["balance"], 400, "state before bad reset")
    bad_authz = [fauthz("a_fut", "u_bob", "u_cy", 10, status="open",
                        created_at=FAR_FUTURE, expires_at="2999-01-02T00:00:00+00:00")]
    expect_error(c.reset(afresh_fixture(users, payments, ok_authz + bad_authz)),
                 422, "validation_failed",
                 "future seeded authorization created_at rejected (A35)")
    eq(get_me(c, toks["ada"])["balance"], 400, "state unchanged (A35)")
    # Supplied created_at drives GET /authorizations ordering (A35/stage-2 R150).
    hold_fix(c, extra_authz=[
        fauthz("a_new", "u_bob", "u_cy", 25, status="open",
               created_at=T2, expires_at=EXPIRES_FUTURE)])
    lst = expect_ok(list_authz(c, toks["bob"]), 200).json()["authorizations"]
    ids = [a["authorization_id"] for a in lst]
    check(ids.index("a_new") < ids.index("a_1"),
          f"newer created_at first (A35/R150): {ids}")


def test_r249_statement_money_movements_only(c):
    toks = hold_fix(c, extra_authz=[
        fauthz("a_exp", "u_ada", "u_bob", 150, status="open",
               created_at=T1, expires_at=EXPIRES_PAST)])
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 300, "h249-a"), 201)
    expect_ok(void_authz(c, toks["ada"], authz["authorization_id"]), 200)
    payment_ids = {p["payment_id"] for p in
                   expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]}
    entry_ids = {e["payment"]["payment_id"] for e in statement_ok(c, toks["ada"])["entries"]}
    check(entry_ids <= payment_ids,
          f"statement contains payments only, no hold events (R249): {entry_ids - payment_ids}")


def test_r250_capture_appears_once_with_link(c):
    toks = hold_fix(c)
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 300, "h250-a"), 201)
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "h250-cap",
                            {"amount": 120, "final": False}), 201)
    for h in ("ada", "bob"):
        entries = [e for e in statement_ok(c, toks[h])["entries"]
                   if e["payment"]["payment_id"] == cap["payment_id"]]
        eq(len(entries), 1, f"capture appears exactly once in {h}'s statement (R250)")
        eq(entries[0]["payment"]["authorization_id"], authz["authorization_id"],
           f"capture carries its authorization link (R250/stage-2 R143)")