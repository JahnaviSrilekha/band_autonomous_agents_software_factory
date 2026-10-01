"""Stage-3 GET /statement (R169-R177, R215-R220, R229, A36, A37)."""
import json

from client import (
    check, eq, expect_error, expect_ok, fixture, fpayment, get_me, statement_ok,
    statement_view, all_statement_entries, correct, correction_body,
    entry_keys_ok, fuser, PAYMENT_KEYS, T1, T2, T3, FAR_PAST, FAR_FUTURE,
)

USERS = [fuser("u_ada", "ada", 9300), fuser("u_bob", "bob", 10100),
         fuser("u_cy", "cy", 600)]
PAYMENTS = [
    fpayment("p_s1", "u_ada", "u_bob", 500, created_at=T1),
    fpayment("p_s2", "u_bob", "u_cy", 300, created_at=T2, note="rent",
             visibility="private"),
    fpayment("p_s3", "u_ada", "u_cy", 200, created_at=T2),
    fpayment("p_s4", "u_bob", "u_cy", 100, created_at=T3),
]
# Openings: ada 10000, bob 10000, cy 0.
OPENING = {"ada": 10000, "bob": 10000, "cy": 0}


def sfix(c):
    r = c.reset(fixture(users=USERS, payments=PAYMENTS))
    eq(r.status, 204, "reset")
    return {u["handle"]: c.token_for(u["handle"]) for u in USERS}


def test_r169_route_requires_auth(c):
    toks = sfix(c)
    expect_error(c.get("/statement"), 401, "unauthenticated", "no token (R169)")
    expect_error(c.get("/statement", token="bogus"), 401, "unauthenticated", "bad token")
    check(statement_ok(c, toks["ada"]), "route exists for authenticated caller (R169)")


def test_r170_from_to_defaults(c):
    toks = sfix(c)
    full = statement_ok(c, toks["ada"])
    eq([e["payment"]["payment_id"] for e in full["entries"]], ["p_s1", "p_s3"],
       "default window covers the whole wallet (R170)")
    bounded = statement_ok(c, toks["ada"], **{"from": FAR_PAST, "to": FAR_FUTURE})
    eq([e["payment"]["payment_id"] for e in bounded["entries"]],
       [e["payment"]["payment_id"] for e in full["entries"]],
       "explicit open bounds == defaults (R170)")


def test_r171_limit_offset_as_requests(c):
    toks = sfix(c)
    for q, what in (("limit=0", "limit 0"), ("limit=201", "limit 201"),
                    ("limit=4.0", "limit 4.0"), ("limit=1e9", "limit 1e9"),
                    ("offset=-1", "offset -1"), ("offset=+4", "offset +4")):
        expect_error(statement_view(c, toks["ada"], extra_q=q), 422,
                     "validation_failed", f"{q} rejected (R171/R41/R39)")
    p1 = statement_ok(c, toks["ada"], limit=1, offset=0)
    check(p1["has_more"] is True, "has_more true when more entries exist (R171)")
    p2 = statement_ok(c, toks["ada"], limit=1, offset=1)
    check(p2["has_more"] is False, "has_more false on last page (R171)")


def test_r172_response_shape(c):
    toks = sfix(c)
    body = statement_ok(c, toks["ada"])
    check({"opening_balance", "entries", "closing_balance", "has_more",
           "snapshot"} <= set(body.keys()),
          f"statement body fields: {sorted(body.keys())} (R172/R221)")
    check(isinstance(body["snapshot"], str) and body["snapshot"],
          "snapshot token is a non-empty opaque string (R221)")
    for e in body["entries"]:
        entry_keys = {"payment", "delta", "balance_after", "revision",
                      "effective_at", "recorded_at"}
        check(entry_keys <= set(e.keys()),
              f"entry fields per R172/R216: {sorted(e.keys())}")
        check(PAYMENT_KEYS <= set(e["payment"].keys()),
              f"entry payment is the full payment representation (R158): {sorted(e['payment'])}")
    check(isinstance(body["has_more"], bool), "has_more bool")


