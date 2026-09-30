"""Atomic net settlements (§11: R86-R93, A9)."""
from client import (check, eq, expect_error, expect_ok, fresh, get_me, RFC3339)


def settle(c, token, transfers, key, extra=None):
    body = {"transfers": transfers}
    if extra:
        body.update(extra)
    return c.post("/settlements", body=body, token=token,
                  headers={"Idempotency-Key": key})


def t(from_handle, to_handle, amount, note=None, visibility=None):
    d = {"from_handle": from_handle, "to_handle": to_handle, "amount": amount}
    if note is not None:
        d["note"] = note
    if visibility is not None:
        d["visibility"] = visibility
    return d


def test_settlement_happy_shape(c):
    toks = fresh(c, operator=True)
    r = expect_ok(settle(c, toks["op"],
                         [t("ada", "bob", 100), t("bob", "cy", 50)], "st-1"), 201)
    eq(set(r.keys()), {"settlement_id", "committed_at", "payments"},
       "settlement 201 exact top-level shape (R91)")
    check(RFC3339.match(r["committed_at"]),
          f"committed_at RFC3339: {r['committed_at']!r}")
    eq(len(r["payments"]), 2, "one payment per transfer, in input order")
    for i, p in enumerate(r["payments"]):
        eq(p["from_handle"], ["ada", "bob"][i], "input order")
        eq(p["to_handle"], ["bob", "cy"][i], "input order")
        eq(p["amount"], [100, 50][i], "input order")
        eq(p["settlement_id"], r["settlement_id"], "members linked (R91)")
        check(p["request_id"] is None, "members have null request_id (R91)")
        eq(p["created_at"], r["committed_at"], "member created_at == committed_at (R91)")
        eq(p["note"], "", "default empty note (R87)")
        eq(p["visibility"], "public", "default public (R87)")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 100, "net debits applied")
    eq(get_me(c, toks["bob"])["balance"], 50000 + 100 - 50, "net credits applied")
    eq(get_me(c, toks["cy"])["balance"], 50, "receiver credited")
    # Ordinary payments expose settlement_id null (R56/R91).
    p = expect_ok(make_pay(c, toks["ada"], "bob", 10), 201)
    check(p["settlement_id"] is None, "nonmember exposes null settlement_id (R91)")


def make_pay(c, token, to_handle, amount):
    return c.post("/payments", body={"to_handle": to_handle, "amount": amount},
                  token=token, headers={"Idempotency-Key": f"mp-{token[:8]}-{amount}"})


def test_operator_permissions(c):
    toks = fresh(c, operator=True)
    expect_error(c.post("/settlements",
                        body={"transfers": [t("ada", "bob", 10)]},
                        headers={"Idempotency-Key": "st-noauth"}), 401,
                 "unauthenticated")
    expect_error(settle(c, toks["ada"], [t("ada", "bob", 10)], "st-2"), 403, "forbidden", "non-operator (R88)")
    # Operator permission does not grant access to others' requests/private feed.
    rq = expect_ok(c.post("/requests", body={"payer_handle": "bob", "amount": 10},
                          token=toks["ada"], headers={"Idempotency-Key": "perm-1"}),
                   201)
    out = expect_ok(c.get("/requests", token=toks["op"]), 200)["requests"]
    check(all(x["request_id"] != rq["request_id"] for x in out),
          "operator sees only own requests (R86)")
    expect_ok(make_pay(c, toks["ada"], "bob", 30), 201)
    expect_ok(c.post("/payments",
                     body={"to_handle": "bob", "amount": 20, "visibility": "private"},
                     token=toks["ada"], headers={"Idempotency-Key": "perm-2"}),
              201, "private payment")
    feed = expect_ok(c.get("/activity", token=toks["op"]), 200)["payments"]
    check(all(p["visibility"] == "public" or p["from_handle"] == "op"
              or p["to_handle"] == "op" for p in feed),
          "operator's feed follows the ordinary contract (R86)")


def test_transfers_bounds_and_shape(c):
    toks = fresh(c, operator=True)
    op = toks["op"]
    expect_error(settle(c, op, [], "b-1"), 422, "validation_failed",
                 "zero transfers (R87)")
    expect_error(settle(c, op, [t("ada", "bob", 1)] * 33, "b-2"), 422,
                 "validation_failed", "33 transfers rejected (R87)")
    r = settle(c, op, [t("ada", "bob", 1)] * 32, "b-3")
    eq(r.status, 201, "32 transfers accepted (R87 boundary)")
    # A9: wrong-typed batch shape is 422, not 400.
    for i, raw in enumerate(('{"transfers":"x"}', '{"transfers":[1]}',
                             '{"transfers":[{"from_handle":5,"to_handle":"bob","amount":1}]}',
                             '{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":"1"}]}',
                             '{"transfers":[{"to_handle":"bob","amount":1}]}',
                             '{"transfers":[{"from_handle":"ada","amount":1}]}')):
        r = c.post("/settlements", raw_body=raw, token=op,
                   headers={"Idempotency-Key": f"shape-{i}"})
        expect_error(r, 422, "validation_failed", f"malformed batch shape {raw} (A9/R88)")
    r = c.post("/settlements", body={"amount": 10}, token=op,
               headers={"Idempotency-Key": "shape-missing"})
    expect_error(r, 422, "validation_failed", "missing transfers (R88)")


