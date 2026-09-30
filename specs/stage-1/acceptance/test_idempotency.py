"""Idempotency (R48-R54, R41 key ranges, A6, A8) across all five write paths."""
import json

from client import (check, eq, expect_error, expect_ok, fresh, get_me,
                    make_payment, payment_body, run_concurrently)


def test_missing_and_empty_key_on_every_write_path(c):
    toks = fresh(c, operator=True)
    op = toks["op"]
    # Create a pending request so /pay has a target.
    rq = expect_ok(c.post("/requests", body={"payer_handle": "op", "amount": 50},
                          token=toks["ada"], headers={"Idempotency-Key": "mk-0"}),
                   201, "seed request")
    pay_path = f"/requests/{rq['request_id']}/pay"
    cases = [
        ("/payments", {"to_handle": "bob", "amount": 100}, toks["ada"]),
        ("/requests", {"payer_handle": "ada", "amount": 100}, toks["bob"]),
        (pay_path, {}, toks["op"]),
        ("/splits", {"amount": 300, "participant_handles": ["ada", "bob"]}, toks["ada"]),
        ("/settlements", {"transfers": [{"from_handle": "op", "to_handle": "bob",
                                         "amount": 10}]}, op),
    ]
    for path, body, tok in cases:
        expect_error(c.post(path, body=body, token=tok),
                     400, f"missing_idempotency_key (no header): {path}")
        expect_error(c.post(path, body=body, token=tok, headers={"Idempotency-Key": ""}),
                     400, f"missing_idempotency_key (empty header): {path}")


def test_first_use_201_replay_200_diff_body_409(c):
    toks = fresh(c)
    r1 = expect_ok(make_payment(c, toks["ada"], "bob", 100, "first-1"), 201, "first use")
    r2 = c.post("/payments", body=payment_body("bob", 100), token=toks["ada"],
                headers={"Idempotency-Key": "first-1"})
    eq(r2.status, 200, "replay is 200 (R51)")
    eq(r2.json(), r1, "replay body identical as a JSON value (R51)")
    r3 = c.post("/payments", body=payment_body("bob", 101), token=toks["ada"],
                headers={"Idempotency-Key": "first-1"})
    expect_error(r3, 409, "idempotency_key_reuse")
    # Original replay still works after the 409.
    r4 = c.post("/payments", body=payment_body("bob", 100), token=toks["ada"],
                headers={"Idempotency-Key": "first-1"})
    eq(r4.status, 200, "original replay still 200 after 409")


def test_key_scoped_per_user(c):
    toks = fresh(c)
    expect_ok(make_payment(c, toks["ada"], "bob", 100, "shared-key"), 201, "ada uses key")
    bob_pays_adam = c.post("/payments", body=payment_body("ada", 100),
                           token=toks["bob"], headers={"Idempotency-Key": "shared-key"})
    eq(bob_pays_adam.status, 201, "same key string for another user is a first use (R49)")


def test_same_key_same_body_other_path_is_first_use(c):
    toks = fresh(c)
    expect_ok(make_payment(c, toks["ada"], "bob", 100, "cross-1"), 201, "on /payments")
    r = c.post("/requests", body={"payer_handle": "bob", "amount": 100},
               token=toks["ada"], headers={"Idempotency-Key": "cross-1"})
    eq(r.status, 201, "same key+body shape on different path succeeds (R50)")


