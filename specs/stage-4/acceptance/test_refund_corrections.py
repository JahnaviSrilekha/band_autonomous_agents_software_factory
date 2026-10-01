"""Stage-4 corrections x refunds/captures: immutability extensions, refunded
floor, available-funds gating (R265-R268, amended R267 concurrency clause)."""
from client import (
    check, eq, expect_error, expect_ok, fresh, get_me, make_payment, correct,
    correction_body, create_authz, capture, refund, refund_body,
    revisions_of, run_concurrently, T1, T2,
)


def pay(c, toks, amount=1000, key="p-key", note="n", visibility="public"):
    return expect_ok(make_payment(c, toks["ada"], "bob", amount, key,
                                  note=note, visibility=visibility), 201)


def test_r265_single_correction_still_works(c):
    toks = fresh(c)
    p = pay(c, toks, amount=400)
    r = expect_ok(correct(c, toks["ada"], p["payment_id"], "c-1",
                          correction_body(1, 350, p["created_at"], "trim")), 201)
    eq(r["amount"], 350, "correction applies (R265: stage-3 flow unchanged)")
    eq([rev["amount"] for rev in revisions_of(c, toks["ada"], p["payment_id"])],
       [400, 350], "revision history appended")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 350, "balance follows correction")
    # Request-linked payments remain correctable too.
    from client import create_request, pay_request
    rq = expect_ok(create_request(c, toks["bob"], "ada", 100, "rq-1"), 201)
    rpay = expect_ok(pay_request(c, toks["ada"], rq["request_id"], "pay-1"), 201)
    expect_ok(correct(c, toks["ada"], rpay["payment_id"], "c-2",
                      correction_body(1, 90, rpay["created_at"], "trim")), 201)


def test_r266_capture_and_refund_immutable(c):
    toks = fresh(c)
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 500, "az-1"), 201)
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "cap-1",
                            {"amount": 200, "final": True}), 201)
    expect_error(correct(c, toks["ada"], cap["payment_id"], "c-cap",
                         correction_body(1, 100, cap["created_at"], "trim")),
                 422, "linked_payment_immutable", "capture not correctable (R266)")
    p = pay(c, toks, amount=300)
    ref = expect_ok(refund(c, toks["bob"], p["payment_id"], "rf-1",
                           refund_body(100)), 201)
    expect_error(correct(c, toks["bob"], ref["payment_id"], "c-ref",
                         correction_body(1, 90, ref["created_at"], "trim")),
                 422, "linked_payment_immutable", "refund not correctable (R266)")
    # State unchanged: still revision 1 each.
    eq([r["revision"] for r in revisions_of(c, toks["ada"], cap["payment_id"])],
       [1], "capture unchanged")
    eq([r["revision"] for r in revisions_of(c, toks["bob"], ref["payment_id"])],
       [1], "refund unchanged")


def test_r267_correction_cannot_dip_below_refunded(c):
    toks = fresh(c)
    p = pay(c, toks, amount=1000)
    expect_ok(refund(c, toks["bob"], p["payment_id"], "rf-1",
                     refund_body(300)), 201)
    expect_error(correct(c, toks["ada"], p["payment_id"], "c-low",
                         correction_body(1, 299, p["created_at"], "dip")),
                 422, "refund_exceeds_payment",
                 "correction below refunded sum rejected (R267)")
    eq([r["revision"] for r in revisions_of(c, toks["ada"], p["payment_id"])],
       [1], "state unchanged after rejection")
    # Boundary: correcting to exactly the refunded sum is allowed.
    expect_ok(correct(c, toks["ada"], p["payment_id"], "c-eq",
                      correction_body(1, 300, p["created_at"], "floor")), 201)
    eq([r["amount"] for r in revisions_of(c, toks["ada"], p["payment_id"])],
       [1000, 300], "floor correction applied")


