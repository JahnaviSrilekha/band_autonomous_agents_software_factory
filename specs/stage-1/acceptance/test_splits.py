"""Splits and the §9 rounding table (R71-R77)."""
from client import (check, eq, expect_error, expect_ok, fresh, get_me, fuser,
                    fixture)


def split(c, token, amount, handles, key, note=None):
    body = {"amount": amount, "participant_handles": handles}
    if note is not None:
        body["note"] = note
    return c.post("/splits", body=body, token=token,
                  headers={"Idempotency-Key": key})


SPLIT_KEYS = {"split_id", "amount", "currency", "note", "shares", "requests",
              "created_at"}


def test_split_shape_and_request_creation(c):
    toks = fresh(c)
    r = expect_ok(split(c, toks["ada"], 3000, ["ada", "bob", "cy"], "sp-shape-1",
                        note="dinner"), 201)
    eq(set(r.keys()), SPLIT_KEYS, "split 201 exact shape (R72)")
    eq(r["amount"], 3000, "amount echo")
    eq(r["currency"], "EUR", "currency echo")
    eq(r["note"], "dinner", "note echo")
    eq(r["shares"], [{"handle": "ada", "amount": 1000},
                     {"handle": "bob", "amount": 1000},
                     {"handle": "cy", "amount": 1000}],
       "shares cover every participant in given order, sum to amount (R72)")
    eq([rq["payer_handle"] for rq in r["requests"]], ["bob", "cy"],
       "one request per non-caller participant, same order (R71/R72)")
    for rq in r["requests"]:
        eq(rq["requester_handle"], "ada", "caller is requester")
        eq(rq["status"], "pending", "split requests pending (R71)")
        eq(rq["amount"], 1000, "request amount equals share")


def test_split_caller_omitted(c):
    toks = fresh(c)
    r = expect_ok(split(c, toks["ada"], 2000, ["bob", "cy"], "sp-omit-1"), 201)
    eq([s["handle"] for s in r["shares"]], ["bob", "cy"], "shares as given")
    eq([rq["payer_handle"] for rq in r["requests"]], ["bob", "cy"],
       "requests for both participants")


def test_split_caller_only_valid(c):
    # R74: a split whose only participant is the caller is valid.
    toks = fresh(c)
    r = expect_ok(split(c, toks["ada"], 500, ["ada"], "sp-only-1"), 201)
    eq(r["shares"], [{"handle": "ada", "amount": 500}], "one share")
    eq(r["requests"], [], "zero requests (R74)")


def test_split_no_balance_checks(c):
    # R74: nothing about a split checks anyone's balance.
    toks = fresh(c)
    r = expect_ok(split(c, toks["cy"], 1000000000, ["cy", "ada", "bob"], "sp-nobal-1"),
                  201, "split by broke caller for huge amount")
    eq(len(r["requests"]), 2, "requests created without balance checks")


def test_rounding_table_exact(c):
    # §9 table, all five rows exactly (R76).
    toks = fresh(c)
    rows = [
        (1000, ["ada", "bob", "cy"], [334, 333, 333]),
        (1, ["ada", "bob", "cy"], [1, 0, 0]),
        (10, ["ada", "bob", "cy"], [4, 3, 3]),
        (999, ["ada", "bob", "cy"], [333, 333, 333]),
    ]
    for i, (amount, handles, want) in enumerate(rows):
        r = expect_ok(split(c, toks["ada"], amount, handles, f"rnd-{i}"), 201)
        eq([s["amount"] for s in r["shares"]], want,
           f"rounding row amount={amount} (R76)")
        eq(sum(s["amount"] for s in r["shares"]), amount, "shares sum to amount")
    # 5/5 row needs five participants.
    users = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 50000),
             fuser("u_cy", "cy", 0), fuser("u_d", "d", 0), fuser("u_e", "e", 0)]
    toks = fresh(c, users=users)
    r = expect_ok(split(c, toks["ada"], 5, ["ada", "bob", "cy", "d", "e"], "rnd-4"),
                  201)
    eq([s["amount"] for s in r["shares"]], [1, 1, 1, 1, 1],
       "rounding row amount=5 n=5 (R76)")


def test_zero_share_still_creates_request(c):
    # R76: a share of 0 is legal and still produces a request.
    toks = fresh(c)
    r = expect_ok(split(c, toks["ada"], 1, ["ada", "bob", "cy"], "zero-1"), 201)
    eq([s["amount"] for s in r["shares"]], [1, 0, 0], "row 1/3")
    eq(len(r["requests"]), 2, "both non-caller participants get requests")
    eq(r["requests"][1]["payer_handle"], "cy", "cy request exists despite 0 share")
    eq(r["requests"][1]["amount"], 0, "zero-share request amount 0")


