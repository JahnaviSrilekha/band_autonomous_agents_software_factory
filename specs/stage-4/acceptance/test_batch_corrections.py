"""Stage-4 correction batches: auth/order, bounds, item validation, settlement
completeness, error precedence, combined affordability, replay and history
(R269-R286)."""
import json

from client import (
    check, eq, expect_error, expect_ok, fresh, get_me, make_payment, correct,
    correction_body, fpayment, refund, refund_body, settle, transfer,
    create_request, pay_request, correction_batch, batch_item, revisions_of,
    statement_ok, all_statement_entries, inst, parse_inst, shift, T1, T2, T3,
    T4, FAR_PAST,
)


def seeded_batch_state(c, n=3, base=100):
    """Fixture with n seeded ada->bob payments p_i (revision 1, amount base+i),
    created at T1. Returns (tokens, payment_ids)."""
    users = [fpayment(f"p{i}", "u_ada", "u_bob", base + i, created_at=T1)
             for i in range(1, n + 1)]
    toks = fresh(c, operator=True, payments=users)
    return toks, [f"p{i}" for i in range(1, n + 1)]


def test_r269_auth_operator_key_order(c):
    toks = fresh(c, operator=True)
    body = {"corrections": [batch_item("p1", 1, 50, T1)]}
    # (a) no token -> 401 before everything (even with a bad body).
    expect_error(c.post("/correction-batches", raw_body="{not json"), 401,
                 "unauthenticated", "no token -> 401 (R269/A46)")
    # (b) authenticated non-operator -> 403 before the key check.
    expect_error(c.post("/correction-batches", body=body, token=toks["ada"]),
                 403, "forbidden", "non-operator -> 403 (R269)")
    expect_error(c.post("/correction-batches", body=body, token=toks["ada"],
                        headers={"Idempotency-Key": "b-1"}), 403, "forbidden",
                 "non-operator with key still 403 (R269)")
    # (c) operator but no key -> 400 missing_idempotency_key before handler.
    expect_error(c.post("/correction-batches", body=body, token=toks["op"]),
                 400, "missing_idempotency_key", "operator without key -> 400")
    # (d) operator + key: handler reached (404 unknown payment).
    expect_error(correction_batch(c, toks["op"], "b-2", body["corrections"]),
                 404, "not_found", "unknown payment in batch -> 404 (R272)")


def test_r270_bounds_and_distinct_ids(c):
    toks, ids = seeded_batch_state(c, n=33)
    cb = lambda items, key: correction_batch(c, toks["op"], key, items)
    expect_error(cb([], "b-empty"), 422, "validation_failed", "empty corrections")
    expect_error(cb([batch_item(f"p{i}", 1, 10 + i, T1)
                     for i in range(1, 34)], "b-33"),
                 422, "validation_failed", "33 items rejected (R270)")
    # 32 distinct items accepted.
    r = expect_ok(cb([batch_item(f"p{i}", 1, 10 + i, T1)
                      for i in range(1, 33)], "b-32"), 201)
    eq(len(r["revisions"]), 32, "32 items accepted (R270)")
    # Duplicate payment_id rejected.
    dup = [batch_item("p1", 1, 5, T1), batch_item("p1", 1, 6, T1)]
    expect_error(cb(dup, "b-dup"), 422, "validation_failed", "duplicate ids")
    # Non-array and wrong-type containers are 422 validation_failed (R270).
    for i, bad in enumerate(('{"corrections": {"payment_id": "p1"}}',
                             '{"corrections": "p1"}', '{"corrections": [1]}')):
        expect_error(c.post("/correction-batches", raw_body=bad,
                            token=toks["op"],
                            headers={"Idempotency-Key": f"b-type-{i}"}),
                     422, "validation_failed", f"non-array corrections: {bad}")


