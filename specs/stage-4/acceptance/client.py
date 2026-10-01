"""Shared HTTP client and helpers for the pocketful stage-4 acceptance suite.

Black-box only: talks to the running service over HTTP, per specs/stage-4/
requirements.md (which carries stage-1/stage-2/stage-3 requirements forward by
reference). Stdlib only. Per-request timeout 5s, 10s for /_test/* endpoints
(stage-1 R10).

This module is a strict superset of specs/stage-3/acceptance/client.py (same
helper names/signatures) so the stage-1, stage-2 and stage-3 regression
modules run unmodified against the stage-4 service while sharing one client
implementation.
"""
import json
import re
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection

REQUEST_TIMEOUT = 5.0
TEST_TIMEOUT = 10.0

RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$"
)

PASSWORD = "correct horse"


class SuiteFailure(AssertionError):
    pass


def check(cond, msg):
    if not cond:
        raise SuiteFailure(msg)


def eq(actual, expected, msg):
    check(actual == expected, f"{msg}: expected {expected!r}, got {actual!r}")


def expect_error(resp, status, code, what=""):
    """Assert a 4xx body conforms to stage-1 R35 and carries the specified code."""
    check(
        status <= 499,
        f"expect_error: non-4xx status requested ({status})",
    )
    if resp.status != status:
        raise SuiteFailure(
            f"{what}: expected HTTP {status} {code}, got {resp.status}: "
            f"{resp.raw[:300]!r}"
        )
    check(
        "application/json" in resp.content_type,
        f"{what}: {status} response content-type not JSON: {resp.content_type!r}",
    )
    body = resp.json()
    check(isinstance(body, dict) and "error" in body, f"{what}: error body shape: {body!r}")
    check(
        set(body.keys()) == {"error"},
        f"{what}: error body has unexpected top-level keys: {sorted(body.keys())}",
    )
    err = body["error"]
    check(isinstance(err, dict), f"{what}: error member not an object: {err!r}")
    eq(err.get("code"), code, f"{what}: error code")
    check(
        isinstance(err.get("message"), str) and err.get("message"),
        f"{what}: error.message must be a non-empty string: {err!r}",
    )


def expect_ok(resp, status, what="response"):
    if resp.status != status:
        raise SuiteFailure(f"expected {status} for {what}, got {resp.status}: {resp.raw[:300]!r}")
    return resp.json()


class Response:
    def __init__(self, status, headers, raw):
        self.status = status
        self.headers = {k.lower(): v for k, v in headers}
        self.raw = raw

    @property
    def content_type(self):
        return self.headers.get("content-type", "")

    def json(self):
        try:
            return json.loads(self.raw.decode("utf-8"))
        except Exception:
            raise SuiteFailure(
                f"body is not valid JSON (status {self.status}): {self.raw[:300]!r}"
            )


class Client:
    def __init__(self, base):
        u = urllib.parse.urlparse(base if "://" in base else "http://" + base)
        check(u.scheme == "http", f"unsupported base URL scheme: {base!r}")
        self.host = u.hostname or "127.0.0.1"
        self.port = u.port or 80
        self.prefix = (u.path or "").rstrip("/")
        self.cookie = None  # echo any session cookie the UI hands out, if any

    def request(self, method, path, body=None, *, token=None, headers=None,
                raw_body=None, timeout=REQUEST_TIMEOUT):
        conn = HTTPConnection(self.host, self.port, timeout=timeout)
        hdrs = dict(headers or {})
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        if self.cookie:
            hdrs.setdefault("Cookie", self.cookie)
        payload = None
        if raw_body is not None:
            payload = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
            hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
        elif body is not None:
            payload = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
        try:
            conn.request(method, self.prefix + path, body=payload, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
            set_cookie = resp.getheader("Set-Cookie")
            if set_cookie:
                self.cookie = set_cookie.split(";")[0]
            return Response(resp.status, resp.getheaders(), data)
        except Exception as e:
            raise SuiteFailure(f"{method} {path} transport error: {e!r}")
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body, **kw)

    # -- test-control endpoints (10s timeout, stage-1 R10) --

    def reset(self, fixture_body):
        return self.request("POST", "/_test/reset", body=fixture_body, timeout=TEST_TIMEOUT)

    def export(self):
        return self.get("/_test/export", timeout=TEST_TIMEOUT)

    def import_state(self, obj):
        return self.request("POST", "/_test/import", body=obj, timeout=TEST_TIMEOUT)

    # -- auth --

    def signup(self, email, password=PASSWORD, display_name="Ada"):
        return self.post("/auth/signup", body={
            "email": email, "password": password, "display_name": display_name,
        })

    def login(self, email, password=PASSWORD):
        return self.post("/auth/login", body={"email": email, "password": password})

    def token_for(self, handle):
        r = self.login(f"{handle}@example.com")
        token = expect_ok(r, 200, f"login {handle}").get("token")
        self.prime_session(token)
        return token

    def prime_session(self, token):
        """A28: authenticated page routes authenticate via a session cookie
        (`pocketful_token`, the bearer token URL-encoded) that the page's
        client script sets after login/signup — the server never sends
        Set-Cookie. A pure-HTTP client mirrors that contract here; the JSON
        API keeps its bearer-token contract unchanged."""
        self.cookie = f"pocketful_token={urllib.parse.quote(token, safe='')}"


