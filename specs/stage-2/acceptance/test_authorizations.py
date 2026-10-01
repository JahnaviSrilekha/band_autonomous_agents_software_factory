"""Stage-2 API acceptance: fixture/model (R130-R137), GET /me (R124/R138),
POST /authorizations (R139-R141, R129), capture (R142-R147), void (R148-R149),
list (R150-R151). Derived from specs/stage-2/requirements.md only."""
import time
from datetime import datetime

from client import (
    SuiteFailure, check, eq, expect_error, expect_ok, get_me, rfc3339, fauthz,
    fuser, STANDARD_USERS, PAYMENT_KEYS, ME_KEYS, AUTHZ_KEYS,
    afresh, capture, create_authz, list_authz, void_authz,
    get_authz_list, make_payment,
)


def parse_ts(s):
    return datetime.fromisoformat(s)


def authz_created_delta(auth):
    """expires_at - created_at in seconds (R131/R139)."""
    created = datetime.fromisoformat(auth["created_at"])
    expires = datetime.fromisoformat(auth["expires_at"])
    return (expires - created).total_seconds()


# ---- fixture / model: R130-R137, A22 ----

def test_r130_r135_fixture_accepts_authz_fields(c):
    """Reset accepts ttl + authorizations; omission means an empty list (R135)."""
    toks = afresh(c, users=STANDARD_USERS,
                  authorizations=[fauthz_a(6000)])
    me = get_me(c, toks["ada"])
    eq(me["held"], 6000, "seeded open hold counts (R132)")
    r = c.reset({"currency": "EUR", "minor_units": 2,
                 "users": [dict(u) for u in STANDARD_USERS]})
    eq(r.status, 204, "fixture without authorizations key accepted (R135)")
    toks2 = {u["handle"]: c.token_for(u["handle"]) for u in STANDARD_USERS}
    for h, t in toks2.items():
        eq(get_me(c, t)["held"], 0, f"{h} held==0 when authorizations omitted (R135)")


def fauthz_a(amount, **kw):
    from client import fauthz
    return fauthz("a_seed1", "u_ada", "u_bob", amount, **kw)


def test_r131_ttl_default_600_when_omitted(c):
    toks = afresh(c)
    auth = expect_ok(create_authz(c, toks["ada"], "bob", 500, "k-ttl-def"), 201, "create")
    delta = authz_created_delta(auth)
    check(abs(delta - 600) < 1, f"omitted ttl defaults to 600s (R131), got {delta}")


def test_r131_ttl_from_fixture_applies_to_api_created(c):
    toks = afresh(c, ttl=3600)
    auth = expect_ok(create_authz(c, toks["ada"], "bob", 500, "k-ttl-3600"), 201, "create")
    delta = authz_created_delta(auth)
    check(abs(delta - 3600) < 1, f"fixture ttl 3600 applied (R131), got {delta}")


def test_r131_ttl_must_be_positive_integer(c):
    toks = afresh(c)
    for bad in (0, -5, 1.5, "600", True):
        before = get_me(c, toks["ada"])
        r = c.reset({"currency": "EUR", "minor_units": 2,
                     "users": [dict(u) for u in STANDARD_USERS],
                     "authorization_ttl_seconds": bad})
        eq(r.status, 422, f"ttl {bad!r} must be a reset error (R131)")
        expect_error(r, 422, "validation_failed", f"ttl {bad!r}")
        eq(get_me(c, toks["ada"]), before, "failed reset changed nothing")


def test_r132_available_derived_never_seeded(c):
    toks = afresh(c, users=STANDARD_USERS,
                  authorizations=[fauthz_a(6000)])
    me = get_me(c, toks["ada"])
    eq(me["balance"], 100000, "seeded balance is total")
    eq(me["total"], 100000, "balance equals total (R138)")
    eq(me["held"], 6000, "held from seeded open hold")
    eq(me["available"], 94000, "available = total - held, derived (R132)")
    bob = get_me(c, toks["bob"])
    eq((bob["total"], bob["held"], bob["available"]), (50000, 0, 50000),
       "receiver of the hold is unaffected")


def test_r133_seeded_holds_above_balance_rejected(c):
    toks = afresh(c)
    before_ada, before_bob = get_me(c, toks["ada"]), get_me(c, toks["bob"])
    bad = [fauthz("a_x", "u_ada", "u_bob", 110000)]  # > ada's 100000
    r = c.reset({"currency": "EUR", "minor_units": 2,
                 "users": [dict(u) for u in STANDARD_USERS],
                 "authorizations": bad})
    eq(r.status, 422, "holds above balance are a reset error (R133)")
    expect_error(r, 422, "validation_failed", "R133")
    eq(get_me(c, toks["ada"]), before_ada, "failed reset changed nothing")
    eq(get_me(c, toks["bob"]), before_bob, "failed reset changed nothing")