def test_r271_item_field_validation_in_input_order(c):
    toks, ids = seeded_batch_state(c, n=4)
    ok_item = batch_item("p1", 1, 111, T1)
    cases = [
        (batch_item("p1", 0, 100, T1), 422, "validation_failed", "revision 0"),
        (batch_item("p1", -1, 100, T1), 422, "validation_failed", "revision -1"),
        (batch_item("p1", 1, -1, T1), 422, "validation_failed", "amount -1"),
        (batch_item("p1", 1, 1000000001, T1), 422, "validation_failed", "amount too big"),
        (batch_item("p1", 1, 100, T1, reason=""), 422, "validation_failed", "empty reason"),
        (batch_item("p1", 1, 100, T1, reason="x" * 201), 422, "validation_failed", "long reason"),
        (batch_item("p1", 1, 100, shift(T1, 10)), 422, "validation_failed", "future effective_at"),
        (batch_item("p1", 1, 100, "not-a-time"), 422, "validation_failed", "bad instant"),
        ({"payment_id": "p1", "amount": 100, "effective_at": T1, "reason": "r"},
         422, "validation_failed", "missing expected_revision"),
        ({"payment_id": "p1", "expected_revision": 1, "effective_at": T1, "reason": "r"},
         422, "validation_failed", "missing amount"),
    ]
    for i, (item, status, code, what) in enumerate(cases):
        expect_error(correction_batch(c, toks["op"], f"b-f-{i}", [item]),
                     status, code, f"item validation: {what} (R271)")
    # Wrong JSON types on item fields are 400 malformed_request.
    for i, bad in enumerate(('{"corrections": [{"payment_id": "p1", '
                             '"expected_revision": "1", "amount": 5, '
                             '"effective_at": "%s", "reason": "r"}]}' % T1,
                             '{"corrections": [{"payment_id": "p1", '
                             '"expected_revision": 1, "amount": "5", '
                             '"effective_at": "%s", "reason": "r"}]}' % T1)):
        expect_error(c.post("/correction-batches", raw_body=bad,
                            token=toks["op"],
                            headers={"Idempotency-Key": f"b-t-{i}"}),
                     400, "malformed_request", f"wrong field type: {bad}")
    # Input order decides which item error is reported: a field error on
    # item1 beats a 404 on item2 (both stage-1 of R275).
    expect_error(correction_batch(c, toks["op"], "b-ord-1",
                                  [batch_item("p1", 0, 100, T1),
                                   batch_item("p_ghost", 1, 100, T1)]),
                 422, "validation_failed", "item1 error wins in input order")
    expect_error(correction_batch(c, toks["op"], "b-ord-2",
                                  [batch_item("p_ghost", 1, 100, T1),
                                   batch_item("p1", 0, 100, T1)]),
                 404, "not_found", "reversed order -> 404 wins")
    # Unknown fields inside items are ignored (A42).
    item = batch_item("p1", 1, 112, T1)
    item["unexpected_key"] = "ignored"
    r = expect_ok(correction_batch(c, toks["op"], "b-unk", [item]), 201)
    eq(r["revisions"][0]["amount"], 112, "unknown item fields ignored (A42)")


def test_r272_unknown_payment_404_whole_batch(c):
    toks, ids = seeded_batch_state(c, n=2)
    expect_error(correction_batch(c, toks["op"], "b-404",
                                  [batch_item("p1", 1, 111, T1),
                                   batch_item("p_absent", 1, 222, T1)]),
                 404, "not_found", "one unknown item rejects the batch (R272)")
    eq([r["revision"] for r in revisions_of(c, toks["ada"], "p1")], [1],
       "no partial application (R272/R279)")


def test_r273_stale_revision(c):
    toks, ids = seeded_batch_state(c, n=2)
    expect_error(correction_batch(c, toks["op"], "b-stale",
                                  [batch_item("p1", 2, 111, T1)]),
                 409, "stale_revision", "stale expected revision (R273)")
    eq([r["revision"] for r in revisions_of(c, toks["ada"], "p1")], [1],
       "state unchanged")
    # Input order between item errors: stale on p1 before 404 on p2.
    expect_error(correction_batch(c, toks["op"], "b-stale-2",
                                  [batch_item("p1", 2, 111, T1),
                                   batch_item("p_ghost", 1, 222, T1)]),
                 409, "stale_revision", "item order decides (R275 stage 1)")
    expect_error(correction_batch(c, toks["op"], "b-stale-3",
                                  [batch_item("p_ghost", 1, 222, T1),
                                   batch_item("p1", 2, 111, T1)]),
                 404, "not_found", "reversed order -> 404")


