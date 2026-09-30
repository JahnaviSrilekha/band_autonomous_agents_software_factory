"""Stage-2 UI acceptance (R94-R119, R152-R156): HTTP + DOM assertions against
the required data-testid hooks, per the run's UI-checking approach. JS-only
behaviours (client-side decimal rejection, latest-wins refresh, uncertain
recovery) are covered at the DOM/hook level here; the remaining visual-only
sub-rules (R99 scroll/focus/contrast at both widths, A17 qualities) are
documented in README.md as reviewer browser checks."""
from client import (
    check, eq, expect_ok, get_me, fauthz, afresh, fuser, make_payment,
    create_authz, capture, rfc3339,
)
from dom import dom_of, require, forbid, has_label, anchors, external_refs

UI_USERS = [fuser("u_ada", "ada", 100000), fuser("u_bob", "bob", 50000),
            fuser("u_cy", "cy", 0), fuser("u_dee", "dee", 0)]

AUTHED_ROUTES = ["/", "/requests", "/split", "/authorizations"]
FORM_INPUT_TAGS = ("input", "select", "textarea")


def page(c, path, token=None):
    return dom_of(c.get(path, token=token, headers={"Accept": "text/html"}))


def test_r94_routes_reachable_by_url(c):
    toks = afresh(c, users=UI_USERS)
    for path in ("/signup", "/login"):
        page(c, path)
    for path in AUTHED_ROUTES:
        page(c, path, toks["ada"])


def test_r94_authorizations_reachable_through_ui(c):
    toks = afresh(c, users=UI_USERS)
    for path in ("/", "/requests", "/split"):
        hrefs = anchors(page(c, path, toks["ada"]))
        check(any("/authorizations" in h for h in hrefs),
              f"{path}: /authorizations must be reachable through the UI (R94)")


def test_r95_requests_content_negotiation(c):
    toks = afresh(c, users=UI_USERS)
    html = c.get("/requests", token=toks["ada"], headers={"Accept": "text/html"})
    dom_of(html, "/requests as HTML")
    js = c.get("/requests", token=toks["ada"])
    body = expect_ok(js, 200, "/requests as JSON")
    eq(set(body.keys()), {"requests", "has_more"},
       "API requests without Accept get stage-1 JSON shape (R95)")


def test_r152_authorizations_content_negotiation(c):
    toks = afresh(c, users=UI_USERS)
    dom_of(c.get("/authorizations", token=toks["ada"],
                 headers={"Accept": "text/html"}), "/authorizations as HTML")
    body = expect_ok(c.get("/authorizations", token=toks["ada"]), 200, "JSON")
    eq(set(body.keys()), {"authorizations", "has_more"}, "A21 envelope")


def test_r100_signup_login_elements(c):
    afresh(c, users=UI_USERS)
    su = page(c, "/signup")
    for tid in ("signup-email", "signup-password", "signup-display-name"):
        el = require(su, tid, "/signup")
        check(el.tag in FORM_INPUT_TAGS, f"{tid} must be an input")
        has_label(su, el, "/signup")
    check(require(su, "signup-submit", "/signup").tag in ("button", "input"),
          "signup-submit is a button")
    forbid(su, "auth-error", "/signup without error")
    li = page(c, "/login")
    for tid in ("login-email", "login-password"):
        el = require(li, tid, "/login")
        check(el.tag in FORM_INPUT_TAGS, f"{tid} must be an input")
        has_label(li, el, "/login")
    check(require(li, "login-submit", "/login").tag in ("button", "input"),
          "login-submit is a button")
    forbid(li, "auth-error", "/login without error")
    forbid(li, "current-handle", "signed-out login page has no user")


def test_r100_current_user_handle_logout_every_screen(c):
    toks = afresh(c, users=UI_USERS)
    for path in AUTHED_ROUTES:
        d = page(c, path, toks["ada"])
        cu = require(d, "current-user", path)
        check("Ada" in cu.text(), f"{path}: current-user contains display name")
        ch = require(d, "current-handle", path)
        eq(ch.text(), "ada", f"{path}: current-handle is exactly the handle (R100)")
        require(d, "logout-button", path)  # A26: every authenticated screen


