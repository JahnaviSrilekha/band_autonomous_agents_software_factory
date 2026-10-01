"""Stage-3 payment timestamps (R158-R162)."""
from client import (
    check, eq, expect_error, expect_ok, fauthz, fixture, fresh, fpayment,
    get_me, make_payment, parse_inst, rfc3339, afresh, afixture, fuser,
    RFC3339, T1, T2, T3, FAR_FUTURE, shift,
)


def seed_fixture(extra_payment_kwargs=None):
    users = [fuser("u_ada", "ada", 9300), fuser("u_bob", "bob", 10100),
             fuser("u_cy", "cy", 600)]
    kw = extra_payment_kwargs or {}
    payments = [
        fpayment("p_s1", "u_ada", "u_bob", 500, created_at=kw.get("p1", T1)),
        fpayment("p_s2", "u_bob", "u_cy", 300, created_at=kw.get("p2", T2),
                 note="rent", visibility="private"),
        fpayment("p_s3", "u_ada", "u_cy", 200, created_at=kw.get("p3", T2)),
    ]
    return users, payments


def test_r158_created_at_on_every_payment_representation(c):
    toks = fresh(c, operator=True)
    pay = expect_ok(make_payment(c, toks["ada"], "bob", 700, "r158-pay"), 201)
    check(RFC3339.match(pay["created_at"]) and ("+" in pay["created_at"][10:] or pay["created_at"].endswith("Z")),
          f"POST /payments created_at RFC 3339 with offset: {pay['created_at']!r}")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    check(all(RFC3339.match(p["created_at"]) for p in feed), "activity created_at RFC 3339 (R158)")
    pay2 = expect_ok(make_payment(c, toks["bob"], "cy", 100, "r158-pay2"), 201)
    pay3 = expect_ok(c.post("/requests", body={"payer_handle": "ada", "amount": 150},
                            token=toks["bob"], headers={"Idempotency-Key": "r158-rq"}), 201)
    paid = expect_ok(c.post(f"/requests/{pay3['request_id']}/pay", body={},
                            token=toks["ada"], headers={"Idempotency-Key": "r158-pay3"}), 201)
    check(RFC3339.match(paid["created_at"]), "request-pay payment created_at (R158)")
    split = expect_ok(c.post("/splits", body={"amount": 999, "participant_handles": ["ada", "bob", "cy"]},
                             token=toks["cy"], headers={"Idempotency-Key": "r158-sp"}), 201)
    rq_id = split["requests"][0]["request_id"]
    expect_ok(c.post(f"/requests/{rq_id}/pay", body={}, token=toks["ada"],
                     headers={"Idempotency-Key": "r158-pay4"}), 201)
    stl = expect_ok(c.post("/settlements", body={"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 50}]},
        token=toks["op"], headers={"Idempotency-Key": "r158-stl"}), 201)
    for m in stl["payments"]:
        check(RFC3339.match(m["created_at"]), f"settlement member created_at (R158): {m!r}")
    authz = expect_ok(create_authz_r158(c, toks["ada"], "cy", 400), 201)
    cap = expect_ok(capture_r158(c, toks["cy"], authz["authorization_id"], "r158-cap", 150), 201)
    check(RFC3339.match(cap["created_at"]), f"capture payment created_at (R158): {cap!r}")
    st = expect_ok(c.get("/statement", token=toks["ada"]), 200)
    for e in st["entries"]:
        check(RFC3339.match(e["payment"]["created_at"]),
              f"statement entry payment created_at (R158): {e!r}")


def create_authz_r158(c, token, to_handle, amount):
    return c.post("/authorizations", body={"to_handle": to_handle, "amount": amount},
                  token=token, headers={"Idempotency-Key": "r158-authz"})


def capture_r158(c, token, aid, key, amount):
    return c.post(f"/authorizations/{aid}/capture", body={"amount": amount},
                  token=token, headers={"Idempotency-Key": key})


def test_r159_activity_ordering_unchanged_by_correction(c):
    users, payments = seed_fixture({"p3": T3})
    r = c.reset(fixture(users=users, payments=payments))
    eq(r.status, 204, "reset")
    toks = {u["handle"]: c.token_for(u["handle"]) for u in users}
    api_pay = expect_ok(make_payment(c, toks["ada"], "bob", 700, "r159-api"), 201)
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq([p["payment_id"] for p in feed], [api_pay["payment_id"], "p_s3", "p_s1"],
       "activity newest first by created_at (R75/R159)")
    expect_ok(correct_r159(c, toks["ada"], "p_s1", "r159-corr",
                           {"expected_revision": 1, "amount": 450,
                            "effective_at": T1, "reason": "fix"}), 201)
    feed2 = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq([p["payment_id"] for p in feed2], [p["payment_id"] for p in feed],
       "correction adds no feed entry (R204/R159)")
    eq([p["amount"] for p in feed2], [p["amount"] for p in feed],
       "feed shows original amounts, order unchanged (R159/R203)")


def correct_r159(c, token, pid, key, body):
    return c.post(f"/payments/{pid}/corrections", body=body, token=token,
                  headers={"Idempotency-Key": key})


def test_r160_seeded_created_at_and_reset_default(c):
    users, payments = seed_fixture({"p1": T1, "p2": None, "p3": T3})
    r = c.reset(fixture(users=users, payments=payments))
    eq(r.status, 204, "reset with mixed seeded created_at")
    toks = {u["handle"]: c.token_for(u["handle"]) for u in users}
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    by_id = {p["payment_id"]: p for p in feed}
    eq(by_id["p_s1"]["created_at"], T1, "supplied seeded created_at verbatim (R160/R179)")
    omitted = by_id["p_s3"]["created_at"]
    check(RFC3339.match(omitted), "omitted seeded created_at is RFC 3339")
    check(abs((parse_inst(omitted) - parse_inst(rfc3339(0))).total_seconds()) < 300,
          "omitted seeded created_at == reset time (R160)")
    api_pay = expect_ok(make_payment(c, toks["ada"], "bob", 700, "r160-api"), 201)
    check(parse_inst(omitted) < parse_inst(api_pay["created_at"]),
          "reset-default seeded time before subsequent API-created payments (R160)")


def test_r161_future_seeded_created_at_422_no_state_change(c):
    users, payments = seed_fixture()
    toks = fresh(c, users=users)
    eq(get_me(c, toks["ada"])["balance"], 9300, "state before bad reset")
    bad = fixture(users=users, payments=seed_fixture({"p1": FAR_FUTURE})[1])
    expect_error(c.reset(bad), 422, "validation_failed",
                 "future seeded created_at rejected (R161)")
    eq(get_me(c, toks["ada"])["balance"], 9300, "state unchanged after rejected reset (R161)")
    expect_ok(c.login("ada@example.com"), 200, "pre-reset accounts intact")


def test_r162_fixture_balance_unchanged_by_loading_seeded_payments(c):
    users, payments = seed_fixture()
    toks = fresh(c, users=users)
    # ada's seeded payments net -700; loading them must not debit again (R162).
    eq(get_me(c, toks["ada"])["balance"], 9300, "ending balance == fixture balance (R162)")
    eq(get_me(c, toks["bob"])["balance"], 10100, "bob ending balance verbatim (R162)")
    eq(get_me(c, toks["cy"])["balance"], 600, "cy ending balance verbatim (R162)")