def test_split_error_table(c):
    toks = fresh(c)
    expect_error(split(c, toks["ada"], 0, ["bob"], "spe-1"), 422, "amount 0 (R73)")
    expect_error(split(c, toks["ada"], 1000000001, ["bob"], "spe-2"), 422,
                 "amount > 1e9 (R73)")
    expect_error(split(c, toks["ada"], "100", ["bob"], "spe-3"), 422,
                 "string amount (R73/R38)")
    expect_error(split(c, toks["ada"], 100, [], "spe-4"), 422,
                 "empty participant_handles (R73)")
    expect_error(split(c, toks["ada"], 100, ["bob", "bob"], "spe-5"), 422,
                 "duplicate handle (R73)")
    expect_error(split(c, toks["ada"], 100, ["bob", "nobody"], "spe-6"), 404,
                 "unknown handle (R73)")
    expect_error(split(c, toks["ada"], 100, ["bob"], "spe-7", note="n" * 201), 422,
                 "long note (R73)")
    r = c.post("/splits", raw_body='{"amount":10,"participant_handles":[5]}',
               token=toks["ada"], headers={"Idempotency-Key": "spe-8"})
    expect_error(r, 400, "non-string handle entries are wrong JSON type (R40)")


def test_split_order_dependence(c):
    # R77: the extra unit goes to the first participant in list order.
    toks = fresh(c)
    r1 = expect_ok(split(c, toks["ada"], 1000, ["ada", "bob", "cy"], "ordp-1"), 201)
    eq([s["amount"] for s in r1["shares"]], [334, 333, 333], "ada first gets extra")
    r2 = expect_ok(split(c, toks["ada"], 1000, ["cy", "bob", "ada"], "ordp-2"), 201)
    eq([s["amount"] for s in r2["shares"]], [334, 333, 333], "row shape")
    eq(r2["shares"][0]["handle"], "cy", "cy first gets the extra unit (R77)")


def test_split_shares_independent(c):
    # R77: each split's shares are independent of previous splits.
    toks = fresh(c)
    r1 = expect_ok(split(c, toks["ada"], 1000, ["ada", "bob", "cy"], "ind-1"), 201)
    r2 = expect_ok(split(c, toks["ada"], 1000, ["ada", "bob", "cy"], "ind-2"), 201)
    eq(r2["shares"], r1["shares"], "identical inputs give identical shares again")


def test_split_idempotent_replay(c):
    toks = fresh(c)
    r1 = expect_ok(split(c, toks["ada"], 300, ["ada", "bob"], "idem-1"), 201)
    r2 = c.post("/splits", body={"amount": 300, "participant_handles": ["ada", "bob"]},
                token=toks["ada"], headers={"Idempotency-Key": "idem-1"})
    eq(r2.status, 200, "replay 200")
    eq(r2.json(), r1, "original split body (R51)")
    out = expect_ok(c.get("/requests?direction=incoming", token=toks["bob"]), 200)
    eq(len(out["requests"]), 1, "no duplicate request from replay")


def test_conservation_after_paying_splits(c):
    # R77: after any number of splits have been paid in full, wallet balances
    # still sum exactly to the seeded total.
    toks = fresh(c)
    seeded_total = sum(u["balance"] for u in [
        {"balance": 100000}, {"balance": 50000}, {"balance": 0}])
    r1 = expect_ok(split(c, toks["ada"], 1000, ["ada", "bob", "cy"], "cons-1"), 201)
    r2 = expect_ok(split(c, toks["bob"], 10, ["ada", "bob", "cy"], "cons-2"), 201)
    for rq in r1["requests"] + r2["requests"]:
        expect_ok(c.post(f"/requests/{rq['request_id']}/pay", body={},
                         token=c.token_for(rq["payer_handle"]),
                         headers={"Idempotency-Key": f"cons-pay-{rq['request_id']}"}),
                  201, "pay split request")
        expect_ok(c.post(f"/requests/{rq['request_id']}/pay", body={},
                         token=c.token_for(rq["payer_handle"]),
                         headers={"Idempotency-Key": f"cons-pay-{rq['request_id']}"}),
                  200, "replay is a no-op")
    total = get_me(c, toks["ada"])["balance"] + get_me(c, toks["bob"])["balance"] \
        + get_me(c, toks["cy"])["balance"]
    eq(total, seeded_total, "balances sum to seeded total after paid splits (R77/R1)")