def test_r134_a22_only_open_holds_anything(c):
    auths = [
        fauthz("a_cap", "u_ada", "u_bob", 1000, status="captured"),
        fauthz("a_void", "u_ada", "u_cy", 1000, status="voided"),
        fauthz("a_exp", "u_ada", "u_bob", 1000, status="expired",
               expires_at=rfc3339(-7200)),
    ]
    toks = afresh(c, users=STANDARD_USERS, authorizations=auths)
    me = get_me(c, toks["ada"])
    eq(me["held"], 0, "only open holds anything (R134)")
    eq(me["available"], 100000, "available untouched by non-open seeds")
    items = {a["authorization_id"]: a for a in get_authz_list(c, toks["ada"])}
    eq(items["a_cap"]["status"], "captured", "seeded captured status")
    eq(items["a_void"]["status"], "voided", "seeded voided status")
    eq(items["a_exp"]["status"], "expired", "seeded expired status")
    for a in items.values():
        eq(a["remaining_amount"], 0, "non-open seeded authz holds nothing")
        eq(a["captured_amount"], 0, "seeded captured/voided default captured_amount (A22b)")
        eq(a["payment_ids"], [], "seeded captured/voided default payment_ids (A22b)")


def test_a22_expired_seed_past_expires_accepted(c):
    toks = afresh(c, users=STANDARD_USERS,
                  authorizations=[fauthz("a_e", "u_ada", "u_bob", 4000,
                                         status="expired", expires_at=rfc3339(-7200))])
    eq(get_me(c, toks["ada"])["held"], 0, "seeded expired (past) holds nothing")
    items = get_authz_list(c, toks["ada"])
    eq(items[0]["status"], "expired", "A22a")


def test_a22_contradictory_seeds_rejected(c):
    toks = afresh(c)
    base_users = [dict(u) for u in STANDARD_USERS]
    cases = [
        ("expired with future expires_at",
         [fauthz("a_e", "u_ada", "u_bob", 1000, status="expired",
                 expires_at=rfc3339(7200))]),
        ("from==to", [fauthz("a_s", "u_ada", "u_ada", 1000)]),
        ("unknown from_user_id", [fauthz("a_u", "u_ghost", "u_bob", 1000)]),
        ("unknown to_user_id", [fauthz("a_u2", "u_ada", "u_ghost", 1000)]),
    ]
    for what, auths in cases:
        r = c.reset({"currency": "EUR", "minor_units": 2,
                     "users": base_users, "authorizations": auths})
        eq(r.status, 422, f"{what}: reset error (A22)")
        expect_error(r, 422, "validation_failed", what)
    eq(get_me(c, toks["ada"])["total"], 100000, "failed resets changed nothing")


def test_r130_unknown_fixture_fields_ignored(c):
    auth = fauthz("a_uf", "u_ada", "u_bob", 1000)
    auth["settlement_hint"] = 12345
    toks = afresh(c, users=STANDARD_USERS, authorizations=[auth])
    eq(get_me(c, toks["ada"])["held"], 1000, "unknown seeded fields ignored (stage-1 R16)")


# ---- GET /me: R124, R138 ----

def test_r124_r138_me_shape_and_holds(c):
    toks = afresh(c, users=STANDARD_USERS,
                  authorizations=[fauthz("a_1", "u_ada", "u_bob", 6000)])
    me = get_me(c, toks["ada"])
    eq(set(me.keys()), ME_KEYS, "GET /me exact field set (R138)")
    eq(me["balance"], me["total"], "balance == total always (R124)")
    eq(me["available"], me["total"] - me["held"], "available = total - held")
    eq(me["held"], 6000, "held sums open holds")
    cy = get_me(c, toks["cy"])
    eq((cy["balance"], cy["total"], cy["available"], cy["held"]), (0, 0, 0, 0),
       "no holds: all four agree, held zero (R124)")


# ---- POST /authorizations: R139, R140, R141, R129, A14, A16 ----

def test_r139_create_shape_and_defaults(c):
    toks = afresh(c)
    auth = expect_ok(create_authz(c, toks["ada"], "bob", 2000, "k-c1"), 201, "create")
    eq(set(auth.keys()), AUTHZ_KEYS, "create response exact shape (R139+R146)")
    eq(auth["captured_amount"], 0, "captured_amount starts 0")
    eq(auth["from_handle"], "ada", "caller is the payer (R139)")
    eq(auth["to_handle"], "bob", "")
    eq(auth["amount"], 2000, "")
    eq(auth["captured_amount"], 0, "captured_amount starts 0")
    eq(auth["status"], "open", "status open (R139)")
    eq(auth["payment_id"], None, "payment_id null on create (R139)")
    eq(auth["payment_ids"], [], "payment_ids empty on create")
    eq(auth["remaining_amount"], 2000, "remaining_amount = amount (R146)")
    eq(auth["note"], "", "note defaults empty (same defaults as /payments)")
    eq(auth["visibility"], "public", "visibility defaults public")
    check(auth["expires_at"] > auth["created_at"], "expires_at after created_at")