def test_r274_operator_reaches_many_kinds_immutable_ones_rejected(c):
    toks, _ = seeded_batch_state(c, n=1)
    # Ordinary + request payment in one batch, operator is not their sender.
    rq = expect_ok(create_request(c, toks["bob"], "ada", 120, "rq-1"), 201)
    rpay = expect_ok(pay_request(c, toks["ada"], rq["request_id"], "pay-1"), 201)
    r = expect_ok(correction_batch(c, toks["op"], "b-mix",
                                   [batch_item("p1", 1, 111, T1),
                                    batch_item(rpay["payment_id"], 1, 120,
                                               rpay["created_at"])]), 201)
    eq([rev["amount"] for rev in r["revisions"]], [111, 120],
       "operator corrects ordinary + request payments (R274)")
    # Captures and refunds stay immutable in batches.
    from client import create_authz, capture
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 500, "az-1"), 201)
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "cap-1",
                            {"amount": 200, "final": True}), 201)
    expect_error(correction_batch(c, toks["op"], "b-cap",
                                  [batch_item(cap["payment_id"], 1, 100,
                                              cap["created_at"])]),
                 422, "linked_payment_immutable", "capture immutable in batch (R274)")
    p = expect_ok(make_payment(c, toks["ada"], "bob", 300, "p-rf"), 201)
    ref = expect_ok(refund(c, toks["bob"], p["payment_id"], "rf-1",
                           refund_body(50)), 201)
    expect_error(correction_batch(c, toks["op"], "b-ref",
                                  [batch_item(ref["payment_id"], 1, 10,
                                              ref["created_at"])]),
                 422, "linked_payment_immutable", "refund immutable in batch (R274)")


def test_r276_incomplete_settlement(c):
    from client import fuser, rfc3339
    users = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 50000),
             fuser("u_cy", "cy", 1000), fuser("u_op", "op", 10000)]
    seeded = [fpayment("r1", "u_ada", "u_bob", 150, created_at=T2)]
    toks = fresh(c, operator=True, users=users, operators=["u_op"],
                 payments=seeded)
    st = expect_ok(settle(c, toks["op"], [transfer("ada", "bob", 300),
                                          transfer("bob", "cy", 200)], "st-1"), 201)
    check(st["settlement_id"], "settlement created")
    m1, m2 = (p["payment_id"] for p in st["payments"])
    eff = rfc3339(-60)
    # One member alone: 422 incomplete_settlement.
    expect_error(correction_batch(c, toks["op"], "b-inc-1",
                                  [batch_item(m1, 1, 310, eff)]),
                 422, "incomplete_settlement", "single member rejected (R276)")
    # Both members: accepted; the nonmember item may differ in effective_at.
    r = expect_ok(correction_batch(c, toks["op"], "b-inc-2",
                                   [batch_item(m1, 1, 310, eff),
                                    batch_item(m2, 1, 210, eff),
                                    batch_item("r1", 1, 160, T2)]), 201)
    eq([rev["amount"] for rev in r["revisions"]], [310, 210, 160],
       "full settlement + nonmember corrected (R276)")
    # A three-member settlement partially included is rejected.
    toks3 = fresh(c, operator=True, users=users, operators=["u_op"])
    st3 = expect_ok(settle(c, toks3["op"], [transfer("ada", "bob", 101),
                                            transfer("ada", "bob", 102),
                                            transfer("ada", "bob", 103)],
                           "st-2"), 201)
    m = [p["payment_id"] for p in st3["payments"]]
    expect_error(correction_batch(c, toks3["op"], "b-inc-3",
                                  [batch_item(m[0], 1, 111, eff),
                                   batch_item(m[1], 1, 112, eff)]),
                 422, "incomplete_settlement", "2 of 3 members rejected (R276)")


def test_r277_identical_instants_offsets_may_differ(c):
    from client import fuser, rfc3339
    users = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 50000),
             fuser("u_cy", "cy", 1000), fuser("u_op", "op", 10000)]
    toks = fresh(c, operator=True, users=users, operators=["u_op"])
    st = expect_ok(settle(c, toks["op"], [transfer("ada", "bob", 300),
                                          transfer("bob", "cy", 200)], "st-1"), 201)
    m1, m2 = (p["payment_id"] for p in st["payments"])
    # Same instant, different offset spellings: accepted.
    z_spelling = "2026-09-01T13:00:00+02:00"  # == T1 (11:00+00:00)
    r = expect_ok(correction_batch(c, toks["op"], "b-off",
                                   [batch_item(m1, 1, 310, T1),
                                    batch_item(m2, 1, 210, z_spelling)]), 201)
    eq(len(r["revisions"]), 2, "offset spellings of one instant accepted (R277)")
    # Different instants: 422 validation_failed.
    expect_error(correction_batch(c, toks["op"], "b-off-2",
                                  [batch_item(m1, 1, 320, T1),
                                   batch_item(m2, 1, 220, T2)]),
                 422, "validation_failed", "differing instants rejected (R277)")


