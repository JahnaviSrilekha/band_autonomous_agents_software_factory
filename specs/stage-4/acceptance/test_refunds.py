"""Stage-4 refunds: request/pipeline order, targets, money movement, shape,
replay (R253-R264, R257, amended R262 concurrency clause)."""
import json

from client import (
    check, eq, expect_error, expect_ok, fresh, get_me, make_payment,
    payment_body, run_concurrently, refund, refund_body, create_authz, capture,
    create_request, pay_request, latest_amount, rfc3339, statement_ok,
    all_statement_entries, revisions_of, T1,
)


def seeded_payment(c, amount=1000, note="seed pay", visibility="public"):
    """Reset to the standard fixture and create one ada->bob payment."""
    toks = fresh(c)
    pay = expect_ok(make_payment(c, toks["ada"], "bob", amount, "pay-1",
                                 note=note, visibility=visibility), 201)
    return toks, pay


def test_r253_auth_then_key_then_handler_order(c):
    toks = fresh(c)
    # (a) no token: 401 wins even with an unknown payment and no key.
    expect_error(c.post("/payments/p_nope/refunds", body={"amount": 1}), 401,
                 "unauthenticated", "no token -> 401 before key/404 (R253)")
    # (b) token but no Idempotency-Key: 400 missing_idempotency_key before 404.
    expect_error(c.post("/payments/p_nope/refunds", body={"amount": 1},
                        token=toks["ada"]), 400, "missing_idempotency_key",
                 "missing key -> 400 before 404 (R253)")
    # (c) empty key string is the same 400.
    expect_error(c.post("/payments/p_nope/refunds", body={"amount": 1},
                        token=toks["ada"], headers={"Idempotency-Key": ""}),
                 400, "missing_idempotency_key", "empty key -> 400")
    # (d) key present, unknown payment: handler reached, 404 (R254).
    expect_error(refund(c, toks["ada"], "p_nope", "rf-a",
                        refund_body(1)), 404, "not_found", "unknown payment")


def test_r254_unknown_payment_404(c):
    toks, _ = seeded_payment(c)
    expect_error(refund(c, toks["bob"], "p_absent", "rf-b", refund_body(5)),
                 404, "not_found", "unknown payment is 404 (R254)")


def test_r255_only_receiver_may_refund(c):
    toks, pay = seeded_payment(c)
    # The original sender is not the receiver.
    expect_error(refund(c, toks["ada"], pay["payment_id"], "rf-s",
                        refund_body(10)), 403, "forbidden",
                 "sender cannot refund own outgoing payment (R255)")
    # A third party is not the receiver either.
    expect_error(refund(c, toks["cy"], pay["payment_id"], "rf-t",
                        refund_body(10)), 403, "forbidden",
                 "third party cannot refund (R255)")


def test_r256_refund_of_refund_and_precedence(c):
    toks, pay = seeded_payment(c)
    ref = expect_ok(refund(c, toks["bob"], pay["payment_id"], "rf-1",
                           refund_body(100)), 201)
    # Refunding the refund: the refund payment's receiver is ada.
    expect_error(refund(c, toks["ada"], ref["payment_id"], "rf-2",
                        refund_body(10)), 422, "invalid_refund_target",
                 "refunds of refunds are rejected (R256)")
    # Precedence (A39): 403 (receiver check) before invalid_refund_target —
    # a non-receiver refunding the refund sees 403, not 422.
    expect_error(refund(c, toks["cy"], ref["payment_id"], "rf-3",
                        refund_body(10)), 403, "forbidden",
                 "403 precedes invalid_refund_target (A39)")


def test_r257_refundable_target_kinds(c):
    toks = fresh(c)
    # Direct payment.
    pay = expect_ok(make_payment(c, toks["ada"], "bob", 100, "k-direct"), 201)
    r1 = expect_ok(refund(c, toks["bob"], pay["payment_id"], "rf-direct",
                          refund_body(40)), 201)
    eq(r1["refund_of"], pay["payment_id"], "direct target refund (R257)")
    # Request payment.
    rq = expect_ok(create_request(c, toks["bob"], "ada", 70, "k-req"), 201)
    rpay = expect_ok(pay_request(c, toks["ada"], rq["request_id"], "k-pay"), 201)
    check(rpay["request_id"] == rq["request_id"], "precondition: request-linked")
    r2 = expect_ok(refund(c, toks["bob"], rpay["payment_id"], "rf-req",
                          refund_body(70)), 201)
    eq(r2["refund_of"], rpay["payment_id"], "request-payment target (R257)")
    # Capture payment (correction-immutable per R266 yet refundable, R257).
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 200, "k-authz"), 201)
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "k-cap",
                            {"amount": 150, "final": True}), 201)
    check(cap["authorization_id"] == authz["authorization_id"],
          "precondition: capture linked")
    r3 = expect_ok(refund(c, toks["bob"], cap["payment_id"], "rf-cap",
                          refund_body(150)), 201)
    eq(r3["refund_of"], cap["payment_id"], "capture target (R257)")


