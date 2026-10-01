"""Stage-3 GET /me temporal queries: as_of, known_at (R163-R168, R207-R214,
R220, R202, A34, A36)."""
from client import (
    check, eq, expect_error, expect_ok, fixture, fpayment, get_me, inst, make_payment,
    me_json, me_view, mid, parse_inst, correct, revision_keys_ok, revisions_of,
    shift, statement_ok, statement_view, T0, T1, T2, T3, T4, FAR_FUTURE, FAR_PAST,
    fuser,
)

USERS = [fuser("u_ada", "ada", 9300), fuser("u_bob", "bob", 10100),
         fuser("u_cy", "cy", 600)]
PAYMENTS = [
    fpayment("p_s1", "u_ada", "u_bob", 500, created_at=T1),
    fpayment("p_s2", "u_bob", "u_cy", 300, created_at=T2, note="rent",
             visibility="private"),
    fpayment("p_s3", "u_ada", "u_cy", 200, created_at=T2),
    fpayment("p_s4", "u_bob", "u_cy", 100, created_at=T3),
]
# Openings: ada 10000, bob 10000, cy 0. Seeded total 20000.
OPENING = {"ada": 10000, "bob": 10000, "cy": 0}
SEEDED_TOTAL = 20000


def sfix(c):
    r = c.reset(fixture(users=USERS, payments=PAYMENTS))
    eq(r.status, 204, "reset")
    return {u["handle"]: c.token_for(u["handle"]) for u in USERS}


def test_r163_as_of_validation(c):
    toks = sfix(c)
    eq(me_json(c, toks["ada"], as_of=T2)["balance"], 9300, "valid as_of accepted (R163)")
    for bad in ("2026-09-01T10:00:00", "2026-09-01", ""):
        expect_error(me_view(c, toks["ada"], as_of=bad), 422, "validation_failed",
                     f"as_of={bad!r} rejected (R163)")


def test_r164_plain_me_reports_current_corrected_values(c):
    toks = sfix(c)
    eq(get_me(c, toks["ada"])["balance"], 9300, "current before correction")
    expect_ok(correct(c, toks["ada"], "p_s1", "r164-k",
                      {"expected_revision": 1, "amount": 700,
                       "effective_at": T1, "reason": "fix"}), 201)
    eq(get_me(c, toks["ada"])["balance"], 9100,
       "plain /me reflects the latest revision (R164)")
    eq(get_me(c, toks["bob"])["balance"], 10300, "receiver side corrected (R164)")


def test_r165_as_of_inclusive_uncorrected(c):
    toks = sfix(c)
    eq(me_json(c, toks["ada"], as_of=T1)["balance"], 9500,
       "payment at exactly as_of counts (R165)")
    eq(me_json(c, toks["ada"], as_of=shift(T1, -1))["balance"], 10000,
       "instant before the payment excludes it (R165)")


def test_r165_as_of_same_instant_tie(c):
    toks = sfix(c)
    eq(me_json(c, toks["cy"], as_of=T2)["balance"], 600,
       "both same-instant payments included at as_of (R165)")
    eq(me_json(c, toks["cy"], as_of=shift(T2, -1))["balance"], 0, "before them: opening")


def test_r166_as_of_after_latest_returns_current(c):
    toks = sfix(c)
    eq(me_json(c, toks["ada"], as_of=T3)["balance"], 9300, "as_of == latest payment")
    eq(me_json(c, toks["ada"], as_of=FAR_FUTURE)["balance"], 9300, "as_of beyond latest")
    eq(me_json(c, toks["ada"], as_of=T3)["balance"], get_me(c, toks["ada"])["balance"],
       "equals plain balance (R166)")


def test_r167_as_of_before_earliest_returns_opening(c):
    toks = sfix(c)
    for h, opening in OPENING.items():
        eq(me_json(c, toks[h], as_of=FAR_PAST)["balance"], opening,
           f"{h} opening balance (R167/R180)")


def test_r168_as_of_echoed_exactly(c):
    toks = sfix(c)
    given = "2026-09-01T15:30:00+02:00"
    eq(me_json(c, toks["ada"], as_of=given)["as_of"], given,
       "as_of echoed exactly as given (R168)")


def test_r207_known_at_accepted_on_me_and_statement(c):
    toks = sfix(c)
    check(me_json(c, toks["ada"], known_at=T3), "GET /me?known_at accepted (R207)")
    check(statement_ok(c, toks["ada"], known_at=T3), "GET /statement?known_at accepted (R207)")