def test_r139_note_visibility_explicit(c):
    toks = afresh(c)
    auth = expect_ok(create_authz(c, toks["ada"], "bob", 2000, "k-c2",
                                  note="deposit", visibility="private"), 201, "create")
    eq(auth["note"], "deposit", "note verbatim")
    eq(auth["visibility"], "private", "visibility verbatim")


def test_r140_case_table(c):
    toks = afresh(c)  # cy has balance 0 → available 0
    expect_error(create_authz(c, toks["cy"], "bob", 1, "k-f1"), 409,
                 "insufficient_funds", "available below amount")
    expect_error(create_authz(c, toks["ada"], "bob", 0, "k-f2"), 422,
                 "validation_failed", "amount below 1")
    expect_error(create_authz(c, toks["ada"], "bob", 1000000001, "k-f3"), 422,
                 "validation_failed", "amount above 1e9")
    expect_error(create_authz(c, toks["ada"], "bob", 15.5, "k-f4"), 422,
                 "validation_failed", "non-integer amount")
    expect_error(create_authz(c, toks["ada"], "bob", "15", "k-f5"), 422,
                 "validation_failed", "string amount")
    expect_error(create_authz(c, toks["ada"], "bob", True, "k-f6"), 422,
                 "validation_failed", "boolean amount")
    expect_error(create_authz(c, toks["ada"], "ada", 100, "k-f7"), 422,
                 "self_payment", "own handle")
    expect_error(create_authz(c, toks["ada"], "bob", 100, "k-f8", note="x" * 201), 422,
                 "validation_failed", "note over 200 chars")
    expect_error(create_authz(c, toks["ada"], "bob", 100, "k-f9", visibility="friends"), 422,
                 "validation_failed", "bad visibility")
    expect_error(create_authz(c, toks["ada"], "ghost", 100, "k-f10"), 404,
                 "not_found", "unknown handle")
    r = c.post("/authorizations", body={"amount": 100}, token=toks["ada"],
               headers={"Idempotency-Key": "k-f11"})
    expect_error(r, 422, "validation_failed", "missing to_handle")
    r = c.post("/authorizations", body={"to_handle": "bob"}, token=toks["ada"],
               headers={"Idempotency-Key": "k-f12"})
    expect_error(r, 422, "validation_failed", "missing amount")
    r = c.post("/authorizations", body={"to_handle": 5, "amount": 100}, token=toks["ada"],
               headers={"Idempotency-Key": "k-f13"})
    expect_error(r, 400, "malformed_request", "to_handle wrong JSON type")
    expect_ok(make_payment(c, toks["ada"], "bob", 1, "k-f14"), 201,
              "amount 1 is valid (boundary)")
    expect_error(create_authz(c, toks["ada"], "bob", 1000000000, "k-f16"), 409,
                 "insufficient_funds", "1e9 refused on funds, not shape (A14 order)")
    # 1e9 is a shape-valid amount: needs a wallet that can actually afford it,
    # otherwise the funds check (A14: after shape/existence) correctly refuses.
    # (A second reset here invalidates the first fixture's tokens, so re-login.)
    rich = afresh(c, users=STANDARD_USERS + [fuser("u_rich", "rich", 1000000000)])
    expect_ok(create_authz(c, rich["rich"], "bob", 1000000000, "k-f15"), 201,
              "amount 1e9 boundary valid for a wallet that can afford it")


def test_a14_precedence_shape_before_existence_before_self_before_funds(c):
    toks = afresh(c)
    expect_error(create_authz(c, toks["cy"], "ghost", 15.5, "k-p1"), 422,
                 "validation_failed", "field shape before 404")
    # cy's available is 0: a funds-refused amount, but self_payment (A14:
    # existence/self before funds) wins
    expect_error(create_authz(c, toks["cy"], "cy", 500000, "k-p2"), 422,
                 "self_payment", "existence/self before funds (A14)")


def test_a16_non_object_body_400(c):
    toks = afresh(c)
    r = c.request("POST", "/authorizations", raw_body="[1,2]", token=toks["ada"],
                  headers={"Idempotency-Key": "k-n1"})
    expect_error(r, 400, "malformed_request", "A16 non-object body")
    r = c.request("POST", "/authorizations", raw_body='"x"', token=toks["ada"],
                  headers={"Idempotency-Key": "k-n2"})
    expect_error(r, 400, "malformed_request", "A16 non-object body")


