"""Stage-3 corrections: request validation, money movement, failure modes,
revisions endpoint (R178-R206, A32, A33, plus A34 placement)."""
from client import (
    check, eq, expect_error, expect_ok, fixture, fpayment, get_me, correct,
    correction_body, revisions_of, revision_keys_ok, statement_ok, make_payment,
    fuser, RFC3339, T0, T1, T2, T3, FAR_PAST, shift, rfc3339, parse_inst,
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


def sfix(c):
    r = c.reset(fixture(users=USERS, payments=PAYMENTS))
    eq(r.status, 204, "reset")
    return {u["handle"]: c.token_for(u["handle"]) for u in USERS}


def api_payment(c, toks, amount=100, key="api-pay", **kw):
    return expect_ok(make_payment(c, toks["ada"], "bob", amount, key, **kw), 201)


def test_r178_revision1_of_api_payment(c):
    toks = sfix(c)
    pay = api_payment(c, toks)
    revs = revisions_of(c, toks["ada"], pay["payment_id"])
    eq(len(revs), 1, "exactly revision 1 initially (R178)")
    r1 = revs[0]
    revision_keys_ok(r1)
    eq(r1["revision"], 1, "numbered 1 (R178)")
    eq(r1["amount"], 100, "amount as originally paid (R178)")
    eq(r1["effective_at"], pay["created_at"], "effective_at == created_at (R178)")
    eq(r1["recorded_at"], pay["created_at"], "recorded_at == created_at (R178)")
    eq(r1["reason"], "", "revision 1 reason empty string (R205)")


def test_r179_seeded_revision1_uses_seeded_created_at(c):
    toks = sfix(c)
    revs = revisions_of(c, toks["ada"], "p_s1")
    eq(len(revs), 1, "seeded payment has revision 1 (R179)")
    eq(revs[0]["effective_at"], T1, "effective_at == supplied created_at (R179)")
    eq(revs[0]["recorded_at"], T1, "recorded_at == supplied created_at (R179)")
    eq(revs[0]["amount"], 500, "amount as originally seeded (R179)")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    omitted = [p for p in feed if p["payment_id"] == "p_s3"][0]
    revs3 = revisions_of(c, toks["ada"], "p_s3")
    eq(revs3[0]["effective_at"], omitted["created_at"],
       "omitted created_at -> reset time is revision 1's effective/recorded (R179/R160)")


def test_r183_requires_idempotency_key(c):
    toks = sfix(c)
    body = correction_body(1, 400, T1)
    r = c.post("/payments/p_s1/corrections", body=body, token=toks["ada"])
    expect_error(r, 400, "missing_idempotency_key", "missing key (R183/stage-1 §7)")
    r = c.post("/payments/p_s1/corrections", body=body, token=toks["ada"],
               headers={"Idempotency-Key": ""})
    expect_error(r, 400, "missing_idempotency_key", "empty key (R183)")


def test_r184_non_sender_403_unknown_404(c):
    toks = sfix(c)
    body = correction_body(1, 400, T1)
    expect_error(correct(c, toks["bob"], "p_s1", "r184-b", body), 403, "forbidden",
                 "receiver is not the original sender (R184)")
    expect_error(correct(c, toks["cy"], "p_s1", "r184-c", body), 403, "forbidden",
                 "third party (R184)")
    expect_error(correct(c, toks["ada"], "p_nope", "r184-u", body), 404, "not_found",
                 "unknown payment (R184)")


def test_r185_all_fields_required(c):
    toks = sfix(c)
    full = correction_body(1, 400, T1, "r185")
    for missing in ("expected_revision", "amount", "effective_at", "reason"):
        body = {k: v for k, v in full.items() if k != missing}
        expect_error(correct(c, toks["ada"], "p_s1", f"r185-{missing}", body),
                     422, "validation_failed", f"missing {missing} (R185)")


def test_r186_expected_revision_rules(c):
    toks = sfix(c)
    for bad, status in ((0, 422), (-1, 422), (1.5, 422), ("1", 400), (True, 400)):
        expect_error(correct(c, toks["ada"], "p_s1", f"r186-{bad!r}",
                             {"expected_revision": bad, "amount": 400,
                              "effective_at": T1, "reason": "x"}),
                     status, "validation_failed" if status == 422 else "malformed_request",
                     f"expected_revision={bad!r} (R186)")


def test_r187_amount_rules(c):
    toks = sfix(c)
    for bad, status in ((-1, 422), (1000000001, 422), ("400", 400), (1.5, 422)):
        expect_error(correct(c, toks["ada"], "p_s1", f"r187-{bad!r}",
                             {"expected_revision": 1, "amount": bad,
                              "effective_at": T1, "reason": "x"}),
                     status, "validation_failed" if status == 422 else "malformed_request",
                     f"amount={bad!r} (R187)")


def test_r187_zero_reverses_entire_payment(c):
    toks = sfix(c)
    resp = expect_ok(correct(c, toks["ada"], "p_s1", "r187-zero",
                             correction_body(1, 0, T1, "reversed")), 201)
    eq(resp["amount"], 0, "amount 0 accepted (R187)")
    eq(get_me(c, toks["ada"])["balance"], 9800, "ada refunded the full 500")


def test_r188_reason_rules(c):
    toks = sfix(c)
    for bad in ("", "x" * 201, 5, None):
        expect_error(correct(c, toks["ada"], "p_s1", f"r188-{bad!r}",
                             {"expected_revision": 1, "amount": 400,
                              "effective_at": T1, "reason": bad}),
                     422, "validation_failed", f"reason={bad!r} (R188)")
    expect_ok(correct(c, toks["ada"], "p_s1", "r188-ok",
                      {"expected_revision": 1, "amount": 400,
                       "effective_at": T1, "reason": "x" * 200}), 201)


def test_r189_effective_at_rules(c):
    toks = sfix(c)
    for bad in (rfc3339(3600), "2026-09-01T10:00:00", "2026-09-01", ""):
        expect_error(correct(c, toks["ada"], "p_s1", f"r189-{bad[:10]}",
                             {"expected_revision": 1, "amount": 400,
                              "effective_at": bad, "reason": "x"}),
                     422, "validation_failed", f"effective_at={bad!r} (R189)")


def test_r190_unknown_body_fields_ignored_not_422(c):
    toks = sfix(c)
    body = correction_body(1, 400, T1, "r190")
    body["totally_unknown"] = {"junk": [1, 2]}
    resp = expect_ok(correct(c, toks["ada"], "p_s1", "r190-k", body), 201)
    eq(resp["amount"], 400, "unknown body field ignored per stage-1 R16 (R190 family)")


def test_r191_correction_changes_neither_parties_nor_visibility(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["bob"], "p_s2", "r191-k",
                      correction_body(1, 250, T2, "priv")), 201)
    feed = expect_ok(c.get("/activity", token=toks["bob"]), 200)["payments"]
    p = [x for x in feed if x["payment_id"] == "p_s2"][0]
    eq((p["from_user_id"], p["to_user_id"], p["visibility"]), ("u_bob", "u_cy", "private"),
       "parties and visibility untouched (R191)")
    e = [x for x in statement_ok(c, toks["bob"])["entries"]
         if x["payment"]["payment_id"] == "p_s2"][0]
    eq((e["payment"]["from_user_id"], e["payment"]["to_user_id"], e["payment"]["visibility"]),
       ("u_bob", "u_cy", "private"), "statement payment representation unchanged (R191)")