def test_r172_r173_entries_oldest_first_and_tie_by_id(c):
    toks = sfix(c)
    eq([e["payment"]["payment_id"] for e in statement_ok(c, toks["ada"])["entries"]],
       ["p_s1", "p_s3"], "ada oldest first (R172)")
    cy = statement_ok(c, toks["cy"])
    eq([e["payment"]["payment_id"] for e in cy["entries"]], ["p_s2", "p_s3", "p_s4"],
       "same-instant tie broken by ascending payment id (R173/A37)")


def test_r174_opening_closing_balances(c):
    toks = sfix(c)
    st = statement_ok(c, toks["ada"], **{"from": T2, "to": T3})
    eq(st["opening_balance"], 9500, "balance immediately before from (F3 at ==from excluded, R174)")
    eq(st["closing_balance"], 9300, "balance immediately before to (R174)")
    eq([e["payment"]["payment_id"] for e in st["entries"]], ["p_s3"],
       "half-open window [from, to) (R172)")
    bob = statement_ok(c, toks["bob"], **{"from": T1, "to": T3})
    eq(bob["opening_balance"], 10000, "bob opening before T1 (R174)")
    eq(bob["closing_balance"], 10200, "bob closing before T3 (F4 at ==to excluded)")
    eq([e["payment"]["payment_id"] for e in bob["entries"]], ["p_s1", "p_s2"],
       "bob window entries")


def test_r175_full_window_delta_invariant(c):
    toks = sfix(c)
    body, entries = all_statement_entries(c, toks["bob"], **{"from": T1, "to": FAR_FUTURE})
    eq(body["opening_balance"] + sum(e["delta"] for e in entries), body["closing_balance"],
       "opening + sum(all deltas) == closing across the FULL window (R175)")
    deltas = {e["payment"]["payment_id"]: e["delta"] for e in entries}
    check(deltas["p_s1"] == 500 and deltas["p_s2"] == -300 and deltas["p_s4"] == -100,
          f"received positive, sent negative (R175): {deltas}")


def test_r176_pagination_stable(c):
    toks = sfix(c)
    full = statement_ok(c, toks["bob"], **{"from": T1, "to": T3})
    pages = [statement_ok(c, toks["bob"], **{"from": T1, "to": T3},
                          limit=1, offset=o) for o in (0, 1)]
    for p in pages:
        eq(p["opening_balance"], full["opening_balance"],
           "opening_balance identical across pages (R176)")
        eq(p["closing_balance"], full["closing_balance"],
           "closing_balance identical across pages (R176)")
    eq([e for p in pages for e in p["entries"]], full["entries"],
       "sliced entries == full-window entries with same balance_after (R176)")


def test_r177_statement_privacy(c):
    toks = sfix(c)
    ada_ids = [e["payment"]["payment_id"] for e in statement_ok(c, toks["ada"])["entries"]]
    check("p_s2" not in ada_ids and "p_s4" not in ada_ids,
          "third-party payments absent from ada's statement even when public (R177)")
    cy_ids = [e["payment"]["payment_id"] for e in statement_ok(c, toks["cy"])["entries"]]
    check("p_s2" in cy_ids, "own private payment present in own statement (R177)")
    bob_ids = [e["payment"]["payment_id"] for e in statement_ok(c, toks["bob"])["entries"]]
    check("p_s2" in bob_ids and "p_s4" in bob_ids, "bob sees own sent payments (R177)")


def test_r215_ordering_by_selected_effective_at(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r215-k",
                      {"expected_revision": 1, "amount": 400,
                       "effective_at": T3, "reason": "moved"}), 201)
    eq([e["payment"]["payment_id"] for e in statement_ok(c, toks["ada"])["entries"]],
       ["p_s3", "p_s1"],
       "ordering by selected effective_at, not created_at (R215/A34)")


def test_r217_payment_amount_is_selected_amount(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r217-k",
                      {"expected_revision": 1, "amount": 400,
                       "effective_at": T1, "reason": "amt"}), 201)
    e = [x for x in statement_ok(c, toks["ada"])["entries"]
         if x["payment"]["payment_id"] == "p_s1"][0]
    eq(e["payment"]["amount"], 400, "embedded payment.amount is the selected amount (R217)")
    eq(e["delta"], -400, "delta matches selected amount (R175/R217)")
    eq(e["revision"], 2, "entry carries the selected revision (R216)")


