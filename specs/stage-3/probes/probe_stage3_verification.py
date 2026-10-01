"""Reviewer's independent stage-3 stress/invariant probe (final verification).

Runs against a live container (BASE_URL, default localhost:18090) built fresh
from main@0313387 via stage-3/RUN.md. Exercises many concurrent, retried and
mixed operations and checks R202 (conservation), R246 (no negative total/
available in any historical view), R231 (exactly-once correction under race),
and A29/R182-style all-or-nothing on a deliberately invalid concurrent reset.
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost:18090")
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
     "display_name": "Ada", "handle": "ada", "balance": 100000},
    {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
     "display_name": "Bob", "handle": "bob", "balance": 100000},
    {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
     "display_name": "Cy", "handle": "cy", "balance": 100000},
]
SEEDED_TOTAL = 300000
FIXTURE = {"currency": "EUR", "minor_units": 2, "users": USERS}


def setup():
    s, b = reset(FIXTURE)
    check("reviewer probe: fixture reset 204", s == 204, f"{s} {b}")
    toks = {u["handle"]: login(u["email"]) for u in USERS}
    return toks


def test_exactly_once_under_race(toks):
    s, pay = req("POST", "/payments",
                 {"to_handle": "bob", "amount": 500, "currency": "EUR"},
                 token=toks["ada"], headers={"Idempotency-Key": "probe-pay-1"})
    check("probe: seed payment 201", s == 201, f"{s} {pay}")
    pid = pay["payment_id"]

    results = []
    lock = threading.Lock()

    def attempt(i):
        s, b = req("POST", f"/payments/{pid}/corrections",
                   {"expected_revision": 1, "amount": 300,
                    "effective_at": pay["created_at"], "reason": f"race-{i}"},
                   token=toks["ada"], headers={"Idempotency-Key": f"probe-corr-{i}"})
        with lock:
            results.append(s)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok_count = results.count(201)
    stale_count = results.count(409)
    check("R231: exactly one concurrent same-expected-revision correction succeeds",
          ok_count == 1 and stale_count == 9, f"results={sorted(results)}")
    check("R231: zero 5xx under correction race", all(r < 500 for r in results),
          f"results={results}")


def test_conservation_and_no_negative(toks):
    s, pay1 = req("POST", "/payments", {"to_handle": "cy", "amount": 1000, "currency": "EUR"},
                  token=toks["bob"], headers={"Idempotency-Key": "probe-pay-2"})
    check("probe: second seed payment 201", s == 201, f"{s} {pay1}")

    def mixed_ops(i):
        req("POST", "/payments", {"to_handle": "ada", "amount": 10, "currency": "EUR"},
            token=toks["cy"], headers={"Idempotency-Key": f"probe-mix-pay-{i}"})
        req("GET", "/statement", token=toks["ada"])
        req("GET", "/me", token=toks["bob"], raw_query="as_of=2026-09-01T00:00:00%2B00:00")
        req("GET", "/activity", token=toks["cy"])

    threads = [threading.Thread(target=mixed_ops, args=(i,)) for i in range(13)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    views = [
        {}, {"as_of": "2026-09-01T00:00:00+00:00"},
        {"as_of": "2026-12-01T00:00:00+00:00"},
        {"known_at": "2026-09-01T00:00:00+00:00"},
    ]
    for view in views:
        raw_q = "&".join(f"{k}={v.replace('+', '%2B')}" for k, v in view.items())
        total_sum = 0
        for h in ("ada", "bob", "cy"):
            s, m = req("GET", "/me", token=toks[h], raw_query=raw_q or None)
            check(f"R246: total >= 0 for {h} at {view}", m.get("total", -1) >= 0, m)
            check(f"R246: available >= 0 for {h} at {view}", m.get("available", -1) >= 0, m)
            total_sum += m.get("total", 0)
        check(f"R202: conservation holds at {view}", total_sum == SEEDED_TOTAL,
              f"got {total_sum}, want {SEEDED_TOTAL}")


def test_all_or_nothing_reset():
    bad_fixture = {"currency": "EUR", "minor_units": 2,
                   "users": [{"id": "u_x", "email": "x@example.com", "password": "correct horse",
                              "display_name": "X", "handle": "x", "balance": -5}]}
    s, b = reset(bad_fixture)
    check("A29/R182: negative seeded balance rejected 422", s == 422, f"{s} {b}")
    s2, me = req("GET", "/health")
    check("A29/R182: rejected reset leaves prior state intact (health still ok)",
          s2 == 200 and me.get("status") == "ok", f"{s2} {me}")
    s3, b3 = req("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
    check("A29/R182: prior users still present after rejected reset", s3 == 200, f"{s3} {b3}")


def main():
    toks = setup()
    test_exactly_once_under_race(toks)
    toks = setup()
    test_conservation_and_no_negative(toks)
    test_all_or_nothing_reset()
    print(f"\n{len(fails)} failing checks" if fails else "\nall reviewer probe checks passed")
    for f in fails:
        print("  - " + f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
