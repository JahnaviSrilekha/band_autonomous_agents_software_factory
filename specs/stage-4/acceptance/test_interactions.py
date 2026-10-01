"""Stage-4 route census (R252), settlement/refund interactions (R287),
concurrency serialization (R288), export/import compatibility (R289, R290)."""
import os

from client import (
    check, eq, expect_error, expect_ok, fresh, get_me, make_payment, correct,
    correction_body, fpayment, refund, refund_body, settle, transfer,
    create_request, pay_request, split, create_authz, capture, correction_batch,
    batch_item, revisions_of, run_concurrently, load_export, T1, T2,
)

V1_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fixtures", "stage1_upgrade.json")


def test_r252_ten_idempotent_write_paths(c):
    """Exactly ten (method, path) routes require Idempotency-Key and replay
    with 200 (R252)."""
    toks = fresh(c, operator=True)
    # The ten routes, each exercised first-use then replay.
    pay = expect_ok(make_payment(c, toks["ada"], "bob", 100, "k1"), 201)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 50, "k2"), 201)
    rpay = expect_ok(pay_request(c, toks["ada"], rq["request_id"], "k3"), 201)
    sp = expect_ok(split(c, toks["ada"], 30, ["bob", "cy"], "k4"), 201)
    st = expect_ok(settle(c, toks["op"], [transfer("ada", "bob", 10)], "k5"), 201)
    az = expect_ok(create_authz(c, toks["ada"], "bob", 40, "k6"), 201)
    cap = expect_ok(capture(c, toks["bob"], az["authorization_id"], "k7",
                            {"amount": 20, "final": True}), 201)
    corr = expect_ok(correct(c, toks["ada"], pay["payment_id"], "k8",
                             correction_body(1, 110, pay["created_at"], "r")), 201)
    ref = expect_ok(refund(c, toks["bob"], pay["payment_id"], "k9",
                           refund_body(10)), 201)
    bat = expect_ok(correction_batch(c, toks["op"], "k10",
                                     [batch_item(pay["payment_id"], 2, 120,
                                                 pay["created_at"])]), 201)
    # Replays all return 200.
    eq(make_payment(c, toks["ada"], "bob", 100, "k1").status, 200, "/payments replay")
    eq(create_request(c, toks["bob"], "ada", 50, "k2").status, 200, "/requests replay")
    eq(pay_request(c, toks["ada"], rq["request_id"], "k3").status, 200,
       "/requests/{id}/pay replay")
    eq(split(c, toks["ada"], 30, ["bob", "cy"], "k4").status, 200, "/splits replay")
    eq(settle(c, toks["op"], [transfer("ada", "bob", 10)], "k5").status, 200,
       "/settlements replay")
    eq(create_authz(c, toks["ada"], "bob", 40, "k6").status, 200,
       "/authorizations replay")
    eq(capture(c, toks["bob"], az["authorization_id"], "k7",
               {"amount": 20, "final": True}).status, 200, "capture replay")
    eq(correct(c, toks["ada"], pay["payment_id"], "k8",
               correction_body(1, 110, pay["created_at"], "r")).status, 200,
       "corrections replay")
    eq(refund(c, toks["bob"], pay["payment_id"], "k9", refund_body(10)).status,
       200, "refunds replay")
    eq(correction_batch(c, toks["op"], "k10",
                        [batch_item(pay["payment_id"], 2, 120,
                                    pay["created_at"])]).status, 200,
       "correction-batches replay")
    # Each of the ten rejects a missing key with 400 missing_idempotency_key
    # (after auth/operator gates).
    expect_error(c.post("/payments", body={"to_handle": "bob", "amount": 1},
                        token=toks["ada"]), 400, "missing_idempotency_key",
                 "route 1 /payments")
    expect_error(c.post("/requests", body={"payer_handle": "ada", "amount": 1},
                        token=toks["bob"]), 400, "missing_idempotency_key",
                 "route 2 /requests")
    expect_error(c.post(f"/requests/{rq['request_id']}/pay", body={},
                        token=toks["ada"]), 400, "missing_idempotency_key",
                 "route 3 pay")
    expect_error(c.post("/splits", body={"amount": 9,
                                         "participant_handles": ["bob"]},
                        token=toks["ada"]), 400, "missing_idempotency_key",
                 "route 4 /splits")
    expect_error(c.post("/settlements", body={"transfers": []},
                        token=toks["op"]), 400, "missing_idempotency_key",
                 "route 5 /settlements")
    expect_error(c.post("/authorizations", body={"to_handle": "bob",
                                                 "amount": 5},
                        token=toks["ada"]), 400, "missing_idempotency_key",
                 "route 6 /authorizations")
    expect_error(c.post(f"/authorizations/{az['authorization_id']}/capture",
                        body={}, token=toks["bob"]), 400,
                 "missing_idempotency_key", "route 7 capture")
    expect_error(c.post(f"/payments/{pay['payment_id']}/corrections",
                        body=correction_body(2, 130, pay["created_at"], "r"),
                        token=toks["ada"]), 400, "missing_idempotency_key",
                 "route 8 corrections")
    expect_error(c.post(f"/payments/{pay['payment_id']}/refunds",
                        body={"amount": 5}, token=toks["bob"]), 400,
                 "missing_idempotency_key", "route 9 refunds")
    expect_error(c.post("/correction-batches",
                        body={"corrections": [batch_item("p1", 1, 5,
                                                         pay["created_at"])]},
                        token=toks["op"]), 400, "missing_idempotency_key",
                 "route 10 correction-batches")