def test_r275_precedence_item_errors_then_completeness_then_funds(c):
    # (1) item errors before settlement completeness: r1's field error is
    # reported even though the batch also omits one settlement member.
    from client import fuser, rfc3339
    users = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 400),
             fuser("u_cy", "cy", 1000), fuser("u_op", "op", 10000)]
    seeded = [
        fpayment("r1", "u_ada", "u_bob", 150, created_at=T2),
    ]
    toks = fresh(c, operator=True, users=users, operators=["u_op"],
                 payments=seeded)
    st = expect_ok(settle(c, toks["op"], [transfer("ada", "bob", 300),
                                          transfer("bob", "cy", 200)], "st-1"),
                   201)
    m1, m2 = (p["payment_id"] for p in st["payments"])
    eff = rfc3339(-60)
    expect_error(correction_batch(c, toks["op"], "b-prec-1",
                                  [batch_item("r1", 1, -5, T1),
                                   batch_item(m1, 1, 310, eff)]),
                 422, "validation_failed",
                 "item error beats incomplete_settlement (R275)")
    # (2) settlement completeness before funds: bob declared 400, so the
    # completed batch (m1 +1000, m2 -1800 on bob) would fail current funds —
    # but omitting m2 must fail completeness first.
    expect_error(correction_batch(c, toks["op"], "b-prec-2",
                                  [batch_item(m1, 1, 1300, eff)]),
                 422, "incomplete_settlement",
                 "completeness beats resulting funds (R275)")
    # (3) combined current funds before historical: the same batch with all
    # members included now fails on current affordability.
    expect_error(correction_batch(c, toks["op"], "b-prec-3",
                                  [batch_item(m1, 1, 1300, eff),
                                   batch_item(m2, 1, 2000, eff)]),
                 409, "insufficient_funds",
                 "combined current funds overdraw bob (R275)")


def test_r278_combined_effect_not_sequential(c):
    """Each item alone would overdraw mid-batch; the combined net is exactly
    zero, so the batch must succeed (R278)."""
    from client import fuser
    users = [fuser("u_ada", "ada", 50), fuser("u_bob", "bob", 50000),
             fuser("u_cy", "cy", 0), fuser("u_op", "op", 10000)]
    seeded = [
        fpayment("p1", "u_bob", "u_ada", 1000, created_at=T1),
        fpayment("p2", "u_ada", "u_bob", 1000, created_at=T2),
    ]
    toks = fresh(c, operator=True, users=users, operators=["u_op"],
                 payments=seeded)
    before = {h: get_me(c, t) for h, t in toks.items()}
    r = expect_ok(correction_batch(c, toks["op"], "b-comb",
                                   [batch_item("p1", 1, 0, T1),
                                    batch_item("p2", 1, 0, T1)]), 201)
    eq([rev["amount"] for rev in r["revisions"]], [0, 0],
       "both zero-reversals applied together (R278)")
    after = {h: get_me(c, t) for h, t in toks.items()}
    for h in before:
        eq(after[h]["balance"], before[h]["balance"], f"{h} balance net-zero")
    # Combined insufficiency: one item revised short of the other's full
    # reversal; ada (declared 50) goes negative only on the combined delta.
    toks2 = fresh(c, operator=True, users=users, operators=["u_op"],
                  payments=seeded)
    expect_error(correction_batch(c, toks2["op"], "b-comb-2",
                                  [batch_item("p1", 1, 0, T1),
                                   batch_item("p2", 1, 100, T1)]),
                 409, "insufficient_funds",
                 "ada's combined delta is -100 (R278)")