# -- fixtures --

def fuser(uid, handle, balance, email=None, password=PASSWORD):
    return {
        "id": uid, "email": email or f"{handle}@example.com", "password": password,
        "display_name": handle.capitalize(), "handle": handle, "balance": balance,
    }


def fixture(users=None, payments=None, requests=None, currency="EUR",
            minor_units=2, operators=None, extra=None):
    f = {
        "currency": currency,
        "minor_units": minor_units,
        "users": users if users is not None else [],
        "payments": payments if payments is not None else [],
        "requests": requests if requests is not None else [],
    }
    if operators is not None:
        f["settlement_operator_ids"] = operators
    if extra:
        f.update(extra)
    return f


def rfc3339(offset_seconds):
    """Absolute RFC 3339 timestamp `offset_seconds` from now (R16 style, +00:00)."""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def fauthz(aid, from_user_id, to_user_id, amount, status="open",
           expires_at=None, note="deposit", visibility="public", created_at=None):
    """Seeded authorization per stage-2 R130/R134; stage-3 R248/A35 adds the
    optional seeded `created_at` (creation event time for historical views).

    `expires_at` defaults to 24h from now (R137: seeded times are at least an
    hour from reset time). Pass a past timestamp to seed an expired hold.
    """
    a = {
        "id": aid, "from_user_id": from_user_id, "to_user_id": to_user_id,
        "amount": amount, "note": note, "visibility": visibility,
        "status": status, "expires_at": expires_at or rfc3339(86400),
    }
    if created_at is not None:
        a["created_at"] = created_at
    return a


def afixture(users=None, authorizations=None, ttl=None, **kw):
    """Stage-2 fixture (R130): optional `authorizations` array and service-wide
    `authorization_ttl_seconds` (omitted from the fixture entirely when None)."""
    f = fixture(users=users, **kw)
    if authorizations is not None:
        f["authorizations"] = authorizations
    if ttl is not None:
        f["authorization_ttl_seconds"] = ttl
    return f


STANDARD_USERS = [
    fuser("u_ada", "ada", 100000),
    fuser("u_bob", "bob", 50000),
    fuser("u_cy", "cy", 0),
]

OPERATOR_USERS = STANDARD_USERS + [fuser("u_op", "op", 10000)]


def fresh(c, operator=False, users=None, operators=None, **kw):
    """Reset to the standard fixture; return {handle: token} for seeded users."""
    if users is None:
        users = OPERATOR_USERS if operator else STANDARD_USERS
    if operator and operators is None:
        operators = ["u_op"]
    r = c.reset(fixture(users=users, operators=operators, **kw))
    check(r.status == 204, f"reset failed: HTTP {r.status}: {r.raw[:300]!r}")
    handles = [u["handle"] for u in users]
    return {h: c.token_for(h) for h in handles}