def test_r287_settlement_member_refund_membership_unchanged(c):
    from client import fuser
    users = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 50000),
             fuser("u_cy", "cy", 1000), fuser("u_op", "op", 10000)]
    seeded = [
        fpayment("q1", "u_ada", "u_bob", 300, created_at=T1),
        fpayment("q2", "u_bob", "u_cy", 200, created_at=T2),
    ]
    toks = fresh(c, operator=True, users=users, operators=["u_op"],
                 payments=seeded)
    st = expect_ok(settle(c, toks["op"], [transfer("ada", "bob", 300),
                                          transfer("bob", "cy", 200)], "st-1"), 201)
    sid = st["settlement_id"]
    m1 = st["payments"][0]["payment_id"]  # the ada->bob 300 member
    exp_before = expect_ok(c.export(), 200, "export before refund")
    settle_before = exp_before["state"].get("settlements", [])
    # Refund the settlement member m1 under the ordinary rules (bob receives).
    ref = expect_ok(refund(c, toks["bob"], m1, "rf-s1", refund_body(100)), 201)
    eq(ref["refund_of"], m1, "settlement member refunded (R287)")
    eq(ref["request_id"], None, "refund payment stands alone")
    exp_after = expect_ok(c.export(), 200, "export after refund")
    settle_after = exp_after["state"].get("settlements", [])
    eq(settle_after, settle_before, "settlement records untouched by the refund (R287)")
    mem = [p for p in exp_after["state"]["payments"] if p["id"] == m1][0]
    eq(mem.get("settlement_id"), sid, "member keeps its settlement_id (R287)")
    # The refund payment is NOT a member.
    refp = [p for p in exp_after["state"]["payments"]
            if p["id"] == ref["payment_id"]][0]
    eq(refp.get("settlement_id"), None, "refund is not a settlement member")
    eq(refp.get("refund_of"), m1, "refund_of points at the member")
    # Settlement receipt (replay) unchanged.
    st_replay = settle(c, toks["op"], [transfer("ada", "bob", 300),
                                       transfer("bob", "cy", 200)], "st-1")
    eq(st_replay.status, 200, "settlement replay 200")
    eq(st_replay.json(), st, "settlement retry body unchanged (R287/R284)")


def test_r288_concurrent_corrections_same_revision(c):
    toks, _ = seeded_state(c)
    pid = "p1"
    responses = run_concurrently([
        lambda i=i: correct(c, toks["ada"], pid, f"c-race-{i}",
                            correction_body(1, 100 + i, T1, f"race-{i}"))
        for i in range(4)
    ])
    statuses = [r.status for r in responses]
    eq(sorted(s <= 299 for s in statuses), [False, False, False, True],
       f"exactly one of 4 same-revision corrections commits (R288): {statuses}")
    for r in responses:
        if r.status >= 400:
            expect_ok_shape_409(r)
    eq([rev["revision"] for rev in revisions_of(c, toks["ada"], pid)], [1, 2],
       "exactly one new revision (R288)")
    # Mixed: single correction races a batch naming the same payment/revision.
    toks2, _ = seeded_state(c)
    responses2 = run_concurrently([
        lambda: correct(c, toks2["ada"], "p1", "c-mix-1",
                        correction_body(1, 111, T1, "solo")),
        lambda: correction_batch(c, toks2["op"], "b-mix",
                                 [batch_item("p1", 1, 222, T1),
                                  batch_item("p2", 1, 333, T1)]),
    ])
    winners = [r for r in responses2 if r.status <= 299]
    eq(len(winners), 1, f"exactly one of single/batch commits (R288)")
    loser = next(r for r in responses2 if r.status >= 400)
    eq(loser.status, 409, "loser gets 409")
    eq(loser.json()["error"]["code"], "stale_revision", "loser code stale_revision")
    # Exactly the winner's effects are present — the loser's are fully absent
    # (all-or-nothing for a rejected batch, R279/R288).
    batch_won = winners[0].json().get("correction_batch_id") is not None
    p1_revs = [rev["revision"] for rev in revisions_of(c, toks2["ada"], "p1")]
    p2_revs = [rev["revision"] for rev in revisions_of(c, toks2["ada"], "p2")]
    if batch_won:
        eq(p1_revs, [1, 2], "batch applied its p1 revision once")
        eq(p2_revs, [1, 2], "batch applied its p2 revision once")
    else:
        eq(p1_revs, [1, 2], "single correction applied once")
        eq(p2_revs, [1], "rejected batch applied nothing to its other item (R279/R288)")


