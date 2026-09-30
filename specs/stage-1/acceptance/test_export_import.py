"""Export/import (§10: R78-R85, R93)."""
from client import (check, eq, expect_error, expect_ok, fresh, get_me,
                    make_payment, payment_body)

EXPORT_KEYS = {"track", "format_version", "state"}


def export(c):
    r = c.export()
    eq(r.status, 200, "export returns 200 (R78)")
    body = r.json()
    eq(set(body.keys()), EXPORT_KEYS, "export top-level shape (R78)")
    eq(body["track"], "pocketful", "track (R78)")
    eq(body["format_version"], 1, "format_version 1 (R78)")
    check(isinstance(body["state"], dict), "state is a JSON object")
    return body


def test_export_unauthenticated_shape(c):
    fresh(c)
    export(c)


def test_round_trip_is_a_noop(c):
    toks = fresh(c)
    expect_ok(make_payment(c, toks["ada"], "bob", 500, "rt-1"), 201)
    snapshot = export(c)
    # Mutate after export, then import the snapshot back.
    expect_ok(make_payment(c, toks["ada"], "bob", 999, "rt-2"), 201)
    r = c.import_state(snapshot)
    eq(r.status, 204, "import returns 204 (R79)")
    eq(get_me(c, toks["ada"])["balance"], 100000 - 500,
       "post-import state equals exported state (R79)")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq([p["amount"] for p in feed], [500], "no duplicate payments (R79)")


def test_import_replacement_not_merge(c):
    toks = fresh(c)
    snapshot = export(c)
    # Build a completely different destination state.
    other = fresh(c, users=[{"id": "u_z", "email": "z@example.com",
                             "password": "correct horse", "display_name": "Z",
                             "handle": "z", "balance": 5}])
    r = c.import_state(snapshot)
    eq(r.status, 204, "import 204")
    expect_error(c.get("/me", token=other["z"]), 401, "unauthenticated",
                 "destination credentials removed (R83)")
    eq(get_me(c, toks["ada"])["balance"], 100000,
       "imported state restored exactly (R79)")
    # Repeating the import restores without duplicating anything (R79).
    expect_ok(make_payment(c, toks["ada"], "bob", 10, "dup-1"), 201)
    eq(c.import_state(snapshot).status, 204, "repeat import 204")
    eq(get_me(c, toks["ada"])["balance"], 100000, "repeat import no duplication")
    eq(len(expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]), 0,
       "payment count not duplicated by repeat import")


def test_import_errors_leave_destination_unchanged(c):
    toks = fresh(c)
    snapshot = export(c)
    for i, bad in enumerate([
        {"track": "other", "format_version": 1, "state": snapshot["state"]},
        {"track": "pocketful", "format_version": 2, "state": snapshot["state"]},
        {"track": "pocketful", "format_version": 1},
        {"track": "pocketful", "format_version": 1, "state": "nope"},
        {"track": "pocketful", "format_version": 1, "state": None},
    ]):
        r = c.import_state(bad)
        expect_error(r, 422, "validation_failed", f"bad import payload {i} (R80)")
    r = c.request("POST", "/_test/import", raw_body="{broken", timeout=10)
    expect_error(r, 400, "malformed_request", "invalid JSON (R80)")
    # Destination unchanged.
    eq(get_me(c, toks["ada"])["balance"], 100000, "state unchanged (R80)")
    eq(c.import_state(snapshot).status, 204, "valid import still accepted")


def test_export_is_atomic_read_only_snapshot(c):
    # R81: subsequent source writes do not change an already-taken export.
    toks = fresh(c)
    snapshot = export(c)
    expect_ok(make_payment(c, toks["ada"], "bob", 700, "snap-1"), 201)
    # Importing the older snapshot must not contain the later payment.
    eq(c.import_state(snapshot).status, 204, "import older snapshot")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    check(all(p["amount"] != 700 for p in feed),
          "later write not present in earlier snapshot (R81)")


