"""Reviewer's independent stage-4 stress/invariant probe (final verification).

Runs against a live container (BASE_URL, default localhost:18091) built fresh
from main@169fbe0 via stage-4/RUN.md (docker build --no-cache). Exercises
concurrent, retried and mixed operations (payments, refunds, single and
batch corrections, settlements) with up to 50 in flight and checks the
money invariants: conservation, no negative balance/available/held ever,
exactly-once under concurrent identical-idempotency-key retries,
all-or-nothing on a rejected batch, and the stage-1 rounding table.
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost:18091")
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f": {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def req(method, path, body=None, token=None, headers=None, raw_query=None):
    url = BASE_URL + path + (("?" + raw_query) if raw_query else "")
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def reset(fixture):
    return req("POST", "/_test/reset", fixture)


def login(email):
    s, b = req("POST", "/auth/login", {"email": email, "password": "correct horse"})
    assert s == 200, (s, b)
    return b["token"]


USERS = [
    {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
     "display_name": "Ada", "handle": "ada", "balance": 500000},
    {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
     "display_name": "Bob", "handle": "bob", "balance": 500000},
    {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
     "display_name": "Cy", "handle": "cy", "balance": 500000},
    {"id": "u_op", "email": "op@example.com", "password": "correct horse",
     "display_name": "Op", "handle": "op", "balance": 100},
]
SEEDED_TOTAL = sum(u["balance"] for u in USERS)
FIXTURE = {"currency": "EUR", "minor_units": 2,
           "settlement_operator_ids": ["u_op"], "users": USERS}


def setup():
    s, b = reset(FIXTURE)
    check("reviewer probe: fixture reset 204", s == 204, f"{s} {b}")
    return {u["handle"]: login(u["email"]) for u in USERS}


def totals_and_invariants(label):
    total_sum = 0
    for h in ("ada", "bob", "cy", "op"):
        s, me = req("GET", "/me", token=toks[h])
        check(f"{label}: total >= 0 for {h}", me.get("total", -1) >= 0, me)
        check(f"{label}: available >= 0 for {h}", me.get("available", -1) >= 0, me)
        check(f"{label}: held >= 0 for {h}", me.get("held", 0) >= 0, me)
        total_sum += me.get("total", 0)
    check(f"{label}: conservation holds (sum == {SEEDED_TOTAL})",
          total_sum == SEEDED_TOTAL, f"got {total_sum}")


def test_50_in_flight_mixed_burst():
    global toks
    toks = setup()
    s, p = req("POST", "/payments", {"to_handle": "bob", "amount": 2000,
               "note": "seed", "visibility": "public"},
               token=toks["ada"], headers={"Idempotency-Key": "probe-seed-1"})
    check("probe: seed payment 201", s == 201, (s, p))
    target = p["payment_id"]

    errors_5xx = []
    lock = threading.Lock()

    def record(s):
        if s >= 500:
            with lock:
                errors_5xx.append(s)

    def do_payment(i):
        s, _ = req("POST", "/payments", {"to_handle": "cy", "amount": 15,
                   "note": "burst", "visibility": "public"},
                   token=toks["ada"], headers={"Idempotency-Key": f"probe-burst-pay-{i}"})
        record(s)

    def do_refund(i):
        s, _ = req("POST", f"/payments/{target}/refunds", {"amount": 10},
                   headers={"Authorization": f"Bearer {toks['bob']}",
                            "Idempotency-Key": f"probe-burst-ref-{i}"})
        record(s)

    def do_correction(i):
        s, _ = req("POST", f"/payments/{target}/corrections",
                   {"expected_revision": 1, "amount": 1990,
                    "effective_at": "2026-09-20T12:00:00+00:00", "reason": "x"},
                   token=toks["ada"], headers={"Idempotency-Key": f"probe-burst-corr-{i}"})
        record(s)

    def do_batch(i):
        s, pb = req("POST", "/payments", {"to_handle": "cy", "amount": 300,
                    "note": "batch-target", "visibility": "public"},
                    token=toks["bob"], headers={"Idempotency-Key": f"probe-batch-seed-{i}"})
        if s != 201:
            record(s)
            return
        s, _ = req("POST", "/correction-batches",
                   {"corrections": [{"payment_id": pb["payment_id"], "expected_revision": 1,
                                      "amount": 250, "effective_at": "2026-09-20T12:00:00+00:00",
                                      "reason": "x"}]},
                   token=toks["op"], headers={"Idempotency-Key": f"probe-burst-batch-{i}"})
        record(s)

    def do_settlement(i):
        s, _ = req("POST", "/settlements",
                   {"transfers": [{"from_handle": "cy", "to_handle": "ada", "amount": 5}]},
                   token=toks["op"], headers={"Idempotency-Key": f"probe-burst-settle-{i}"})
        record(s)

    def do_read(i):
        req("GET", "/statement", token=toks["ada"])
        req("GET", "/activity", token=toks["bob"])
        req("GET", "/me", token=toks["cy"])

    workers = []
    for i in range(15):
        workers.append((do_payment, i))
    for i in range(10):
        workers.append((do_refund, i))
    for i in range(10):
        workers.append((do_correction, i))
    for i in range(8):
        workers.append((do_batch, i))
    for i in range(4):
        workers.append((do_settlement, i))
    for i in range(3):
        workers.append((do_read, i))

    threads = [threading.Thread(target=fn, args=(arg,)) for fn, arg in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check("50-in-flight burst: zero 5xx", len(errors_5xx) == 0, errors_5xx)
    totals_and_invariants("post-burst")


def test_exactly_once_under_concurrent_retry():
    global toks
    toks = setup()
    results = []
    lock = threading.Lock()

    def attempt(i):
        s, b = req("POST", "/payments", {"to_handle": "bob", "amount": 777,
                   "note": "once", "visibility": "public"},
                   token=toks["ada"], headers={"Idempotency-Key": "probe-exactly-once"})
        with lock:
            results.append((s, b))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [s for s, _ in results]
    check("exactly-once: all 20 concurrent identical-key requests succeed (201 or 200 replay)",
          all(s in (200, 201) for s in statuses) and statuses.count(201) == 1, statuses)
    payment_ids = {b.get("payment_id") for s, b in results if s == 201}
    check("exactly-once: all responses reference the same single payment",
          len(payment_ids) == 1, payment_ids)
    s, me = req("GET", "/me", token=toks["bob"])
    check("exactly-once: receiver credited exactly once (not 20x)",
          me["total"] == USERS[1]["balance"] + 777, me)


def test_all_or_nothing_on_rejected_batch():
    global toks
    toks = setup()
    s, p1 = req("POST", "/payments", {"to_handle": "bob", "amount": 100,
               "note": "x", "visibility": "public"},
               token=toks["ada"], headers={"Idempotency-Key": "probe-aon-1"})
    assert s == 201, p1
    s, p2 = req("POST", "/payments", {"to_handle": "cy", "amount": 100,
               "note": "x", "visibility": "public"},
               token=toks["ada"], headers={"Idempotency-Key": "probe-aon-2"})
    assert s == 201, p2
    before = {}
    for h in ("ada", "bob", "cy"):
        _, before[h] = req("GET", "/me", token=toks[h])

    s, body = req("POST", "/correction-batches",
                 {"corrections": [
                     {"payment_id": p1["payment_id"], "expected_revision": 1, "amount": 90,
                      "effective_at": "2026-09-20T12:00:00+00:00", "reason": "ok"},
                     {"payment_id": p2["payment_id"], "expected_revision": 9, "amount": 90,
                      "effective_at": "2026-09-20T12:00:00+00:00", "reason": "stale"},
                 ]},
                 token=toks["op"], headers={"Idempotency-Key": "probe-aon-batch"})
    check("all-or-nothing: batch with one stale item rejected", s == 409, (s, body))

    for h in ("ada", "bob", "cy"):
        _, after = req("GET", "/me", token=toks[h])
        check(f"all-or-nothing: {h}'s balance unchanged after rejected batch",
              after["total"] == before[h]["total"], (before[h], after))


def test_rounding_table():
    # stage-1 sec9-style rounding: amounts are integer minor units; the API
    # must reject non-integer / fractional-unit amounts rather than rounding.
    global toks
    toks = setup()
    s, body = req("POST", "/payments", {"to_handle": "bob", "amount": 10.5,
                  "note": "x", "visibility": "public"},
                  token=toks["ada"], headers={"Idempotency-Key": "probe-round-1"})
    check("rounding: fractional minor-unit amount rejected 422", s == 422, (s, body))


def main():
    test_50_in_flight_mixed_burst()
    test_exactly_once_under_concurrent_retry()
    test_all_or_nothing_on_rejected_batch()
    test_rounding_table()
    print(f"\n{len(fails)} failing checks" if fails else "\nall reviewer probe checks passed")
    for f in fails:
        print("  - " + f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