def expect_ok_shape_409(r):
    eq(r.status, 409, "correction losers get 409")
    eq(r.json()["error"]["code"], "stale_revision", "loser code (R288)")


def seeded_state(c):
    seeded = [
        fpayment("p1", "u_ada", "u_bob", 1000, created_at=T1),
        fpayment("p2", "u_ada", "u_bob", 500, created_at=T1),
    ]
    toks = fresh(c, operator=True, payments=seeded)
    return toks, ["p1", "p2"]


def test_r288_refund_vs_batch_race_serialized(c):
    """Refund and batch-correction race one payment: the shared lock
    serializes validate-then-commit (amended R288), so both effects, if both
    allowed, apply exactly once — never a half-applied state."""
    toks, _ = seeded_state(c)
    ada_before = get_me(c, toks["ada"])["balance"]
    bob_before = get_me(c, toks["bob"])["balance"]
    responses = run_concurrently([
        lambda: refund(c, toks["bob"], "p2", "rf-race", refund_body(100)),
        lambda: correction_batch(c, toks["op"], "b-race",
                                 [batch_item("p2", 1, 100, T1),
                                  batch_item("p1", 1, 1100, T1)]),
    ])
    for r in responses:
        check(r.status <= 299,
              f"both race participants may succeed (compatible orders): "
              f"{[r.status for r in responses]} {r.raw[:200]!r}")
    # Batch deltas on ada: p2 500->100 (+400), p1 1000->1100 (-100) = +300.
    # Refund of p2 by its receiver bob credits ada +100, debits bob -100.
    eq(get_me(c, toks["ada"])["balance"], ada_before + 300 + 100,
       "both effects applied exactly once")
    eq(get_me(c, toks["bob"])["balance"], bob_before - 300 - 100,
       "bob debited once (batch -300, refund -100)")
    eq([rev["revision"] for rev in revisions_of(c, toks["ada"], "p2")], [1, 2],
       "exactly one new p2 revision")
    eq([rev["revision"] for rev in revisions_of(c, toks["ada"], "p1")], [1, 2],
       "exactly one new p1 revision")
    exp = expect_ok(c.export(), 200, "export")
    check(refund_sum_ok(exp), "no over-refund after the race (R262/R288)")


def refund_sum_ok(exp):
    payments = {p["id"]: p for p in exp["state"]["payments"]}
    for p in payments.values():
        revs = p.get("revisions") or []
        current = revs[-1]["amount"] if revs else p["amount"]
        refunded = sum(q["amount"] for q in payments.values()
                       if q.get("refund_of") == p["id"])
        if refunded > current:
            return False
    return True


def test_r289_import_earlier_stage_exports(c):
    toks = fresh(c, operator=True)
    # (a) Stage-1 export (fixture file) imports cleanly; imported payments
    # default refund_of to null and revisions to correction_batch_id null,
    # and refunds/batches operate on the imported state.
    v1 = load_export(V1_FIXTURE)["export"]
    eq(c.import_state(v1).status, 204, "stage-1 (v1) export accepted (R289)")
    exp = expect_ok(c.export(), 200, "export after v1 import")
    check(exp["state"]["payments"], "v1 import seeded payments")
    for p in exp["state"]["payments"]:
        eq(p.get("refund_of"), None, f"{p['id']} refund_of defaults null (R289)")
        for rev in p.get("revisions") or []:
            eq(rev.get("correction_batch_id"), None,
               "imported revisions have no batch id (R289)")
    target = next(p for p in exp["state"]["payments"]
                  if p.get("settlement_id") is None)
    users_by_id = {u["id"]: u["handle"] for u in exp["state"]["users"]}
    receiver = users_by_id[target["to_user_id"]]
    tok_receiver = login_asis(c, receiver)
    ref = expect_ok(refund(c, tok_receiver, target["id"], "rf-imp",
                           refund_body(1)), 201)
    eq(ref["refund_of"], target["id"], "refund works on imported state (R289)")
    # (b) Settlement membership survives earlier-stage export/import: build a
    # settlement, then downgrade the export's version label to 3 and 2
    # (same-team earlier-stage payload) and import each; membership is
    # preserved exactly.
    users2 = None
    toks2, _ = seeded_state(c)
    st = expect_ok(settle(c, toks2["op"], [transfer("ada", "bob", 300),
                                           transfer("bob", "cy", 200)], "st-m"), 201)
    sid = st["settlement_id"]
    sm1, sm2 = (p["payment_id"] for p in st["payments"])
    fresh_exp = expect_ok(c.export(), 200, "export with settlement")
    membership = {p["id"]: p.get("settlement_id")
                  for p in fresh_exp["state"]["payments"]}
    check(membership.get(sm1) == sid and membership.get(sm2) == sid,
          "precondition: settlement members linked (R289)")
    for version in (2, 3):
        relabeled = {"track": fresh_exp["track"], "format_version": version,
                     "state": fresh_exp["state"]}
        eq(c.import_state(relabeled).status, 204,
           f"v{version}-labeled export accepted (R289)")
        after = expect_ok(c.export(), 200, f"export after v{version} import")
        eq({p["id"]: p.get("settlement_id") for p in after["state"]["payments"]},
           membership, f"settlement membership preserved through v{version} (R289)")