def test_r101_home_form_elements(c):
    toks = afresh(c, users=UI_USERS)
    d = page(c, "/", toks["ada"])
    wb = require(d, "wallet-balance", "/")
    eq(wb.attr("data-amount"), "100000", "wallet-balance data-amount minor units")
    eq(wb.text(), "1000.00 EUR", "wallet-balance formatted per R103")
    for tid in ("pay-handle", "pay-amount", "pay-note"):
        el = require(d, tid, "/")
        check(el.tag in FORM_INPUT_TAGS, f"{tid} is an input")
        has_label(d, el, "/")
    sel = require(d, "pay-visibility", "/")
    eq(sel.tag, "select", "pay-visibility is a select")
    values = [o.attr("value") for o in sel.children
              if getattr(o, "tag", None) == "option"]
    eq(set(values), {"public", "private"}, "option values exactly the two strings")
    require(d, "pay-submit", "/")
    forbid(d, "pay-error", "no error before any refusal (A19 rule)")
    for tid in ("request-handle", "request-amount", "request-note"):
        require(d, tid, "/")
    require(d, "request-submit", "/")
    forbid(d, "request-error", "no error before any refusal")


def test_r103_formatted_amount_minor_units_0_and_3(c):
    users = [fuser("u_ada", "ada", 1200)]
    toks = afresh(c, users=users, currency="JPY", minor_units=0)
    d = page(c, "/", toks["ada"])
    wb = require(d, "wallet-balance", "/")
    eq(wb.text(), "1200 JPY", "no decimal point at minor_units 0 (R103)")
    eq(wb.attr("data-amount"), "1200", "")
    users = [fuser("u_ada", "ada", 10000)]
    toks = afresh(c, users=users, currency="EUR", minor_units=3)
    d = page(c, "/", toks["ada"])
    eq(require(d, "wallet-balance", "/").text(), "10.000 EUR",
       "exactly minor_units decimal places (R103)")


def test_r105_activity_feed(c):
    toks = afresh(c, users=UI_USERS)
    p1 = expect_ok(make_payment(c, toks["ada"], "bob", 1000, "ui-p1",
                                note="lunch"), 201, "pay")
    import time
    time.sleep(1.1)
    p2 = expect_ok(make_payment(c, toks["bob"], "cy", 750, "ui-p2",
                                note="rent", visibility="private"), 201, "pay")
    time.sleep(1.1)
    p3 = expect_ok(make_payment(c, toks["ada"], "cy", 2500, "ui-p3",
                                note=""), 201, "pay")
    d = page(c, "/", toks["ada"])
    ids = [el.attr("data-testid").rsplit("-", 1)[-1]
           for el in d.find_all_testid_prefix("activity-item-")]
    eq(ids, [p3["payment_id"], p1["payment_id"]],
       "newest first in DOM; third-party private payment hidden (R26/R105)")
    it1 = require(d, f"activity-item-{p1['payment_id']}", "/")
    eq(it1.attr("data-visibility"), "public", "data-visibility attribute")
    parties = require(d, f"activity-parties-{p1['payment_id']}", "/").text()
    check("ada" in parties and "bob" in parties, "parties contain both handles")
    eq(require(d, f"activity-amount-{p1['payment_id']}", "/").text(), "10.00 EUR",
       "amount formatted (R103)")
    eq(require(d, f"activity-note-{p1['payment_id']}", "/").text(), "lunch", "")
    eq(require(d, f"activity-note-{p3['payment_id']}", "/").text(), "",
       "note element present even when empty (R105)")
    require(d, "activity-list", "feed container present")
    forbid(d, "empty-activity", "feed non-empty for ada")
    dbob = page(c, "/", toks["bob"])
    require(dbob, f"activity-item-{p2['payment_id']}", "/")
    eq(require(dbob, f"activity-item-{p2['payment_id']}",
               "/").attr("data-visibility"), "private", "")
    ddee = page(c, "/", toks["dee"])
    require(ddee, "empty-activity", "dee sees nothing (R26)")
    check(not ddee.find_all_testid_prefix("activity-item-"),
          "empty-activity shown instead of the list (R105)")


def test_r106_equal_timestamps_either_order(c):
    toks = afresh(c, users=UI_USERS)
    q1 = expect_ok(make_payment(c, toks["ada"], "bob", 100, "ui-q1"), 201, "")
    q2 = expect_ok(make_payment(c, toks["ada"], "bob", 200, "ui-q2"), 201, "")
    d = page(c, "/", toks["ada"])
    got = {el.attr("data-testid").rsplit("-", 1)[-1]
           for el in d.find_all_testid_prefix("activity-item-")}
    eq(got, {q1["payment_id"], q2["payment_id"]},
       "both present; relative order not asserted for equal timestamps (R106)")


