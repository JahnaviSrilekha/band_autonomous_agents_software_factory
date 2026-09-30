# Stage 2 design — pocketful

Implements `specs/stage-2/requirements.md` (this commit) on top of stage 1's design
(`specs/stage-1/design.md`, unchanged sections carried forward by reference below). See
`adr/005-*.md` onward for stage-2's significant decisions; `adr/001-004` (stage 1) still
apply unchanged.

## 1. Stack

Unchanged from stage-1 design §1: Python 3.12, standard library only. Stage 2 adds a
browser UI but does **not** add a templating or frontend framework dependency — see
ADR-007. No network access is available at runtime (spec §2), so every asset (the one
JS file, any CSS) ships inside the image; no CDN links anywhere in served HTML.

## 2. Process model

Unchanged from stage-1 design §2: one `ThreadingHTTPServer`, one process-wide
`threading.RLock` (`STATE_LOCK`) guarding all mutable state, held for the full duration of
every handler including reads. This now also covers: creating/capturing/voiding an
authorization, and every `held`/`available` computation (§9 below) — a `GET /me` or
`GET /authorizations` call takes the same lock as a write so it never observes a
partially-applied capture. Password hashing continues to run outside the lock (ADR-003,
unchanged); nothing about authorizations changes that.

## 3. Data model (in-memory) — additions

```
State (additions to stage-1 design §3):
  authorization_ttl_seconds: int             # default 600; from fixture, or API default
  authorizations: dict[authorization_id -> Authorization]

Authorization: id, from_user_id, to_user_id, amount, note, visibility,
           status ("open" | "captured" | "voided"),   # "expired" is never stored —
                                                        # computed at read time, see §9
           captured_amount (int, cumulative), payment_ids (ordered list),
           created_at, expires_at

Payment (extension to stage-1 design §3):
  authorization_id: str | None    # set on a payment created by a capture; else None
```

`Authorization.status` never stores `"expired"` — only `"open"`, `"captured"` or
`"voided"` are ever written. Whether an `"open"` record currently *behaves* as expired is
always derived at the moment it's read or acted on (§9), per R136/R151: this avoids a
background sweep needing to run before an expiry is observable, and keeps "does this hold
anything right now" a pure function of `(record, now)` rather than depending on when some
other thread last swept the table.

`payment_id` on the capture response (R146) is `payment_ids[-1]` when non-empty, else
`None`. `captured_amount` is `sum` over the amounts of the payments referenced by
`payment_ids`. `remaining_amount` (added to every authorization representation, R146) is
computed, never stored: `0` if `status != "open"` or the record is clock-expired, else
`amount - captured_amount`.

## 4. Invariants and where they are enforced — additions

| Invariant | Enforcement |
|---|---|
| Conservation on `total` (R121) | Unchanged from stage-1's R1 enforcement (`_debit`+`_credit` pair, §4 stage-1 design): a hold never calls either, so `total` is untouched by authorize/void/expiry; only a capture (which calls the same `_debit(payer, amt)` + `_credit(receiver, amt)` pair as an ordinary payment) moves `total`. |
| `available = total - held` never negative (R122) | `held(user)` (§9) is recomputed from live authorization state on every check, under `STATE_LOCK`; every debit path (`POST /payments`, `POST /requests/{id}/pay`, settlements, `POST /authorizations`) checks `total - held - amount >= 0` — i.e. against `available`, not `total` — atomically with the debit itself, so no two concurrent debits can both pass the check against a stale `available`. |
| Cumulative captures ≤ authorized amount; closed hold uncapturable; each capture moves money once (R123) | `POST /authorizations/{id}/capture`'s amount-vs-remainder check (`capture_exceeds_authorization`) reads `remaining_amount` (§3) inside the same lock acquisition as the debit/credit and the `captured_amount`/`payment_ids` update — one atomic step, same "claim key → validate → mutate → commit" shape as every other idempotent write (§6 stage-1 design, extended by §5 below); a non-`open` (or clock-expired) authorization fails the resource-state check before any debit is attempted. |
| Linearizability under concurrency (R157) | Identical mechanism to stage-1's conservation/exactly-once enforcement: every state-touching handler (read or write) acquires the single `STATE_LOCK` for its entire duration (§2), so the observed history of any concurrent run is exactly some serialization of the individual lock acquisitions — the standard argument for a single global lock producing linearizable behavior. |

## 5. Write-path algorithm — extended to seven idempotent paths

