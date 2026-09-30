# Stage 1 requirements — pocketful: payments and settlements

Source: `we-are-devs/pocketful/spec/stage-1.md` (full text pasted into every handoff).
Kind values: behaviour, error, limit, concurrency, retry, time, compatibility, interface.

## Scope and money invariants (§1)

- **R1** (behaviour, concurrency). "The sum of wallet balances always equals the total seeded
  by the last `POST /_test/reset`." — Acceptance: after any sequence/mix of concurrent
  operations, sum of all wallet balances == sum of seeded fixture balances (post-seeded-payment
  balances) from the most recent reset.
- **R2** (concurrency). "No wallet balance may be negative, including transiently." —
  Acceptance: no balance ever observed or computed as < 0, even under concurrent writes racing
  on the same wallet.
- **R3** (retry, concurrency). "A payment request may move money at most once." — Acceptance:
  concurrent/duplicate identical idempotent write requests move money exactly once; replays
  never move money again.
- **R4** (behaviour). "Money moves only between existing wallets" and deposits/top-ups/
  withdrawals/cards/bank integrations are out of scope — Acceptance: no endpoint creates or
  destroys money outside of transfers between existing wallets seeded/created via signup.
- **R5** (behaviour). Amounts are exact integer counts of minor units — Acceptance: all monetary
  math uses integer arithmetic (no floats), never loses precision.

## Delivery and deployment (§2)

- **R6** (interface). Deliver an HTTP service, `Dockerfile`, `RUN.md` with a command that builds
  and starts without manual setup; `docker-compose.yml` optional — Acceptance: `docker build` +
  the documented run command yields a working container.
- **R7** (interface). "The submission is a containerized HTTP service, not a Python package...
  The harness builds the submitted `Dockerfile`, starts the resulting image and tests only its
  HTTP behavior" — Acceptance: no reliance on host Python env; all behavior reachable via HTTP
  only.
- **R8** (interface). Image runs standalone with `-e PORT=<port>` and a port mapping; no compose
  needed to start — Acceptance: `docker run -e PORT=8080 -p 8080:8080 <image>` alone serves
  traffic.
- **R9** (limit). "Runtime networking has no outbound access... All runtime dependencies,
  initialization and seed data must work within that single container." — Acceptance: container
  started with no network egress still becomes healthy and serves all endpoints.
- **R10** (limit). Resource limits table: CPU 2 vCPU, Memory 2 GiB, start-to-healthy ≤60s,
  concurrent requests up to 50 in flight, per-request timeout 5s (10s for
  `POST /_test/reset`/test-control endpoints), outbound network build-time only, disk ephemeral —
  Acceptance: service meets all these under the isolated harness run.
- **R11** (limit). "Runtime assets and dependencies must be included in the image." —
  Acceptance: no CDN links, no runtime fetches; stdlib-only per technical direction (ADR-001).

## Runtime contract (§3)

- **R12** (interface). Listen on `0.0.0.0` using `PORT` env var, default `8080` — Acceptance:
  server binds `0.0.0.0:$PORT`, defaults to 8080 when unset.
- **R13** (behaviour, time). `GET /health` → 200 `{"status":"ok"}` once service/store can serve
  requests, within 60s of start; non-200 permitted before ready — Acceptance: health check
  passes within 60s and stays 200 thereafter, and the body is exactly `{"status":"ok"}`.
- **R14** (behaviour). `POST /_test/reset` replaces all state with the fixture body, returns 204;
  subsequent requests see only that fixture; repeated resets supported; unauthenticated —
  Acceptance: after 204, `GET /me`/`/activity`/etc. reflect only fixture data; calling reset again
  fully replaces state again.
- **R15** (error). Fixture `balance` below zero is a reset error → 422 `validation_failed` from
  `POST /_test/reset`, state unchanged — Acceptance: negative seeded balance rejected, prior
  state (if any) untouched.