def test_r258_amount_validation(c):
    toks, pay = seeded_payment(c)
    pid = pay["payment_id"]
    for amount, what in ((0, "zero"), (-5, "negative"),
                         (1000000001, "over upper bound"), (None, "missing")):
        body = {} if amount is None else {"amount": amount}
        expect_error(refund(c, toks["bob"], pid, f"rf-bad-{what}", body),
                     422, "validation_failed",
                     f"invalid refund amount ({what}) is 422 (R258/A40)")
    # Non-integer-valued number: still 422 validation_failed (R258).
    expect_error(refund(c, toks["bob"], pid, "rf-frac", {"amount": 200.5}),
                 422, "validation_failed", "fractional amount is 422 (R258)")
    # Wrong JSON types are 400 malformed_request (stage-1 R40).
    for i, bad in enumerate(('{"amount": "200"}', '{"amount": [200]}',
                             '{"amount": true}')):
        expect_error(c.post(f"/payments/{pid}/refunds", raw_body=bad,
                            token=toks["bob"],
                            headers={"Idempotency-Key": f"rf-type-{i}"}),
                     400, "malformed_request",
                     f"wrong JSON type amount -> 400: {bad}")
    # Upper bound accepted by validation: 1e9 on a small payment fails the
    # later cumulative-cap check instead (A39 order).
    expect_error(refund(c, toks["bob"], pid, "rf-big", refund_body(1000000000)),
                 422, "refund_exceeds_payment",
                 "1e9 passes validation, hits cap check (A40/A39)")


def test_r259_cumulative_cap_and_corrected_amount(c):
    toks, pay = seeded_payment(c, amount=1000)
    pid = pay["payment_id"]
    expect_ok(refund(c, toks["bob"], pid, "rf-a", refund_body(600)), 201)
    expect_error(refund(c, toks["bob"], pid, "rf-b", refund_body(401)),
                 422, "refund_exceeds_payment",
                 "601 cumulative > 1000 rejected (R259)")
    # Boundary: filling the cap exactly is allowed.
    expect_ok(refund(c, toks["bob"], pid, "rf-c", refund_body(400)), 201)
    expect_error(refund(c, toks["bob"], pid, "rf-d", refund_body(1)),
                 422, "refund_exceeds_payment", "cap exhausted")
    # The cap tracks the *current corrected* amount (R259): correct a fresh
    # payment down, then the cap shrinks with it.
    toks2, pay2 = seeded_payment(c, amount=1000)
    from client import correct, correction_body
    expect_ok(correct(c, toks2["ada"], pay2["payment_id"], "corr-1",
                      correction_body(1, 500, pay2["created_at"], "shrink")), 201)
    expect_ok(refund(c, toks2["bob"], pay2["payment_id"], "rf-e",
                     refund_body(500)), 201)
    expect_error(refund(c, toks2["bob"], pay2["payment_id"], "rf-f",
                        refund_body(1)), 422, "refund_exceeds_payment",
                 "cap follows corrected amount 500 (R259)")
    # State unchanged after each rejection (checked via balance math on the
    # API-created payment: ada paid 1000, got 500 back from the correction and
    # 500 from the refund).
    eq(get_me(c, toks2["ada"])["balance"], 100000, "ada balance")
    eq(get_me(c, toks2["bob"])["balance"], 50000, "bob balance")


def test_r260_refund_shape_and_direction(c):
    toks, pay = seeded_payment(c, amount=300, note="concert", visibility="private")
    ref = expect_ok(refund(c, toks["bob"], pay["payment_id"], "rf-x",
                           refund_body(120)), 201)
    eq(ref["from_user_id"], pay["to_user_id"], "opposite direction: from (R260)")
    eq(ref["to_user_id"], pay["from_user_id"], "opposite direction: to (R260)")
    eq(ref["from_handle"], "bob", "from_handle")
    eq(ref["to_handle"], "ada", "to_handle")
    eq(ref["refund_of"], pay["payment_id"], "refund_of names target (R260)")
    eq(ref["request_id"], None, "request_id null (R260)")
    eq(ref["authorization_id"], None, "authorization_id null (R260)")
    eq(ref["settlement_id"], None, "refund is not a settlement member")
    eq(ref["note"], "concert", "original note copied (R260)")
    eq(ref["visibility"], "private", "original visibility copied (R260)")
    eq(ref["amount"], 120, "refund amount is the refund's own amount")
    revs = revisions_of(c, toks["bob"], ref["payment_id"])
    eq([r["amount"] for r in revs], [120], "fresh revision-1 amount (R260)")
    # Money moved: receiver of the target (bob) is debited, sender credited.
    eq(get_me(c, toks["bob"])["balance"], 50000 + 300 - 120, "bob debited")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 300 + 120, "ada credited")