def test_r192_201_response_shape(c):
    toks = sfix(c)
    resp = expect_ok(correct(c, toks["ada"], "p_s1", "r192-k",
                             correction_body(1, 400, T0, "shape")), 201)
    for f in ("payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"):
        check(f in resp, f"201 body includes {f} (R192)")
    eq(resp["payment_id"], "p_s1", "payment_id (R192)")
    eq(resp["revision"], 2, "revision == expected_revision + 1 (R192)")
    eq(resp["amount"], 400, "amount (R192)")
    eq(resp["effective_at"], T0, "effective_at as supplied (R192)")
    eq(resp["reason"], "shape", "reason (R192)")
    check(RFC3339.match(resp["recorded_at"]), "recorded_at server-assigned RFC 3339 (R192)")
    check(resp["recorded_at"] != T0, "recorded_at != far-past effective_at (server-assigned)")


def test_r193_recorded_times_strictly_increase(c):
    toks = sfix(c)
    prev = None
    for i, key in enumerate(("r193-a", "r193-b", "r193-c")):
        expect_ok(correct(c, toks["ada"], "p_s1", key,
                          correction_body(i + 1, 400 + i, T1, f"r{i}")), 201)
        revs = revisions_of(c, toks["ada"], "p_s1")
        rec = parse_inst(revs[-1]["recorded_at"])
        if prev is not None:
            check(rec > prev, f"recorded_at strictly increases (R193): {revs[-1]!r}")
        prev = rec


