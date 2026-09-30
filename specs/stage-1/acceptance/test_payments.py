"""POST /payments (R56-R59, R18, R30, R38, R40) and concurrent atomicity (R2)."""
from client import (check, eq, expect_error, expect_ok, fresh, get_me,
                    make_payment, payment_body, run_concurrently)

PAYMENT_KEYS = {"payment_id", "from_user_id", "from_handle", "to_user_id",
                "to_handle", "amount", "currency", "note", "visibility",
                "request_id", "created_at", "settlement_id"}


def test_payment_happy_shape(c):
    toks = fresh(c)
    r = expect_ok(make_payment(c, toks["ada"], "bob", 1500, "pay-shape-1",
                               note="dinner", visibility="public"), 201)
    eq(set(r.keys()), PAYMENT_KEYS, "payment 201 exact shape (R56)")
    eq(r["from_handle"], "ada", "from_handle")
    eq(r["to_handle"], "bob", "to_handle")
    eq(r["amount"], 1500, "amount")
    eq(r["currency"], "EUR", "currency")
    eq(r["note"], "dinner", "note")
    eq(r["visibility"], "public", "visibility")
    check(r["request_id"] is None, "request_id null on direct payment")
    check(r["settlement_id"] is None, "settlement_id null on ordinary payment (R56)")
    check(r["payment_id"] and isinstance(r["payment_id"], str), "payment_id present")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 1500, "sender debited")
    eq(get_me(c, toks["bob"])["balance"], 50000 + 1500, "receiver credited")


def test_payment_defaults(c):
    toks = fresh(c)
    r = expect_ok(c.post("/payments", body={"to_handle": "bob", "amount": 100},
                         token=toks["ada"], headers={"Idempotency-Key": "def-1"}),
                  201, "minimal body")
    eq(r["note"], "", "note defaults to empty string (R56)")
    eq(r["visibility"], "public", "visibility defaults to public (R56)")


def test_amount_integral_numeric_forms(c):
    toks = fresh(c)
    for i, raw in enumerate(('{"to_handle":"bob","amount":1000}',
                             '{"to_handle":"bob","amount":1000.0}',
                             '{"to_handle":"bob","amount":1e3}')):
        r = c.post("/payments", raw_body=raw, token=toks["ada"],
                   headers={"Idempotency-Key": f"int-{i}"})
        eq(r.status, 201, f"integral numeric amount form {raw} accepted (R18)")


def test_amount_bounds_and_types(c):
    users = [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 100000},
        {"id": "u_rich", "email": "rich@example.com", "password": "correct horse",
         "display_name": "Rich", "handle": "rich", "balance": 1000000000},
    ]
    c.reset({"currency": "EUR", "minor_units": 2, "users": users,
             "payments": [], "requests": []})
    rich = c.token_for("rich")
    for key, amount in [("amt-neg", -5), ("amt-0", 0), ("amt-over", 1000000001)]:
        expect_error(make_payment(c, rich, "ada", amount, key), 422,
                     f"amount {amount} rejected (R57/R30)")
    eq(make_payment(c, rich, "ada", 1, "amt-1").status, 201, "amount 1 accepted")
    eq(make_payment(c, rich, "ada", 1000000000, "amt-max").status, 201,
       "amount 1000000000 accepted (R30 boundary)")
    for i, raw in enumerate(('{"to_handle":"ada","amount":"100"}',
                             '{"to_handle":"ada","amount":true}',
                             '{"to_handle":"ada","amount":false}',
                             '{"to_handle":"ada","amount":1.5}')):
        r = c.post("/payments", raw_body=raw, token=rich,
                   headers={"Idempotency-Key": f"amt-type-{i}"})
        expect_error(r, 422, f"non-integer amount {raw} (R38)")
    r = c.post("/payments", body={"to_handle": "ada"}, token=rich,
               headers={"Idempotency-Key": "amt-missing"})
    expect_error(r, 422, "missing amount (R36)")
    r = c.post("/payments", raw_body='{"to_handle":5,"amount":1}', token=rich,
               headers={"Idempotency-Key": "th-type"})
    expect_error(r, 400, "non-string to_handle (R40)")
    r = c.post("/payments", body={"amount": 1}, token=rich,
               headers={"Idempotency-Key": "th-missing"})
    expect_error(r, 422, "missing to_handle (R36)")


