"""Stage-3 settlement history and export/import v3 (R232-R237, A30)."""
import json
import os

from client import (
    check, eq, expect_error, expect_ok, fixture, fpayment, get_me, correct,
    correction_body, revisions_of, revision_keys_ok, statement_ok, me_json,
    fuser, make_payment, create_authz, capture, T1, T2, RFC3339,
)

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE1_EXPORT = os.path.join(HERE, "fixtures", "stage1_upgrade.json")

USERS = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 50000),
         fuser("u_cy", "cy", 1000), fuser("u_op", "op", 10000)]


def ofix(c):
    r = c.reset(fixture(users=USERS, operators=["u_op"]))
    eq(r.status, 204, "reset")
    return {u["handle"]: c.token_for(u["handle"]) for u in USERS}


def settle(c, toks, transfers, key):
    return c.post("/settlements", body={"transfers": transfers}, token=toks["op"],
                  headers={"Idempotency-Key": key})


def test_r232_settlement_receipts_and_privacy_unchanged(c):
    toks = ofix(c)
    stl = expect_ok(settle(c, toks, [
        {"from_handle": "ada", "to_handle": "bob", "amount": 700, "note": "n1"},
        {"from_handle": "bob", "to_handle": "cy", "amount": 200, "visibility": "private"},
    ], "r232-k"), 201)
    check({"settlement_id", "committed_at", "payments"} <= set(stl.keys()),
          f"stage-1 receipt shape (R91/R232): {sorted(stl.keys())}")
    eq([m["settlement_id"] for m in stl["payments"]],
       [stl["settlement_id"]] * 2, "members linked (R91/R232)")
    replay = expect_ok(settle(c, toks, [
        {"from_handle": "ada", "to_handle": "bob", "amount": 700, "note": "n1"},
        {"from_handle": "bob", "to_handle": "cy", "amount": 200, "visibility": "private"},
    ], "r232-k"), 200)
    eq(replay, stl, "replay returns the original receipt (R92/R232)")
    # Corrections still work on ordinary (non-member) payments.
    pay = expect_ok(make_payment(c, toks["ada"], "bob", 100, "r232-pay"), 201)
    expect_ok(correct(c, toks["ada"], pay["payment_id"], "r232-corr",
                      correction_body(1, 120, pay["created_at"], "ok")), 201)


def test_r233_settlement_member_revision_uses_committed_at(c):
    toks = ofix(c)
    stl = expect_ok(settle(c, toks, [
        {"from_handle": "ada", "to_handle": "bob", "amount": 700}], "r233-k"), 201)
    member = stl["payments"][0]
    revs = revisions_of(c, toks["ada"], member["payment_id"])
    eq(len(revs), 1, "one revision (R233)")
    eq(revs[0]["effective_at"], stl["committed_at"],
       "effective_at == committed_at (R233)")
    eq(revs[0]["recorded_at"], stl["committed_at"],
       "recorded_at == committed_at (R233)")
    eq(revs[0]["amount"], 700, "amount as settled (R233)")


def test_r234_settlement_member_correction_422(c):
    toks = ofix(c)
    stl = expect_ok(settle(c, toks, [
        {"from_handle": "ada", "to_handle": "bob", "amount": 700}], "r234-k"), 201)
    member = stl["payments"][0]
    expect_error(correct(c, toks["ada"], member["payment_id"], "r234-corr",
                         correction_body(1, 600, stl["committed_at"], "no")),
                 422, "linked_payment_immutable", "settlement member immutable (R234)")
    eq(len(revisions_of(c, toks["ada"], member["payment_id"])), 1, "no revision appended")


def test_r235_import_v1_export(c):
    toks = ofix(c)
    wrap = json.load(open(STAGE1_EXPORT))
    r = c.import_state(wrap["export"])
    eq(r.status, 204, "stage-1 (format_version:1) export accepted (R235)")
    # Imported tokens keep working (stage-1 R82 across the v3 service).
    ada = wrap["tokens"]["ada"]
    me = expect_ok(c.get("/me", token=ada), 200, "imported token authenticates")
    eq(me["balance"], 96500, "imported balance (R82)")
    # Statements work as if seeded natively (R235): entries carry revision fields.
    st = statement_ok(c, ada)
    check(st["entries"], "imported payments appear in statements (R235)")
    e = st["entries"][0]
    eq(e["revision"], 1, "synthesized revision 1 (A30)")
    eq(e["effective_at"], e["payment"]["created_at"], "effective_at == created_at (A30)")
    # Corrections on an imported payment (R235: usable under stage-3 features).
    lost = wrap["lost_payment"]
    corr = expect_ok(correct(c, ada, lost["payment_id"], "r235-corr",
                             correction_body(1, 2400, T1, "import corrected")), 201)
    eq(corr["amount"], 2400, "correction applies to imported payment (R235)")
    # Original idempotent replay still returns the original response (R82/R203).
    replay = c.post("/payments", body=lost["body"], token=ada,
                    headers={"Idempotency-Key": lost["key"]})
    eq(replay.status, 200, "imported key replays (R82)")
    eq(replay.json()["amount"], 2500, "original amount preserved verbatim (R203)")
    # Historical queries on imported history (R235).
    past = me_json(c, ada, as_of=T1)
    check(isinstance(past["balance"], int), "historical balance computed (R235)")
    # Reset after import clears everything (stage-1 R84).
    eq(c.reset(fixture(users=USERS, operators=["u_op"])).status, 204, "reset clears import")