- **R16** (interface). Requests/responses `application/json; charset=utf-8`; timestamps RFC 3339
  with explicit offset; unknown body fields ignored; unknown query params ignored; IDs opaque
  strings ≤64 chars, format ours — Acceptance: content-type set; timestamps like
  `2026-09-24T19:00:00+02:00`; extra fields/params never error.

## Model (§4)

- **R17** (behaviour). One currency per service declared in fixture (`currency`, `minor_units`
  ∈ {0,2,3}); amount `1000` at `minor_units:2` is 10.00 units — Acceptance: `/me` and payment
  responses echo `currency`; amounts are raw minor-unit integers.
- **R18** (behaviour). API amounts must have an integral numeric value; JSON `1000`, `1000.0`,
  `1e3` all valid identical amounts; booleans/strings are not numbers — Acceptance: parser
  accepts numeric JSON values equal to an integer regardless of literal form; rejects bool/string
  typed amount fields per R-error rules.
- **R19** (behaviour). Handles: unique service-wide, match `^[a-z0-9_]{1,20}$`, immutable once
  set — Acceptance: handle uniqueness enforced at signup and seed; format validated.
- **R20** (behaviour). Signup-derived handle: lowercase local-part of email, replace chars
  outside `[a-z0-9_]` with `_`, truncate to 20 chars; if taken, signup fails (§6 table) —
  Acceptance: derivation matches rule exactly; collision → 409 `handle_taken`, no account
  created.
- **R21** (behaviour). New users start with balance `0`; can receive money / be asked for money
  immediately — Acceptance: post-signup balance is 0 and wallet accepts incoming
  payments/requests right away.
- **R22** (behaviour). A payment moves money from one wallet to another, immediately and
  atomically; created directly or by paying a request — Acceptance: debit+credit are a single
  atomic step (R33).
- **R23** (behaviour). A request has states `pending` → exactly one of `paid`/`declined`/
  `cancelled`; only payer may pay/decline; only requester may cancel — Acceptance: state machine
  enforced; other-party actions rejected (403).
- **R24** (behaviour, error). "A request may exceed the payer's balance" — legal at creation; pay
  attempt while short is `409 insufficient_funds` and changes nothing; money can arrive later
  making it payable — Acceptance: request creation never balance-checks payer; pay-time check
  only, non-mutating on failure.
- **R25** (behaviour). Visibility belongs to the payment, chosen by payer when money moves; a
  request carries no visibility and never appears in anyone else's feed — Acceptance: request
  objects have no visibility field; requests never surface via `/activity`.

### Feed contract (§4)

- **R26** (behaviour). `GET /activity` returns payments only; a payment appears for a caller iff
  `visibility=public` OR caller is sender/receiver; no other rule (no follow graph, no mute
  list) — Acceptance: exhaustive per-caller filter matches this rule exactly.
- **R27** (behaviour). Requests never appear in activity feed; read via `GET /requests`, which
  returns only requests where caller is requester or payer — Acceptance: `/requests` never
  leaks third-party requests.
- **R28** (behaviour). A split is not a feed item; its created requests are visible to their two
  parties; resulting payments follow R26 — Acceptance: `/activity` never lists a split itself.
- **R29** (behaviour). Visibility is one value on the payment, seen identically by both parties
  and everyone else; a `private` payment is hidden from third parties, not from its own receiver
  — Acceptance: sender and receiver always see their own private payments regardless of
  visibility.

### Arithmetic range (§4)

- **R30** (limit). `amount` at most `1000000000` per single request; no operation produces a
  balance outside ±2⁵³; exact minor-unit arithmetic, no rounding error — Acceptance: amounts
  >1e9 rejected (422); internal arithmetic uses integers (e.g. int64), never floating point.

### Fixture format (§4)

- **R31** (interface). Fixture shape: `currency`, `minor_units`, `users[]` (`id`,`email`,
  `password`,`display_name`,`handle`,`balance`), `payments[]`, `requests[]` — Acceptance: reset
  parses and applies this shape; unknown fixture fields ignored per R16.