def test_r129_create_replay_rules(c):
    toks = afresh(c)
    body = {"to_handle": "bob", "amount": 500}
    a1 = expect_ok(create_authz(c, toks["ada"], "bob", 500, "k-r1"), 201, "first use")
    r = c.post("/authorizations", body=body, token=toks["ada"],
               headers={"Idempotency-Key": "k-r1"})
    a2 = expect_ok(r, 200, "replay")
    eq(a2, a1, "replay body identical (R51)")
    expect_error(c.post("/authorizations", body={"to_handle": "bob", "amount": 501},
                        token=toks["ada"], headers={"Idempotency-Key": "k-r1"}),
                 409, "idempotency_key_reuse", "same key different body")
    r = c.post("/authorizations", body={"to_handle": "bob", "amount": 500},
               token=toks["ada"])
    expect_error(r, 400, "missing_idempotency_key", "key required (R129)")
    # a 4xx attempt frees the key (R51)
    expect_error(create_authz(c, toks["ada"], "ada", 500, "k-r3"), 422,
                 "self_payment", "failed first use")
    expect_ok(create_authz(c, toks["ada"], "bob", 500, "k-r3"), 201,
              "key reusable after 4xx")
    # per-user scoping (R49) and per-path independence (R50/R129)
    expect_ok(create_authz(c, toks["bob"], "cy", 100, "k-r1"), 201,
              "same key another user (R49)")
    expect_ok(make_payment(c, toks["ada"], "bob", 100, "k-r1"), 201,
              "same key another write path (R50/R129)")


def test_r120_r121_hold_reserves_without_moving(c):
    toks = afresh(c)
    before = {h: get_me(c, t)["total"] for h, t in toks.items()}
    auth = expect_ok(create_authz(c, toks["ada"], "bob", 2000, "k-h1"), 201, "create")
    aid = auth["authorization_id"]
    after = {h: get_me(c, t)["total"] for h, t in toks.items()}
    eq(after, before, "a hold moves no money (R121)")
    ada, bob = get_me(c, toks["ada"]), get_me(c, toks["bob"])
    eq(ada["held"], 2000, "payer held")
    eq(ada["available"], before["ada"] - 2000, "payer available reduced")
    eq(bob["held"], 0, "receiver holds nothing")
    items = get_authz_list(c, toks["ada"])
    eq([a["authorization_id"] for a in items], [aid], "one open authz listed")


def test_r141_authorization_never_in_activity(c):
    toks = afresh(c)
    base = expect_ok(c.get("/activity", token=toks["ada"]), 200, "activity").get("payments", [])
    expect_ok(create_authz(c, toks["ada"], "bob", 2000, "k-a1"), 201, "create")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200, "activity").get("payments", [])
    eq(feed, base, "open authorisation is not a feed item (R141)")


# ---- capture: R142-R147, A14, A24 ----

def _open(c, toks, amount, key, note="deposit", visibility="private"):
    return expect_ok(create_authz(c, toks["ada"], "bob", amount, key,
                                  note=note, visibility=visibility), 201, "create")


def test_r142_r143_r144_default_final_capture(c):
    toks = afresh(c)
    auth = _open(c, toks, 2000, "k-o1")
    aid = auth["authorization_id"]
    payer_total = get_me(c, toks["ada"])["total"]
    pay = expect_ok(capture(c, toks["bob"], aid, "k-c1", {"amount": 1500}), 201, "capture")
    eq(set(pay.keys()), PAYMENT_KEYS, "capture returns exact POST /payments shape (R143)")
    eq(pay["authorization_id"], aid, "authorization_id set (R143)")
    eq(pay["request_id"], None, "request_id null (R143)")
    eq(pay["settlement_id"], None, "settlement_id null")
    eq(pay["amount"], 1500, "payment amount is captured amount")
    eq(pay["note"], "deposit", "note copied from authorisation (R143)")
    eq(pay["visibility"], "private", "visibility copied (R143)")
    eq(pay["to_handle"], "bob", "money moves payer→receiver")
    cur = expect_ok(c.get(f"/authorizations", token=toks["bob"]), 200, "list")
    item = next(a for a in cur["authorizations"] if a["authorization_id"] == aid)
    eq(item["status"], "captured", "closed by default final capture (R144)")
    eq(item["captured_amount"], 1500, "captured_amount")
    eq(item["payment_id"], pay["payment_id"], "payment_id is latest capture")
    eq(item["payment_ids"], [pay["payment_id"]], "payment_ids in order")
    eq(item["remaining_amount"], 0, "remainder released (R144)")
    ada, bob = get_me(c, toks["ada"]), get_me(c, toks["bob"])
    eq(ada["total"], payer_total - 1500, "capture moves money (R120)")
    eq(ada["held"], 0, "hold fully released")
    eq(ada["available"], payer_total - 1500,
       "available = total after capture: hold fully released (R144)")
    eq(bob["total"], 50000 + 1500, "receiver credited")


