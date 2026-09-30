"""Money requests: create/pay/decline/cancel/list (R23-R25, R60-R70, A6)."""
from client import (check, eq, expect_error, expect_ok, fresh, get_me,
                    make_payment, payment_body)


def create_request(c, token, payer_handle, amount, key, note=None):
    body = {"payer_handle": payer_handle, "amount": amount}
    if note is not None:
        body["note"] = note
    return c.post("/requests", body=body, token=token,
                  headers={"Idempotency-Key": key})


def pay_request(c, token, request_id, key, visibility=None):
    body = {} if visibility is None else {"visibility": visibility}
    return c.post(f"/requests/{request_id}/pay", body=body, token=token,
                  headers={"Idempotency-Key": key})


REQUEST_KEYS = {"request_id", "requester_id", "requester_handle", "payer_id",
                "payer_handle", "amount", "currency", "note", "status",
                "payment_id", "created_at"}


def test_request_create_shape_and_defaults(c):
    toks = fresh(c)
    r = expect_ok(create_request(c, toks["bob"], "ada", 1200, "rq-shape-1",
                                 note="taxi"), 201)
    eq(set(r.keys()), REQUEST_KEYS, "request 201 exact shape (R60)")
    eq(r["requester_handle"], "bob", "caller is requester (R60)")
    eq(r["payer_handle"], "ada", "payer from body")
    eq(r["amount"], 1200, "amount")
    eq(r["note"], "taxi", "note")
    eq(r["status"], "pending", "status pending (R23)")
    check(r["payment_id"] is None, "payment_id null while pending")
    r2 = expect_ok(create_request(c, toks["bob"], "ada", 10, "rq-def-1"), 201)
    eq(r2["note"], "", "note defaults to empty (R60)")


def test_request_error_table(c):
    toks = fresh(c)
    expect_error(create_request(c, toks["bob"], "bob", 100, "sr-1"), 422,
                 "self_request")
    expect_error(create_request(c, toks["bob"], "ada", 0, "amt-1"), 422,
                 "validation_failed")
    expect_error(create_request(c, toks["bob"], "ada", 1000000001, "amt-2"), 422,
                 "validation_failed")
    expect_error(create_request(c, toks["bob"], "ada", "100", "amt-3"), 422,
                 "string amount 422 (R38)")
    expect_error(create_request(c, toks["bob"], "nobody", 100, "unk-1"), 404,
                 "not_found")
    expect_error(create_request(c, toks["bob"], "ada", 100, "note-1",
                                note="n" * 201), 422, "validation_failed")
    r = c.post("/requests", raw_body='{"payer_handle":5,"amount":1}',
               token=toks["bob"], headers={"Idempotency-Key": "ph-type"})
    expect_error(r, 400, "non-string payer_handle (R40)")
    r = c.post("/requests", body={"amount": 1}, token=toks["bob"],
               headers={"Idempotency-Key": "ph-missing"})
    expect_error(r, 422, "missing payer_handle (R36)")


def test_request_creation_ignores_payer_balance(c):
    # R24/R62: a request may exceed the payer's balance; legal at creation.
    toks = fresh(c)
    r = expect_ok(create_request(c, toks["bob"], "cy", 1000000000, "nobal-1"), 201)
    eq(r["status"], "pending", "created pending despite payer balance 0")


def test_pay_happy_and_payer_choice(c):
    toks = fresh(c)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 1200, "pay-1"), 201)
    r = expect_ok(pay_request(c, toks["ada"], rq["request_id"], "pay-1-k",
                              visibility="private"), 201)
    check("settlement_id" in r and r["settlement_id"] is None,
          "pay-created payment exposes settlement_id null (R56)")
    eq(r["request_id"], rq["request_id"], "payment carries request_id (R64)")
    eq(r["visibility"], "private", "payer chooses visibility (R25/R63)")
    eq(r["from_handle"], "ada", "payer is sender")
    eq(r["to_handle"], "bob", "requester is receiver")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 1200, "payer debited")
    eq(get_me(c, toks["bob"])["balance"], 50000 + 1200, "requester credited")
    # Request now paid and linked.
    listing = expect_ok(c.get("/requests", token=toks["bob"]), 200)["requests"]
    paid = [x for x in listing if x["request_id"] == rq["request_id"]][0]
    eq(paid["status"], "paid", "request becomes paid (R64)")
    eq(paid["payment_id"], r["payment_id"], "request carries payment_id (R64)")
    check("visibility" not in paid, "request carries no visibility field (R25)")


