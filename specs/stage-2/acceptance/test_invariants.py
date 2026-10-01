"""Stage-2 money invariants under concurrency (R121-R123, R157 + stage-1 R1-R3,
rounding table). Drives the running service with up to 50 requests in flight
and asserts every invariant after each wave."""
import random
import time

from client import (
    check, eq, expect_ok, get_me, fauthz, afresh, make_payment, create_authz,
    capture, void_authz, run_concurrently,
)

STORM_USERS = [
    dict(id="u_ada", email="ada@example.com", password="correct horse",
         display_name="Ada", handle="ada", balance=800000),
    dict(id="u_bob", email="bob@example.com", password="correct horse",
         display_name="Bob", handle="bob", balance=800000),
    dict(id="u_cy", email="cy@example.com", password="correct horse",
         display_name="Cy", handle="cy", balance=800000),
    dict(id="u_dee", email="dee@example.com", password="correct horse",
         display_name="Dee", handle="dee", balance=800000),
    dict(id="u_ell", email="ell@example.com", password="correct horse",
         display_name="Ell", handle="ell", balance=800000),
    dict(id="u_op", email="op@example.com", password="correct horse",
         display_name="Op", handle="op", balance=100000),
]
HANDLES = ["ada", "bob", "cy", "dee", "ell"]
SEED_SUM = sum(u["balance"] for u in STORM_USERS)


def _no5xx(resp, what):
    check(resp.status < 500, f"{what}: server error HTTP {resp.status}: {resp.raw[:200]!r}")
    return resp


def _assert_state_invariants(c, toks):
    """R121 conservation, R122 available>=0/held>=0, R123 captures<=amount,
    stage-1 R2 — over the whole wallet set and authorization table."""
    totals = {}
    for h, t in toks.items():
        me = expect_ok(_no5xx(c.get("/me", token=t), f"me {h}"), 200, "me")
        check(me["total"] >= 0, f"{h}: negative total")
        eq(me["available"], me["total"] - me["held"],
           f"{h}: available = total - held (R122)")
        check(me["available"] >= 0, f"{h}: available negative (R122)")
        check(me["held"] >= 0, f"{h}: negative held")
        totals[h] = me["total"]
    eq(sum(totals.values()), SEED_SUM, "conservation on total (R121)")
    auths = {}
    for h, t in toks.items():
        for direction in ("incoming", "outgoing"):
            page = expect_ok(_no5xx(c.get(f"/authorizations?direction={direction}&limit=200",
                                          token=t), f"list {h}"), 200, "list")
            for a in page["authorizations"]:
                auths[a["authorization_id"]] = a
                check(page["has_more"] in (True, False), "has_more bool")
    for aid, a in auths.items():
        check(a["captured_amount"] <= a["amount"],
              f"{aid}: cumulative captures exceed authorized (R123)")
        check(a["remaining_amount"] >= 0, f"{aid}: negative remaining")
        if a["status"] != "open":
            eq(a["remaining_amount"], 0, f"{aid}: closed holds must release (R123)")
    return auths