def test_r144_capture_without_amount_defaults_to_remaining(c):
    toks = afresh(c)
    aid = _open(c, toks, 800, "k-o2")["authorization_id"]
    pay = expect_ok(capture(c, toks["bob"], aid, "k-c2", {}), 201, "capture {}")
    eq(pay["amount"], 800, "omitted amount defaults to remaining (R142)")
    item = get_authz_list(c, toks["bob"])[0]
    eq(item["status"], "captured", "closed")
    eq(item["captured_amount"], 800, "")


def test_r145_second_capture_after_final_409(c):
    toks = afresh(c)
    aid = _open(c, toks, 2000, "k-o3")["authorization_id"]
    expect_ok(capture(c, toks["bob"], aid, "k-c3", {"amount": 500}), 201, "first")
    expect_error(capture(c, toks["bob"], aid, "k-c4", {"amount": 500}), 409,
                 "authorization_not_open", "second capture after final (R145)")


def test_r146_extended_multi_capture(c):
    toks = afresh(c)
    aid = _open(c, toks, 2000, "k-o4", note="d", visibility="public")["authorization_id"]
    p1 = expect_ok(capture(c, toks["bob"], aid, "k-c5", {"amount": 700, "final": False}),
                   201, "capture 1")
    item = get_authz_list(c, toks["bob"])[0]
    eq(item["status"], "open", "final:false keeps open (R146)")
    eq(item["captured_amount"], 700, "cumulative")
    eq(item["remaining_amount"], 1300, "remainder still held")
    eq(get_me(c, toks["ada"])["held"], 1300, "payer held tracks remaining")
    p2 = expect_ok(capture(c, toks["bob"], aid, "k-c6", {"amount": 600, "final": False}),
                   201, "capture 2")
    item = get_authz_list(c, toks["bob"])[0]
    eq(item["captured_amount"], 1300, "cumulative (R146)")
    eq(item["payment_id"], p2["payment_id"], "payment_id is latest capture")
    eq(item["payment_ids"], [p1["payment_id"], p2["payment_id"]], "payment_ids in order")
    p3 = expect_ok(capture(c, toks["bob"], aid, "k-c7", {}), 201, "final capture defaults remaining")
    eq(p3["amount"], 700, "omitted amount = remaining (R146)")
    item = get_authz_list(c, toks["bob"])[0]
    eq(item["status"], "captured", "default final closes")
    eq(item["captured_amount"], 2000, "captured_amount sum")
    eq(item["payment_ids"], [p1["payment_id"], p2["payment_id"], p3["payment_id"]], "")
    eq(item["remaining_amount"], 0, "zero when closed (R146)")
    eq(get_me(c, toks["ada"])["held"], 0, "all released")
    eq(get_me(c, toks["bob"])["total"], 50000 + 2000, "receiver got everything")


def test_r146_capture_exceeds_compares_remaining(c):
    toks = afresh(c)
    aid = _open(c, toks, 2000, "k-o5")["authorization_id"]
    expect_ok(capture(c, toks["bob"], aid, "k-c8", {"amount": 700, "final": False}),
              201, "partial")
    expect_error(capture(c, toks["bob"], aid, "k-c9", {"amount": 1301}), 422,
                 "capture_exceeds_authorization", "vs remaining, not original (R146)")
    expect_ok(capture(c, toks["bob"], aid, "k-c10", {"amount": 1300}), 201,
              "up to remaining is fine")


def test_r146_exact_remainder_final_false_closes(c):
    toks = afresh(c)
    aid = _open(c, toks, 1000, "k-o6")["authorization_id"]
    expect_ok(capture(c, toks["bob"], aid, "k-c11", {"amount": 400, "final": False}),
              201, "partial 1")
    expect_ok(capture(c, toks["bob"], aid, "k-c12", {"amount": 600, "final": False}),
              201, "partial 2 = remainder")
    item = get_authz_list(c, toks["bob"])[0]
    eq(item["status"], "captured", "capturing entire remainder closes even final:false (R146)")
    eq(item["remaining_amount"], 0, "")