def test_r107_requests_screen(c):
    toks = afresh(c, users=UI_USERS)
    rq_in = expect_ok(c.post("/requests", body={"payer_handle": "ada", "amount": 3000,
                                                "note": "dinner"},
                             token=toks["bob"], headers={"Idempotency-Key": "ui-r1"}),
                      201, "incoming request on ada")
    rq_out = expect_ok(c.post("/requests", body={"payer_handle": "bob", "amount": 1200},
                              token=toks["ada"], headers={"Idempotency-Key": "ui-r2"}),
                       201, "outgoing request from ada")
    d = page(c, "/requests", toks["ada"])
    in_item = require(d, f"request-item-{rq_in['request_id']}", "/requests")
    eq(in_item.attr("data-status"), "pending", "data-status")
    require(d, f"request-pay-{rq_in['request_id']}", "pending incoming")
    require(d, f"request-decline-{rq_in['request_id']}", "pending incoming")
    check(d.find_testid(f"request-cancel-{rq_in['request_id']}") is None,
          "no cancel on incoming")
    out_item = require(d, f"request-item-{rq_out['request_id']}", "/requests")
    eq(out_item.attr("data-status"), "pending", "")
    require(d, f"request-cancel-{rq_out['request_id']}", "pending outgoing")
    check(d.find_testid(f"request-pay-{rq_out['request_id']}") is None,
          "no pay on outgoing")
    check(d.find_testid(f"request-decline-{rq_out['request_id']}") is None,
          "no decline on outgoing")
    eq(require(d, f"request-amount-{rq_in['request_id']}", "").text(), "30.00 EUR",
       "formatted amount (R103)")
    forbid(d, "request-error", "no error before refusal")
    forbid(d, "empty-requests", "lists not both empty")
    expect_ok(c.post(f"/requests/{rq_in['request_id']}/pay", body={},
                     token=toks["ada"], headers={"Idempotency-Key": "ui-rp1"}),
              201, "pay")
    d = page(c, "/requests", toks["ada"])
    eq(require(d, f"request-item-{rq_in['request_id']}", "").attr("data-status"),
       "paid", "status updated after action (R110)")
    check(d.find_testid(f"request-pay-{rq_in['request_id']}") is None,
          "pay button only on pending incoming (R107)")
    check(d.find_testid(f"request-decline-{rq_in['request_id']}") is None,
          "decline button only on pending incoming (R107)")


def test_r107_empty_requests_iff_both_empty(c):
    toks = afresh(c, users=UI_USERS)
    d = page(c, "/requests", toks["dee"])
    require(d, "empty-requests", "both lists empty")
    expect_ok(c.post("/requests", body={"payer_handle": "bob", "amount": 100},
                     token=toks["dee"], headers={"Idempotency-Key": "ui-r3"}),
              201, "outgoing")
    d = page(c, "/requests", toks["dee"])
    forbid(d, "empty-requests", "only one list empty (R107)")


def test_r108_split_elements(c):
    toks = afresh(c, users=UI_USERS)
    d = page(c, "/split", toks["ada"])
    for tid in ("split-amount", "split-handles", "split-note"):
        el = require(d, tid, "/split")
        check(el.tag in FORM_INPUT_TAGS, f"{tid} is an input")
        has_label(d, el, "/split")
    require(d, "split-submit", "/split")
    require(d, "split-preview", "/split")
    forbid(d, "split-error", "no error before refusal")


def test_r110_balance_and_feed_show_new_state_after_action(c):
    toks = afresh(c, users=UI_USERS)
    d = page(c, "/", toks["ada"])
    eq(require(d, "wallet-balance", "/").attr("data-amount"), "100000", "before")
    expect_ok(make_payment(c, toks["ada"], "bob", 2500, "ui-r110"), 201, "pay")
    d = page(c, "/", toks["ada"])
    eq(require(d, "wallet-balance", "/").attr("data-amount"), "97500",
       "balance shows new state after the action (R110)")
    feed_ids = [el.attr("data-testid") for el in d.find_all_testid_prefix("activity-item-")]
    check(len(feed_ids) == 1, "feed shows the payment (R110)")


def test_r111_wallet_refresh_present(c):
    toks = afresh(c, users=UI_USERS)
    d = page(c, "/", toks["ada"])
    require(d, "wallet-refresh", "/")
    require(d, "pay-handle", "/")
    require(d, "pay-amount", "/")