def test_r121_r122_r123_r157_mixed_concurrent_storm(c):
    """6 waves x 50 concurrent mixed operations (all seven idempotent write
    paths plus voids, replays, over-captures and reader threads), fixture
    ttl=2 so expiry races the storm (R136 lazy expiry)."""
    toks = afresh(c, users=STORM_USERS, operators=["u_op"], ttl=2)
    rng = random.Random(20260930)
    key_n = [0]
    captured_authz = []  # (aid, payer_handle, receiver_handle) to over-capture

    def new_key():
        key_n[0] += 1
        return f"storm-{key_n[0]}"

    def op_payment(h):
        t = toks[h]
        to = rng.choice([x for x in HANDLES if x != h])
        amt = rng.randint(1, 400)
        return lambda: _no5xx(make_payment(c, t, to, amt, new_key()), "pay")

    def op_payment_replay(h):
        t = toks[h]
        to = rng.choice([x for x in HANDLES if x != h])
        amt = rng.randint(1, 100)
        key = new_key()
        body = {"to_handle": to, "amount": amt}
        def go():
            r1 = _no5xx(c.post("/payments", body=body, token=t,
                               headers={"Idempotency-Key": key}), "pay-replay-1")
            r2 = _no5xx(c.post("/payments", body=body, token=t,
                               headers={"Idempotency-Key": key}), "pay-replay-2")
            check(r1.status in (200, 201, 409), "replay first leg")
            if r1.status in (200, 201):
                eq(r2.status, 200 if r1.status == 201 else r1.status, "replay leg")
                eq(r2.json(), r1.json(), "identical replay body")
        return go

    def op_request(h):
        t = toks[h]
        payer = rng.choice([x for x in HANDLES if x != h])
        amt = rng.randint(1, 300)
        return lambda: _no5xx(c.post("/requests", body={
            "payer_handle": payer, "amount": amt}, token=t,
            headers={"Idempotency-Key": new_key()}), "request")

    def op_pay_request(h):
        t = toks[h]
        def go():
            page = _no5xx(c.get("/requests?direction=incoming&status=pending&limit=5",
                                token=t), "list")
            for rq in expect_ok(page, 200, "list")["requests"]:
                r = _no5xx(c.post(f"/requests/{rq['request_id']}/pay", body={},
                                  token=t, headers={"Idempotency-Key": new_key()}),
                           "request-pay")
                check(r.status < 500, "request-pay 5xx")
                if r.status == 201:
                    return
        return go

    def op_decline_or_cancel(h):
        t = toks[h]
        def go():
            direction = "incoming" if rng.random() < 0.5 else "outgoing"
            page = _no5xx(c.get(f"/requests?direction={direction}&status=pending&limit=5",
                                token=t), "list")
            for rq in expect_ok(page, 200, "list")["requests"]:
                rid = rq["request_id"]
                if direction == "incoming":
                    action = "decline" if rng.random() < 0.5 else "pay"
                else:
                    action = "cancel"
                r = _no5xx(c.post(f"/requests/{rid}/{action}", body={}, token=t),
                           action)
                check(r.status < 500, f"{action} 5xx")
                return
        return go

    def op_split(h):
        t = toks[h]
        others = [x for x in HANDLES if x != h]
        participants = [h] + rng.sample(others, rng.randint(1, 3))
        amt = rng.randint(1, 500)
        return lambda: _no5xx(c.post("/splits", body={
            "amount": amt, "participant_handles": participants}, token=t,
            headers={"Idempotency-Key": new_key()}), "split")

    def op_settlement(h):
        t = toks[h]
        a, b = rng.sample(HANDLES, 2)
        return lambda: _no5xx(c.post("/settlements", body={"transfers": [
            {"from_handle": a, "to_handle": b, "amount": rng.randint(1, 200)}]},
            token=t, headers={"Idempotency-Key": new_key()}), "settlement")

    def op_authorize(h):
        t = toks[h]
        to = rng.choice([x for x in HANDLES if x != h])
        amt = rng.randint(1, 800)
        def go():
            r = _no5xx(create_authz(c, t, to, amt, new_key()), "authorize")
            if r.status == 201:
                captured_authz.append((r.json()["authorization_id"], h, to))
            check(r.status in (200, 201, 409, 422, 404), "authorize status")
        return go

    def op_capture(h):
        t = toks[h]
        def go():
            page = _no5xx(c.get("/authorizations?direction=incoming&status=open&limit=5",
                                token=t), "list")
            for a in expect_ok(page, 200, "list")["authorizations"]:
                body = {"final": rng.random() < 0.4}
                if rng.random() < 0.5:
                    body["amount"] = rng.randint(1, max(1, a["remaining_amount"]))
                r = _no5xx(capture(c, t, a["authorization_id"], new_key(), body),
                           "capture")
                check(r.status in (200, 201, 409, 422), "capture status")
                return
        return go

    def op_capture_over(h):
        if not captured_authz:
            return op_authorize(h)
        aid, payer, receiver = captured_authz[rng.randrange(len(captured_authz))]
        t = toks[receiver]
        return lambda: check(_no5xx(capture(c, t, aid, new_key(),
                                            {"amount": 900000}), "capture-over").status
                             in (409, 422, 200, 201), "capture-over status")

    def op_void(h):
        t = toks[h]
        def go():
            page = _no5xx(c.get("/authorizations?direction=outgoing&status=open&limit=5",
                                token=t), "list")
            for a in expect_ok(page, 200, "list")["authorizations"]:
                r = _no5xx(void_authz(c, t, a["authorization_id"]), "void")
                check(r.status in (200, 409), "void status")
                return
        return go

    def op_reader(h):
        t = toks[h]
        def go():
            me = expect_ok(_no5xx(c.get("/me", token=t), "reader"), 200, "me")
            check(me["available"] >= 0, "reader: available negative (R122)")
            eq(me["available"], me["total"] - me["held"], "reader: derivation")
        return go

    OPS = [op_payment, op_payment_replay, op_request, op_pay_request,
           op_decline_or_cancel, op_split, op_settlement, op_authorize,
           op_capture, op_capture_over, op_void, op_reader]
    weights = [12, 4, 6, 5, 4, 3, 3, 6, 5, 2, 3, 7]
    for wave in range(6):
        fns = []
        for i in range(50):
            pick = rng.choices(OPS, weights=weights)[0]
            fns.append(pick(HANDLES[i % len(HANDLES)]))
        run_concurrently(fns)
        _assert_state_invariants(c, toks)  # invariants after every wave (R157)
    # storm leaves a fully consistent state
    _assert_state_invariants(c, toks)