def afresh(c, users=None, authorizations=None, ttl=None, operator=False,
           operators=None, **kw):
    """Reset with a stage-2/3 fixture; return {handle: token}."""
    if users is None:
        users = OPERATOR_USERS if operator else STANDARD_USERS
    if operator and operators is None:
        operators = ["u_op"]
    r = c.reset(afixture(users=users, authorizations=authorizations, ttl=ttl,
                         operators=operators, **kw))
    check(r.status == 204, f"reset failed: HTTP {r.status}: {r.raw[:300]!r}")
    return {u["handle"]: c.token_for(u["handle"]) for u in users}


def payment_body(to_handle, amount, note=None, visibility=None, extra=None):
    b = {"to_handle": to_handle, "amount": amount}
    if note is not None:
        b["note"] = note
    if visibility is not None:
        b["visibility"] = visibility
    if extra:
        b.update(extra)
    return b


def make_payment(c, token, to_handle, amount, key, note=None, visibility=None, **kw):
    return c.post("/payments", body=payment_body(to_handle, amount, note, visibility, **kw),
                  token=token, headers={"Idempotency-Key": key})


def get_me(c, token):
    return expect_ok(c.get("/me", token=token), 200, "GET /me")


def balances_sum(c, tokens):
    return sum(get_me(c, t)["balance"] for t in tokens.values())


# -- stage 2: authorizations (R139-R150) --

AUTHZ_KEYS = {
    "authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
    "amount", "captured_amount", "currency", "note", "visibility", "status",
    "expires_at", "payment_id", "created_at", "remaining_amount", "payment_ids",
}

ME_KEYS = {
    "user_id", "display_name", "handle", "balance", "total", "available",
    "held", "currency", "minor_units",
}

# stage-1 R56 payment shape + stage-2 R143 authorization_id + stage-4 R264 refund_of
PAYMENT_KEYS = {
    "payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
    "amount", "currency", "note", "visibility", "request_id", "created_at",
    "settlement_id", "authorization_id", "refund_of",
}


def authz_body(to_handle, amount, note=None, visibility=None, extra=None):
    b = {"to_handle": to_handle, "amount": amount}
    if note is not None:
        b["note"] = note
    if visibility is not None:
        b["visibility"] = visibility
    if extra:
        b.update(extra)
    return b


def create_authz(c, token, to_handle, amount, key, note=None, visibility=None, **kw):
    return c.post("/authorizations", body=authz_body(to_handle, amount, note, visibility, **kw),
                  token=token, headers={"Idempotency-Key": key})


def capture(c, token, aid, key, body=None):
    return c.post(f"/authorizations/{aid}/capture", body=body if body is not None else {},
                  token=token, headers={"Idempotency-Key": key})


def void_authz(c, token, aid, headers=None):
    return c.post(f"/authorizations/{aid}/void", body={}, token=token, headers=headers)


def list_authz(c, token, direction=None, status=None, limit=None, offset=None):
    q = []
    if direction is not None:
        q.append(f"direction={direction}")
    if status is not None:
        q.append(f"status={status}")
    if limit is not None:
        q.append(f"limit={limit}")
    if offset is not None:
        q.append(f"offset={offset}")
    path = "/authorizations" + ("?" + "&".join(q) if q else "")
    return c.get(path, token=token)


def get_authz_list(c, token, **kw):
    r = expect_ok(list_authz(c, token, **kw), 200, "GET /authorizations")
    check(isinstance(r, dict) and set(r.keys()) == {"authorizations", "has_more"},
          f"GET /authorizations envelope per A21: {sorted(r.keys())}")
    check(isinstance(r["has_more"], bool), "has_more must be bool (A21)")
    return r["authorizations"]


def all_totals(c, tokens):
    return {h: get_me(c, t)["total"] for h, t in tokens.items()}


# -- concurrency --

