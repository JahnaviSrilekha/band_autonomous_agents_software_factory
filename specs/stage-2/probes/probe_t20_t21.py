import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "stage-2", "tests"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "stage-2", "src"))
import base

httpd, port = base.make_server()
BASE = {"currency": "EUR", "minor_units": 2}
fails = []

def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

def user(uid, handle, balance, email=None):
    return {"id": uid, "email": email or f"{handle}@example.com", "password": "correct horse",
            "display_name": handle.title(), "handle": handle, "balance": balance}

def login(email="a@example.com"):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                       body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}

status, body, _ = base.request(port, "POST", "/_test/reset", {**BASE,
    "users": [user("u_a", "a", 1000), user("u_b", "b", 500)],
    "authorization_ttl_seconds": 30,
})
check("R130/R131 valid ttl fixture resets 204", status == 204)

# R133: hold sum exceeds balance -> 422, prior state unchanged
status, body, _ = base.request(port, "POST", "/_test/reset", {**BASE,
    "users": [user("u_c", "c", 100)],
    "authorizations": [
        {"id": "auth_1", "from_user_id": "u_c", "to_user_id": "u_c", "amount": 60,
         "status": "open", "expires_at": "2099-01-01T00:00:00Z"},
        {"id": "auth_2", "from_user_id": "u_c", "to_user_id": "u_c", "amount": 60,
         "status": "open", "expires_at": "2099-01-01T00:00:00Z"},
    ],
})
check("R133 seeded hold sum > balance -> 422", status == 422 and body.get("error", {}).get("code") == "validation_failed")
h = login("a@example.com")
status, body, _ = base.request(port, "GET", "/me", headers=h)
check("R133 state unchanged after rejected reset (u_a from prior reset still logs in)", status == 200 and body["user_id"] == "u_a")

# R131: non-positive / non-integer / bool ttl rejected
for bad_ttl, label in [(0, "zero"), (-5, "negative"), (1.5, "non-integer-float"), (True, "bool")]:
    status, body, _ = base.request(port, "POST", "/_test/reset", {**BASE,
        "users": [user("u_a", "a", 100)],
        "authorization_ttl_seconds": bad_ttl,
    })
    check(f"R131 ttl={label} rejected 422", status == 422)

# R135: fixture omitting authorizations key -> held == 0
status, body, _ = base.request(port, "POST", "/_test/reset", {**BASE, "users": [user("u_a", "a", 100)]})
check("R135 stage-1-shaped fixture (no authorizations) resets 204", status == 204)
h = login()
status, body, _ = base.request(port, "GET", "/me", headers=h)
check("R135 held==0, available==total==balance with omitted authorizations",
      status == 200 and body["held"] == 0 and body["available"] == body["total"] == body["balance"] == 100)

# R136: expired-but-stored-open hold contributes 0 to held/available
status, body, _ = base.request(port, "POST", "/_test/reset", {**BASE,
    "users": [user("u_a", "a", 100)],
    "authorizations": [
        {"id": "auth_exp", "from_user_id": "u_a", "to_user_id": "u_a", "amount": 50,
         "status": "open", "expires_at": "2000-01-01T00:00:00Z"},
    ],
})
check("R136 past-dated open hold fixture accepted (doesn't count toward R133 sum)", status == 204)
h = login()
status, body, _ = base.request(port, "GET", "/me", headers=h)
check("R136 clock-expired stored-open hold -> held==0, available==total",
      status == 200 and body["held"] == 0 and body["available"] == 100)

# R138: exact field set + live hold reduces available
status, body, _ = base.request(port, "POST", "/_test/reset", {**BASE,
    "users": [user("u_a", "a", 100), user("u_b", "b", 50)],
    "authorizations": [
        {"id": "auth_live", "from_user_id": "u_a", "to_user_id": "u_b", "amount": 30,
         "status": "open", "expires_at": "2099-01-01T00:00:00Z"},
    ],
})
check("reset for R138 live-hold check ok", status == 204)
h = login()
status, body, _ = base.request(port, "GET", "/me", headers=h)
check("R138 exact field set", status == 200 and set(body.keys()) == {
    "user_id", "display_name", "handle", "balance", "total", "available", "held",
    "currency", "minor_units"})
check("R138 balance==total", status == 200 and body["balance"] == body["total"])
check("R156 live hold reduces available immediately, no API call in between",
      status == 200 and body["held"] == 30 and body["available"] == 70 and body["total"] == 100)

base.stop_server(httpd)
print(f"\n{len(fails)} failing checks" if fails else "\nALL PROBES PASSED")
sys.exit(1 if fails else 0)