def test_r3_r52_r157_concurrent_identical_exactly_once_seven_paths(c):
    """For each of the seven idempotent write paths: 50 concurrent identical
    (key, body) requests → exactly one 201, others 200, identical bodies, and
    the effect happens exactly once."""
    users = [dict(u) for u in STORM_USERS]
    toks = afresh(c, users=users, operators=["u_op"], ttl=600)
    N = 50
    ada, bob, op = toks["ada"], toks["bob"], toks["op"]

    def burst(fn):
        results = run_concurrently([lambda i=i: fn(i) for i in range(N)])
        statuses = [r.status for r in results]
        eq(statuses.count(201), 1, f"exactly one 201 (statuses {statuses})")
        check(all(s in (200, 201) for s in statuses), f"no other statuses: {statuses}")
        bodies = [r.json() for r in results]
        check(all(b == bodies[0] for b in bodies), "all replay bodies identical")
        return bodies[0]

    # 1. POST /payments
    burst(lambda i: c.post("/payments", body={"to_handle": "bob", "amount": 300},
                           token=ada, headers={"Idempotency-Key": "eo-pay"}))
    eq(get_me(c, toks["bob"])["total"], 800000 + 300, "money moved exactly once")

    # 2. POST /requests
    burst(lambda i: c.post("/requests", body={"payer_handle": "ada", "amount": 120},
                           token=bob, headers={"Idempotency-Key": "eo-req"}))
    rqs = expect_ok(c.get("/requests?direction=outgoing", token=bob), 200, "")
    eq(len([r for r in rqs["requests"] if r["amount"] == 120]), 1,
       "exactly one request created")

    # 3. POST /requests/{id}/pay
    rid = rqs["requests"][0]["request_id"]
    burst(lambda i: c.post(f"/requests/{rid}/pay", body={},
                           token=ada, headers={"Idempotency-Key": "eo-rpay"}))
    eq(get_me(c, toks["bob"])["total"], 800000 + 300 + 120, "request paid exactly once")
    rqs = expect_ok(c.get("/requests?direction=outgoing", token=bob), 200, "")
    eq([r["status"] for r in rqs["requests"] if r["request_id"] == rid][0],
       "paid", "request paid once")

    # 4. POST /splits
    burst(lambda i: c.post("/splits", body={
        "amount": 300, "participant_handles": ["ada", "bob", "cy"]},
        token=ada, headers={"Idempotency-Key": "eo-split"}))
    page = expect_ok(c.get("/requests?direction=outgoing&limit=200", token=ada),
                     200, "")
    eq(len([r for r in page["requests"] if r["note"] == "" and r["amount"] == 100
            and r["payer_handle"] in ("bob", "cy")]), 2,
       "split created its requests exactly once")

    # 5. POST /settlements
    burst(lambda i: c.post("/settlements", body={"transfers": [
        {"from_handle": "dee", "to_handle": "ell", "amount": 75}]},
        token=op, headers={"Idempotency-Key": "eo-settle"}))
    eq(get_me(c, toks["ell"])["total"], 800000 + 75, "settlement moved money once")

    # 6. POST /authorizations
    burst(lambda i: c.post("/authorizations", body={"to_handle": "bob", "amount": 600},
                           token=ada, headers={"Idempotency-Key": "eo-authz"}))
    outs = expect_ok(c.get("/authorizations?direction=outgoing", token=ada),
                     200, "")["authorizations"]
    eq(len([a for a in outs if a["amount"] == 600]), 1, "one authorization created")
    eq(get_me(c, toks["ada"])["held"], 600, "hold placed exactly once")
    aid = [a for a in outs if a["amount"] == 600][0]["authorization_id"]

    # 7. POST /authorizations/{id}/capture
    burst(lambda i: c.post(f"/authorizations/{aid}/capture",
                           body={"amount": 250, "final": False},
                           token=bob, headers={"Idempotency-Key": "eo-cap"}))
    eq(get_me(c, toks["bob"])["total"], 800000 + 300 + 120 + 250, "captured money moved once")
    a = [a for a in expect_ok(c.get("/authorizations", token=ada), 200, "")
         ["authorizations"] if a["authorization_id"] == aid][0]
    eq(a["captured_amount"], 250, "captured once (R123)")
    eq(len(a["payment_ids"]), 1, "one capture payment")