def test_r146_void_after_partial_releases_remainder_preserves_records(c):
    toks = afresh(c)
    auth = _open(c, toks, 2000, "k-o7")
    aid = auth["authorization_id"]
    expect_ok(capture(c, toks["bob"], aid, "k-c13", {"amount": 700, "final": False}),
              201, "partial")
    v = expect_ok(void_authz(c, toks["ada"], aid), 200, "void")
    eq(v["status"], "voided", "voided")
    eq(v["captured_amount"], 700, "capture records preserved (R146)")
    eq(v["payment_ids"], [v["payment_id"]], "payment_ids preserved")
    eq(v["remaining_amount"], 0, "only remainder released")
    eq(get_me(c, toks["ada"])["held"], 0, "remainder released")
    eq(get_me(c, toks["ada"])["total"], 100000 - 700, "captured part stays moved")
    eq(get_me(c, toks["bob"])["total"], 50000 + 700, "receiver keeps captured part")


def test_r142_capture_body_equality(c):
    toks = afresh(c)
    aid = _open(c, toks, 2000, "k-o8")["authorization_id"]
    first = expect_ok(capture(c, toks["bob"], aid, "k-c14", {"amount": 500}), 201, "first")
    again = expect_ok(capture(c, toks["bob"], aid, "k-c14", {"amount": 500}), 200, "replay")
    eq(again, first, "identical capture replay returns original (R51/R53)")
    expect_error(capture(c, toks["bob"], aid, "k-c15", {}), 409,
                 "authorization_not_open", "new key on closed authz")
    aid2 = _open(c, toks, 2000, "k-o9")["authorization_id"]
    expect_ok(capture(c, toks["bob"], aid2, "k-c16", {}), 201, "capture {} first use")
    expect_error(capture(c, toks["bob"], aid2, "k-c16", {"amount": 2000}), 409,
                 "idempotency_key_reuse", "{} vs {'amount':N} differ (R142)")


def test_a24_final_wrong_type_400(c):
    toks = afresh(c)
    aid = _open(c, toks, 2000, "k-o10")["authorization_id"]
    for bad in ("yes", 1, None, [True]):
        r = c.post(f"/authorizations/{aid}/capture",
                   body={"amount": 100, "final": bad},
                   token=toks["bob"], headers={"Idempotency-Key": f"k-c17{repr(bad)}"})
        expect_error(r, 400, "malformed_request", f"final={bad!r} wrong type (A24)")


def test_r147_case_table(c):
    toks = afresh(c)
    expect_error(capture(c, toks["bob"], "a_nope", "k-c18", {"amount": 100}), 404,
                 "not_found", "unknown authorisation")
    aid = _open(c, toks, 2000, "k-o11")["authorization_id"]
    expect_error(capture(c, toks["ada"], aid, "k-c19", {"amount": 100}), 403,
                 "forbidden", "payer is not the receiver (R142)")
    expect_error(capture(c, toks["cy"], aid, "k-c20", {"amount": 100}), 403,
                 "forbidden", "third party 403 (R149)")
    expect_error(capture(c, toks["cy"], "a_nope", "k-c21", {"amount": 100}), 404,
                 "not_found", "existence before permission (A14)")
    expect_error(capture(c, toks["bob"], aid, "k-c22", {"amount": 0}), 422,
                 "validation_failed", "amount below 1")
    expect_error(capture(c, toks["bob"], aid, "k-c23", {"amount": 15.5}), 422,
                 "validation_failed", "non-integer amount")
    expect_error(capture(c, toks["bob"], aid, "k-c24", {"amount": True}), 422,
                 "validation_failed", "boolean amount")
    expect_error(capture(c, toks["bob"], aid, "k-c25", {"amount": 2001}), 422,
                 "capture_exceeds_authorization", "above authorised amount")
    expect_error(capture(c, toks["bob"], aid, "k-c26", {"amount": "100"}), 422,
                 "validation_failed", "string amount")
    r = c.request("POST", f"/authorizations/{aid}/capture", raw_body="[1]",
                  token=toks["bob"], headers={"Idempotency-Key": "k-c27"})
    expect_error(r, 400, "malformed_request", "A16 non-object capture body")


def test_r147_a14_permission_before_state(c):
    toks = afresh(c)
    aid = _open(c, toks, 2000, "k-o12")["authorization_id"]
    expect_ok(capture(c, toks["bob"], aid, "k-c28", {"amount": 2000}), 201, "close it")
    expect_error(capture(c, toks["ada"], aid, "k-c29", {"amount": 100}), 403,
                 "forbidden", "payer 403 even though authz closed (A14 order)")


def test_r136_r147_capture_on_expired_409_expired(c):
    toks = afresh(c, ttl=1)
    aid = _open(c, toks, 2000, "k-o13")["authorization_id"]
    time.sleep(2.3)  # TTL 1s; lazy expiry needs no sweep (R136)
    expect_error(capture(c, toks["bob"], aid, "k-c30", {"amount": 100}), 409,
                 "authorization_expired", "expires_at <= now (R147)")
    expect_error(void_authz(c, toks["ada"], aid), 409,
                 "authorization_not_open", "expired void is not_open, not expired (R148)")