def test_r194_stale_revision(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r194-k1",
                      correction_body(1, 450, T1)), 201)
    before_me = get_me(c, toks["ada"])
    before_revs = revisions_of(c, toks["ada"], "p_s1")
    expect_error(correct(c, toks["ada"], "p_s1", "r194-k2",
                         correction_body(1, 460, T1)), 409, "stale_revision",
                 "expected_revision behind latest (R194)")
    eq(revisions_of(c, toks["ada"], "p_s1"), before_revs, "revision history unchanged (R194)")
    eq(get_me(c, toks["ada"])["balance"], before_me["balance"], "balances unchanged (R194)")


def test_r195_replay_returns_original_revision(c):
    toks = sfix(c)
    first = expect_ok(correct(c, toks["ada"], "p_s1", "r195-k",
                              correction_body(1, 450, T1, "first")), 201)
    expect_ok(correct(c, toks["ada"], "p_s1", "r195-other",
                      correction_body(2, 460, T1, "second")), 201)
    replay = expect_ok(correct(c, toks["ada"], "p_s1", "r195-k",
                               correction_body(1, 450, T1, "first")), 200)
    eq(replay, first, "replay returns the ORIGINAL revision even after newer ones (R195)")


def test_r196_same_key_different_body(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r196-k",
                      correction_body(1, 450, T1)), 201)
    expect_error(correct(c, toks["ada"], "p_s1", "r196-k",
                         correction_body(1, 460, T1)), 409, "idempotency_key_reuse",
                 "different body, same key (R196)")
    expect_error(correct(c, toks["ada"], "p_s1", "r196-k",
                         {"expected_revision": "bad", "amount": 460,
                          "effective_at": T1, "reason": "x"}),
                 409, "idempotency_key_reuse",
                 "idempotency resolves before field validation (R54/A32)")


def test_r197_delta_moves_between_same_wallets(c):
    toks = sfix(c)
    ada0, bob0 = get_me(c, toks["ada"])["balance"], get_me(c, toks["bob"])["balance"]
    expect_ok(correct(c, toks["ada"], "p_s1", "r197-up",
                      correction_body(1, 700, T1)), 201)
    eq(get_me(c, toks["ada"])["balance"], ada0 - 200, "increase debits original sender (R197)")
    eq(get_me(c, toks["bob"])["balance"], bob0 + 200, "receiver credited the delta (R197)")
    ada1, bob1 = get_me(c, toks["ada"])["balance"], get_me(c, toks["bob"])["balance"]
    expect_ok(correct(c, toks["ada"], "p_s1", "r197-down",
                      correction_body(2, 450, T1)), 201)
    eq(get_me(c, toks["ada"])["balance"], ada1 + 250, "decrease credits original sender (R197)")
    eq(get_me(c, toks["bob"])["balance"], bob1 - 250, "decrease debits original receiver (R197)")


def test_r197_zero_delta_appends_revision_moves_nothing(c):
    toks = sfix(c)
    ada0 = get_me(c, toks["ada"])["balance"]
    expect_ok(correct(c, toks["ada"], "p_s1", "r197-same",
                      correction_body(1, 500, T1, "same amount")), 201)
    eq(get_me(c, toks["ada"])["balance"], ada0, "no money moved (R197)")
    eq(len(revisions_of(c, toks["ada"], "p_s1")), 2, "revision still appended")