def test_r275_historical_overdraft_combined_boundaries(c):
    """Each item alone is fine at every boundary; the combined timeline
    overdrafts between T2.5 and T3 -> 409 historical_overdraft (R275/A45)."""
    seeded = [
        fpayment("p0", "u_bob", "u_ada", 100, created_at=T1),
        fpayment("p1", "u_ada", "u_bob", 1, created_at=T2),
        fpayment("p2", "u_ada", "u_cy", 1, created_at=shift(T2, 1)),
        fpayment("p3", "u_cy", "u_ada", 1, created_at=T3),
    ]
    toks = fresh(c, operator=True, payments=seeded)
    # Sanity: each item alone succeeds.
    expect_ok(correction_batch(c, toks["op"], "b-h-a",
                               [batch_item("p1", 1, 81, T2)]), 201)
    toks2 = fresh(c, operator=True, payments=seeded)
    expect_ok(correction_batch(c, toks2["op"], "b-h-b",
                               [batch_item("p2", 1, 81, shift(T2, 1))]), 201)
    toks3 = fresh(c, operator=True, payments=seeded)
    expect_ok(correction_batch(c, toks3["op"], "b-h-c",
                               [batch_item("p3", 1, 61, T3)]), 201)
    # Combined: ada's timeline: T1 +100; T2 -80 (p1 1->81); T2+1us -80
    # (p2 1->81) -> -60 < 0 at that boundary; T3 +60 (p3 1->61) -> 0 now.
    toks4 = fresh(c, operator=True, payments=seeded)
    expect_error(correction_batch(c, toks4["op"], "b-h-all",
                                  [batch_item("p1", 1, 81, T2),
                                   batch_item("p2", 1, 81, shift(T2, 1)),
                                   batch_item("p3", 1, 61, T3)]),
                 409, "historical_overdraft",
                 "combined timeline overdrafts between T2+1us and T3 (A45)")
    eq([r["revision"] for r in revisions_of(c, toks4["ada"], "p1")], [1],
       "rejected batch leaves revisions unchanged (R279)")
    # Current-before-historical: with a modest opening for ada, two parallel
    # raises each affordable alone overdraft ada *now* (and at the shared
    # past boundary) — the response must be insufficient_funds (stage 3 of
    # R275), not historical_overdraft.
    from client import fuser
    users = [fuser("u_ada", "ada", 200), fuser("u_bob", "bob", 50000),
             fuser("u_cy", "cy", 1000), fuser("u_op", "op", 10000)]
    poor = [
        fpayment("p0", "u_bob", "u_ada", 100, created_at=T1),
        fpayment("p1", "u_ada", "u_bob", 1, created_at=T2),
        fpayment("p2", "u_ada", "u_cy", 1, created_at=shift(T2, 1)),
    ]
    toks5 = fresh(c, operator=True, users=users, operators=["u_op"],
                  payments=poor)
    # Sanity: each item alone succeeds on a fresh state.
    toks6 = fresh(c, operator=True, users=users, operators=["u_op"],
                  payments=poor)
    expect_ok(correction_batch(c, toks6["op"], "b-cur-a",
                               [batch_item("p1", 1, 200, T2)]), 201)
    toks7 = fresh(c, operator=True, users=users, operators=["u_op"],
                  payments=poor)
    expect_ok(correction_batch(c, toks7["op"], "b-cur-b",
                               [batch_item("p2", 1, 200, shift(T2, 1))]), 201)
    expect_error(correction_batch(c, toks5["op"], "b-h-cur",
                                  [batch_item("p1", 1, 200, T2),
                                   batch_item("p2", 1, 200, shift(T2, 1))]),
                 409, "insufficient_funds",
                 "current affordability precedes the historical check (R275)")


def test_r279_rejected_batch_leaves_nothing_including_key(c):
    toks, ids = seeded_batch_state(c, n=2)
    balances_before = {h: get_me(c, t)["balance"] for h, t in toks.items()}
    expect_error(correction_batch(c, toks["op"], "b-rej",
                                  [batch_item("p1", 2, 111, T1)]),
                 409, "stale_revision", "batch rejected")
    for h, t in toks.items():
        eq(get_me(c, t)["balance"], balances_before[h], f"{h} balance unchanged")
    eq([r["revision"] for r in revisions_of(c, toks["ada"], "p1")], [1],
       "no revision appended (R279)")
    # The idempotency key is freed: same key now with a VALID body succeeds.
    r = expect_ok(correction_batch(c, toks["op"], "b-rej",
                                   [batch_item("p1", 1, 111, T1)]), 201)
    eq(r["revisions"][0]["amount"], 111, "freed key treated as first use (R279)")


