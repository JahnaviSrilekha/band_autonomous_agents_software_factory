"""Stage-2 acceptance: how the existing stage-1 endpoints change (R120,
R124-R128) — funds checked against `available`, no holds from payments,
request-pay immediate, splits untouched."""
from client import (
    check, eq, expect_error, expect_ok, get_me, fauthz,
    afresh, fresh, make_payment, create_authz,
)


def test_r126_payments_check_available(c):
    toks = afresh(c, users=None, authorizations=[
        fauthz("a_h1", "u_ada", "u_bob", 6000)])  # ada: total 100000, available 94000
    expect_error(make_payment(c, toks["ada"], "bob", 94001, "k-av1"), 409,
                 "insufficient_funds", "payment above available (R126)")
    expect_ok(make_payment(c, toks["ada"], "bob", 94000, "k-av2"), 201,
              "payment up to available succeeds")
    expect_error(make_payment(c, toks["ada"], "bob", 1, "k-av3"), 409,
                 "insufficient_funds", "held funds cannot fund payments (R122)")


def test_r126_request_pay_checks_available(c):
    toks = afresh(c, users=None, authorizations=[
        fauthz("a_h2", "u_ada", "u_bob", 6000)])
    rq = expect_ok(c.post("/requests", body={"payer_handle": "ada", "amount": 94001},
                          token=toks["bob"], headers={"Idempotency-Key": "k-rq2"}),
                   201, "request (creation never balance-checks, stage-1 R24)")
    expect_error(c.post(f"/requests/{rq['request_id']}/pay", body={},
                        token=toks["ada"], headers={"Idempotency-Key": "k-rp1"}),
                 409, "insufficient_funds", "pay above available (R126)")
    still = expect_ok(c.get("/requests?direction=incoming", token=toks["ada"]),
                      200, "requests").get("requests", [])
    eq(still[0]["status"], "pending", "refused pay changes nothing (stage-1 R24)")


def test_r126_settlements_check_available_net(c):
    toks = afresh(c, operator=True, authorizations=[
        fauthz("a_h3", "u_ada", "u_bob", 6000)])  # ada available 94000, bob 50000
    expect_error(c.post("/settlements", body={"transfers": [
        {"from_handle": "ada", "to_handle": "cy", "amount": 94001}]},
        token=toks["op"], headers={"Idempotency-Key": "k-s10"}), 409,
        "insufficient_funds", "net debit above available (R126)")
    expect_ok(c.post("/settlements", body={"transfers": [
        {"from_handle": "ada", "to_handle": "cy", "amount": 94000},
        {"from_handle": "bob", "to_handle": "ada", "amount": 50000}]},
        token=toks["op"], headers={"Idempotency-Key": "k-s11"}), 201,
        "net-affordable settlement against available")


def test_r125_payments_never_leave_holds(c):
    toks = afresh(c)
    lists_before = {h: expect_ok(c.get("/authorizations", token=t), 200, "list")
                    for h, t in toks.items()}
    held_before = {h: get_me(c, t)["held"] for h, t in toks.items()}
    expect_ok(make_payment(c, toks["ada"], "bob", 1000, "k-nh1"), 201, "payment")
    for h, t in toks.items():
        after = expect_ok(c.get("/authorizations", token=t), 200, "list")
        eq(after["authorizations"], lists_before[h]["authorizations"],
           f"{h}: payment created no authorization entry (R125)")
        eq(get_me(c, t)["held"], held_before[h], f"{h}: held unchanged (R125)")


def test_r127_request_pay_immediate_no_authorize(c):
    toks = afresh(c)
    rq = expect_ok(c.post("/requests", body={"payer_handle": "ada", "amount": 500},
                          token=toks["bob"], headers={"Idempotency-Key": "k-rq3"}),
                   201, "request")
    bob_total = get_me(c, toks["bob"])["total"]
    pay = expect_ok(c.post(f"/requests/{rq['request_id']}/pay", body={},
                           token=toks["ada"], headers={"Idempotency-Key": "k-rp2"}),
                    201, "pay")
    eq(get_me(c, toks["bob"])["total"], bob_total + 500,
       "paying a request moves money immediately (R127)")
    eq(pay["request_id"], rq["request_id"], "")
    r = c.post(f"/requests/{rq['request_id']}/authorize", body={},
               token=toks["ada"], headers={"Idempotency-Key": "k-az1"})
    check(r.status in (404, 405),
          f"authorizing a request is out of scope (R127), got {r.status}")


def test_r128_splits_unchanged_no_balance_check(c):
    toks = afresh(c)  # cy balance 0
    sp = expect_ok(c.post("/splits", body={
        "amount": 999, "participant_handles": ["cy", "ada", "bob"]},
        token=toks["cy"], headers={"Idempotency-Key": "k-sp1"}), 201,
        "split from a zero-balance caller (stage-1 R74, unchanged R128)")
    eq([s["amount"] for s in sp["shares"]], [334, 333, 332],
       "stage-1 §9 rounding rule unchanged (R128)")
    eq(len(sp["requests"]), 2, "one request per participant except caller")


def test_r124_no_holds_behavior_unchanged(c):
    toks = afresh(c)  # regression in depth via stage-1 modules; spot check here
    me = get_me(c, toks["ada"])
    eq((me["balance"], me["total"], me["available"], me["held"]),
       (100000, 100000, 100000, 0), "no open holds: all agree (R124)")
    expect_ok(make_payment(c, toks["ada"], "bob", 100000, "k-all"), 201,
              "full-balance payment fine with no holds")
    expect_error(make_payment(c, toks["ada"], "bob", 1, "k-over"), 409,
                 "insufficient_funds", "stage-1 funds rule unchanged at zero holds")