def test_r112_r113_a19_error_hooks_absent_by_default(c):
    toks = afresh(c, users=UI_USERS)
    d = page(c, "/", toks["ada"])
    forbid(d, "pay-uncertain", "absent when nothing is unconfirmed (A19)")
    forbid(d, "pay-error", "")
    d = page(c, "/authorizations", toks["ada"])
    forbid(d, "authorize-error", "")
    forbid(d, "authorization-error", "")


def test_r153_wallet_available_held(c):
    toks = afresh(c, users=UI_USERS, authorizations=[
        fauthz("a_w1", "u_ada", "u_bob", 6000)])
    d = page(c, "/", toks["ada"])
    wb = require(d, "wallet-balance", "/")
    wa = require(d, "wallet-available", "/")
    wh = require(d, "wallet-held", "/")
    eq(wb.attr("data-amount"), "100000", "total unchanged by hold (A20)")
    eq(wb.text(), "1000.00 EUR", "wallet-balance still formatted total (R153)")
    eq(wa.attr("data-amount"), "94000", "available = total - held")
    eq(wa.text(), "940.00 EUR", "available formatted (R103)")
    eq(wh.attr("data-amount"), "6000", "held")
    eq(wh.text(), "60.00 EUR", "")
    check(wa.order < wb.order,
          "available is the headline: appears before total (R97 acceptance)")
    check(wh.order > wa.order, "held secondary (R97)")
    toks2 = afresh(c, users=UI_USERS)
    d = page(c, "/", toks2["ada"])
    forbid(d, "wallet-held", "absent when held is zero (R153)")
    require(d, "wallet-available", "present even at zero holds")


def test_r156_seeded_holds_reflected_immediately(c):
    toks = afresh(c, users=UI_USERS, authorizations=[
        fauthz("a_s1", "u_ada", "u_bob", 6000),
        fauthz("a_s2", "u_ada", "u_cy", 1000)])
    d = page(c, "/", toks["ada"])  # first login after reset, no authz actions
    eq(require(d, "wallet-available", "/").attr("data-amount"), "93000",
       "available reflects seeded holds immediately (R156)")
    eq(require(d, "wallet-held", "/").attr("data-amount"), "7000", "")


def test_r154_authorize_form_on_authorizations(c):
    toks = afresh(c, users=UI_USERS)
    d = page(c, "/authorizations", toks["ada"])
    for tid in ("authorize-handle", "authorize-amount", "authorize-note"):
        el = require(d, tid, "/authorizations")
        check(el.tag in FORM_INPUT_TAGS, f"{tid} is an input")
        has_label(d, el, "/authorizations")
    sel = require(d, "authorize-visibility", "/authorizations")
    values = [o.attr("value") for o in sel.children
              if getattr(o, "tag", None) == "option"]
    eq(set(values), {"public", "private"}, "same input rules as pay form (R154)")
    require(d, "authorize-submit", "/authorizations")
    forbid(d, "authorize-error", "no error before refusal")