Stage-1 design §5's algorithm (parse → authenticate → resolve idempotency key → validate →
mutate, all under one lock acquisition, non-object bodies gated at step 1 per A8/A16)
applies unchanged to `POST /authorizations` and `POST /authorizations/{id}/capture` — they
are simply the sixth and seventh entries in the idempotency-key-required set (R129).
`POST /authorizations/{id}/void` joins `decline`/`cancel` as a **no-idempotency-key**
state-transition endpoint (A15): it skips steps 3-4 of stage-1 §5 entirely but still runs
under `STATE_LOCK` for its read-check-mutate sequence, and is itself naturally idempotent
by the spec's explicit rule (voiding an already-voided authorization is `200` with current
state, not an error — R148) without needing the idempotency-key machinery at all.

## 6. Canonical body comparison

Unchanged from stage-1 design §6 (the JSON-type-aware comparison, bool-vs-number-safe).
Reused as-is for `POST /authorizations` and `.../capture` bodies. R146 is explicit that the
new *response* fields (`remaining_amount`, `payment_ids`, `final`'s echoed value) never
enter this comparison — only the *request* body is ever compared for replay/reuse
purposes, exactly as for every other write path.

## 7. Rounding function

Unchanged, unused by any stage-2 addition (`POST /splits` is explicitly unchanged — R128).
See stage-1 design §7.

## 8. IDs, tokens, timestamps

Extends stage-1 design §8 with one new id prefix: authorizations use `a_{uuid4().hex}`.
Timestamps (`created_at`, `expires_at`) use the same `datetime.now(timezone.utc).isoformat()`
convention as every other stage-1 timestamp, so `expires_at` is RFC 3339 with an explicit
offset (R155's `authorization-expires-{id}` renders this value verbatim as text).

## 9. Held/available computation and expiry (R121-R123, R136, R151)

```python
def is_live_hold(a: Authorization, now: datetime) -> bool:
    return a.status == "open" and a.expires_at > now

def held(user_id: str, now: datetime) -> int:
    return sum(a.amount - a.captured_amount
               for a in state.authorizations.values()
               if a.from_user_id == user_id and is_live_hold(a, now))

def available(user_id: str, now: datetime) -> int:
    return state.users[user_id].balance - held(user_id, now)
```

Called under `STATE_LOCK`, with one `now = datetime.now(timezone.utc)` snapshot per
request, so `held`/`available` are internally consistent within a single response even
though they're derived rather than stored. This function is the **sole** place that
decides whether a given authorization currently holds money or has (by clock) expired;
every endpoint — `GET /me`, `GET /authorizations` (status filtering and the per-item
`status` field, R151), `POST /authorizations` and the three other debit paths' funds
checks, and capture/void's "not open"/"expired" case discrimination (R147/R148) — calls
through it rather than re-deriving expiry locally. `O(authorizations for that user)` per
call is acceptable at the harness's fixture/load scale (≤ tens of thousands of records,
well under the 5s per-request budget).

No background expiry thread exists or is needed: because every observation recomputes
`is_live_hold` against a fresh `now`, an authorization "expires" the instant any code next
looks at it, satisfying R136's "reads and writes must reflect expiry even if no request
occurred at the deadline" without a sweep ever having to run.

## 10. Export/import — format v2 (extends stage-1 design §9)

`state`'s JSON shape gains two fields beyond stage-1's: `authorization_ttl_seconds` and
`authorizations` (each record serialized per §3, including `captured_amount` and
`payment_ids` so a partially-captured hold survives the round trip exactly, per R123/R146's
"preserve all capture records"). Stage 2 exports `format_version: 2`.

**Import version negotiation** (R115, and ADR-004's anticipated "later stage defaults any
field absent from the imported JSON"): `POST /_test/import` accepts `format_version` `1`
*or* `2`.
- `format_version: 2` → load `authorization_ttl_seconds` and `authorizations` directly from
  `state`.
- `format_version: 1` → the imported `state` has no `authorization_ttl_seconds` or
  `authorizations` keys at all; default `authorization_ttl_seconds = 600` and
  `authorizations = {}` (identical defaulting to an omitted-`authorizations` reset fixture,
  R135), then proceed with the rest of stage-1's field-by-field load unchanged (R115: a
  stage-1 export must be fully usable afterward — users, tokens, payments, requests,
  splits, settlements, idempotency records all load exactly as stage-1 §9 already
  specifies).
- Any other `format_version` → `422 validation_failed`, no change (unchanged from stage-1
  R80).

`POST /_test/reset` applies the identical default when the fixture omits
`authorization_ttl_seconds`/`authorizations` (R131/R135), reusing the same load path as a
`format_version: 1` import for those two fields. Export remains an atomic snapshot under
`STATE_LOCK` (unchanged from R81); import remains atomic replacement under `STATE_LOCK`
(unchanged from R83).

## 11. UI architecture (ADR-007)

**Rendering.** Each of `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations`
is served by a handler that, for `Accept: text/html`, renders a full HTML document via
plain Python string templates (f-strings/`string.Template`, stdlib only — no Jinja2 or
other third-party templating). `/requests` and `/authorizations` keep returning stage-1's
JSON shape for any other `Accept` value (R95/R152) — the same handler branches on
`Accept`, it does not become two separate routes.

**Client script.** One static JS file (`/static/app.js`, bundled into the image, no CDN,
served with its own tiny static-file handler) is loaded by every authenticated page. It
owns:
- **Idempotency-key derivation** (R102): a key is derived deterministically from the
  current form's field values (e.g. a stable JSON-stringify + hash of `{handle, amount,
  note, visibility}`) so that resubmitting *without changing a field* reuses the same
  string, and changing *any* field changes it — no server round trip needed to decide
  this.
- **Sequence numbers for "latest wins"** (R111): every fetch that can update
  balance/feed/list state is tagged with a locally-incrementing counter at send time; when
  a response arrives, it is applied only if its counter is ≥ the highest counter already
  applied, otherwise discarded. This covers `wallet-refresh`, the implicit post-action
  refresh (R110), and the retry path (R113) uniformly.
- **Lost-response / uncertain-outcome handling** (R113): a pay `fetch` failing (network
  error, or exceeding a client-side timeout well under the spec's 5s server budget, e.g.
  4.5s) with no distinguishable HTTP response shows `pay-uncertain`, keeps the form's
  current values and derived key intact, and leaves the submit button wired to retry with
  that identical key+body. An HTTP response that *does* arrive (whether 201, 200 replay, or
  a 4xx) is always conclusive — `pay-uncertain` only covers the no-response case, never a
  received error, matching "Unknown outcomes are not confirmed rejections."
- **Decimal-to-minor-units parsing and validation** (R104), shared by every amount input
  (`pay-amount`, `request-amount`, `split-amount`, `authorize-amount`,
  `authorization-capture-amount-{id}`): one client-side function, parameterized by the
  service's `minor_units` (fetched once from `GET /me` after login and cached for the
  session), rejects non-numeric input or excess decimal places before any `fetch` is sent.
- **Split preview** (R109): the same share-computation function as stage-1 design §7
  (`compute_shares`), reimplemented in JS from the same table/spec rule (not fetched from
  the server), so `split-preview` renders instantly as `split-handles`/`split-amount`
  change; the value is verified against the server's actual response on submit (both sides
  implement the identical documented rule, so they agree by construction, not by one
  querying the other).

**No SPA router / no build step.** Each route is its own server-rendered document;
navigation between routes (e.g. `/` → `/requests`) is an ordinary link/full navigation,
satisfying R110's "any mechanism is fine, including a full navigation" — only *within* a
page (after a form submit, or `wallet-refresh`) does the script update the DOM in place
without a reload.

## 12. Validation order per endpoint — additions (A14)

For `POST /authorizations` (after the idempotency step): field-shape errors (`amount`,
`note`, `visibility`) → handle resolution (`404`) → self-payment (`422 self_payment`) →
available-funds (`409 insufficient_funds`) last — same pattern as stage-1 design §10's
`/payments` order, `available` substituted for balance.

For `POST /authorizations/{id}/capture` and `.../void`: resource existence (`404
not_found`) → permission (`403 forbidden` — receiver-only for capture, payer-only for
void) → resource-state (`409 authorization_not_open` / `409 authorization_expired`, via
§9's `is_live_hold`) → (capture only) amount-shape (`422 validation_failed`) →
amount-vs-remainder (`422 capture_exceeds_authorization`) last. Existence and permission
must precede state/amount checks because both depend on having resolved the record and its
parties first; the relative order of the two amount-related capture checks follows A1's
"any single deterministic order" latitude.

## 13. What stage 2 deliberately does not build

No correction/refund endpoints or historical "as of"/"as known at" queries (stage 3+, per
stage-1 design §11 — still true); no multi-currency; no background expiry-sweeping thread
(§9's lazy computation is the deliberate design, not a gap); no websockets/SSE/polling for
cross-client live updates (R110/R114 explicitly do not require this); no build step or
frontend framework for the UI (ADR-007); no "authorize a request" endpoint (R127
explicitly out of scope).