- **R32** (behaviour). Seeded users can log in with the given password immediately — Acceptance:
  after reset, `POST /auth/login` with fixture email/password succeeds for every seeded user.
- **R33** (behaviour). Seeded `balance` is the wallet balance *after* every seeded payment has
  been applied; seeded numbers are consistent; reset must not replay seeded payments against
  balances — Acceptance: post-reset wallet balance == fixture `balance` value exactly (not
  balance plus/minus replayed seeded payments).
- **R34** (limit). `minor_units` is 0, 2 or 3 — Acceptance: reset accepts only these values
  (other numeric values are a validation error per R15's family — treated as 422
  `validation_failed` since not separately listed, general rule applies).

## Errors (§5)

- **R35** (error, interface). Every 4xx/5xx body is `{"error":{"code":...,"message":...}}` —
  Acceptance: all error responses conform, any endpoint.
- **R36** (error). Status/code table: 400 `malformed_request` (unparseable body or field of
  wrong JSON type), 400 `missing_idempotency_key`, 401 `unauthenticated`, 403 `forbidden`, 404
  `not_found`, 409 `idempotency_key_reuse`, 422 `validation_failed` (required field/query param
  missing or a stated rule violated with no more specific code) — Acceptance: each case in the
  spec maps exactly to this status+code.
- **R37** (error). A correctly-typed field with invalid format/out-of-range (invalid dates,
  negative counts, values exceeding a stated max/length) → 422 `validation_failed` unless an
  endpoint specifies otherwise — Acceptance: generic out-of-range/format errors use 422 not 400.
- **R38** (error). Endpoint-specific field rules take precedence: invalid `amount` (incl.
  strings/booleans), non-string `note` (incl. `null`), any `visibility` other than
  `public`/`private` → 422 `validation_failed`; omission alone selects optional-field defaults —
  Acceptance: these specific invalid-type cases are 422, not 400, even though "wrong JSON type"
  would otherwise suggest 400.
- **R39** (error). Integer-valued **query parameters** written as plain decimal digits: `1e9`,
  `4.0`, `+4` are 422 `validation_failed` regardless of numeric value — Acceptance: strict
  decimal-digit-string parsing for `limit`/`offset` query params.
- **R40** (error). "Reserve 400 `malformed_request` for a body that does not parse or a field of
  the wrong type." — Acceptance: 400 only for JSON-parse failure or wrong-type field not covered
  by R38's endpoint-specific overrides.
- **R41** (limit). Shared ranges on every endpoint that takes them: `Idempotency-Key` 1–255
  chars else 422; `limit` integer 1–200 else 422; `offset` integer ≥0 else 422 — Acceptance:
  enforced uniformly across all idempotent-write and listing endpoints.
- **R42** (error). "Requests must not produce 5xx responses, including under concurrent load." —
  Acceptance: no 5xx observed in any load/concurrency test.

## Authentication (§6)

- **R43** (interface). `POST /auth/signup` body `email,password,display_name` → 201
  `{user_id,display_name,token}`; `POST /auth/login` body `email,password` → 200 same shape —
  Acceptance: exact response shapes.
- **R44** (error). Signup/login cases: email already registered → 409 `email_taken`; password
  <8 chars → 422 `validation_failed`; `email` not `local@domain` form → 422
  `validation_failed`; wrong password or unknown email on login → 401 `unauthenticated`; derived
  handle already taken → 409 `handle_taken`, no account created — Acceptance: each case
  produces exactly this status+code.
- **R45** (interface). Every endpoint except `/health`, `/_test/reset`, `/auth/signup`,
  `/auth/login` (and other `/_test/*` control endpoints per §10) requires
  `Authorization: Bearer <token>`; wallet endpoints require auth — Acceptance: missing/malformed/
  unknown token → 401 `unauthenticated` on all other endpoints.