def test_r280_201_shape_and_input_order(c):
    toks, ids = seeded_batch_state(c, n=3)
    r = expect_ok(correction_batch(c, toks["op"], "b-shape",
                                   [batch_item("p3", 1, 333, T1, reason="r3"),
                                    batch_item("p1", 1, 111, T1, reason="r1"),
                                    batch_item("p2", 1, 222, T1, reason="r2")]),
                 201)
    check(isinstance(r.get("correction_batch_id"), str)
          and r["correction_batch_id"], "correction_batch_id present (R280)")
    check(r.get("recorded_at") and r["recorded_at"].endswith("+00:00"),
          f"recorded_at RFC 3339: {r.get('recorded_at')!r}")
    revs = r["revisions"]
    eq([rev["amount"] for rev in revs], [333, 111, 222],
       "revisions in input order, not payment order (R280)")
    eq([rev["reason"] for rev in revs], ["r3", "r1", "r2"], "reasons align")
    eq([rev["revision"] for rev in revs], [2, 2, 2], "each appends revision 2")


def test_r281_shared_recorded_at_strictly_later_and_batch_id(c):
    toks, ids = seeded_batch_state(c, n=3)
    before = {pid: revisions_of(c, toks["ada"], pid) for pid in ids}
    max_before = max(parse_inst(before[pid][-1]["recorded_at"]) for pid in ids)
    r = expect_ok(correction_batch(c, toks["op"], "b-time",
                                   [batch_item(pid, 1, 100 + i, T1)
                                    for i, pid in enumerate(ids)]), 201)
    recorded = {rev["recorded_at"] for rev in r["revisions"]}
    eq(len(recorded), 1, "all revisions share one recorded_at (R281)")
    check(parse_inst(recorded.pop()) > max_before,
          "shared recorded_at strictly later than every member's previous (R281/A43)")
    for rev, pid in zip(r["revisions"], ids):
        eq(rev.get("correction_batch_id"), r["correction_batch_id"],
           "revision exposes correction_batch_id (R281)")
        stored = revisions_of(c, toks["ada"], pid)
        eq(stored[-1].get("correction_batch_id"), r["correction_batch_id"],
           f"{pid} revision history exposes the batch id (R281)")
        eq(stored[0].get("correction_batch_id"), None,
           "revision 1 has no batch id (R281)")
    # A single-correction revision also has correction_batch_id null.
    expect_ok(correct(c, toks["ada"], "p1", "c-single",
                      correction_body(2, 999, T1, "solo")), 201)
    eq(revisions_of(c, toks["ada"], "p1")[-1].get("correction_batch_id"),
       None, "non-batch revision has null correction_batch_id (R281)")


def test_r282_effective_at_not_future(c):
    from client import rfc3339
    toks, ids = seeded_batch_state(c, n=1)
    expect_error(correction_batch(c, toks["op"], "b-fut",
                                  [batch_item("p1", 1, 111, rfc3339(60))]),
                 422, "validation_failed",
                 "future effective_at on a batch item is 422 (R282)")


def test_r283_original_payments_and_receipts_unchanged(c):
    toks, ids = seeded_batch_state(c, n=1)
    original_rev1 = revisions_of(c, toks["ada"], "p1")[0]
    before_entries = statement_ok(c, toks["ada"])["entries"]
    r = expect_ok(correction_batch(c, toks["op"], "b-orig",
                                   [batch_item("p1", 1, 555, T1)]), 201)
    after = revisions_of(c, toks["ada"], "p1")
    eq(after[0], original_rev1, "revision 1 record identical after the batch (R283)")
    eq(after[0]["amount"], 101, "original revision-1 amount intact (R283)")
    # The statement still shows exactly one entry for p1, now at revision 2
    # (R219 semantics): the original entry is replaced, not duplicated.
    entries = statement_ok(c, toks["ada"])["entries"]
    p1_entries = [e for e in entries if e["payment"]["payment_id"] == "p1"]
    eq(len(p1_entries), 1, "exactly one entry per payment (stage-3 R219)")
    eq(p1_entries[0]["revision"], 2, "entry now shows the batch revision")
    eq(p1_entries[0]["delta"], -555, "entry delta is the corrected amount (R217)")
    others = [e for e in entries if e["payment"]["payment_id"] != "p1"]
    eq(others, before_entries, "other payments' entries untouched (R283)")