def test_import_preserves_tokens_login_replays_and_failed_keys(c):
    # R82: accounts/hashed-password login, tokens, completed idempotent bodies
    # and original responses, failed keys reusable, settlement permissions.
    toks = fresh(c, operator=True)
    ada_token_pre = toks["ada"]
    p1 = expect_ok(make_payment(c, ada_token_pre, "bob", 300, "pres-1"), 201)
    # A failed (4xx) key that must remain reusable after import.
    expect_error(make_payment(c, ada_token_pre, "bob", 1000000001, "pres-fail"),
                 422, "validation_failed")
    bal_ada, bal_bob = get_me(c, ada_token_pre)["balance"], get_me(c, toks["bob"])["balance"]
    snapshot = export(c)
    # Change destination state entirely.
    fresh(c, users=[{"id": "u_z", "email": "z@example.com",
                     "password": "correct horse", "display_name": "Z",
                     "handle": "z", "balance": 5}])
    eq(c.import_state(snapshot).status, 204, "import 204")
    # Old bearer token still authenticates.
    eq(get_me(c, ada_token_pre)["balance"], bal_ada, "old token valid post-import (R82)")
    # Hashed-password login preserved (R82).
    expect_ok(c.login("ada@example.com"), 200, "pre-import password still logs in")
    # Completed key replays the original response without moving money again.
    r = c.post("/payments", body=payment_body("bob", 300), token=ada_token_pre,
               headers={"Idempotency-Key": "pres-1"})
    eq(r.status, 200, "completed key replays 200 post-import (R82)")
    eq(r.json(), p1, "original response body preserved (R82)")
    eq(get_me(c, ada_token_pre)["balance"], bal_ada, "replay moved no money (R82)")
    eq(get_me(c, toks["bob"])["balance"], bal_bob, "receiver unchanged by replay")
    # Failed key is still a fresh first use post-import (R82).
    r = make_payment(c, ada_token_pre, "bob", 100, "pres-fail")
    eq(r.status, 201, "failed key reusable post-import (R82)")
    # Operator permission preserved (R93).
    r = c.post("/settlements", body={"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 10}]},
        token=toks["op"], headers={"Idempotency-Key": "pres-op-1"})
    eq(r.status, 201, "operator permission preserved post-import (R93)")


def test_import_preserves_settlement_membership(c):
    # R93: settlement membership and retry responses survive import.
    toks = fresh(c, operator=True)
    r1 = expect_ok(c.post("/settlements", body={"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 100}]},
        token=toks["op"], headers={"Idempotency-Key": "mem-1"}), 201)
    member = r1["payments"][0]
    snapshot = export(c)
    fresh(c, users=[{"id": "u_z", "email": "z@example.com",
                     "password": "correct horse", "display_name": "Z",
                     "handle": "z", "balance": 5}])
    eq(c.import_state(snapshot).status, 204, "import 204")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq(feed[0]["settlement_id"], member["settlement_id"],
       "settlement membership preserved (R93)")
    eq(feed[0]["payment_id"], member["payment_id"],
       "identities not regenerated (R82)")
    r2 = c.post("/settlements", body={"transfers": [
        {"from_handle": "ada", "to_handle": "bob", "amount": 100}]},
        token=toks["op"], headers={"Idempotency-Key": "mem-1"})
    eq(r2.status, 200, "settlement retry replay preserved (R93)")
    eq(r2.json(), r1, "original settlement response preserved (R93)")


def test_reset_clears_imported_state(c):
    # R84: reset clears all state, including imported state.
    toks = fresh(c)
    snapshot = export(c)
    fresh(c, users=[{"id": "u_z", "email": "z@example.com",
                     "password": "correct horse", "display_name": "Z",
                     "handle": "z", "balance": 5}])
    eq(c.import_state(snapshot).status, 204, "import 204")
    fresh(c)  # reset with the standard fixture
    expect_error(c.get("/me", token=toks["ada"]), 401, "unauthenticated",
                 "imported credentials cleared by reset (R84)")
    new_ada = c.token_for("ada")
    eq(get_me(c, new_ada)["balance"], 100000, "reset state is the fresh fixture (R84)")