def test_r198_current_unaffordable_insufficient_funds(c):
    users = [fuser("u_ada", "ada", 0), fuser("u_bob", "bob", 100),
             fuser("u_cy", "cy", 700)]
    payments = [fpayment("p_a", "u_ada", "u_bob", 800, created_at=T1),
                fpayment("p_b", "u_bob", "u_cy", 700, created_at=T2)]
    r = c.reset(fixture(users=users, payments=payments))
    eq(r.status, 204, "reset")
    toks = {u["handle"]: c.token_for(u["handle"]) for u in users}
    before = [get_me(c, toks[h])["balance"] for h in ("ada", "bob", "cy")]
    expect_error(correct(c, toks["ada"], "p_a", "r198-k",
                         correction_body(1, 300, T1)), 409, "insufficient_funds",
                 "receiver cannot afford the decreased amount's debit (R198)")
    after = [get_me(c, toks[h])["balance"] for h in ("ada", "bob", "cy")]
    eq(after, before, "balances preserved on insufficient_funds (R201)")
    eq(len(revisions_of(c, toks["ada"], "p_a")), 1, "no revision appended (R201)")
    st = statement_ok(c, toks["bob"])
    eq(st["opening_balance"] + sum(e["delta"] for e in st["entries"]),
       st["closing_balance"], "statement consistent, unchanged (R201)")


def test_r199_historical_overdraft_total(c):
    users = [fuser("u_ada", "ada", 1000), fuser("u_bob", "bob", 0), fuser("u_cy", "cy", 0)]
    payments = [fpayment("p_a", "u_ada", "u_bob", 700, created_at=T1),
                fpayment("p_b", "u_bob", "u_ada", 700, created_at=T2)]
    r = c.reset(fixture(users=users, payments=payments))
    eq(r.status, 204, "reset")
    toks = {u["handle"]: c.token_for(u["handle"]) for u in users}
    before = [get_me(c, toks[h]) for h in ("ada", "bob")]
    # bob (original sender of p_b) back-dates p_b's effect before he was funded.
    expect_error(correct(c, toks["bob"], "p_b", "r199-k",
                         correction_body(1, 700, T0, "backdated")), 409,
                 "historical_overdraft",
                 "bob's balance would go negative at the back-dated boundary (R199)")
    after = [get_me(c, toks[h]) for h in ("ada", "bob")]
    eq([{k: v for k, v in b.items() if k in ("balance", "total", "available", "held")}
        for b in after],
       [{k: v for k, v in b.items() if k in ("balance", "total", "available", "held")}
        for b in before],
       "money fields preserved on historical_overdraft (R201)")
    eq(len(revisions_of(c, toks["bob"], "p_b")), 1, "no revision appended (R201)")
    # R201: the failed attempt frees the idempotency key.
    resp = correct(c, toks["bob"], "p_b", "r199-k",
                   correction_body(1, 700, T2, "retry-ok"))
    eq(resp.status, 201, "failed request frees the key for reuse (stage-1 R51/R201)")


def test_r200_combined_effect_at_same_instant(c):
    users = [fuser("u_ada", "ada", 500), fuser("u_bob", "bob", 0), fuser("u_cy", "cy", 500)]
    payments = [fpayment("p_a", "u_ada", "u_bob", 500, created_at=T2),
                fpayment("p_b", "u_bob", "u_cy", 500, created_at=T2)]
    r = c.reset(fixture(users=users, payments=payments))
    eq(r.status, 204, "reset")
    toks = {u["handle"]: c.token_for(u["handle"]) for u in users}
    # At T2 bob's movements combine to 0; checked sequentially in p_b-then-p_a
    # order bob would transiently go negative — R200 requires the combined read.
    resp = expect_ok(correct(c, toks["ada"], "p_a", "r200-k",
                             correction_body(1, 600, T2, "combined")), 201)
    eq(get_me(c, toks["ada"])["balance"], 400, "sender debited the delta")
    eq(get_me(c, toks["bob"])["balance"], 100, "bob's combined boundary stays nonnegative (R200)")
    eq(get_me(c, toks["cy"])["balance"], 500, "conservation at every wallet")