def test_pay_body_equality_strict(c):
    # R63: {} and {"visibility":"public"} are different JSON values for replay.
    toks = fresh(c)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 100, "be-1"), 201)
    expect_ok(pay_request(c, toks["ada"], rq["request_id"], "be-1-k"), 201,
              "pay with empty body")
    r = c.post(f"/requests/{rq['request_id']}/pay",
               body={"visibility": "public"}, token=toks["ada"],
               headers={"Idempotency-Key": "be-1-k"})
    expect_error(r, 409, "idempotency_key_reuse ({} vs visibility default)")


def test_pay_error_table(c):
    toks = fresh(c)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 1000000000, "pe-1"), 201)
    rid = rq["request_id"]
    # Caller not the payer.
    expect_error(pay_request(c, toks["bob"], rid, "pe-2"), 403, "forbidden")
    expect_error(pay_request(c, toks["cy"], rid, "pe-3"), 403, "forbidden")
    # Unknown request.
    expect_error(pay_request(c, toks["bob"], "rq_does_not_exist", "pe-4"),
                 404, "not_found")
    # Insufficient funds, changes nothing (R24).
    bal = get_me(c, toks["ada"])["balance"]
    expect_error(pay_request(c, toks["ada"], rid, "pe-5"), 409, "insufficient_funds")
    eq(get_me(c, toks["ada"])["balance"], bal, "failed pay leaves balance (R24)")
    st = [x for x in expect_ok(c.get("/requests", token=toks["ada"]), 200)["requests"]
          if x["request_id"] == rid][0]
    eq(st["status"], "pending", "failed pay leaves request pending (R24)")
    # Money arrives later; the same request becomes payable (R24). Refund ada
    # first via a fresh operator fixture.
    toks = fresh(c, operator=True)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 1000000000, "pe-7"), 201)
    rid = rq["request_id"]
    expect_error(pay_request(c, toks["ada"], rid, "pe-8"), 409, "insufficient_funds")
    expect_ok(c.post("/payments", body=payment_body("ada", 1000000000),
                     token=toks["op"], headers={"Idempotency-Key": "pe-9"}),
              201, "operator funds ada")
    expect_ok(pay_request(c, toks["ada"], rid, "pe-10"), 201,
              "same request payable after money arrives (R24)")
    # Not pending after paid.
    expect_error(pay_request(c, toks["ada"], rid, "pe-11"), 409,
                 "request_not_pending")


def test_pay_replay_after_paid(c):
    # R66: replay returns the original payment, no extra money, no 409.
    toks = fresh(c)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 500, "rp-1"), 201)
    p1 = expect_ok(pay_request(c, toks["ada"], rq["request_id"], "rp-1-k"), 201)
    bal = get_me(c, toks["ada"])["balance"]
    r = c.post(f"/requests/{rq['request_id']}/pay", body={}, token=toks["ada"],
               headers={"Idempotency-Key": "rp-1-k"})
    eq(r.status, 200, "replay is 200 (R66)")
    eq(r.json(), p1, "original payment body (R66)")
    eq(get_me(c, toks["ada"])["balance"], bal, "no additional money moved (R66)")
    # Different key on an already-paid request is not a replay: 409.
    expect_error(pay_request(c, toks["ada"], rq["request_id"], "rp-1-other"), 409,
                 "request_not_pending (R3)")