- **R46** (behaviour). Tokens do not expire; an account may have multiple valid tokens/concurrent
  sessions — Acceptance: multiple logins/signups yield independently valid tokens, all usable
  concurrently.
- **R47** (behaviour, compatibility). Passwords stored using a password-hashing function
  (bcrypt/scrypt/Argon2 or equivalent); plaintext storage not permitted — Acceptance: stored
  password representation is a salted hash, never the raw password; verified via hashing library.

## Idempotency (§7)

- **R48** (interface). Five write paths require `Idempotency-Key`: `POST /payments`,
  `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements` — Acceptance:
  each of these 5 endpoints enforces the header.
- **R49** (behaviour). Key scoped to the authenticated user; two different users may reuse the
  same key string independently — Acceptance: same key string across two users never
  interacts.
- **R50** (behaviour). Replay = same user, same method, same path, same body ("same JSON value
  after parsing — key order/whitespace don't matter"); same key+body on a different path is a
  different request and must succeed normally — Acceptance: canonical-JSON-equality comparison
  ignoring key order/whitespace; per-path independence.
- **R51** (error, retry). Situation table: header absent/empty → 400
  `missing_idempotency_key`; first use → normal response, 201; replay same key+body → 200,
  body identical (as JSON value) to original; same key different body → 409
  `idempotency_key_reuse`; key reused after original failed with 4xx → treated as first use —
  Acceptance: exact behavior per row, including that a failed (4xx) attempt frees the key for
  reuse.
- **R52** (concurrency, retry). "For concurrent identical requests with an unused key, exactly
  one returns 201. The others return 200 with the same body. The operation takes effect only
  once." — Acceptance: N concurrent identical requests on a fresh key → exactly one 201, rest
  200 identical body, single state mutation.
- **R53** (retry). A successful replay returns the original response even after the resource
  changes/is cancelled, and makes no further state changes — Acceptance: replay after e.g.
  request becomes non-pending still returns original 200 payment body, no new mutation.
- **R54** (behaviour, retry). "After the body has parsed as a JSON object and the caller is
  authenticated, an already claimed key is resolved before endpoint field validation or
  current-resource checks." So a same-key-different-later-invalid-body still gives 409
  `idempotency_key_reuse` (not a validation error) — Acceptance: processing order = parse body →
  authenticate → resolve idempotency key → validate fields/resource state (ADR captures this as
  the single required order).

## API (§8)

### GET /me
- **R55** (interface). Returns `{user_id,display_name,handle,balance,currency,minor_units}` —
  Acceptance: exact shape, requires auth (R45).

### POST /payments
- **R56** (interface, retry). Idempotent write; body `to_handle,amount,note?(default ""),
  visibility?(default "public")`; 201 body includes `payment_id,from_user_id,from_handle,
  to_user_id,to_handle,amount,currency,note,visibility,request_id:null,created_at,
  settlement_id:null` — Acceptance: exact shape/defaults, including `settlement_id` present
  and `null` (this endpoint never creates a settlement member). Every payment representation
  returned anywhere in the API (this response, `GET /activity` items, the payment embedded in
  a `POST /requests/{id}/pay` response, and each entry of a settlement's `payments[]`) shares
  this exact same shape; `settlement_id` is `null` except on a settlement's own members
  (R91).
- **R57** (error). Case table: balance below `amount` → 409 `insufficient_funds`; `amount` <1,
  >1e9, or non-integer → 422 `validation_failed`; `to_handle` == caller's own handle → 422
  `self_payment`; `note` >200 chars → 422 `validation_failed`; `visibility` not
  public/private → 422 `validation_failed`; unknown handle → 404 `not_found` — Acceptance:
  exact status+code per case; precedence per order tested is not specified beyond §7's
  idempotency-first rule, so any consistent order across these validations is acceptable
  (A2).
- **R58** (concurrency, behaviour). Debit and credit are one atomic step; never visible in one
  wallet and not the other; failed payment leaves no trace in either — Acceptance: no
  intermediate state observable; failure is fully non-mutating.
- **R59** (behaviour). `note` stored/returned verbatim: no trimming/escaping/normalisation;
  Unicode/emoji survive round trip byte for byte — Acceptance: byte-identical round trip.

### POST /requests
- **R60** (interface, retry). Idempotent write; body `payer_handle,amount,note?`; caller is
  requester; 201 body `request_id,requester_id,requester_handle,payer_id,payer_handle,amount,
  currency,note,status:"pending",payment_id:null,created_at` — Acceptance: exact shape.
- **R61** (error). `amount` <1/>1e9/non-integer → 422 `validation_failed`; `payer_handle` ==
  caller's own → 422 `self_request`; `note` >200 chars → 422 `validation_failed`; unknown
  handle → 404 `not_found` — Acceptance: exact status+code.
- **R62** (behaviour). Payer's balance not checked at creation; over-balance request created
  normally, sits pending — Acceptance: no balance check on this path (ties to R24).

### POST /requests/{id}/pay
- **R63** (interface, retry). Idempotent write, payer only; body `visibility?` default
  `"public"`; replay must send identical body (`{}` vs `{"visibility":"public"}` are different
  JSON values → different idempotency outcome per §7) — Acceptance: body-equality is exact
  JSON-value equality, defaults not pre-filled before the comparison.
- **R64** (behaviour). Returns 201 with the created payment (same shape as POST /payments) with
  `request_id` set; request becomes `paid`, carries new `payment_id` — Acceptance: exact
  linkage.
- **R65** (error). Case table: request not pending → 409 `request_not_pending`; payer balance <
  amount → 409 `insufficient_funds`; caller not the payer → 403 `forbidden`; unknown request →
  404 `not_found` — Acceptance: exact status+code.
- **R66** (retry). Replaying a successful payment returns 200 with original payment body, even
  when request is already `paid`; moves no additional money; must not return 409
  `request_not_pending` — Acceptance: idempotency short-circuits the not-pending check on
  legitimate replay.

### POST /requests/{id}/decline
- **R67** (interface, error). Payer only, no idempotency key; 200 with request,
  `status:"declined"`; declining an already-declined request is 200 with current state (not an
  error); `paid`/`cancelled` request → 409 `request_not_pending`; not payer → 403 `forbidden` —
  Acceptance: exact behavior incl. idempotent-decline-of-declined.

### POST /requests/{id}/cancel
- **R68** (interface, error). Requester only, no idempotency key; 200 with request,
  `status:"cancelled"`; cancelling an already-cancelled request is 200; `paid`/`declined` → 409
  `request_not_pending`; not requester → 403 `forbidden` — Acceptance: symmetric to R67.

### GET /requests
- **R69** (interface). Query `direction` (`incoming`=caller is payer / `outgoing`=caller is
  requester / absent=both), `status` (one of 4, or absent=all), `limit` (default 50, 1-200),
  `offset` (default 0, ≥0); newest first by `created_at`; `has_more` true when more exist beyond
  returned page — Acceptance: exact filter/paging semantics.
- **R70** (error). Unknown `direction`/`status` value → 422 `validation_failed`; out-of-range
  `limit`/`offset` → 422 `validation_failed` — Acceptance: exact.

### POST /splits
- **R71** (interface, retry). Idempotent write; body `amount,participant_handles[],note?`;
  caller may be included/omitted from `participant_handles`; shares follow §9 rounding, in given
  order; one `pending` request created per participant except the caller, caller as requester —
  Acceptance: exact request-creation semantics.
- **R72** (interface). 201 body `split_id,amount,currency,note,shares[{handle,amount}]` (covers
  every participant incl. caller, in order, sums to amount),`requests[]` (covers every
  participant except caller, same order), `created_at` — Acceptance: exact shape.
- **R73** (error). `amount` <1/>1e9/non-integer → 422; `participant_handles` empty or containing
  a duplicate → 422 `validation_failed`; `note` >200 → 422; any unknown handle → 404
  `not_found` — Acceptance: exact.
- **R74** (behaviour, limit). A split whose only participant is the caller is valid: one share,
  zero requests, `"requests":[]`; nothing about a split checks anyone's balance — Acceptance: no
  balance check anywhere in split creation.

### GET /activity
- **R75** (interface). Query `limit,offset` as `/requests`; payments visible per feed contract
  (R26), newest first by `created_at`; response body `{"payments":[...],"has_more":bool}`;
  relative order of same-second payments unspecified; stable pagination during concurrent
  writes not required — Acceptance: exact filter/paging including `has_more` (true when items
  exist beyond the returned page, same rule as R69); same-second ordering not asserted by
  tests (A3).

## Money and rounding (§9)

- **R76** (behaviour, limit). Shares: whole minor units, sum exactly to `amount`, differ by at
  most 1 minor unit; when amount doesn't divide evenly, larger shares go to first participants
  in `participant_handles` order — Acceptance: matches the table exactly: 1000/3→334,333,333;
  1/3→1,0,0; 10/3→4,3,3; 999/3→333,333,333; 5/5→1,1,1,1,1. A share of 0 is legal and still
  produces a request for that participant.
- **R77** (behaviour). Different `participant_handles` order gives the extra unit(s) to a
  different person; each split's shares independent of previous splits; after any number of
  splits paid in full, wallet balances still sum exactly to seeded total — Acceptance: order-
  dependence verified; conservation holds after paid splits.

## Export and import (§10)

- **R78** (interface). `GET /_test/export` and `POST /_test/import`, unauthenticated test
  endpoints; export 200 body `{track:"pocketful", format_version:1, state:{...opaque...}}`;
  state format opaque to caller, must be accepted unchanged by import — Acceptance: round trip
  export→import is a no-op on subsequent behavior.
- **R79** (behaviour, time). Import atomically replaces service state, returns 204; must accept
  an unchanged export produced by this service; no dependency on source process/files/volume/
  port/network address; import is replacement not merge — repeating it restores exported state
  without duplication; test-control calls (`/_test/*`) have a 10s timeout — Acceptance: import
  is idempotent-as-replacement, isolated from source process.
- **R80** (error). Invalid JSON → §5 rules (400 `malformed_request`); missing fields, wrong
  track/version, or invalid state → 422 `validation_failed`, no change to destination —
  Acceptance: exact.
- **R81** (behaviour, time). Export is an atomic read-only snapshot; subsequent source writes do
  not change an already-taken export — Acceptance: export captured at a single instant under the
  same global critical section as writes.
- **R82** (compatibility, behaviour). Preserve on import: accounts and hashed-password login,
  existing bearer tokens, currency, balances, payments, requests, permissions, all completed
  idempotent request bodies and original responses; identities/timestamps/monetary records not
  regenerated or replayed against an already-net balance; failed request keys remain reusable;
  existing receipts/tokens/retries remain valid after import — Acceptance: post-import, an old
  token still authenticates, a completed idempotency key still replays its original response
  without moving money again, a previously-failed key is still usable as a first use, **and a
  user can still log in with their pre-import password** (hashed-password login is preserved,
  not just the token).
- **R83** (behaviour). Import removes all previous destination data/credentials (full
  replacement) — Acceptance: pre-import state not merged with imported state.
- **R84** (behaviour). Reset clears all state, including imported state — Acceptance: reset
  after import behaves like reset from any other state.
- **R85** (limit). State need not survive an abrupt container restart — Acceptance: no
  persistence-to-disk requirement (A4: in-memory only, per technical direction).

## Atomic net settlements (§11)

- **R86** (interface). Reset fixture may include `settlement_operator_ids` (array of user ids,
  default `[]`); an operator may execute a settlement across any wallets; this permission does
  not grant access to another user's requests or private activity items — Acceptance:
  operator-only capability scoped strictly to `POST /settlements`.
- **R87** (interface, retry). `POST /settlements` requires an operator and idempotency key
  (5th idempotent write path); body `{"transfers":[{from_handle,to_handle,amount,note?,
  visibility?}...]}`, 1..32 entries, each using ordinary payment amount/note/visibility rules
  (defaults empty note, public) — Acceptance: exact.
- **R88** (error). No token → 401 `unauthenticated`; authenticated non-operator → 403
  `forbidden`; unknown handle → 404; self-transfer → 422 `self_payment`; malformed batch shape
  → 422 `validation_failed`; "entry errors take precedence in input order, before insufficient
  funds"; unknown fields ignored — Acceptance: validate every entry (in order) for
  shape/handle/self-transfer errors before any affordability check. "Malformed batch shape"
  includes `transfers` not being an array, `transfers` containing a non-object entry, and an
  entry whose `from_handle`/`to_handle`/`amount` is present with the wrong JSON type — all
  422 `validation_failed`, not 400 (see A9).
- **R89** (behaviour, concurrency). A settlement is affordable when every wallet's balance after
  all incoming and outgoing transfers is nonnegative (net effect, not per-transfer sequential
  check); insufficient collective funds → 409 `insufficient_funds` — Acceptance: affordability
  computed on net per-wallet effect across the whole batch.
- **R90** (behaviour). All-or-nothing: either all movements commit together or none do; failed
  validation claims no idempotency key and creates no payment or revision — Acceptance: on any
  rejection, zero state mutation including the idempotency key.
- **R91** (interface). 201 with `settlement_id,committed_at,payments[]` in input order; every
  member is an ordinary payment with `settlement_id` linking the batch (nonmembers null); members
  have null `request_id` and the same server-assigned `created_at` == `committed_at` —
  Acceptance: exact shape/linkage.
- **R92** (behaviour, retry). Constituents follow ordinary activity-feed visibility (R26);
  settlement response contains every member's receipt; replays return 200 with original complete
  response (5th idempotent path, full §7 rules apply) — Acceptance: exact.
- **R93** (compatibility). Reset/import must preserve settlement operator permissions, original
  payments, requests, settlement membership and retry responses — Acceptance: covered by R82/
  R84 plus operator id preservation.

## Assumptions

- **A1**. Validation-order across independent 422/404/409 cases within one endpoint (beyond the
  idempotency-first rule of R54 and the explicit precedence in R88) is not specified by the
  spec text for `/payments`, `/requests`, `/requests/{id}/pay`, `/splits`. We pick one fixed,
  documented order per endpoint (see design.md) and apply it consistently; a single documented
  order used consistently satisfies "a stated rule violated with no more specific code" and
  keeps replay-equality well-defined. Reasoning: spec explicitly orders §7 (idempotency first)
  and §11 (entry errors before insufficient funds) but is silent elsewhere, so the most
  conservative reading is "any single deterministic order is acceptable as long as it never
  contradicts an explicit ordering rule."
- **A2**. Within `/payments`, `/requests`, `pay`: field-shape/format errors (422/400) are checked
  before resource-existence (404 unknown handle) and before balance/state checks (409), except
  where idempotency key resolution (R54) or explicit precedence (settlements, R88) requires
  otherwise. Reasoning: matches the general pattern in §5 ("required field... missing" is a 422
  before any resource lookup) and avoids leaking resource existence via error-ordering side
  channels.
- **A3**. `/activity` same-second ordering is unconstrained; our implementation's stable
  secondary order is acceptable since the spec states it is unspecified.
- **A4**. All state is in memory only (no disk persistence across restart), per the run's
  technical direction and spec §10 ("State need not persist... need not survive an abrupt
  container restart" / disk ephemeral R10). Reasoning: matches technical direction explicitly.
- **A5**. `minor_units` values other than 0/2/3 supplied to `/_test/reset` are treated as 422
  `validation_failed` (general fixture-validation rule), since the spec states the set of values
  fixtures use but does not give a distinct error code for an out-of-set value.
- **A6**. The `Idempotency-Key` header requirement (§7/R48) does not apply to
  `POST /requests/{id}/decline` or `.../cancel` (explicitly "No idempotency key" per §8), nor to
  non-write/read endpoints, `/auth/*`, `/_test/*`. If a client supplies the header on
  decline/cancel anyway, it is ignored entirely — not read, not claimed, not consumed — so a
  later write elsewhere reusing the same key string is a fresh first use. Reasoning: these two
  endpoints are outside the five idempotent write paths entirely (§7 names exactly five), so
  there is no mechanism for them to interact with the idempotency table at all.
- **A7**. "Password shorter than 8 characters" (R44) is checked independently of email-format
  validation; when both are invalid we return whichever our fixed per-endpoint order picks
  first (A1) — the spec does not state relative precedence between the two signup validation
  errors.
- **A8**. A request body on one of the five idempotent write paths that parses as valid JSON
  but whose top-level value is not a JSON object (an array, string, number, boolean, or
  `null`) is treated the same as a body that does not parse at all: `400 malformed_request`,
  returned before authentication and before any idempotency-key interaction (it is neither
  claimed nor freed). Reasoning: R54 gates idempotency-key resolution behind "the body has
  parsed as a JSON object," so a non-object body must be rejected earlier in the pipeline than
  that gate; R40 reserves 400 for "a body that does not parse or a field of the wrong type,"
  and the top-level value being the wrong type is such a case.
- **A9**. Within a `POST /settlements` body, `transfers` not being an array, `transfers`
  containing a non-object entry, or an entry's `from_handle`/`to_handle`/`amount` being present
  with the wrong JSON type, is `422 validation_failed` ("malformed batch shape," §11) rather
  than the general `400 malformed_request`. Reasoning: §5 states endpoint-specific field rules
  take precedence over the general wrong-type-is-400 rule, and §11 explicitly names "malformed
  batch shape" as a 422 case; a wrong-typed field inside a transfer entry is such a shape
  defect, the same pattern as the existing endpoint-specific overrides for `amount`/`note`/
  `visibility` elsewhere (R38).
- **A10**. `POST /auth/signup` requires `email`, `password` and `display_name` all present;
  a missing one is `422 validation_failed`; one present with the wrong JSON type (e.g. a
  number) is `400 malformed_request` (R40); `display_name` has no stated length limit and none
  is enforced. Reasoning: §6 states endpoint-specific overrides only for password length and
  email format, so presence/type of the three fields otherwise follows the general rule
  (required-and-missing → 422, wrong type → 400).
- **A11**. Email matching, for uniqueness (`409 email_taken`) and for login lookup, is exact
  case-sensitive string comparison; `A@x.com` and `a@x.com` are different emails. Reasoning:
  §4 states an explicit lowercase-and-sanitize rule for the *derived handle*, but states no
  normalisation rule for the email address itself; the conservative reading applies no
  normalisation the spec doesn't state.
- **A12**. A reset fixture's `requests[]` entries are only ever seeded with `status:"pending"`
  in practice; if a fixture nonetheless supplies a different status value, it is accepted
  verbatim (no validation error — no rule forbids it), but the implementation does not
  synthesize a `payment_id` or a backing payment for it, since the fixture format has no field
  to supply one. Reasoning: the spec's only example seeds `pending`, and states neither an
  error case nor a backing-payment rule for other statuses, so the conservative choice is
  to neither reject the input nor fabricate missing linkage.
- **A13**. A reset fixture missing `currency`, or with `currency` not a non-empty string, is a
  fixture validation error: `422 validation_failed` from `POST /_test/reset`, state unchanged.
  Reasoning: mirrors R15's treatment of an invalid fixture value (negative seeded balance is
  also 422, not 400) — §4 states the fixture "declares" the currency but gives no distinct
  error code for a missing/invalid one, so this keeps one consistent code for fixture-shape
  defects.