def test_r123_r157_concurrent_capture_oversubscribe(c):
    toks = afresh(c, users=[dict(u) for u in STORM_USERS])
    auth = expect_ok(create_authz(c, toks["ada"], "bob", 1000, "ov-a"), 201, "authz")
    aid = auth["authorization_id"]
    N = 50
    results = run_concurrently([
        lambda i=i: capture(c, toks["bob"], aid, f"ov-{i}", {"amount": 300, "final": False})
        for i in range(N)])
    ok = [r for r in results if r.status == 201]
    exceeded = [r for r in results if r.status == 422]
    closed = [r for r in results if r.status == 409]
    eq(len(ok) + len(exceeded) + len(closed), N, "only 2xx/409/422 outcomes")
    eq(len(ok), 3, "300x4 > 1000, so exactly three partial captures succeed (final:false)")
    eq(len(exceeded), N - 3, "rest rejected capture_exceeds_authorization")
    a = [a for a in expect_ok(c.get("/authorizations", token=toks["ada"]), 200, "")
         ["authorizations"] if a["authorization_id"] == aid][0]
    eq(a["captured_amount"], 900, "cumulative captures bounded by amount (R123)")
    eq(len(a["payment_ids"]), 3, "each idempotent capture moved money once")
    eq(a["remaining_amount"], 100, "remainder still held (final:false)")
    eq(get_me(c, toks["bob"])["total"], 800000 + 900, "conservation")


def test_r121_r122_concurrent_authorize_vs_spend(c):
    """Authorizations and payments racing the same wallet: every debit passes
    only if available allows it at that instant (R122), and holds never move
    money (R121)."""
    toks = afresh(c, users=[dict(u) for u in STORM_USERS], ttl=1)
    N = 40
    fns = []
    for i in range(N):
        if i % 2 == 0:
            fns.append(lambda i=i: check(
                _no5xx(create_authz(c, toks["ada"], "bob", 20000, f"rz-{i}"),
                       "authz").status in (200, 201, 409, 422, 404), "authz status"))
        else:
            fns.append(lambda i=i: check(
                _no5xx(make_payment(c, toks["ada"], "bob", 20000, f"pm-{i}"),
                       "pay").status in (200, 201, 409, 422, 404), "pay status"))
    run_concurrently(fns)
    me = get_me(c, toks["ada"])
    check(me["available"] >= 0, "available never negative under race (R122)")
    eq(me["available"], me["total"] - me["held"], "identity holds at rest")
    totals = {h: get_me(c, t)["total"] for h, t in toks.items()}
    eq(sum(totals.values()), SEED_SUM, "conservation (R121)")


def test_stage1_r76_rounding_table_unchanged(c):
    toks = afresh(c, users=STORM_USERS)  # five participants + operator
    cases = [
        (1000, ["ada", "bob", "cy"], [334, 333, 333]),
        (1, ["ada", "bob", "cy"], [1, 0, 0]),
        (10, ["ada", "bob", "cy"], [4, 3, 3]),
        (999, ["ada", "bob", "cy"], [333, 333, 333]),
        (5, ["ada", "bob", "cy", "dee", "ell"], [1, 1, 1, 1, 1]),
    ]
    for n, (amount, participants, shares) in enumerate(cases):
        sp = expect_ok(c.post("/splits", body={
            "amount": amount, "participant_handles": participants},
            token=toks["ada"], headers={"Idempotency-Key": f"rd-{n}"}), 201,
            f"rounding case {amount}/{participants}")
        eq([s["amount"] for s in sp["shares"]], shares,
           f"stage-1 §9 table row {amount}/3 (R76, unchanged by stage 2 R128)")