def test_r236_import_v2_export_with_authorizations(c):
    toks = ofix(c)
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 5000, "r236-authz"), 201)
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "r236-cap",
                            {"amount": 1500, "final": False}), 201)
    pre_me = get_me(c, toks["ada"])
    eq((pre_me["held"], pre_me["available"]), (3500, pre_me["total"] - 3500),
       "nonfinal capture leaves the remainder held (stage-2 R146)")
    exp = expect_ok(c.export(), 200, "export")
    v2 = {"track": exp["track"], "format_version": 2, "state": exp["state"]}
    # format v2 predates revisions (ADR-010/design §10): strip them per payment.
    def strip(obj):
        if isinstance(obj, list):
            return [strip(x) for x in obj]
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in obj.items() if k != "revisions"}
        return obj
    v2["state"] = strip(v2["state"])
    eq(c.import_state(v2).status, 204, "format_version:2 export accepted (R235)")
    post_me = get_me(c, toks["ada"])
    eq(post_me["total"], pre_me["total"], "imported total preserved (R82/R236)")
    eq((post_me["held"], post_me["available"]), (3500, post_me["total"] - 3500),
       "imported open hold still holds (R236)")
    # Captures imported from the export are immutable linked payments (R237).
    expect_error(correct(c, toks["ada"], cap["payment_id"], "r236-corr",
                         correction_body(1, 1400, T1, "no")), 422,
                 "linked_payment_immutable", "imported capture immutable (R237)")
    # Stage-2 rules continue on the imported state: new authz + capture works.
    authz2 = expect_ok(create_authz(c, toks["bob"], "cy", 800, "r236-authz2"), 201)
    expect_ok(capture(c, toks["cy"], authz2["authorization_id"], "r236-cap2", {}), 201)


def test_r237_live_capture_correction_422(c):
    toks = ofix(c)
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 400, "r237-authz"), 201)
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "r237-cap", {}),
                    201)
    expect_error(correct(c, toks["ada"], cap["payment_id"], "r237-corr",
                         correction_body(1, 300, cap["created_at"], "no")),
                 422, "linked_payment_immutable", "capture immutable (R237)")
    eq(len(revisions_of(c, toks["ada"], cap["payment_id"])), 1, "no revision appended")


def test_export_v3_with_revisions(c):
    toks = ofix(c)
    pay = expect_ok(make_payment(c, toks["ada"], "bob", 250, "v3-pay"), 201)
    expect_ok(correct(c, toks["ada"], pay["payment_id"], "v3-corr",
                      correction_body(1, 260, pay["created_at"], "v3")), 201)
    exp = expect_ok(c.export(), 200, "export")
    eq(exp["track"], "pocketful", "track (stage-1 R78)")
    eq(exp["format_version"], 3, "stage-3 exports format_version 3 (ADR-010/design §10)")
    revs = [p for p in exp["state"]["payments"] if p["id"] == pay["payment_id"]][0]["revisions"]
    eq([r["revision"] for r in revs], [1, 2], "payment carries its revision history (design §10)")


def test_export_v3_round_trip(c):
    toks = ofix(c)
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 300, "rt-authz"), 201)
    expect_ok(capture(c, toks["bob"], authz["authorization_id"], "rt-cap",
                      {"amount": 100, "final": False}), 201)
    pay = expect_ok(make_payment(c, toks["ada"], "bob", 250, "rt-pay"), 201)
    expect_ok(correct(c, toks["ada"], pay["payment_id"], "rt-corr",
                      correction_body(1, 260, pay["created_at"], "rt")), 201)
    token = statement_ok(c, toks["ada"])["snapshot"]
    before_me = {h: get_me(c, t) for h, t in toks.items()}
    before_stmt = statement_ok(c, toks["ada"])
    before_revs = revisions_of(c, toks["ada"], pay["payment_id"])
    exp = expect_ok(c.export(), 200, "export")
    eq(c.import_state(exp).status, 204, "re-import own v3 export")
    after_me = {h: get_me(c, t) for h, t in toks.items()}
    after_stmt = statement_ok(c, toks["ada"])
    after_revs = revisions_of(c, toks["ada"], pay["payment_id"])
    for h in toks:
        eq({k: after_me[h][k] for k in ("balance", "total", "available", "held")},
           {k: before_me[h][k] for k in ("balance", "total", "available", "held")},
           f"{h} money fields identical after round trip (R79/T47)")
    eq({k: after_stmt[k] for k in ("opening_balance", "closing_balance", "entries")},
       {k: before_stmt[k] for k in ("opening_balance", "closing_balance", "entries")},
       "statement identical after round trip (R79)")
    eq(after_revs, before_revs, "revision history identical after round trip (A30/R82)")
    # The pre-import snapshot token, however, is gone (fresh epoch, A38).
    expect_error(statement_view(c, toks["ada"], snapshot=token), 404, "not_found",
                 "post-import epoch invalidates the token (A38)")