def login_asis(c, handle):
    from client import expect_ok as eo
    r = c.login(f"{handle}@example.com")
    return eo(r, 200, f"login {handle}")["token"]


def test_r289_v4_round_trip_preserves_refunds(c):
    toks, _ = seeded_state(c)
    expect_ok(correct(c, toks["ada"], "p1", "c-pre", correction_body(1, 900, T1, "pre")), 201)
    ref = expect_ok(refund(c, toks["bob"], "p2", "rf-rt", refund_body(50)), 201)
    bat = expect_ok(correction_batch(c, toks["op"], "b-rt",
                                     [batch_item("p1", 2, 880, T1)]), 201)
    exp = expect_ok(c.export(), 200, "export with refunds/batches")
    eq(c.import_state(exp).status, 204, "v4 round trip accepted (R289)")
    exp2 = expect_ok(c.export(), 200, "re-export")
    eq(exp2, exp, "export is a fixed point of import (R289/R82)")
    # Refund/correction state still live after import (tokens preserved, R82):
    # p2 already refunded 50, so 50 more fits; 1000 does not.
    expect_ok(refund(c, toks["bob"], "p2", "rf-post", refund_body(50)), 201)
    expect_error(refund(c, toks["bob"], "p2", "rf-post-2", refund_body(1000)),
                 422, "refund_exceeds_payment",
                 "refund cap survived the import (R289)")
    expect_error(correct(c, toks["bob"], ref["payment_id"], "c-post",
                         correction_body(1, 10, T1, "x")),
                 422, "linked_payment_immutable",
                 "refunds stay immutable after import (R289)")


def test_r290_export_v4(c):
    toks, _ = seeded_state(c)
    expect_ok(correct(c, toks["ada"], "p1", "c-1", correction_body(1, 900, T1, "x")), 201)
    ref = expect_ok(refund(c, toks["bob"], "p2", "rf-1", refund_body(50)), 201)
    bat = expect_ok(correction_batch(c, toks["op"], "b-1",
                                     [batch_item("p1", 2, 880, T1)]), 201)
    exp = expect_ok(c.export(), 200, "export")
    eq(exp["track"], "pocketful", "track (stage-1 R78)")
    eq(exp["format_version"], 4, "stage-4 exports format_version 4 (R290)")
    payments = {p["id"]: p for p in exp["state"]["payments"]}
    for pid, p in payments.items():
        check("refund_of" in p, f"payment {pid} carries refund_of (R290)")
    eq(payments[ref["payment_id"]]["refund_of"], "p2",
       "refund payment carries its target's id in the export (R290/R264)")
    eq(payments["p2"]["refund_of"], None,
       "non-refund payments' refund_of null (R264)")
    eq(payments["p1"]["refund_of"], None, "ordinary refund_of null (R290)")
    revs = payments["p1"]["revisions"]
    eq([r["revision"] for r in revs], [1, 2, 3], "revision history exported")
    eq(revs[0].get("correction_batch_id"), None, "revision 1 batch id null")
    eq(revs[1].get("correction_batch_id"), None, "single-correction batch id null")
    eq(revs[2].get("correction_batch_id"), bat["correction_batch_id"],
       "batch revision exposes its batch id in the export (R290)")
    # Stage-3 v3 contents still carried: users with hashed credentials,
# settlement fields (the R82 carry-over family is regression-tested).
    state = exp["state"]
    check(state.get("users"), "users exported")
    check(all("password_hash" in u for u in state["users"]),
          "hashed credentials exported (stage-1 R82)")
    check("settlement_operator_ids" in state, "operators exported")
    # Round trip is a no-op on money fields.
    eq(c.import_state(exp).status, 204, "re-import own v4 export")
    for h, t in toks.items():
        me = get_me(c, t)
        check(me["balance"] >= 0, f"{h} balance nonnegative after round trip")