def test_a32_linked_payment_immutability_before_field_shape(c):
    toks = sfix(c)
    authz = expect_ok(c.post("/authorizations", body={"to_handle": "bob", "amount": 300},
                             token=toks["ada"], headers={"Idempotency-Key": "a32-authz"}), 201)
    cap = expect_ok(c.post(f"/authorizations/{authz['authorization_id']}/capture",
                           body={}, token=toks["bob"],
                           headers={"Idempotency-Key": "a32-cap"}), 201)
    expect_error(correct(c, toks["ada"], cap["payment_id"], "a32-corr",
                         {"expected_revision": "bad", "amount": "bad",
                          "effective_at": "bad", "reason": ""}),
                 422, "linked_payment_immutable",
                 "resource-shape fact checked before body field-shape (A32)")


def test_a33_no_correction_count_cap(c):
    toks = sfix(c)
    for i in range(5):
        resp = expect_ok(correct(c, toks["ada"], "p_s1", f"a33-{i}",
                                 correction_body(i + 1, 500 + i + 1, T1, f"step {i}")), 201)
        eq(resp["revision"], i + 2, f"revision {i + 2} appended (A33)")
    eq(len(revisions_of(c, toks["ada"], "p_s1")), 6, "six revisions after five corrections (A33)")


def test_r203_original_payment_and_idempotent_responses_unchanged(c):
    toks = sfix(c)
    orig = expect_ok(make_payment(c, toks["ada"], "bob", 333, "r203-k", note="orig"), 201)
    replay1 = expect_ok(make_payment(c, toks["ada"], "bob", 333, "r203-k", note="orig"), 200)
    check(replay1 == orig, "replay equals original 201 body (stage-1 R51)")
    pid = orig["payment_id"]
    expect_ok(correct(c, toks["ada"], pid, "r203-corr",
                      correction_body(1, 444, orig["created_at"], "changed")), 201)
    replay2 = make_payment(c, toks["ada"], "bob", 333, "r203-k", note="orig")
    eq(replay2.status, 200, "replay still 200 (R203)")
    check(replay2.json() == orig, "original idempotent response body unchanged by the correction (R203)")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    p = [x for x in feed if x["payment_id"] == pid][0]
    eq(p["amount"], 333, "original payment representation unchanged (R203)")


def test_r204_activity_unchanged_by_correction(c):
    toks = sfix(c)
    before = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    expect_ok(correct(c, toks["ada"], "p_s1", "r204-k",
                      correction_body(1, 400, T1, "feed")), 201)
    after = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    eq(after, before, "activity feed byte-identical across a correction (R204)")


def test_r205_revisions_listing(c):
    toks = sfix(c)
    expect_ok(correct(c, toks["ada"], "p_s1", "r205-k",
                      correction_body(1, 450, T1, "audit")), 201)
    revs = revisions_of(c, toks["ada"], "p_s1")
    eq([r["revision"] for r in revs], [1, 2], "ascending revision order (R205)")
    eq(revs[0]["reason"], "", "revision 1 reason empty (R205)")
    eq(revs[1]["reason"], "audit", "correction reason recorded (R205)")
    for r in revs:
        revision_keys_ok(r)


def test_r206_revisions_visibility(c):
    toks = sfix(c)
    expect_error(c.get("/payments/p_s1/revisions"), 401, "unauthenticated",
                 "no token (R206)")
    expect_error(c.get("/payments/p_s1/revisions", token=toks["cy"]), 404, "not_found",
                 "third party 404 even for a public payment (R206)")
    eq(revisions_of(c, toks["ada"], "p_s1")[0]["revision"], 1, "sender can read (R206)")
    eq(revisions_of(c, toks["bob"], "p_s1")[0]["revision"], 1, "receiver can read (R206)")


def test_a34_correction_effective_at_before_created_at_accepted(c):
    toks = sfix(c)
    resp = expect_ok(correct(c, toks["ada"], "p_s1", "a34-early",
                             correction_body(1, 450, T0, "earlier than created_at")), 201)
    eq(resp["effective_at"], T0, "effective_at unconstrained below created_at (A34/R189)")
    eq(get_me(c, toks["ada"])["balance"], 9350, "current reflects the corrected amount")
    from client import me_json
    eq(me_json(c, toks["ada"], as_of=T0)["balance"], 9550,
       "historical view at the back-dated instant includes the corrected amount (A34)")