def test_canonical_body_equality(c):
    toks = fresh(c)
    # Key order and whitespace don't matter (R50).
    expect_ok(c.post("/payments", raw_body='{"amount": 100, "to_handle": "bob"}',
                     token=toks["ada"], headers={"Idempotency-Key": "canon-1"}),
              201, "first use")
    r = c.post("/payments",
               raw_body='{  "to_handle" : "bob" ,\n  "amount": 100 }',
               token=toks["ada"], headers={"Idempotency-Key": "canon-1"})
    eq(r.status, 200, "reordered keys / whitespace replay (R50)")
    # 1000, 1000.0 and 1e3 are the same numeric JSON value (R18, R50).
    expect_ok(c.post("/payments", raw_body='{"to_handle":"bob","amount":1000}',
                     token=toks["ada"], headers={"Idempotency-Key": "canon-2"}),
              201, "first use 1000")
    r = c.post("/payments", raw_body='{"to_handle":"bob","amount":1e3}',
               token=toks["ada"], headers={"Idempotency-Key": "canon-2"})
    eq(r.status, 200, "1e3 replays 1000 (R18/R50)")
    r = c.post("/payments", raw_body='{"to_handle":"bob","amount":1000.0}',
               token=toks["ada"], headers={"Idempotency-Key": "canon-2"})
    eq(r.status, 200, "1000.0 replays 1000 (R18/R50)")
    # JSON booleans are NOT the same value as numbers (design §6, JSON-type-aware).
    expect_ok(c.post("/payments",
                     body={"to_handle": "bob", "amount": 100, "zz": 1},
                     token=toks["ada"], headers={"Idempotency-Key": "canon-3"}),
              201, "first use zz=1")
    r = c.post("/payments", raw_body='{"to_handle":"bob","amount":100,"zz":true}',
               token=toks["ada"], headers={"Idempotency-Key": "canon-3"})
    expect_error(r, 409, "idempotency_key_reuse (true != 1)")
    expect_ok(c.post("/payments",
                     body={"to_handle": "bob", "amount": 100, "zz": 0},
                     token=toks["ada"], headers={"Idempotency-Key": "canon-4"}),
              201, "first use zz=0")
    r = c.post("/payments", raw_body='{"to_handle":"bob","amount":100,"zz":false}',
               token=toks["ada"], headers={"Idempotency-Key": "canon-4"})
    expect_error(r, 409, "idempotency_key_reuse (false != 0)")


def test_key_reusable_after_4xx_failure(c):
    toks = fresh(c)
    # 409 failure frees the key (R51 last row).
    r = c.post("/payments", body=payment_body("bob", 10_000_000), token=toks["ada"],
               headers={"Idempotency-Key": "reuse-1"})
    expect_error(r, 409, "insufficient_funds")
    r = c.post("/payments", body=payment_body("bob", 100), token=toks["ada"],
               headers={"Idempotency-Key": "reuse-1"})
    eq(r.status, 201, "key freed after 4xx failure (R51)")
    # 422 failure frees the key too.
    r = c.post("/payments", body=payment_body("bob", 0), token=toks["ada"],
               headers={"Idempotency-Key": "reuse-2"})
    expect_error(r, 422, "validation_failed")
    r = c.post("/payments", body=payment_body("bob", 100), token=toks["ada"],
               headers={"Idempotency-Key": "reuse-2"})
    eq(r.status, 201, "key freed after 422 failure (R51)")


def test_claimed_key_resolved_before_field_validation(c):
    # R54: after parse+auth, an already-claimed key is resolved before endpoint
    # field validation or current-resource checks.
    toks = fresh(c)
    expect_ok(make_payment(c, toks["ada"], "bob", 100, "claim-1"), 201, "claim")
    # Invalid body (amount 0) with the same key: 409, not 422.
    r = c.post("/payments", body=payment_body("bob", 0), token=toks["ada"],
               headers={"Idempotency-Key": "claim-1"})
    expect_error(r, 409, "idempotency_key_reuse before validation (R54)")
    # Unknown-handle body with same key: 409, not 404.
    r = c.post("/payments", body=payment_body("nobody", 100), token=toks["ada"],
               headers={"Idempotency-Key": "claim-1"})
    expect_error(r, 409, "idempotency_key_reuse before resource checks (R54)")
    # Same key, different path, invalid body: different request -> normal validation.
    r = c.post("/requests", body={"payer_handle": "bob", "amount": 0},
               token=toks["ada"], headers={"Idempotency-Key": "claim-1"})
    expect_error(r, 422, "validation_failed (different path not a replay, R50)")


