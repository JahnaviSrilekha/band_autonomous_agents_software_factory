"""Authentication (R43-R47, R19-R21, A10, A11) incl. black-box password-hash check."""
from client import (PASSWORD, check, eq, expect_error, expect_ok, fresh, get_me)


def test_signup_login_shapes(c):
    fresh(c)
    r = expect_ok(c.signup("new@example.com", PASSWORD, "New"), 201, "signup")
    eq(set(r.keys()), {"user_id", "display_name", "token"}, "signup 201 shape (R43)")
    eq(r["display_name"], "New", "signup display_name echo")
    check(isinstance(r["user_id"], str) and r["user_id"], "user_id non-empty string")
    r2 = expect_ok(c.login("new@example.com"), 200, "login")
    eq(set(r2.keys()), {"user_id", "display_name", "token"}, "login 200 shape (R43)")
    eq(r2["user_id"], r["user_id"], "same user_id on login")


def test_signup_error_table(c):
    fresh(c)
    expect_ok(c.signup("new1@example.com", PASSWORD, "N1"), 201, "first new1")
    # Email already registered (exact string, A11).
    expect_error(c.signup("new1@example.com"), 409, "email_taken")
    # A case-variant email is a DIFFERENT email (A11) but its derived handle
    # collides: expect handle_taken, not email_taken (R20/A11).
    r = c.signup("NEW1@example.com", PASSWORD, "N1b")
    expect_error(r, 409, "handle_taken")
    # Password shorter than 8 characters.
    expect_error(c.signup("p1@example.com", "short"), 422, "validation_failed")
    expect_ok(c.signup("p1@example.com", "short7x", "P1"), 201,
              "8-char password accepted (boundary)")
    # Email not of the form local@domain.
    for bad in ("no-at", "a@b@c", "@example.com", "local@", "local@domain@x"):
        expect_error(c.signup(bad, PASSWORD, "X"), 422, f"bad email {bad!r} (R44)")


def test_email_case_sensitivity_login(c):
    # A11: emails are matched exactly; no normalisation.
    fresh(c)
    expect_ok(c.signup("Upper@x.com", PASSWORD, "U"), 201, "signup Upper@x.com")
    expect_error(c.login("upper@x.com"), 401, "unauthenticated")
    expect_ok(c.login("Upper@x.com"), 200, "exact-case login works")


def test_derived_handle_rule(c):
    fresh(c)
    # local part -> lowercase, non-[a-z0-9_] -> '_', truncate to 20 (R20).
    r = expect_ok(c.signup("First.Last+tag@Example.COM", PASSWORD, "F"), 201)
    # Derive expected handle: "first.last+tag" -> "first_last_tag"
    expect_ok(c.post("/payments",
                     body={"to_handle": "first_last_tag", "amount": 1},
                     token=c.token_for("ada"), headers={"Idempotency-Key": "dh-1"}),
              201, "pay to derived handle first_last_tag")
    # Truncation to 20 chars.
    r2 = expect_ok(c.signup("abcdefghijklmnopqrstuvwx@x.com", PASSWORD, "T"), 201)
    expect_ok(c.post("/payments",
                     body={"to_handle": "abcdefghijklmnopqrst", "amount": 1},
                     token=c.token_for("ada"), headers={"Idempotency-Key": "dh-2"}),
              201, "pay to truncated 20-char handle")


def test_derived_handle_collision(c):
    fresh(c)
    expect_ok(c.signup("collide@x.com", PASSWORD, "C1"), 201)  # handle "collide"
    r = c.signup("Collide@x.com", PASSWORD, "C2")  # derived handle also "collide"
    # Emails differ (A11), so the failure must be handle_taken, not email_taken.
    expect_error(r, 409, "handle_taken")
    expect_error(c.login("Collide@x.com"), 401, "unauthenticated (no account created)")


def test_new_user_zero_balance_and_receivable(c):
    toks = fresh(c)
    r = expect_ok(c.signup("fresh@example.com", PASSWORD, "Fresh"), 201, "signup fresh")
    me = expect_ok(c.get("/me", token=r["token"]), 200, "GET /me fresh")
    eq(me["balance"], 0, "new user balance 0 (R21)")
    expect_ok(c.post("/payments", body={"to_handle": "fresh", "amount": 250},
                     token=toks["ada"], headers={"Idempotency-Key": "nu-1"}),
              201, "new user can receive immediately (R21)")
    eq(get_me(c, r["token"])["balance"], 250, "received amount credited")
    expect_ok(c.post("/requests", body={"payer_handle": "fresh", "amount": 10},
                     token=toks["ada"], headers={"Idempotency-Key": "nu-2"}),
              201, "new user can be asked for money immediately (R21)")


def test_multiple_tokens_concurrent_sessions(c):
    toks = fresh(c)
    t1 = toks["ada"]
    t2 = expect_ok(c.login("ada@example.com"), 200)["token"]
    t3 = expect_ok(c.login("ada@example.com"), 200)["token"]
    check(len({t1, t2, t3}) == 3, "each login issues a distinct token (R46)")
    for t in (t1, t2, t3):
        eq(expect_ok(c.get("/me", token=t), 200)["handle"], "ada",
           "all tokens valid concurrently (R46)")


def test_missing_or_bad_token_401(c):
    toks = fresh(c)
    paths = [("GET", "/me"), ("GET", "/activity"), ("GET", "/requests"),
             ("POST", "/payments"), ("POST", "/requests")]
    for method, path in paths:
        expect_error(c.request(method, path), 401, f"unauthenticated: {method} {path}")
    r = c.get("/me", token="totally-unknown-token")
    expect_error(r, 401, "unknown token")
    r = c.get("/me", headers={"Authorization": "Basic dXNlcjpwdw=="})
    expect_error(r, 401, "non-bearer auth scheme")
    r = c.get("/me", headers={"Authorization": "Bearer"})
    expect_error(r, 401, "bare Bearer scheme")
    # Wallet API endpoints require auth even with a valid-format but unknown token.
    expect_error(c.post("/payments", body={"to_handle": "bob", "amount": 1},
                        headers={"Idempotency-Key": "noauth-1"}),
                 401, "unauthenticated")


def test_passwords_not_stored_plaintext(c):
    # R47, black-box via export: the raw exported state must not contain the
    # password string anywhere (state is opaque, but plaintext storage would
    # leak the literal).
    toks = fresh(c)
    secret = "correct horse battery staple zqx"
    expect_ok(c.signup("hashcheck@example.com", secret, "H"), 201, "signup hashcheck")
    exp = c.export()
    eq(exp.status, 200, "export status")
    raw = exp.raw.decode("utf-8", errors="replace")
    check(secret not in raw,
          "exported state contains the plaintext password (R47 violated)")
    # Login still works (hashing round-trips).
    expect_ok(c.login("hashcheck@example.com", secret), 200, "hashed login works")