def test_r261_replay_200_and_key_reuse(c):
    toks, pay = seeded_payment(c)
    body = refund_body(99)
    first = refund(c, toks["bob"], pay["payment_id"], "rf-key", body)
    eq(first.status, 201, "first use 201 (R261)")
    original = first.json()
    replay = refund(c, toks["bob"], pay["payment_id"], "rf-key", body)
    eq(replay.status, 200, "replay 200 (R261)")
    eq(replay.json(), original, "replay body identical (R261)")
    # No double effect: only one refund exists.
    eq(get_me(c, toks["bob"])["balance"], 50000 + 1000 - 99, "single debit")
    # Same key, different body -> 409 idempotency_key_reuse.
    expect_error(refund(c, toks["bob"], pay["payment_id"], "rf-key",
                        refund_body(98)), 409, "idempotency_key_reuse",
                 "key reuse with different body (R261)")


def test_r262_insufficient_funds_atomic_and_available(c):
    # Total funds short: bob received 300, then spent nearly everything, so a
    # full refund fits the cumulative cap but exceeds his remaining funds.
    toks, pay = seeded_payment(c, amount=300)
    expect_ok(make_payment(c, toks["bob"], "cy", 50200, "spend-1"), 201)
    before_ada = get_me(c, toks["ada"])
    expect_error(refund(c, toks["bob"], pay["payment_id"], "rf-big",
                        refund_body(300)), 409, "insufficient_funds",
                 "refund beyond receiver's remaining funds (R262)")
    eq(get_me(c, toks["ada"]), before_ada, "no state change on failure (R262)")
    # Key freed after the 409: same key now succeeds with a valid amount.
    expect_ok(refund(c, toks["bob"], pay["payment_id"], "rf-big",
                     refund_body(50)), 201)
    # Available (not total) funds gate the refund: bob holds most of his
    # balance with an authorization.
    toks2, pay2 = seeded_payment(c, amount=1000)
    authz = expect_ok(create_authz(c, toks2["bob"], "cy", 50500, "hold-1"), 201)
    me = get_me(c, toks2["bob"])
    eq(me["held"], 50500, "hold recorded (stage-2 R120)")
    eq(me["available"], 500, "bob's available reduced by the hold")
    expect_error(refund(c, toks2["bob"], pay2["payment_id"], "rf-avail",
                        refund_body(600)), 409, "insufficient_funds",
                 "available funds, not total, gate refunds (R262)")
    eq(get_me(c, toks2["ada"])["balance"], 100000 - 1000, "ada unchanged")
    # Partial refund that fits available succeeds.
    expect_ok(refund(c, toks2["bob"], pay2["payment_id"], "rf-fit",
                     refund_body(400)), 201)
    eq(get_me(c, toks2["bob"])["available"], me["available"] - 400,
       "available reduced by the refund (R262)")


def test_r262_concurrent_refunds_cumulative_cap(c):
    toks, pay = seeded_payment(c, amount=1000)
    pid = pay["payment_id"]
    responses = run_concurrently([
        lambda i=i: refund(c, toks["bob"], pid, f"rf-cc-{i}", refund_body(800))
        for i in range(3)
    ])
    statuses = [r.status for r in responses]
    eq(sorted(s <= 299 for s in statuses), [False, False, True],
       "exactly one of three over-refunding concurrent refunds commits "
       "(amended R262)")
    winner = next(r for r in responses if r.status <= 299)
    losers = [r for r in responses if r.status >= 400]
    for r in losers:
        check(r.status in (409, 422),
              f"loser status must be 409 or 422, got {r.status}")
        body = r.json()
        code = body.get("error", {}).get("code")
        if r.status == 422:
            eq(code, "refund_exceeds_payment", "cap losers see the cap code")
        else:
            eq(code, "insufficient_funds", "funds losers see the funds code")
    eq(winner.json()["amount"], 800, "winner committed its full amount")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 1000 + 800, "credit once")
    eq(get_me(c, toks["bob"])["balance"], 50000 + 1000 - 800, "debit once")
    # Winner's key replays 200; a loser's freed key, retried, now hits the
    # filled cumulative cap (1000 - 800 = 200 remaining < 800).
    wid = winner.json()["payment_id"]
    wkey = f"rf-cc-{responses.index(winner)}"
    eq(refund(c, toks["bob"], pid, wkey, refund_body(800)).status, 200,
       "winner key replays 200")
    for i, r in enumerate(responses):
        if r.status >= 400:
            expect_error(refund(c, toks["bob"], pid, f"rf-cc-{i}",
                                refund_body(800)), 422, "refund_exceeds_payment",
                         "loser key was freed (R279-family); retry hits the cap")


