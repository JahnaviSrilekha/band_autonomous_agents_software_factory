"""Stage-2 upgrade acceptance (R115-R119): a stage-2 service must accept an
export produced by the same team's stage-1 service; sessions, pending requests
and lost-response retries survive the import boundary.

The fixture file is a real export captured from the team's verified stage-1
service (a data artifact, not implementation source): it contains the export
body, tokens that were valid pre-export, the body+key of a payment whose
response was "lost", and a pending request id."""
import json
import os

from client import check, eq, expect_ok, expect_error, get_me
from dom import dom_of, require

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = json.load(open(os.path.join(HERE, "fixtures", "stage1_upgrade.json")))


def _import_v1(c):
    r = c.import_state(FIXTURE["export"])
    eq(r.status, 204, "stage-1 format_version:1 export accepted (R115)")


def test_r115_import_stage1_export(c):
    af_reset = c.reset({"currency": "EUR", "minor_units": 2, "users": []})
    eq(af_reset.status, 204, "start from an empty service")
    _import_v1(c)
    me = expect_ok(c.get("/me", token=FIXTURE["tokens"]["ada"]), 200, "me")
    eq(me["balance"], 100000 - 2500 - 1000, "imported balances load (stage-1 R82); "
       "unpaid split requests moved nothing")


def test_r116_pre_import_token_still_authenticated(c):
    _import_v1(c)
    me = expect_ok(c.get("/me", token=FIXTURE["tokens"]["ada"]), 200, "me")
    eq(me["handle"], "ada", "token obtained before the upgrade still works (R116)")


def test_r82_r115_login_password_preserved(c):
    _import_v1(c)
    tok = expect_ok(c.login("ada@example.com", "correct horse"), 200, "login")
    eq(expect_ok(c.get("/me", token=tok["token"]), 200, "me")["handle"], "ada",
       "hashed-password login preserved (stage-1 R82 via R115)")


def test_r117_pending_request_still_payable(c):
    _import_v1(c)
    rid = FIXTURE["pending_request_id"]
    rqs = expect_ok(c.get("/requests?direction=incoming&status=pending",
                          token=FIXTURE["tokens"]["ada"]), 200, "requests")
    check(any(r["request_id"] == rid for r in rqs["requests"]),
          "imported pending request is pending")
    d = dom_of(c.get("/requests", token=FIXTURE["tokens"]["ada"],
                     headers={"Accept": "text/html"}), "/requests")
    require(d, f"request-pay-{rid}", "request screen (R117)")
    before = get_me(c, FIXTURE["tokens"]["bob"])["total"]
    pay = expect_ok(c.post(f"/requests/{rid}/pay", body={},
                           token=FIXTURE["tokens"]["ada"],
                           headers={"Idempotency-Key": "post-import-pay"}),
                    201, "pay after import")
    eq(pay["request_id"], rid, "")
    eq(get_me(c, FIXTURE["tokens"]["bob"])["total"], before + 3000,
       "money moved once through the upgraded service")


def test_r118_lost_response_retry_after_import(c):
    _import_v1(c)
    lp = FIXTURE["lost_payment"]
    ada_before = get_me(c, FIXTURE["tokens"]["ada"])["total"]
    bob_before = get_me(c, FIXTURE["tokens"]["bob"])["total"]
    r = c.post("/payments", body=lp["body"], token=FIXTURE["tokens"]["ada"],
               headers={"Idempotency-Key": lp["key"]})
    eq(r.status, 200, "replay after import returns replay status (R118)")
    eq(r.json()["payment_id"], lp["payment_id"], "original payment recovered (R118)")
    eq(r.json()["amount"], 2500, "original body")
    eq(get_me(c, FIXTURE["tokens"]["ada"])["total"], ada_before, "no money moved again")
    eq(get_me(c, FIXTURE["tokens"]["bob"])["total"], bob_before, "exactly-once across upgrade")


def test_r118_r116_ui_signed_in_and_consistent_after_import(c):
    _import_v1(c)
    d = dom_of(c.get("/", token=FIXTURE["tokens"]["ada"],
                     headers={"Accept": "text/html"}), "/")
    require(d, "current-handle", "browser session concept survives import (R116)")
    eq(require(d, "current-handle", "/").text(), "ada", "same user")


def test_r115_import_v1_defaults_authz_fields(c):
    _import_v1(c)
    me = get_me(c, FIXTURE["tokens"]["ada"])
    eq(me["held"], 0, "no authorizations imported from v1 (ADR-006)")
    eq(me["available"], me["total"], "available agrees")
    auth = expect_ok(c.post("/authorizations", body={"to_handle": "bob", "amount": 500},
                            token=FIXTURE["tokens"]["ada"],
                            headers={"Idempotency-Key": "post-import-authz"}),
                     201, "create after v1 import")
    from datetime import datetime
    delta = (datetime.fromisoformat(auth["expires_at"])
             - datetime.fromisoformat(auth["created_at"])).total_seconds()
    check(abs(delta - 600) < 1, "v1 import defaults ttl to 600 (ADR-006/R131)")


def test_r119_import_between_browser_requests(c):
    """Import completing between browser requests: page → import → page."""
    tok = FIXTURE["tokens"]["ada"]
    d1 = dom_of(c.get("/", token=tok, headers={"Accept": "text/html"}), "/ pre-import")
    check(d1 is not None, "page renders pre-import")
    _import_v1(c)
    d2 = dom_of(c.get("/", token=tok, headers={"Accept": "text/html"}), "/ post-import")
    eq(require(d2, "wallet-balance", "/").attr("data-amount"),
       str(get_me(c, tok)["total"]),
       "imported state shown; no reload beyond the next request (R119)")
    # and a v2 export of the imported state round-trips (stage-1 R78/R79 still hold)
    exp = expect_ok(c.export(), 200, "export v2")
    eq(exp["format_version"], 2, "stage-2 exports v2 (ADR-006)")
    eq(c.import_state(exp).status, 204, "v2 round trip accepted")
    eq(get_me(c, tok)["balance"], get_me(c, tok)["total"], "state stable after round trip")