def test_entry_rules_and_defaults(c):
    toks = fresh(c, operator=True)
    op = toks["op"]
    expect_error(settle(c, op, [t("ada", "nobody", 10)], "e-1"), 404,
                 "not_found", "unknown handle")
    expect_error(settle(c, op, [t("ada", "ada", 10)], "e-2"), 422, "self_payment")
    expect_error(settle(c, op, [t("ada", "bob", 0)], "e-3"), 422,
                 "validation_failed", "amount 0")
    expect_error(settle(c, op, [t("ada", "bob", 10, note="n" * 201)], "e-3"), 422,
                 "validation_failed", "long note")
    expect_error(settle(c, op, [t("ada", "bob", 10, visibility="secret")], "e-4"), 422,
                 "validation_failed", "bad visibility")
    r = expect_ok(c.post("/settlements",
                         body={"transfers": [dict(t("ada", "bob", 10), zzz=1)]},
                         token=op, headers={"Idempotency-Key": "e-5"}), 201)
    check(r["payments"][0]["note"] == "", "unknown entry fields ignored (R88)")


def test_entry_errors_precede_affordability_in_input_order(c):
    toks = fresh(c, operator=True)
    op = toks["op"]
    # Entry 1 is affordable; entry 2 has an unknown handle: 404 wins over any
    # batch-level insufficiency (R88).
    expect_error(settle(c, op, [t("ada", "bob", 100), t("nobody", "cy", 10)], "pre-1"),
                 404, "not_found", "entry error before affordability")
    # First entry's error wins when multiple entries are invalid.
    expect_error(settle(c, op, [t("ada", "ada", 10), t("nobody", "cy", 10)], "pre-2"),
                 422, "self_payment", "reported for entry 1")
    expect_error(settle(c, op, [t("nobody", "cy", 10), t("ada", "ada", 10)], "pre-3"),
                 404, "not_found", "unknown handle reported for entry 1")
    # Entry errors beat batch insufficiency: entry 1 fine, entry 2 unknown
    # handle, batch also collectively unaffordable.
    expect_error(settle(c, op, [t("ada", "bob", 1000000000), t("nobody", "cy", 5)],
                        "pre-4"), 404, "not_found",
                 "entry error precedes insufficient funds (R88)")


def test_net_affordability_not_sequential(c):
    # R89: affordability is computed on each wallet's NET position.
    toks = fresh(c, operator=True)
    op = toks["op"]
    # Sequentially ada would go 100000->20000->(-20000 rejected); net is fine:
    # ada 100000 - 80000 - 40000 + 40000 = 20000, bob 40000-40000 = 0, cy +120000.
    users = [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 100000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 40000},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 0},
        {"id": "u_op", "email": "op@example.com", "password": "correct horse",
         "display_name": "Op", "handle": "op", "balance": 0},
    ]
    c.reset({"currency": "EUR", "minor_units": 2, "users": users, "payments": [],
             "requests": [], "settlement_operator_ids": ["u_op"]})
    op = c.token_for("op")
    r = expect_ok(settle(c, op, [t("ada", "cy", 80000), t("ada", "cy", 40000),
                                 t("bob", "ada", 40000)], "net-1"), 201,
                  "net-affordable batch commits (R89)")
    eq(len(r["payments"]), 3, "all movements committed together")
    eq(get_me(c, c.token_for("ada"))["balance"], 20000, "net position (R89)")
    eq(get_me(c, c.token_for("bob"))["balance"], 0, "net position (R89)")
    eq(get_me(c, c.token_for("cy"))["balance"], 120000, "net position (R89)")


def test_insufficient_collective_all_or_nothing(c):
    toks = fresh(c, operator=True)
    op = toks["op"]
    before = {h: get_me(c, tok)["balance"] for h, tok in toks.items()}
    feed_before = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    # ada nets -100001: unaffordable as a batch (R89).
    expect_error(settle(c, op, [t("ada", "bob", 60000), t("ada", "cy", 40001)],
                        "isf-1"), 409, "insufficient_funds")
    after = {h: get_me(c, tok)["balance"] for h, tok in toks.items()}
    eq(after, before, "no wallet changed on failed settlement (R90)")
    feed_after = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq(feed_after, feed_before, "no payments created on failure (R90)")
    # Failed attempt claimed no idempotency key (R90/R51).
    r = settle(c, op, [t("ada", "bob", 10)], "isf-1")
    eq(r.status, 201, "key freed after failed settlement (R90)")


def test_settlement_replay(c):
    toks = fresh(c, operator=True)
    op = toks["op"]
    r1 = expect_ok(settle(c, op, [t("ada", "bob", 100)], "rep-1"), 201)
    r2 = c.post("/settlements", body={"transfers": [t("ada", "bob", 100)]},
                token=op, headers={"Idempotency-Key": "rep-1"})
    eq(r2.status, 200, "replay 200 (R92)")
    eq(r2.json(), r1, "original complete response (R92)")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 100, "no additional movement")


def test_settlement_feed_visibility(c):
    # R92: constituents follow ordinary activity-feed visibility.
    toks = fresh(c, operator=True)
    r = expect_ok(settle(c, toks["op"], [t("ada", "bob", 100, visibility="private")],
                         "vis-1"), 201)
    member_id = r["payments"][0]["payment_id"]
    check(member_id in [p["payment_id"] for p in expect_ok(
        c.get("/activity", token=toks["ada"]), 200)["payments"]],
        "member visible to sender")
    check(member_id in [p["payment_id"] for p in expect_ok(
        c.get("/activity", token=toks["bob"]), 200)["payments"]],
        "member visible to receiver")
    check(member_id not in [p["payment_id"] for p in expect_ok(
        c.get("/activity", token=toks["cy"]), 200)["payments"]],
        "private member hidden from third party (R92)")


def test_settlement_operator_id_in_fixture_default(c):
    # R86: settlement_operator_ids defaults to [] — nobody may settle.
    toks = fresh(c)
    r = c.post("/settlements", body={"transfers": [t("ada", "bob", 10)]},
               token=toks["ada"], headers={"Idempotency-Key": "dflt-1"})
    expect_error(r, 403, "forbidden", "no operator permission by default (R86)")