def test_r148_r149_void(c):
    toks = afresh(c)
    aid = _open(c, toks, 2000, "k-o14", visibility="public")["authorization_id"]
    payer_total = get_me(c, toks["ada"])["total"]
    v = expect_ok(void_authz(c, toks["ada"], aid), 200, "payer voids")
    eq(v["status"], "voided", "status voided (R148)")
    eq(v["remaining_amount"], 0, "hold released")
    eq(set(v.keys()), AUTHZ_KEYS, "void returns the authorisation")
    eq(get_me(c, toks["ada"])["held"], 0, "held released")
    eq(get_me(c, toks["ada"])["total"], payer_total, "void moved no money (R121)")
    v2 = expect_ok(void_authz(c, toks["ada"], aid), 200, "repeat void")
    eq(v2["status"], "voided", "voiding voided is 200 (R148)")
    expect_error(void_authz(c, toks["bob"], aid), 403, "forbidden",
                 "receiver voiding: permission (403) precedes state per A14")
    aid2 = _open(c, toks, 500, "k-o15")["authorization_id"]
    expect_ok(capture(c, toks["bob"], aid2, "k-c31", {"amount": 500}), 201, "close")
    expect_error(void_authz(c, toks["ada"], aid2), 409,
                 "authorization_not_open", "captured is 409 (R148)")


def test_r149_a15_void_permissions_and_ignored_key(c):
    toks = afresh(c)
    aid = _open(c, toks, 2000, "k-o16")["authorization_id"]
    expect_error(void_authz(c, toks["bob"], aid), 403, "forbidden", "receiver cannot void")
    expect_error(void_authz(c, toks["cy"], aid), 403, "forbidden", "neither party 403")
    expect_error(void_authz(c, toks["cy"], "a_nope"), 404, "not_found",
                 "existence before permission (A14)")
    expect_ok(void_authz(c, toks["ada"], aid, headers={"Idempotency-Key": "k-void-key"}),
              200, "void with client key succeeds")
    expect_ok(create_authz(c, toks["ada"], "bob", 100, "k-void-key"), 201,
              "key on void ignored, never consumed (A15)")


def test_r143_authorization_id_null_on_other_paths(c):
    toks = afresh(c, operator=True)
    pay = expect_ok(make_payment(c, toks["ada"], "bob", 100, "k-p20"), 201, "payment")
    eq(pay["authorization_id"], None, "plain payment (R143)")
    rq = expect_ok(c.post("/requests", body={"payer_handle": "ada", "amount": 50},
                          token=toks["bob"], headers={"Idempotency-Key": "k-rq1"}),
                   201, "request")
    pay2 = expect_ok(c.post(f"/requests/{rq['request_id']}/pay", body={},
                            token=toks["ada"], headers={"Idempotency-Key": "k-p21"}),
                     201, "request pay")
    eq(pay2["authorization_id"], None, "request-pay payment (R143)")
    st = expect_ok(c.post("/settlements", body={"transfers": [
        {"from_handle": "ada", "to_handle": "cy", "amount": 25}]},
        token=toks["op"], headers={"Idempotency-Key": "k-s1"}), 201, "settlement")
    for m in st["payments"]:
        eq(m["authorization_id"], None, "settlement member (R143)")


# ---- list: R150, R151, A21 ----

