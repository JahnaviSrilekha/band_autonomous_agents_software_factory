"""Stage-3 stable statement pagination: snapshots (R221-R230, R251, A36, A38)."""
from client import (
    check, eq, expect_error, expect_ok, fixture, fpayment, get_me, statement_ok,
    statement_view, correct, correction_body, create_authz, capture, void_authz,
    run_concurrently, fuser, T1, T2, T3,
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


def sfix(c):
    r = c.reset(fixture(users=USERS, payments=PAYMENTS))
    eq(r.status, 204, "reset")
    return {u["handle"]: c.token_for(u["handle"]) for u in USERS}


def body_key(body):
    """The frozen content of a statement response (everything but a fresh
    snapshot token, whose value is per-call, and has_more, which legitimately
    differs across page sizes)."""
    return {k: body[k] for k in ("opening_balance", "closing_balance")}, \
        [e for e in body["entries"]]


def test_r221_snapshot_on_first_read(c):
    toks = sfix(c)
    for params in ({}, {"from": T1, "to": T3}, {"known_at": T2}, {"limit": 1}):
        body = statement_ok(c, toks["ada"], **params)
        check(isinstance(body.get("snapshot"), str) and body["snapshot"],
              f"first read returns opaque snapshot token (R221): params={params}")


def test_r222_r223_snapshot_freezes_result(c):
    toks = sfix(c)
    frozen = statement_ok(c, toks["ada"], **{"from": T1})
    token = frozen["snapshot"]
    # A later payment lands after the frozen default `to` (R222) ...
    expect_ok(c.post("/payments", body={"to_handle": "bob", "amount": 999},
                     token=toks["ada"], headers={"Idempotency-Key": "snap-pay"}), 201)
    # ... and a later correction moves p_s1's effective_at inside the window.
    expect_ok(correct(c, toks["ada"], "p_s1", "snap-corr",
                      correction_body(1, 700, T2, "moved")), 201)
    paged = statement_ok(c, toks["ada"], snapshot=token, limit=1, offset=0)
    ek, ee = body_key(frozen)
    pk, pe = body_key(paged)
    eq(pk, ek, "frozen balances survive later payments/corrections (R222/R223)")
    eq(pe[0], frozen["entries"][0], "first frozen entry byte-identical (R223)")
    eq(pe, frozen["entries"][:1], "snapshot pages the exact frozen result (R223)")
    # The live view DID change — proving the mutations happened while the
    # snapshot stayed frozen (R229/R230).
    live = statement_ok(c, toks["ada"], **{"from": T1})
    live_ek, live_ee = body_key(live)
    check(live_ee != frozen["entries"] or live_ek != ek,
          "live window differs from frozen snapshot after corrections (R229/R230)")


def test_r224_snapshot_param_combinations(c):
    toks = sfix(c)
    token = statement_ok(c, toks["ada"])["snapshot"]
    for q, what in (("from=" + T1, "from"), ("to=" + T3, "to"),
                    ("known_at=" + T2, "known_at")):
        expect_error(statement_view(c, toks["ada"], snapshot=token,
                                    extra_q=q + "&limit=5"), 422, "validation_failed",
                     f"snapshot + {what} rejected (R224)")
    ok = statement_ok(c, toks["ada"], snapshot=token, limit=1, offset=0)
    check(ok, "snapshot + limit/offset accepted (R224)")


def test_r225_unknown_other_user_and_stale_tokens(c):
    toks = sfix(c)
    ada_token = statement_ok(c, toks["ada"])["snapshot"]
    expect_error(statement_view(c, toks["ada"], snapshot="no-such-token"), 404,
                 "not_found", "unknown token (R225)")
    expect_error(statement_view(c, toks["bob"], snapshot=ada_token), 404, "not_found",
                 "another user's token (R225)")
    pre_reset_token = ada_token
    eq(c.reset(fixture(users=USERS, payments=PAYMENTS)).status, 204, "reset")
    # Reset invalidates bearer tokens too — re-login so the assertion below
    # exercises the snapshot-token 404 path (R225), not authentication.
    toks["ada"] = c.token_for("ada")
    expect_error(statement_view(c, toks["ada"], snapshot=pre_reset_token), 404,
                 "not_found", "token from before reset (R225)")


def test_r226_token_valid_until_reset(c):
    toks = sfix(c)
    token = statement_ok(c, toks["ada"])["snapshot"]
    statement_ok(c, toks["ada"], snapshot=token, limit=1)
    expect_ok(c.post("/payments", body={"to_handle": "bob", "amount": 1},
                     token=toks["ada"], headers={"Idempotency-Key": "r226-p"}), 201)
    check(statement_ok(c, toks["ada"], snapshot=token, limit=1),
          "token still valid after unrelated writes (R226)")
    eq(c.reset(fixture(users=USERS, payments=PAYMENTS)).status, 204, "reset")
    # Reset invalidates bearer tokens too — re-login so the assertion below
    # exercises the snapshot-token 404 path (R226), not authentication.
    toks["ada"] = c.token_for("ada")
    expect_error(statement_view(c, toks["ada"], snapshot=token), 404, "not_found",
                 "token invalid after reset (R226)")


def test_r227_paging_no_mutation_has_more(c):
    toks = sfix(c)
    token = statement_ok(c, toks["ada"])["snapshot"]
    before = {h: get_me(c, t)["balance"] for h, t in toks.items()}
    # ada has 2 frozen entries: page size 1 leaves one behind -> has_more True
    # on every non-final page (R227), regardless of the original read's shape.
    first = statement_ok(c, toks["ada"], snapshot=token, limit=1, offset=0)
    eq(first["has_more"], True, "snapshot first page has_more true (R227)")
    mid = statement_ok(c, toks["ada"], snapshot=token, limit=1, offset=1)
    eq(mid["has_more"], False, "snapshot final partial page has_more false (R227)")
    beyond = statement_ok(c, toks["ada"], snapshot=token, limit=1, offset=99)
    eq(beyond["entries"], [], "offset beyond end: empty entries (R227)")
    eq(beyond["has_more"], False, "offset beyond end: has_more false (R227)")
    after = {h: get_me(c, t)["balance"] for h, t in toks.items()}
    eq(after, before, "paging mutated no balances (R227)")


def test_r228_r230_snapshot_stable_under_concurrent_writes(c):
    toks = sfix(c)
    frozen = statement_ok(c, toks["ada"], **{"from": T1})
    token = frozen["snapshot"]
    ek, ee = body_key(frozen)

    def burst(i):
        if i % 3 == 0:
            return c.post("/payments", body={"to_handle": "bob", "amount": 10 + i},
                          token=toks["ada"], headers={"Idempotency-Key": f"r230-p{i}"})
        if i % 3 == 1:
            return statement_ok(c, toks["bob"], limit=5)
        return correct(c, toks["bob"], "p_s2", f"r230-c{i}",
                       correction_body(1, 290 + i, T2, "concurrent"))

    results = run_concurrently([lambda i=i: burst(i) for i in range(9)])
    check(all(getattr(r, "status", 200) < 500 for r in results),
          "no 5xx under concurrent payments/statements/corrections (R157/R42)")
    paged = statement_ok(c, toks["ada"], snapshot=token, limit=50)
    pk, pe = body_key(paged)
    eq(pk, ek, "snapshot balances unchanged during concurrent writes (R230)")
    eq(pe, frozen["entries"], "snapshot entries unchanged during concurrent writes (R230)")


def test_r251_snapshot_stable_under_lifecycle_actions(c):
    toks = sfix(c)
    frozen = statement_ok(c, toks["ada"], **{"from": T1})
    token = frozen["snapshot"]
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 400, "r251-authz"), 201)
    aid = authz["authorization_id"]
    cap = expect_ok(capture(c, toks["bob"], aid, "r251-cap", {"amount": 150,
                                                              "final": False}), 201)
    expect_ok(void_authz(c, toks["ada"], aid), 200, "void releases the remainder")
    paged = statement_ok(c, toks["ada"], snapshot=token, limit=50)
    ek, ee = body_key(frozen)
    pk, pe = body_key(paged)
    eq(pk, ek, "snapshot balances unchanged after capture/void (R251)")
    eq(pe, frozen["entries"], "snapshot entries unchanged after capture/void (R251)")
    live = statement_ok(c, toks["ada"], **{"from": T1})
    cap_ids = [e["payment"]["payment_id"] for e in live["entries"]
               if e["payment"]["authorization_id"] == aid]
    eq(cap_ids, [cap["payment_id"]], "live statement shows the capture exactly once (R250)")


def test_a38_import_invalidates_snapshots(c):
    toks = sfix(c)
    token = statement_ok(c, toks["ada"])["snapshot"]
    exp = expect_ok(c.export(), 200, "export")
    eq(c.import_state(exp).status, 204, "import own export")
    expect_error(statement_view(c, toks["ada"], snapshot=token), 404, "not_found",
                 "snapshot token invalid after import (A38)")