def test_r263_refunds_never_reopen_or_restore(c):
    toks = fresh(c)
    # Request: paying settles it; refunding the payment must not reopen it.
    rq = expect_ok(create_request(c, toks["bob"], "ada", 80, "rq-1"), 201)
    pay = expect_ok(pay_request(c, toks["ada"], rq["request_id"], "pay-rq"), 201)
    expect_ok(refund(c, toks["bob"], pay["payment_id"], "rf-rq",
                     refund_body(80)), 201)
    r = expect_ok(c.get("/requests", token=toks["bob"]), 200)
    found = [q for q in r.get("requests", []) if q["request_id"] == rq["request_id"]]
    check(found, "request still listed")
    check(found[0]["status"] != "pending", "request not reopened by refund (R263)")
    # Authorization: refunding a capture payment changes nothing on the hold.
    authz = expect_ok(create_authz(c, toks["ada"], "bob", 500, "az-1"), 201)
    cap = expect_ok(capture(c, toks["bob"], authz["authorization_id"], "cap-1",
                            {"amount": 200, "final": False}), 201)
    az_before = expect_ok(c.get(f"/authorizations", token=toks["ada"]), 200)
    bob_me = get_me(c, toks["bob"])
    expect_ok(refund(c, toks["bob"], cap["payment_id"], "rf-cap",
                     refund_body(200)), 201)
    az_after_list = expect_ok(c.get(f"/authorizations", token=toks["ada"]), 200)
    def az(body):
        return [a for a in body["authorizations"]
                if a["authorization_id"] == authz["authorization_id"]][0]
    a0, a1 = az(az_before), az(az_after_list)
    eq(a1["status"], a0["status"], "authorization status untouched (R263)")
    eq(a1["captured_amount"], a0["captured_amount"], "captured_amount untouched (R263)")
    eq(a1["payment_ids"], a0["payment_ids"], "payment_ids untouched (R263)")
    eq(a1["remaining_amount"], a0["remaining_amount"],
       "hold not restored or re-released by the refund (R263)")
    # The refund moved available by the balance movement only.
    eq(get_me(c, toks["bob"])["available"], bob_me["available"] - 200,
       "available moves only by the refund itself (R263)")
    # The hold is still releasable by void afterwards (normal lifecycle).
    expect_ok(c.post(f"/authorizations/{authz['authorization_id']}/void",
                     body={}, token=toks["ada"]), 200)


def test_r264_refund_of_null_elsewhere_and_everywhere(c):
    toks, pay = seeded_payment(c, amount=250, note="lunch", visibility="public")
    pid = pay["payment_id"]
    eq(pay["refund_of"], None, "ordinary creation body refund_of null (R264)")
    ref = expect_ok(refund(c, toks["bob"], pid, "rf-e", refund_body(60)), 201)
    eq(ref["refund_of"], pid, "refund creation body refund_of set (R264)")
    # Replay body carries it too.
    replay = refund(c, toks["bob"], pid, "rf-e", refund_body(60))
    eq(replay.json()["refund_of"], pid, "replay body refund_of (R264)")
    # Statement entries expose the payment with refund_of.
    _, entries = all_statement_entries(c, toks["ada"])
    by_id = {e["payment"]["payment_id"]: e["payment"] for e in entries
             if "payment" in e}
    eq(by_id[pid]["refund_of"], None, "ordinary statement entry refund_of null (R264)")
    eq(by_id[ref["payment_id"]]["refund_of"], pid,
       "refund statement entry refund_of set (R264)")


def test_r259_boundary_zero_remaining_via_statement(c):
    """Cap exhaustion leaves the refund as its own statement payment that
    exactly reverses the target (R260/R264)."""
    toks, pay = seeded_payment(c, amount=10)
    pid = pay["payment_id"]
    ref = expect_ok(refund(c, toks["bob"], pid, "rf-z", refund_body(10)), 201)
    expect_error(refund(c, toks["bob"], pid, "rf-z2", refund_body(1)),
                 422, "refund_exceeds_payment", "fully refunded")
    _, entries = all_statement_entries(c, toks["bob"])
    deltas = [e["delta"] for e in entries if e["payment"]["payment_id"] in
              (pid, ref["payment_id"])]
    eq(sum(deltas), 0, "refund payment exactly reverses the target in the statement")