def test_r150_list_envelope_filters_paging(c):
    toks = afresh(c, users=STANDARD_USERS, authorizations=[
        fauthz("a_l1", "u_ada", "u_bob", 100),
        fauthz("a_l2", "u_bob", "u_ada", 200),
        fauthz("a_l3", "u_ada", "u_cy", 300),
    ])
    auth1 = expect_ok(create_authz(c, toks["ada"], "bob", 100, "k-L1"), 201, "")
    time.sleep(1.1)
    auth2 = expect_ok(create_authz(c, toks["ada"], "bob", 100, "k-L2"), 201, "")
    time.sleep(1.1)
    auth3 = expect_ok(create_authz(c, toks["bob"], "ada", 100, "k-L3"), 201, "")
    items = get_authz_list(c, toks["ada"])
    eq([a["authorization_id"] for a in items[:3]],
       [auth3["authorization_id"], auth2["authorization_id"], auth1["authorization_id"]],
       "newest first by created_at (R150): API-created head")
    eq({a["authorization_id"] for a in items},
       {auth1["authorization_id"], auth2["authorization_id"], auth3["authorization_id"],
        "a_l1", "a_l2", "a_l3"},
       "seeded authorizations involving the caller are included (R149)")
    out = get_authz_list(c, toks["ada"], direction="outgoing")
    check(all(a["from_handle"] == "ada" for a in out), "outgoing = caller is payer")
    eq({a["authorization_id"] for a in out},
       {auth1["authorization_id"], auth2["authorization_id"], "a_l1", "a_l3"}, "")
    inc = get_authz_list(c, toks["ada"], direction="incoming")
    check(all(a["to_handle"] == "ada" for a in inc), "incoming = caller is receiver")
    eq({a["authorization_id"] for a in inc},
       {auth3["authorization_id"], "a_l2"}, "")
    for bad in ("sideways", "OUT"):
        expect_error(list_authz(c, toks["ada"], direction=bad), 422, "validation_failed",
                     "bad direction (R70 semantics)")
    for bad in ("semi", "OPEN"):
        expect_error(list_authz(c, toks["ada"], status=bad), 422, "validation_failed",
                     "bad status")
    expect_error(list_authz(c, toks["ada"], limit=0), 422, "validation_failed", "limit<1")
    expect_error(list_authz(c, toks["ada"], limit=201), 422, "validation_failed", "limit>200")
    expect_error(list_authz(c, toks["ada"], offset=-1), 422, "validation_failed", "offset<0")
    r = c.get("/authorizations?limit=1.0", token=toks["ada"])
    expect_error(r, 422, "validation_failed", "non-digit limit (stage-1 R39)")
    page = expect_ok(list_authz(c, toks["ada"], limit=2, offset=0), 200, "page 1")
    eq(len(page["authorizations"]), 2, "limit respected")
    eq(page["has_more"], True, "has_more when more exist")
    page2 = expect_ok(list_authz(c, toks["ada"], limit=2, offset=4), 200, "last page")
    eq(page2["has_more"], False, "has_more false at end")


def test_r150_r151_status_filters_and_lazy_expiry(c):
    toks = afresh(c, users=STANDARD_USERS, authorizations=[
        fauthz("a_s1", "u_ada", "u_bob", 100),
        fauthz("a_s2", "u_ada", "u_bob", 200, status="voided"),
        fauthz("a_s3", "u_ada", "u_cy", 300, expires_at=rfc3339(-7200)),
        fauthz("a_s4", "u_bob", "u_ada", 400, status="captured"),
    ])
    open_ids = [a["authorization_id"] for a in get_authz_list(c, toks["ada"], status="open")]
    eq(open_ids, ["a_s1"], "only unexpired open matches status=open (R151)")
    expired_ids = {a["authorization_id"]
                   for a in get_authz_list(c, toks["ada"], status="expired")}
    check("a_s3" in expired_ids, "clock-expired matches expired (R151)")
    all_ids = {a["authorization_id"] for a in get_authz_list(c, toks["ada"])}
    eq(all_ids, {"a_s1", "a_s2", "a_s3", "a_s4"},
       "only authorizations involving the caller, payer or receiver (R149)")
    bob_ids = {a["authorization_id"] for a in get_authz_list(c, toks["bob"])}
    eq(bob_ids, {"a_s1", "a_s2", "a_s4"}, "caller as receiver sees their side")


def test_r151_expiry_lazy_reads(c):
    toks = afresh(c, ttl=1)
    auth = expect_ok(create_authz(c, toks["ada"], "bob", 2000, "k-x1"), 201, "create")
    aid = auth["authorization_id"]
    eq(get_me(c, toks["ada"])["held"], 2000, "held before expiry")
    time.sleep(2.3)
    me = get_me(c, toks["ada"])
    eq(me["held"], 0, "GET /me reflects expiry lazily (R136)")
    eq(me["available"], me["total"], "released remainder in available (R136)")
    items = {a["authorization_id"]: a for a in get_authz_list(c, toks["ada"])}
    eq(items[aid]["status"], "expired", "GET /authorizations shows expired (R136)")
    eq(items[aid]["remaining_amount"], 0, "no longer held")


def test_r157_r146_expiry_preserves_partial_capture_records(c):
    toks = afresh(c, ttl=1)
    aid = _open(c, toks, 2000, "k-o17")["authorization_id"]
    p = expect_ok(capture(c, toks["bob"], aid, "k-c32", {"amount": 700, "final": False}),
                  201, "partial")
    time.sleep(2.3)
    item = get_authz_list(c, toks["bob"])[0]
    eq(item["status"], "expired", "expired after partial capture")
    eq(item["captured_amount"], 700, "capture records preserved (R146)")
    eq(item["payment_ids"], [p["payment_id"]], "")
    eq(item["remaining_amount"], 0, "remainder released by expiry")
    me = get_me(c, toks["ada"])
    eq(me["held"], 0, "")
    eq(me["total"], 100000 - 700, "only captured money moved")