def test_decline_lifecycle(c):
    toks = fresh(c)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 100, "dec-1"), 201)
    rid = rq["request_id"]
    expect_error(c.post(f"/requests/{rid}/decline", token=toks["bob"]), 403,
                 "requester is not the payer (R67)")
    expect_error(c.post(f"/requests/{rid}/decline", token=toks["cy"]), 403,
                 "third party forbidden (R67)")
    r = expect_ok(c.post(f"/requests/{rid}/decline", token=toks["ada"]), 200)
    eq(r["status"], "declined", "payer declines (R67)")
    r2 = expect_ok(c.post(f"/requests/{rid}/decline", token=toks["ada"]), 200)
    eq(r2["status"], "declined", "double decline is 200 with current state (R67)")
    expect_error(pay_request(c, toks["ada"], rid, "dec-2"), 409,
                 "request_not_pending")
    # Decline a paid request -> 409; decline a cancelled request -> 409.
    rq2 = expect_ok(create_request(c, toks["bob"], "ada", 50, "dec-3"), 201)
    expect_ok(pay_request(c, toks["ada"], rq2["request_id"], "dec-4"), 201)
    expect_error(c.post(f"/requests/{rq2['request_id']}/decline", token=toks["ada"]),
                 409, "request_not_pending (paid)")


def test_cancel_lifecycle(c):
    toks = fresh(c)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 100, "can-1"), 201)
    rid = rq["request_id"]
    expect_error(c.post(f"/requests/{rid}/cancel", token=toks["ada"]), 403,
                 "payer is not the requester (R68)")
    expect_error(c.post(f"/requests/{rid}/cancel", token=toks["cy"]), 403,
                 "third party forbidden (R68)")
    r = expect_ok(c.post(f"/requests/{rid}/cancel", token=toks["bob"]), 200)
    eq(r["status"], "cancelled", "requester cancels (R68)")
    r2 = expect_ok(c.post(f"/requests/{rid}/cancel", token=toks["bob"]), 200)
    eq(r2["status"], "cancelled", "double cancel is 200 (R68)")
    expect_error(pay_request(c, toks["ada"], rid, "can-2"), 409,
                 "request_not_pending")
    rq2 = expect_ok(create_request(c, toks["bob"], "ada", 50, "can-3"), 201)
    expect_ok(c.post(f"/requests/{rq2['request_id']}/decline", token=toks["ada"]), 200)
    expect_error(c.post(f"/requests/{rq2['request_id']}/cancel", token=toks["bob"]),
                 409, "request_not_pending (declined)")


def test_supplied_key_on_decline_cancel_ignored(c):
    # A6: a client-supplied Idempotency-Key on decline/cancel is ignored
    # entirely; the key string stays a fresh first use elsewhere.
    toks = fresh(c)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 100, "a6-1"), 201)
    rid = rq["request_id"]
    expect_ok(c.post(f"/requests/{rid}/decline", token=toks["ada"],
                     headers={"Idempotency-Key": "a6-k"}), 200)
    rq2 = expect_ok(create_request(c, toks["bob"], "ada", 100, "a6-2"), 201)
    expect_ok(c.post(f"/requests/{rq2['request_id']}/cancel", token=toks["bob"],
                     headers={"Idempotency-Key": "a6-k"}), 200)
    r = make_payment(c, toks["ada"], "bob", 100, "a6-k")
    eq(r.status, 201, "key reused after decline/cancel is a first use (A6)")