def test_r218_zero_amount_revision_zero_delta_entry(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r218-k",
                      {"expected_revision": 1, "amount": 0,
                       "effective_at": T1, "reason": "reverse"}), 201)
    e = [x for x in statement_ok(c, toks["ada"])["entries"]
         if x["payment"]["payment_id"] == "p_s1"]
    eq(len(e), 1, "zero-amount revision still yields an entry (R218)")
    eq(e[0]["delta"], 0, "zero delta (R218)")
    eq(e[0]["payment"]["amount"], 0, "selected amount 0 (R217)")
    eq(get_me(c, toks["ada"])["balance"], 9800, "reversal returned the money")


def test_r219_exactly_one_entry_per_payment(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r219-k1",
                      {"expected_revision": 1, "amount": 450,
                       "effective_at": T1, "reason": "one"}), 201)
    expect_ok(correct(c, toks["ada"], "p_s1", "r219-k2",
                      {"expected_revision": 2, "amount": 460,
                       "effective_at": T1, "reason": "two"}), 201)
    ids = [e["payment"]["payment_id"] for e in statement_ok(c, toks["ada"])["entries"]]
    eq(ids.count("p_s1"), 1, "no correction counted alongside the revision it replaces (R219)")


def test_r220_uncorrected_statement_unchanged(c):
    toks = sfix(c)
    st = statement_ok(c, toks["ada"])
    eq(st["opening_balance"], 10000, "opening per R174 (R220)")
    for e in st["entries"]:
        eq(e["revision"], 1, "uncorrected entry is revision 1 (R220)")
        eq(e["effective_at"], e["payment"]["created_at"],
           "effective_at == created_at uncorrected (R220)")
        eq(e["recorded_at"], e["payment"]["created_at"],
           "recorded_at == created_at uncorrected (R220)")


def test_r229_live_window_membership_moves(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r229-k1",
                      {"expected_revision": 1, "amount": 500,
                       "effective_at": T3, "reason": "out"}), 201)
    ids = [e["payment"]["payment_id"] for e in
           statement_ok(c, toks["ada"], **{"from": T1, "to": T3})["entries"]]
    check("p_s1" not in ids, "correction moved the payment OUT of the window (R229)")
    expect_ok(correct(c, toks["ada"], "p_s1", "r229-k2",
                      {"expected_revision": 2, "amount": 500,
                       "effective_at": T1, "reason": "in"}), 201)
    ids = [e["payment"]["payment_id"] for e in
           statement_ok(c, toks["ada"], **{"from": T1, "to": T3})["entries"]]
    check("p_s1" in ids, "correction moved the payment INTO the window (R229)")


def test_a36_statement_cross_route_params_ignored(c):
    toks = sfix(c)
    base = statement_ok(c, toks["ada"])
    junk = statement_ok(c, toks["ada"], as_of=T2)
    for f in ("opening_balance", "closing_balance", "has_more"):
        eq(junk[f], base[f], f"as_of ignored on /statement (A36/R228): {f}")
    eq([e["payment"]["payment_id"] for e in junk["entries"]],
       [e["payment"]["payment_id"] for e in base["entries"]],
       "as_of ignored on /statement entries (A36)")
    token = base["snapshot"]
    snap_asof = statement_ok(c, toks["ada"], snapshot=token, as_of=T2, limit=1)
    check(snap_asof, "as_of alongside snapshot ignored, not 422 (A36/R224)")


def test_r228_unrecognized_params_ignored(c):
    toks = sfix(c)
    check(statement_ok(c, toks["ada"], extra_q="bogus=1&zzz=abc"),
          "unrecognized query params ignored on /statement (R228)")
    check(statement_ok(c, toks["ada"], limit=1, extra_q="bogus=1"),
          "unrecognized params alongside valid ones ignored (R228)")