def test_r284_original_retries_return_original_bodies(c):
    toks, ids = seeded_batch_state(c, n=1)
    # Create a payment via API, correct it via batch, refund part of it.
    p = expect_ok(make_payment(c, toks["ada"], "bob", 700, "pay-orig"), 201)
    original_payment_body = p
    expect_ok(correction_batch(c, toks["op"], "b-retry",
                               [batch_item(p["payment_id"], 1, 750, T1)]), 201)
    expect_ok(refund(c, toks["bob"], p["payment_id"], "rf-after",
                     refund_body(50)), 201)
    replay = expect_ok(make_payment(c, toks["ada"], "bob", 700, "pay-orig"), 200)
    eq(replay, original_payment_body, "original payment retry: original body (R284)")
    eq(replay["refund_of"], None, "original body unchanged by later refunds")
    # Settlement retry returns the original settlement body even after its
    # members were corrected by a batch.
    from client import fuser
    users2 = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 50000),
              fuser("u_cy", "cy", 1000), fuser("u_op", "op", 10000)]
    toks2 = fresh(c, operator=True, users=users2, operators=["u_op"])
    st = expect_ok(settle(c, toks2["op"], [transfer("ada", "bob", 300),
                                           transfer("bob", "cy", 200)], "st-r"), 201)
    original_settlement = st
    sm1, sm2 = (p["payment_id"] for p in st["payments"])
    expect_ok(correction_batch(c, toks2["op"], "b-st",
                               [batch_item(sm1, 1, 350, T1),
                                batch_item(sm2, 1, 250, T1)]), 201)
    st_replay = expect_ok(settle(c, toks2["op"], [transfer("ada", "bob", 300),
                                                  transfer("bob", "cy", 200)], "st-r"), 200)
    eq(st_replay, original_settlement, "settlement retry: original body (R284)")


def test_r285_statements_reflect_revisions_snapshots_frozen(c):
    toks, ids = seeded_batch_state(c, n=1)
    before_body, before_entries = all_statement_entries(c, toks["ada"])
    eq([e["delta"] for e in before_entries if e["payment"]["payment_id"] == "p1"],
       [-101], "pre-batch entry: ada sent 101 (revision 1)")
    snap = before_body["snapshot"]
    expect_ok(correction_batch(c, toks["op"], "b-stmt",
                               [batch_item("p1", 1, 123, T1)]), 201)
    # New statement reflects the new revision.
    _, after_entries = all_statement_entries(c, toks["ada"])
    p1_after = [e for e in after_entries if e["payment"]["payment_id"] == "p1"]
    eq([e["delta"] for e in p1_after], [-123], "statement shows corrected amount (R285)")
    eq([e["revision"] for e in p1_after], [2], "statement entry is revision 2")
    # Earlier snapshot token pages its frozen entries byte-identically.
    frozen_body, frozen_entries = all_statement_entries(c, toks["ada"],
                                                        snapshot=snap)
    eq(frozen_entries, before_entries, "frozen snapshot entries unchanged (R285)")
    eq(frozen_body["opening_balance"], before_body["opening_balance"],
       "frozen opening balance (R285)")
    eq(frozen_body["closing_balance"], before_body["closing_balance"],
       "frozen closing balance (R285)")


def test_r286_batch_replay_200_and_reuse_409(c):
    toks, ids = seeded_batch_state(c, n=2)
    items = [batch_item("p1", 1, 111, T1), batch_item("p2", 1, 222, T1)]
    first = correction_batch(c, toks["op"], "b-replay", items)
    eq(first.status, 201, "first use 201")
    original = first.json()
    replay = correction_batch(c, toks["op"], "b-replay", items)
    eq(replay.status, 200, "replay 200 (R286)")
    eq(replay.json(), original, "replay body identical (R286)")
    # No double application.
    eq([r["revision"] for r in revisions_of(c, toks["ada"], "p1")], [1, 2],
       "exactly one new revision after replay")
    # Different body, same key -> 409 idempotency_key_reuse.
    expect_error(correction_batch(c, toks["op"], "b-replay",
                                  [batch_item("p1", 1, 999, T1)]),
                 409, "idempotency_key_reuse", "key reuse (R286)")