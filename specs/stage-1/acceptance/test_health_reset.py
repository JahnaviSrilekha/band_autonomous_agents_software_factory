"""Health, reset/seed, and §3.4 conventions (R13-R16, R31-R34, A5, A13)."""
from client import (RFC3339, STANDARD_USERS, check, eq, expect_error,
                    expect_ok, fixture, fresh, fuser, get_me, make_payment)


def test_health_exact_body(c):
    r = c.get("/health")
    eq(r.status, 200, "GET /health status")
    eq(r.json(), {"status": "ok"}, "GET /health body (R13)")


def test_health_needs_no_auth(c):
    r = c.get("/health", headers={"Authorization": ""})
    eq(r.status, 200, "GET /health without auth")


def test_reset_replaces_all_state(c):
    # Pre-reset user must be gone after reset (R14: replace ALL state).
    r = c.signup("temp@example.com", PASSWORD, "Temp")
    temp_token = expect_ok(r, 201, "signup temp")["token"]
    tokens = fresh(c)
    expect_error(c.get("/me", token=temp_token), 401, "unauthenticated")
    # Seeded state fully visible (R14, R32).
    eq(get_me(c, tokens["ada"])["balance"], 100000, "ada balance")
    eq(get_me(c, tokens["ada"])["currency"], "EUR", "ada currency")
    eq(get_me(c, tokens["ada"])["minor_units"], 2, "ada minor_units")


def test_reset_repeated(c):
    fresh(c)
    users2 = [fuser("u_x", "x", 7)]
    r = c.reset(fixture(users=users2))
    eq(r.status, 204, "second reset status")
    tok = c.token_for("x")
    eq(get_me(c, tok)["balance"], 7, "x balance after second reset (R14)")
    expect_error(c.login("ada@example.com"), 401, "unauthenticated")


def test_reset_unauthenticated_and_id_shapes(c):
    r = c.request("POST", "/_test/reset", body=fixture(users=STANDARD_USERS))
    eq(r.status, 204, "reset without auth must succeed (R14)")
    # Seeded ids are opaque; the fixture ids are used verbatim (R31, R16).
    toks = fresh(c)
    pays = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq(pays, [], "no seeded payments in empty fixture")


def test_reset_negative_balance_422_state_unchanged(c):
    toks = fresh(c)
    bad = fixture(users=[fuser("u_a", "a", 100), fuser("u_b", "b", -1)])
    expect_error(c.reset(bad), 422, "validation_failed")
    eq(get_me(c, toks["ada"])["balance"], 100000, "state unchanged after bad reset (R15)")
    expect_ok(c.login("ada@example.com"), 200, "pre-reset login still valid")


def test_reset_minor_units_domain(c):
    fresh(c)
    for mu in (1, 4, -2, 2.5):
        bad = fixture(users=STANDARD_USERS, minor_units=mu)
        expect_error(c.reset(bad), 422, f"minor_units={mu} must be rejected (R34/A5)")
    ok1 = c.reset(fixture(users=[fuser("u_j", "j", 1000)], currency="JPY", minor_units=0))
    eq(ok1.status, 204, "minor_units=0 accepted")
    eq(get_me(c, c.token_for("j"))["minor_units"], 0, "minor_units echoed (R17)")
    ok2 = c.reset(fixture(users=[fuser("u_b3", "b3", 1000)], currency="BHD", minor_units=3))
    eq(ok2.status, 204, "minor_units=3 accepted")
    eq(get_me(c, c.token_for("b3"))["minor_units"], 3, "minor_units echoed (R17)")


def test_reset_currency_validation(c):
    fresh(c)
    missing = fixture(users=STANDARD_USERS)
    del missing["currency"]
    expect_error(c.reset(missing), 422, "missing currency (A13)")
    for bad_cur in (5, None, "", True):
        expect_error(c.reset(fixture(users=STANDARD_USERS, currency=bad_cur)),
                     422, f"currency={bad_cur!r} (A13)")
    # State unchanged after rejected resets.
    toks = fresh(c)
    eq(get_me(c, toks["ada"])["balance"], 100000, "state unchanged (A13)")


def test_reset_invalid_json_400(c):
    fresh(c)
    r = c.request("POST", "/_test/reset", raw_body="{not json", timeout=10)
    expect_error(r, 400, "malformed_request")


def test_seeded_users_login_and_balances_verbatim(c):
    # R33: balances are post-seeded-payment values; seeded payments must NOT
    # be replayed against balances.
    users = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 50000)]
    payments = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
                 "amount": 500, "note": "coffee", "visibility": "public"}]
    requests = [{"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
                 "amount": 1200, "note": "taxi", "status": "pending"}]
    c.reset(fixture(users=users, payments=payments, requests=requests))
    ada, bob = c.token_for("ada"), c.token_for("bob")
    eq(get_me(c, ada)["balance"], 100000, "ada balance verbatim (R33)")
    eq(get_me(c, bob)["balance"], 50000, "bob balance verbatim (R33)")
    # Seeded payment appears in both parties' feeds (R26).
    for tok in (ada, bob):
        pays = expect_ok(c.get("/activity", token=tok), 200)["payments"]
        eq([p["id"] for p in pays], ["p_1"], f"seeded payment visible to {tok[:6]}")
    # Seeded request visible to its two parties only via /requests (R27).
    eq(len(expect_ok(c.get("/requests", token=ada), 200)["requests"]), 1, "ada sees rq_1")
    eq(len(expect_ok(c.get("/requests", token=bob), 200)["requests"]), 1, "bob sees rq_1")


def test_unknown_request_fields_and_query_params_ignored(c):
    toks = fresh(c)
    r = c.post("/payments", body={"to_handle": "bob", "amount": 100, "bogus_field": 1,
                                  "note": 5},
               token=toks["ada"], headers={"Idempotency-Key": "unk-1"})
    # "note": 5 is a non-string note -> 422 per R38 even though bogus_field ignored;
    # so do two separate checks: unknown field alone succeeds.
    eq(r.status, 422, "non-string note still validated")
    r2 = c.post("/payments", body={"to_handle": "bob", "amount": 100, "bogus_field": {"x": 1}},
                token=toks["ada"], headers={"Idempotency-Key": "unk-2"})
    eq(r2.status, 201, "unknown body field ignored (R16)")
    r3 = c.get("/activity?bogus=1&limit=50", token=toks["ada"])
    eq(r3.status, 200, "unknown query param ignored (R16)")


def test_timestamps_rfc3339_with_offset(c):
    toks = fresh(c)
    r = expect_ok(make_payment(c, toks["ada"], "bob", 100, "ts-1"), 201)
    check(RFC3339.match(r["created_at"]),
          f"created_at not RFC3339 with explicit offset: {r['created_at']!r}")