def test_r267_concurrent_refund_vs_correction(c):
    """Conflicting race: refund 600 vs correction to 500 — whichever commits
    first makes the other exceed the refunded floor / cap (amended R267/R288)."""
    toks = fresh(c)
    p = pay(c, toks, amount=1000)
    pid = p["payment_id"]
    responses = run_concurrently([
        lambda: refund(c, toks["bob"], pid, "rf-race", refund_body(600)),
        lambda: correct(c, toks["ada"], pid, "c-race",
                        correction_body(1, 500, p["created_at"], "shrink")),
    ])
    statuses = sorted(r.status for r in responses)
    check(statuses[0] <= 299 and statuses[1] >= 400,
          f"exactly one of the racing refund/correction commits: {statuses}")
    loser_code = [r.json()["error"]["code"] for r in responses
                  if r.status >= 400][0]
    eq(loser_code, "refund_exceeds_payment",
       "loser loses on the refunded floor/cap check, serialized (R267)")
    revs = revisions_of(c, toks["ada"], pid)
    refund_won = any(r.status <= 299 and r.json().get("refund_of") == pid
                     for r in responses)
    if refund_won:
        eq([r["amount"] for r in revs], [1000],
           "refund won: payment amount unrevised")
        eq(get_me(c, toks["ada"])["balance"], 100000 - 1000 + 600, "money moved once")
    else:
        eq([r["amount"] for r in revs], [1000, 500], "correction won")
        eq(get_me(c, toks["ada"])["balance"], 100000 - 500, "correction applied once")


def test_r268_correction_debits_gate_on_available(c):
    toks = fresh(c)
    # Tie up most of ada's balance in a hold so available is thin.
    authz = expect_ok(create_authz(c, toks["ada"], "cy", 99500, "az-1"), 201)
    p = pay(c, toks, amount=300)  # ada: total 100000-300+... available small
    me = get_me(c, toks["ada"])
    eq(me["available"], 200, "precondition: ada available is 200 after the hold")
    # Correcting the payment UP debits ada further; beyond available -> 409.
    expect_error(correct(c, toks["ada"], p["payment_id"], "c-up",
                         correction_body(1, 800, p["created_at"], "raise")),
                 409, "insufficient_funds",
                 "correction debit checked against available (R268)")
    # A correction that fits available succeeds.
    expect_ok(correct(c, toks["ada"], p["payment_id"], "c-fit",
                      correction_body(1, 380, p["created_at"], "small")), 201)
    # Receiver-side available also gates: bob with a hold, correction debits bob.
    toks2 = fresh(c)
    p2 = pay(c, toks2, amount=500)
    expect_ok(create_authz(c, toks2["bob"], "cy", 50200, "az-2"), 201)
    expect_error(correct(c, toks2["ada"], p2["payment_id"], "c-down",
                         correction_body(1, 100, p2["created_at"], "reduce")),
                 409, "insufficient_funds",
                 "receiver-side debit (reducing a payment) gated by bob's available")


def test_r267_floor_applies_after_multiple_refunds(c):
    toks = fresh(c)
    p = pay(c, toks, amount=1000)
    expect_ok(refund(c, toks["bob"], p["payment_id"], "rf-a", refund_body(200)), 201)
    expect_ok(refund(c, toks["bob"], p["payment_id"], "rf-b", refund_body(300)), 201)
    expect_error(correct(c, toks["ada"], p["payment_id"], "c-x",
                         correction_body(1, 499, p["created_at"], "dip")),
                 422, "refund_exceeds_payment", "floor is the cumulative sum 500")
    expect_ok(correct(c, toks["ada"], p["payment_id"], "c-y",
                      correction_body(1, 500, p["created_at"], "floor")), 201)
    # And now the remaining refund headroom follows the corrected amount.
    expect_ok(refund(c, toks["bob"], p["payment_id"], "rf-c", refund_body(500)), 201)
    expect_error(refund(c, toks["bob"], p["payment_id"], "rf-d", refund_body(1)),
                 422, "refund_exceeds_payment", "refunded out after floor correction")