def test_r209_omission_means_everything_known(c):
    toks = sfix(c)
    a = get_me(c, toks["ada"])
    b = me_json(c, toks["ada"], known_at=FAR_FUTURE)
    for f in ("balance", "total", "available", "held"):
        eq(a[f], b[f], f"plain /me == known_at-infinity for {f} (R209)")


def test_r212_future_instants_accepted(c):
    toks = sfix(c)
    eq(me_json(c, toks["ada"], as_of=FAR_FUTURE, known_at=FAR_FUTURE)["balance"], 9300,
       "future as_of/known_at accepted (R212)")
    st = statement_ok(c, toks["ada"], **{"from": T1, "to": FAR_FUTURE})
    eq(len(st["entries"]), 2, "future `to` accepted (R212)")


def test_r213_known_at_invalid_422(c):
    toks = sfix(c)
    for bad in ("", "2026-09-01T10:00:00", "2026-09-01"):
        expect_error(me_view(c, toks["ada"], known_at=bad), 422, "validation_failed",
                     f"known_at={bad!r} rejected on /me (R213)")
        expect_error(statement_view(c, toks["ada"], known_at=bad), 422,
                     "validation_failed", f"known_at={bad!r} rejected on /statement (R213)")


def test_r214_known_at_echoed_exactly(c):
    toks = sfix(c)
    given = "2026-09-01T15:30:00+02:00"
    eq(me_json(c, toks["ada"], known_at=given)["known_at"], given,
       "known_at echoed on /me (R214)")
    eq(statement_ok(c, toks["ada"], known_at=given)["known_at"], given,
       "known_at echoed on /statement (R214)")


def test_a34_corrected_inclusion_governed_by_effective_at(c):
    toks = sfix(c)
    # Back-dated correction: effective_at BEFORE the payment's created_at.
    expect_ok(correct(c, toks["ada"], "p_s1", "a34-k1",
                      {"expected_revision": 1, "amount": 700,
                       "effective_at": T0, "reason": "backdated"}), 201)
    eq(me_json(c, toks["ada"], as_of=T0)["balance"], 9300,
       "as_of between effective_at and created_at INCLUDES the corrected payment (A34)")
    eq(me_json(c, toks["ada"], as_of=shift(T0, -1))["balance"], 10000,
       "before the effective_at: opening (A34)")
    eq(me_json(c, toks["ada"], as_of=T2)["balance"], 9300,
       "as_of at latest selected effective_at == current (R166 via A34)")
    # Forward-dated correction: effective_at AFTER the payment's created_at.
    expect_ok(correct(c, toks["bob"], "p_s2", "a34-k2",
                      {"expected_revision": 1, "amount": 100,
                       "effective_at": T4, "reason": "deferred"}), 201)
    eq(me_json(c, toks["bob"], as_of=T2)["balance"], 10700,
       "as_of between created_at and the new effective_at excludes the selected revision (A34)")
    eq(me_json(c, toks["bob"], as_of=T4)["balance"], 10500,
       "as_of at the new effective_at includes it (A34)")
    eq(get_me(c, toks["bob"])["balance"], 10100, "current reflects selected revision")


def test_r202_historical_conservation_grid(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r202-k",
                      {"expected_revision": 1, "amount": 800,
                       "effective_at": T0, "reason": "grid"}), 201)
    for as_of in (FAR_PAST, T0, T1, T2, T3, FAR_FUTURE):
        for known_at in (FAR_PAST, T0, T1, T2, T3, None):
            total = sum(me_json(c, toks[h], as_of=as_of, known_at=known_at)["total"]
                        for h in ("ada", "bob", "cy"))
            eq(total, SEEDED_TOTAL,
               f"conservation at as_of={as_of} known_at={known_at} (R202)")


def test_a36_me_cross_route_params_ignored(c):
    toks = sfix(c)
    plain = get_me(c, toks["ada"])
    junk = me_json(c, toks["ada"], raw_query="from=" + T1 + "&to=" + T2 + "&snapshot=abc")
    for f in ("balance", "total", "available", "held"):
        eq(junk[f], plain[f], f"from/to/snapshot ignored on /me (A36/R228): {f}")


def test_r220_me_uncorrected_matches_created_at_rule(c):
    toks = sfix(c)
    eq(me_json(c, toks["ada"], as_of=T1)["balance"], 9500,
       "uncorrected: created_at rule == effective_at rule (R220/A34)")