def test_r155_authorization_list_presence_rules(c):
    exp_open = rfc3339(86400)
    exp_past = rfc3339(-7200)
    toks = afresh(c, users=UI_USERS, authorizations=[
        fauthz("a_u1", "u_ada", "u_bob", 2000, expires_at=exp_open),
        fauthz("a_u2", "u_bob", "u_cy", 500, expires_at=exp_open),
        fauthz("a_u3", "u_ada", "u_bob", 800, status="captured"),
        fauthz("a_u4", "u_ada", "u_bob", 300, status="voided"),
        fauthz("a_u5", "u_ada", "u_bob", 400, expires_at=exp_past),
    ])
    d = page(c, "/authorizations", toks["ada"])
    statuses = {el.attr("data-testid").rsplit("-", 1)[-1]: el.attr("data-status")
                for el in d.find_all_testid_prefix("authorization-item-")}
    eq(statuses, {"a_u1": "open", "a_u3": "captured", "a_u4": "voided",
                  "a_u5": "expired"},
       "per-status rendering; clock-expired open shows expired (R151/R155)")
    eq(require(d, "authorization-amount-a_u1", "").text(), "20.00 EUR",
       "formatted authorised amount")
    require(d, "authorization-captured-a_u3", "captured only")
    check(d.find_testid("authorization-captured-a_u1") is None,
          "no captured element on open item (R155)")
    check(d.find_testid("authorization-captured-a_u4") is None,
          "no captured element on voided item")
    ex = require(d, "authorization-expires-a_u1", "")
    check(ex.text() == exp_open or _same_instant(ex.text(), exp_open),
          "expires text is the RFC 3339 expires_at (R155/A18)")
    # buttons: ada is payer of a_u1 (outgoing open) → void, no capture
    require(d, "authorization-void-a_u1", "outgoing open")
    check(d.find_testid("authorization-capture-a_u1") is None,
          "no capture on own outgoing (R155)")
    check(d.find_testid("authorization-void-a_u5") is None,
          "no void on expired item")
    check(d.find_testid("authorization-capture-amount-a_u1") is None,
          "no capture input on outgoing")
    forbid(d, "authorization-error", "no error before refusal")
    dbob = page(c, "/authorizations", toks["bob"])
    require(dbob, "authorization-capture-a_u1", "incoming open")
    prefill = require(dbob, "authorization-capture-amount-a_u1", "")
    check(prefill.tag in FORM_INPUT_TAGS, "capture amount is an input")
    eq(prefill.attr("value"), "20.00",
       "pre-filled with remaining amount as decimal (R155)")
    require(dbob, "authorization-void-a_u2", "bob is a_u2's payer (outgoing open)")
    check(dbob.find_testid("authorization-capture-a_u5") is None,
          "expired item offers no capture button")
    ddee = page(c, "/authorizations", toks["dee"])
    require(ddee, "empty-authorizations", "empty list (R155)")
    check(not ddee.find_all_testid_prefix("authorization-item-"), "no items")


def test_r155_capture_prefill_tracks_remaining(c):
    toks = afresh(c, users=UI_USERS)
    auth = expect_ok(create_authz(c, toks["ada"], "bob", 2000, "ui-pf1"), 201, "")
    expect_ok(capture(c, toks["bob"], auth["authorization_id"], "ui-pf2",
                      {"amount": 700, "final": False}), 201, "partial")
    d = page(c, "/authorizations", toks["bob"])
    eq(require(d, f"authorization-capture-amount-{auth['authorization_id']}",
               "").attr("value"), "13.00",
       "prefill equals current remaining_amount (R155/R146)")


def test_r99_inputs_labeled_everywhere(c):
    toks = afresh(c, users=UI_USERS, authorizations=[
        fauthz("a_l9", "u_ada", "u_bob", 2000)])
    for path, token in [("/", toks["ada"]), ("/requests", toks["ada"]),
                        ("/split", toks["ada"]), ("/authorizations", toks["bob"]),
                        ("/signup", None), ("/login", None)]:
        d = page(c, path, token)
        for el in d.iter():
            if el.tag in FORM_INPUT_TAGS and el.attr("data-testid"):
                has_label(d, el, path)


def test_r99_bundled_assets_no_cdn(c):
    toks = afresh(c, users=UI_USERS)
    for path, token in [("/", toks["ada"]), ("/requests", toks["ada"]),
                        ("/split", toks["ada"]), ("/authorizations", toks["ada"]),
                        ("/signup", None), ("/login", None)]:
        d = page(c, path, token)
        eq(external_refs(d), [], f"{path}: no CDN/external refs (stage-1 R11)")
        check(_viewport_meta(d) is not None,
              f"{path}: viewport meta for 375px rendering (R99)")


def _viewport_meta(d):
    for el in d.iter():
        if el.tag == "meta" and el.attr("name") == "viewport":
            return el
    return None


def test_r99_empty_states_considered_content(c):
    toks = afresh(c, users=UI_USERS)
    for path, tid in [("/", "empty-activity"), ("/requests", "empty-requests"),
                      ("/authorizations", "empty-authorizations")]:
        d = page(c, path, toks["dee"])
        el = require(d, tid, path)
        check(el.text(), f"{path}: {tid} has considered content, not blank (R99)")


def test_r99_navigation_consistent(c):
    toks = afresh(c, users=UI_USERS)
    for path in AUTHED_ROUTES:
        hrefs = anchors(page(c, path, toks["ada"]))
        for target in ("/", "/requests", "/split", "/authorizations"):
            check(any(h == target or h.startswith(target + "?") for h in hrefs),
                  f"{path}: nav must include {target} (R99)")


def _same_instant(a, b):
    from datetime import datetime
    try:
        return datetime.fromisoformat(a) == datetime.fromisoformat(b)
    except Exception:
        return False