def test_self_payment_and_unknown_handle(c):
    toks = fresh(c)
    expect_error(make_payment(c, toks["ada"], "ada", 100, "self-1"),
                 422, "self_payment")
    expect_error(make_payment(c, toks["ada"], "nobody", 100, "unk-1"),
                 404, "not_found")
    expect_error(make_payment(c, toks["ada"], "ADA", 100, "unk-2"),
                 404, "handles are lowercase; 'ADA' unknown (R19)")


def test_note_and_visibility_rules(c):
    toks = fresh(c)
    ok_note = "n" * 200
    r = make_payment(c, toks["ada"], "bob", 10, "note-1", note=ok_note)
    eq(r.status, 201, "200-char note accepted (boundary)")
    eq(r.json()["note"], ok_note, "note round trip")
    expect_error(make_payment(c, toks["ada"], "bob", 10, "note-2", note="n" * 201),
                 422, "201-char note rejected (R57)")
    for i, raw in enumerate(('{"to_handle":"bob","amount":10,"note":5}',
                             '{"to_handle":"bob","amount":10,"note":null}',
                             '{"to_handle":"bob","amount":10,"note":["x"]}')):
        r = c.post("/payments", raw_body=raw, token=toks["ada"],
                   headers={"Idempotency-Key": f"note-t-{i}"})
        expect_error(r, 422, f"non-string note {raw} (R38)")
    eq(make_payment(c, toks["ada"], "bob", 10, "vis-1", visibility="private").status,
       201, "private visibility accepted")
    for i, bad in enumerate(("internal", "", "Public", 5, None, True)):
        r = make_payment(c, toks["ada"], "bob", 10, f"vis-bad-{i}", visibility=bad)
        expect_error(r, 422, f"visibility {bad!r} rejected (R57/R38)")


def test_note_verbatim_unicode(c):
    toks = fresh(c)
    note = "café \tline1\nline2 \"quotes\" \\back 日本語  trim-not"
    r = expect_ok(make_payment(c, toks["ada"], "bob", 10, "uni-1", note=note), 201)
    eq(r["note"], note, "note byte-for-byte round trip, no trimming (R59)")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq(feed[0]["note"], note, "note verbatim in feed (R59)")


def test_insufficient_funds_no_trace(c):
    toks = fresh(c)
    ada_bal = get_me(c, toks["ada"])["balance"]
    bob_bal = get_me(c, toks["bob"])["balance"]
    feed_before = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    expect_error(make_payment(c, toks["ada"], "bob", 100001, "isf-1"),
                 409, "insufficient_funds")
    eq(get_me(c, toks["ada"])["balance"], ada_bal, "sender unchanged on failure (R58)")
    eq(get_me(c, toks["bob"])["balance"], bob_bal, "receiver unchanged on failure (R58)")
    feed_after = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq(feed_after, feed_before, "failed payment leaves no trace (R58)")


def test_concurrent_same_sender_never_negative(c):
    # R2/R58: 20 concurrent payments of 600 from a 10000 wallet: exactly 16
    # succeed (9600 total), 4 get 409, final balance 400 and never negative.
    users = [
        {"id": "u_drain", "email": "drain@example.com", "password": "correct horse",
         "display_name": "Drain", "handle": "drain", "balance": 10000},
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 100000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 50000},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 0},
    ]
    c.reset({"currency": "EUR", "minor_units": 2, "users": users,
             "payments": [], "requests": []})
    drain = c.token_for("drain")
    receivers = ["ada", "bob", "cy"]
    results = run_concurrently([
        (lambda i=i: make_payment(c, drain, receivers[i % 3], 600, f"drain-{i}"))
        for i in range(20)
    ])
    codes = [r.status for r in results]
    eq(codes.count(201), 16, "exactly 16 payments fit the balance (R2)")
    eq(codes.count(409), 4, "the rest are 409 insufficient_funds")
    eq(get_me(c, drain)["balance"], 400, "final balance exact, never negative (R2)")
    total_in = sum(get_me(c, c.token_for(h))["balance"] for h in receivers)
    eq(total_in, 100000 + 50000 + 9600, "conservation holds (R1)")
    feed = expect_ok(c.get("/activity", token=drain), 200)["payments"]
    eq(sum(p["amount"] for p in feed), 9600, "ledger total equals debits (R1)")