def test_auth_precedes_key_resolution(c):
    # Pipeline order (design §5): parse -> authenticate -> key handling.
    toks = fresh(c)
    r = c.post("/payments", body=payment_body("bob", 100),
               headers={"Idempotency-Key": "auth-1"})
    expect_error(r, 401, "unauthenticated")
    r = c.post("/payments", body=payment_body("bob", 100), token=toks["ada"],
               headers={"Idempotency-Key": "auth-1"})
    eq(r.status, 201, "401 attempt did not consume the key (R54 order)")


def test_non_object_body_400_before_auth_and_key(c):
    # A8: valid JSON that is not an object -> 400 malformed_request, before auth,
    # never claims or frees a key.
    toks = fresh(c)
    for raw in ("[1,2]", '"x"', "5", "null", "true"):
        r = c.post("/payments", raw_body=raw, headers={"Idempotency-Key": "nonobj-1"})
        expect_error(r, 400, f"non-object body {raw} (A8)")
        r = c.post("/payments", raw_body=raw)  # unauthenticated too
        expect_error(r, 400, f"non-object body {raw} before auth (A8)")
    r = c.post("/payments", body=payment_body("bob", 100), token=toks["ada"],
               headers={"Idempotency-Key": "nonobj-1"})
    eq(r.status, 201, "key still fresh after non-object attempts (A8)")


def test_key_length_bounds(c):
    toks = fresh(c)
    k255 = "k" * 255
    r = make_payment(c, toks["ada"], "bob", 100, k255)
    eq(r.status, 201, "255-char key accepted (R41 boundary)")
    r = make_payment(c, toks["ada"], "bob", 100, "k" * 256)
    expect_error(r, 422, "256-char key rejected (R41)")


def test_concurrent_identical_exactly_once(c):
    toks = fresh(c)
    n = 16
    results = run_concurrently([
        (lambda i=i: make_payment(c, toks["ada"], "bob", 500, "race-1"))
        for i in range(n)
    ])
    codes = sorted(r.status for r in results)
    eq(codes.count(201), 1, "exactly one 201 (R52)")
    eq(codes.count(200), n - 1, "all others 200 (R52)")
    bodies = [r.json() for r in results if r.status in (200, 201)]
    first = bodies[0]
    check(all(b == first for b in bodies), "all replay bodies identical (R52)")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 500, "debited exactly once")
    eq(get_me(c, toks["bob"])["balance"], 50000 + 500, "credited exactly once")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq(len(feed), 1, "one payment in the ledger (R52)")


def test_concurrent_same_key_different_body(c):
    toks = fresh(c)
    n = 8
    results = run_concurrently([
        (lambda i=i: make_payment(c, toks["ada"], "bob", 100 + i, "race-2"))
        for i in range(n)
    ])
    codes = [r.status for r in results]
    eq(codes.count(201), 1, "at most one first-use win")
    check(all(s in (200, 201, 409) for s in codes), f"no other codes: {codes}")
    total = sum(r.json()["amount"] for r in results if r.status in (200, 201))
    eq(total, 100, "only the winning body's amount moved (once)")


def test_replay_after_balance_change(c):
    # R53: a successful replay returns the original response and makes no
    # further state changes, even after the resource state changed.
    toks = fresh(c)
    p1 = expect_ok(make_payment(c, toks["ada"], "bob", 1000, "replay-1"), 201)
    expect_ok(make_payment(c, toks["ada"], "bob", 2000, "replay-2"), 201,
              "another real payment")
    bal_ada = get_me(c, toks["ada"])["balance"]
    r = c.post("/payments", body=payment_body("bob", 1000), token=toks["ada"],
               headers={"Idempotency-Key": "replay-1"})
    eq(r.status, 200, "replay 200")
    eq(r.json(), p1, "original body returned (R53)")
    eq(get_me(c, toks["ada"])["balance"], bal_ada, "no further state change (R53)")