def test_requests_listing_and_filters(c):
    toks = fresh(c)
    r1 = expect_ok(create_request(c, toks["bob"], "ada", 100, "ls-1"), 201)
    r2 = expect_ok(create_request(c, toks["bob"], "cy", 200, "ls-2"), 201)
    r3 = expect_ok(create_request(c, toks["ada"], "bob", 300, "ls-3"), 201)
    expect_ok(pay_request(c, toks["bob"], r3["request_id"], "ls-3-k"), 201)
    import time
    time.sleep(1.1)  # make r4's created_at strictly later for newest-first
    r4 = expect_ok(create_request(c, toks["cy"], "bob", 400, "ls-4"), 201)
    expect_ok(c.post(f"/requests/{r4['request_id']}/decline", token=toks["bob"]), 200)

    def ids(resp):
        return [x["request_id"] for x in resp["requests"]]

    both = expect_ok(c.get("/requests", token=toks["bob"]), 200)
    eq(both["has_more"], False, "has_more false when complete")
    check(set(ids(both)) == {r1["request_id"], r2["request_id"],
                             r3["request_id"], r4["request_id"]},
          "caller sees own incoming+outgoing only (R27/R69)")
    inc = expect_ok(c.get("/requests?direction=incoming", token=toks["bob"]), 200)
    check(set(ids(inc)) == {r3["request_id"], r4["request_id"]},
          "incoming: caller is payer")
    out = expect_ok(c.get("/requests?direction=outgoing", token=toks["bob"]), 200)
    check(set(ids(out)) == {r1["request_id"], r2["request_id"]},
          "outgoing: caller is requester")
    paid = expect_ok(c.get("/requests?status=paid", token=toks["bob"]), 200)
    check(ids(paid) == [r3["request_id"]], "status=paid filter")
    pend = expect_ok(c.get("/requests?status=pending&direction=outgoing",
                           token=toks["bob"]), 200)
    check(set(ids(pend)) == {r1["request_id"], r2["request_id"]},
          "combined filters")
    check(len(expect_ok(c.get("/requests", token=toks["cy"]), 200)["requests"]) == 2,
          "cy sees only own two (R27)")
    # Newest first (R69): r4 created last.
    allb = expect_ok(c.get("/requests", token=toks["bob"]), 200)
    eq(ids(allb)[0], r4["request_id"], "newest first by created_at")
    # Paging.
    pg = expect_ok(c.get("/requests?limit=2", token=toks["bob"]), 200)
    eq(len(pg["requests"]), 2, "limit respected")
    eq(pg["has_more"], True, "has_more true when more exist (R69)")
    rest = expect_ok(c.get(f"/requests?limit=2&offset=2", token=toks["bob"]), 200)
    eq(rest["has_more"], False, "has_more false at end")
    eq(set(ids(pg) + ids(rest)), set(ids(allb)), "offset paging covers all")


def test_requests_listing_validation(c):
    toks = fresh(c)
    expect_error(c.get("/requests?direction=bothways", token=toks["bob"]), 422,
                 "unknown direction (R70)")
    expect_error(c.get("/requests?status=archived", token=toks["bob"]), 422,
                 "unknown status (R70)")
    expect_error(c.get("/requests?limit=0", token=toks["bob"]), 422, "limit 0 (R41)")
    expect_error(c.get("/requests?limit=201", token=toks["bob"]), 422,
                 "limit 201 (R41)")
    eq(expect_ok(c.get("/requests?limit=200", token=toks["bob"]), 200)["requests"],
       expect_ok(c.get("/requests", token=toks["bob"]), 200)["requests"],
       "limit 200 boundary ok")
    r0 = expect_ok(c.get("/requests?offset=0", token=toks["bob"]), 200)
    check(r0["has_more"] in (True, False), "offset 0 boundary ok (R41)")
    # R39: integer query params must be plain decimal digits.
    for q in ("limit=1e9", "limit=4.0", "limit=%2B4", "offset=%2B0",
              "limit=abc", "offset=-1"):
        expect_error(c.get(f"/requests?{q}", token=toks["bob"]), 422,
                     f"bad query {q} (R39/R41)")


def test_request_moves_money_at_most_once(c):
    # R3: two different keys cannot both pay the same request.
    toks = fresh(c)
    rq = expect_ok(create_request(c, toks["bob"], "ada", 700, "once-1"), 201)
    expect_ok(pay_request(c, toks["ada"], rq["request_id"], "once-k1"), 201)
    expect_error(pay_request(c, toks["ada"], rq["request_id"], "once-k2"), 409,
                 "request_not_pending")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 700, "moved exactly once (R3)")