def run_concurrently(fns):
    """Run callables on parallel threads; return their results in order.
    Raises the first exception/error response encountered."""
    results = [None] * len(fns)
    errors = [None] * len(fns)

    def wrap(i, fn):
        try:
            results[i] = fn()
        except BaseException as e:  # noqa: BLE001 - collected below
            errors[i] = e

    threads = [threading.Thread(target=wrap, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for e in errors:
        if e is not None:
            raise e
    return results


def formatted(amount_minor, minor_units, currency):
    """R103: decimal with exactly minor_units places, single space, currency code.
    No decimal point at all when minor_units is 0. Never negative."""
    check(amount_minor >= 0, "formatted(): balances are never negative")
    if minor_units == 0:
        dec = str(amount_minor)
    else:
        s = str(amount_minor).rjust(minor_units + 1, "0")
        dec = f"{s[:-minor_units]}.{s[-minor_units:]}"
    return f"{dec} {currency}"


# -- stage 3: temporal instants, corrections, statements, revisions --

def inst(dt):
    """RFC 3339 instant string (+00:00) from a datetime."""
    return dt.astimezone(timezone.utc).isoformat()


def parse_inst(s):
    """Parse an RFC 3339 instant with offset (A34-family comparisons)."""
    return datetime.fromisoformat(s)


def shift(s, microseconds):
    """RFC 3339 instant `microseconds` away from instant string `s` (signed)."""
    return inst(parse_inst(s) + timedelta(microseconds=microseconds))


def mid(a, b):
    """An instant strictly between two instants (assumes a < b)."""
    return inst(parse_inst(a) + (parse_inst(b) - parse_inst(a)) / 2)


def fpayment(pid, from_uid, to_uid, amount, created_at=None, note="seed",
             visibility="public"):
    """Seeded payment per stage-1 R31 + stage-3 R160 (optional created_at)."""
    p = {"id": pid, "from_user_id": from_uid, "to_user_id": to_uid,
         "amount": amount, "note": note, "visibility": visibility}
    if created_at is not None:
        p["created_at"] = created_at
    return p


# Fixed past instants for seeded history (now is the reset instant, later
# than all of these; deterministic expected values throughout the suite).
T0 = "2026-09-01T09:00:00+00:00"
T1 = "2026-09-01T10:00:00+00:00"
T2 = "2026-09-01T11:00:00+00:00"
T3 = "2026-09-01T12:00:00+00:00"
T4 = "2026-09-01T13:00:00+00:00"
FAR_PAST = "1970-01-01T00:00:00+00:00"
FAR_FUTURE = "2999-01-01T00:00:00+00:00"


def me_view(c, token, as_of=None, known_at=None, raw_query=None):
    """GET /me with temporal parameters (R163/R207); returns the response."""
    q = []
    if as_of is not None:
        q.append("as_of=" + urllib.parse.quote(as_of, safe=""))
    if known_at is not None:
        q.append("known_at=" + urllib.parse.quote(known_at, safe=""))
    if raw_query:
        q.append(raw_query)
    path = "/me" + ("?" + "&".join(q) if q else "")
    return c.get(path, token=token)


def me_json(c, token, as_of=None, known_at=None, raw_query=None):
    return expect_ok(me_view(c, token, as_of, known_at, raw_query), 200,
                     f"GET /me as_of={as_of} known_at={known_at}")


def statement_view(c, token, **params):
    """GET /statement with named query parameters (R169). Values are
    URL-encoded; pass params=None-valued keys freely."""
    q = []
    for name in ("from", "to", "limit", "offset", "known_at", "snapshot",
                 "as_of"):
        v = params.get(name)
        if v is not None:
            q.append(f"{name}={urllib.parse.quote(str(v), safe='')}")
    extra = params.get("extra_q")
    if extra:
        q.append(extra)
    path = "/statement" + ("?" + "&".join(q) if q else "")
    return c.get(path, token=token)


def statement_ok(c, token, **params):
    return expect_ok(statement_view(c, token, **params), 200, "GET /statement")


def all_statement_entries(c, token, **params):
    """Page through a window (or snapshot) collecting every entry (R175)."""
    entries, offset = [], 0
    while True:
        body = statement_ok(c, token, offset=offset, limit=200, **params)
        entries.extend(body["entries"])
        if not body["has_more"]:
            return body, entries
        offset += len(body["entries"])


def correction_body(expected_revision, amount, effective_at, reason="corrected"):
    return {"expected_revision": expected_revision, "amount": amount,
            "effective_at": effective_at, "reason": reason}


def correct(c, token, payment_id, key, body):
    """POST /payments/{id}/corrections with an Idempotency-Key (R183)."""
    return c.post(f"/payments/{payment_id}/corrections", body=body, token=token,
                  headers={"Idempotency-Key": key})


def revisions_of(c, token, payment_id):
    """GET /payments/{id}/revisions (R205); returns the revisions list."""
    body = expect_ok(c.get(f"/payments/{payment_id}/revisions", token=token),
                     200, f"GET /payments/{payment_id}/revisions")
    check(isinstance(body, dict) and set(body.keys()) == {"revisions"},
          f"revisions envelope: {sorted(body.keys())}")
    return body["revisions"]


def revision_keys_ok(rev, with_payment_id=False):
    """Per-revision field presence per R192/R205 (presence, not exclusivity —
    the source shows no worked example body; A31's principle)."""
    need = {"revision", "amount", "effective_at", "recorded_at", "reason"}
    check(need <= set(rev.keys()), f"revision fields {need - set(rev.keys())} missing: {rev!r}")
    check(RFC3339.match(rev["effective_at"]) and RFC3339.match(rev["recorded_at"]),
          f"revision instants RFC 3339: {rev!r}")
    check(isinstance(rev["reason"], str), f"revision reason string: {rev!r}")
    check(isinstance(rev["amount"], int), f"revision amount int: {rev!r}")


STATEMENT_ENTRY_KEYS = {"payment", "delta", "balance_after", "revision",
                        "effective_at", "recorded_at"}


def entry_keys_ok(entry, what="entry"):
    """R172/R216: entry retains payment/delta/balance_after and adds
    revision/effective_at/recorded_at (presence — A31's principle)."""
    check(STATEMENT_ENTRY_KEYS <= set(entry.keys()),
          f"{what} fields {STATEMENT_ENTRY_KEYS - set(entry.keys())} missing: {sorted(entry.keys())}")

# -- stage 4: refunds (R253-R264) and correction batches (R269-R286) --

def refund(c, token, payment_id, key, body):
    """POST /payments/{id}/refunds with an Idempotency-Key (R253)."""
    return c.post(f"/payments/{payment_id}/refunds", body=body, token=token,
                  headers={"Idempotency-Key": key})


def refund_body(amount):
    return {"amount": amount}


def settle(c, token, transfers, key):
    """POST /settlements with an Idempotency-Key, operator token (stage-1 R87)."""
    return c.post("/settlements", body={"transfers": transfers}, token=token,
                  headers={"Idempotency-Key": key})


def transfer(from_handle, to_handle, amount, note=None, visibility=None):
    d = {"from_handle": from_handle, "to_handle": to_handle, "amount": amount}
    if note is not None:
        d["note"] = note
    if visibility is not None:
        d["visibility"] = visibility
    return d


def create_request(c, token, payer_handle, amount, key, note=None):
    b = {"payer_handle": payer_handle, "amount": amount}
    if note is not None:
        b["note"] = note
    return c.post("/requests", body=b, token=token,
                  headers={"Idempotency-Key": key})


def pay_request(c, token, request_id, key, visibility=None):
    b = {} if visibility is None else {"visibility": visibility}
    return c.post(f"/requests/{request_id}/pay", body=b, token=token,
                  headers={"Idempotency-Key": key})


def split(c, token, amount, participant_handles, key, note=None):
    b = {"amount": amount, "participant_handles": participant_handles}
    if note is not None:
        b["note"] = note
    return c.post("/splits", body=b, token=token,
                  headers={"Idempotency-Key": key})


def batch_item(payment_id, expected_revision, amount, effective_at,
               reason="batch-corrected"):
    return {"payment_id": payment_id, "expected_revision": expected_revision,
            "amount": amount, "effective_at": effective_at, "reason": reason}


def correction_batch(c, token, key, corrections):
    """POST /correction-batches with an Idempotency-Key, operator token (R269)."""
    return c.post("/correction-batches", body={"corrections": corrections},
                  token=token, headers={"Idempotency-Key": key})


def load_export(path):
    import json as _json
    with open(path, "r", encoding="utf-8") as fh:
        return _json.load(fh)


def latest_amount(payments_state, payment_id):
    """Current (latest-revision) amount of a payment from an export payload."""
    for p in payments_state:
        if p["id"] == payment_id:
            revs = p.get("revisions") or []
            return revs[-1]["amount"] if revs else p["amount"]
    raise SuiteFailure(f"payment {payment_id} not in export")
