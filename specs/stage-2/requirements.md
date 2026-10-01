# Stage 2 requirements — pocketful: wallet screens and payment authorizations

Source: `we-are-devs/pocketful/spec/stage-2.md` (full text pasted into every handoff), which
states "the stage-1 requirements continue to apply, with the additions below." All of
`specs/stage-1/requirements.md` (R1-R93, A1-A13) therefore stays in force by reference;
this document numbers only stage 2's additions and changes, continuing from R94/A14.
Section references such as §5, §7, §9 refer to `stage-1.md` as stage-2.md itself directs.
Kind values: behaviour, error, limit, concurrency, retry, time, compatibility, interface.

## Routes and content negotiation

- **R94** (interface). "The following screens must be reachable by URL. Other screens must be
  reachable through the UI." — route table: `/` (balance, pay form, request form, activity
  feed), `/requests` (incoming/outgoing requests, pay/decline/cancel), `/split` (split form),
  `/signup`, `/login` — Acceptance: each URL serves its screen directly (no required prior
  navigation); every other required screen (e.g. `/authorizations`, R152) is reachable by
  following links/buttons from these.
- **R95** (interface). "The browser and the API share `/requests`. Return the UI for
  `Accept: text/html`; API requests without that header receive JSON." — Acceptance:
  identical rule applies later to `/authorizations` (R152); a request with
  `Accept: text/html` gets an HTML document, any other/absent `Accept` gets the stage-1 JSON
  shape unchanged.
- **R96** (interface). "The UI must expose the `data-testid` attributes listed below for
  integration testing. Additional elements are permitted, and the visual implementation is
  the team's choice subject to the product-quality requirements below." — Acceptance: every
  `data-testid` named in R100/R101/R105/R107/R108/R111/R153/R154/R155 is present with the
  stated text/attribute/visibility rule; extra markup/testids are not a defect.

## Product and visual direction

- **R97** (behaviour). "The browser experience must feel like a coherent, presentation-ready
  consumer finance product, not a test harness with controls attached... Available funds must
  be the clearest monetary value once holds exist, with total and held funds visibly
  secondary." — Acceptance: once `held > 0`, `wallet-available` is the visually dominant
  balance figure (e.g. largest/first), `wallet-balance` (total) and `wallet-held` are visibly
  secondary; see A17 on how this is judged.
- **R98** (behaviour). "Payments, requests, splits and authorisations should be easy to scan,
  and status, direction, privacy and money movement should be understandable without
  interpreting raw API data... Use a consistent visual system for typography, spacing,
  colour, controls and feedback. Primary actions must be easy to identify... Available, held,
  pending, loading, successful, refused and uncertain states must be visually distinct...
  Format people, amounts and timestamps for people first; expose technical identifiers only
  where they help the user." — Acceptance: each listed state (available/held/pending/
  loading/successful/refused/uncertain) has a visually distinct treatment; primary actions
  (pay/request/split/authorize submit) are visually prominent; displayed amounts use R103's
  formatted form and displayed timestamps are human-formatted, not raw RFC 3339, in ordinary
  page text (raw values may still live in `data-*` attributes — see A18).
- **R99** (interface, limit). "The required flows must remain clear and usable at a 375
  CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling.
  Inputs need visible labels, keyboard focus must be apparent, and text and controls need
  sufficient contrast. Provide considered empty, loading and error states, and keep
  navigation consistent across the required routes. A custom illustration, brand asset or
  exact visual match to a reference is not required." — Acceptance: no horizontal scrollbar
  at 375px width or at common desktop widths (e.g. 1280px+) on every required route; every
  input has an associated `<label>`; a visible focus outline/ring exists on interactive
  elements; text/control contrast meets at least WCAG AA (4.5:1 normal text); every empty-
  state testid (`empty-activity`, `empty-requests`, `empty-authorizations`) renders considered
  content, not a blank container; navigation (links/nav bar) appears identically across
  `/`, `/requests`, `/split`, `/authorizations`.

## Signup and login — `/signup`, `/login`

- **R100** (interface, behaviour). `data-testid` table: `signup-email`, `signup-password`,
  `signup-display-name` (inputs), `signup-submit` (button); `login-email`, `login-password`,
  `login-submit` (inputs/button); `auth-error` ("Present only when there is one");
  `current-user` ("Visible on every screen when signed in. Text contains the display name");
  `current-handle` ("Text is exactly the caller's handle, with no `@` and no surrounding
  words"); `logout-button` — Acceptance: each element present/absent exactly as stated; a
  failed signup/login shows `auth-error` with no prior instance lingering; every authenticated
  screen (`/`, `/requests`, `/split`, `/authorizations`) shows `current-user` and
  `current-handle`; `logout-button` ends the session (at minimum stops sending the stored
  token / returns the UI to a signed-out state).

## Balance and pay — `/`

- **R101** (interface). `data-testid` table: `wallet-balance` (formatted amount,
  `data-amount="{minor units}"`); `pay-handle`, `pay-amount` (decimal string, e.g. `15.00`),
  `pay-note` (inputs); `pay-visibility` (select, values exactly `public`/`private`);
  `pay-submit`; `pay-error` ("when the payment is refused — including insufficient funds");
  `request-handle`, `request-amount`, `request-note`, `request-submit`; `request-error` —
  Acceptance: exact element set, `pay-visibility` option values are the literal strings
  `public` and `private`, `pay-error`/`request-error` appear only on refusal.
- **R102** (retry, behaviour). "Keep the pay form's values after success. Submitting it again
  without changing a field must not send another payment: `wallet-balance` falls once, the
  feed contains one payment and `pay-error` is absent. Changing a field makes the next
  submission a new payment request. Retries follow §7." — Acceptance: post-success, inputs
  retain their values; an unchanged resubmit reuses the same `Idempotency-Key`+body (stage-1
  §7 replay), causing no second debit and no `pay-error`; editing any field (handle, amount,
  note or visibility) produces a new key/body and a genuinely new payment on submit.
- **R103** (interface, behaviour). "**Formatted amount.** `wallet-balance` is the decimal with
  exactly `minor_units` decimal places, a single space, then the currency code: `100.00 EUR`.
  For a `minor_units` of `0` there is no decimal point at all: `1200 JPY`. Balances are never
  negative, so there is no sign." — Acceptance: applies to every formatted-amount testid in
  this document (`wallet-balance`, `wallet-available`, `wallet-held`, `activity-amount-*`,
  `request-amount-*`, `split-share-*`, `authorization-amount-*`, `authorization-captured-*`);
  exact decimal-place count per the service's `minor_units`, single space, currency code, no
  leading `+`/`-`.
- **R104** (behaviour, error). "The form accepts decimal amounts and submits minor units to
  the API. With `minor_units: 2`, `15.00` and `15` both submit `1500`; `15.5` submits `1550`.
  Nonnumeric input or more than `minor_units` decimal places must show the form's error
  element without sending a request. For example, `15.005` is rejected rather than rounded."
  — Acceptance: `pay-amount`/`request-amount`/`split-amount`/`authorize-amount`/
  `authorization-capture-amount-{id}` all follow this rule; a value with excess decimal
  places or non-numeric characters blocks submission client-side and shows the screen's
  error testid (`authorization-error` for the capture-amount input) with zero HTTP requests
  sent for that attempt.

## Activity feed — `/`

- **R105** (interface). `data-testid` table: `activity-list` (container, "Its children are
  newest first in the DOM"); `activity-item-{payment_id}` (`data-visibility="public"` or
  `"private"`); `activity-parties-{payment_id}` ("Text contains both handles");
  `activity-amount-{payment_id}`; `activity-note-{payment_id}` ("Present even when the note
  is empty"); `empty-activity` — Acceptance: exact DOM order (newest first), exact attribute/
  text rules; `activity-note-{id}` exists (possibly empty text) for every visible payment.
- **R106** (limit). "Two payments with equal timestamps may appear in either order." —
  Acceptance: a same-timestamp ordering is not a defect either direction; tester's acceptance
  suite does not assert a specific order for such pairs.

## Requests — `/requests`

- **R107** (interface). `data-testid` table: `incoming-list`, `outgoing-list` (containers);
  `request-item-{request_id}` (`data-status="{status}"`); `request-amount-{request_id}`;
  `request-pay-{request_id}` ("Present only on a `pending` incoming request");
  `request-decline-{request_id}` ("Present only on a `pending` incoming request");
  `request-cancel-{request_id}` ("Present only on a `pending` outgoing request");
  `request-error` ("Shown when a pay, decline or cancel is refused"); `empty-requests`
  ("Shown when both lists are empty") — Acceptance: pay/decline buttons appear only for
  pending incoming requests in `incoming-list`; cancel button only for pending outgoing
  requests in `outgoing-list`; `empty-requests` shown iff both lists are empty (not one).

## Split — `/split`

- **R108** (interface). `data-testid` table: `split-amount` ("Decimal input, same rule as
  `pay-amount`"); `split-handles` ("Text input: handles separated by commas, in order");
  `split-note`, `split-submit`; `split-preview` ("Shows the computed shares before submitting.
  Contains one `split-share-{handle}` per participant"); `split-share-{handle}`; `split-error`
  — Acceptance: `split-handles` parsing preserves comma-order (feeds `participant_handles`
  order per stage-1 R76/R77); `split-preview` contains exactly one `split-share-{handle}` per
  parsed participant, including the caller if included.
- **R109** (behaviour). "`split-preview` must show the shares the server would compute, by the
  rule in `stage-1.md` §9, before anything is posted. The preview and submitted split must
  have identical shares." — Acceptance: client-computed preview shares equal
  `compute_shares` (stage-1 design §7) on the same amount/participant order, and equal the
  `shares` array stage-1's `POST /splits` returns when actually submitted with those same
  inputs.

## Post-action refresh (applies to `/`, `/requests`, `/split`)

- **R110** (behaviour). "After any successful action, the balance, the feed and the request
  lists on the same page must show the new state without a manual reload. Navigation must
  wait for the write to succeed before it refreshes the data. Any mechanism is fine, including
  a full navigation. **There is no live-update requirement here** — another client may change
  state, but this browser need only refresh after its own action or an explicit refresh." —
  Acceptance: after a successful pay/request/split/decline/cancel, the same page's
  balance/feed/request-list testids reflect the new state with no page reload initiated by
  the user; a write that is still pending must not refresh stale data early; a change made
  by another caller need not appear until this browser acts again or the user hits
  `wallet-refresh`.

## Competing clients and uncertain outcomes

- **R111** (concurrency, interface). "Add `wallet-refresh`, a button on `/` that refreshes the
  balance and feed without clearing the pay form. **Latest refresh wins:** a delayed earlier
  read must not overwrite a later refresh, including when responses arrive out of order." —
  Acceptance: `wallet-refresh` exists on `/`; clicking it never clears `pay-handle`/
  `pay-amount`/`pay-note`/`pay-visibility`; given two in-flight refreshes where the first
  request's response arrives after the second's (simulated via sequence numbers/delay), the
  displayed balance/feed matches the later-issued request, never the earlier one.
- **R112** (concurrency, behaviour). "Another client may spend the balance after this browser
  reads it. A refused payment shows `pay-error`, refreshes the balance/feed, and preserves all
  pay inputs. A request cancelled elsewhere while its pay button is visible must show
  `request-error` when payment is refused and refresh the request list so the stale pay button
  disappears." — Acceptance: a `409 insufficient_funds` (or, for requests, the request having
  become non-pending) on submit shows the relevant error testid, triggers a balance/feed (or
  request-list) refresh, and leaves the form's current input values intact.
- **R113** (retry, concurrency, behaviour). "If a payment response is lost, including after
  `POST /payments` commits, show `pay-uncertain` (nonempty text), not `pay-error`. Keep the
  unchanged form retryable with the **same key and body**. Successful retry removes both
  error/uncertainty elements, refreshes the balance and feed, and moves money exactly once.
  Unknown outcomes are not confirmed rejections." — Acceptance: `pay-uncertain` is a required
  `data-testid` (named here, without its own table row — see A19), shown with nonempty text
  when the pay request's response cannot be confirmed (timeout/network failure after send);
  the form stays submittable with the identical `Idempotency-Key` and body used for the lost
  attempt; a retry that lands resolves to either the original success (money moved once,
  `pay-uncertain`/`pay-error` cleared, balance/feed refreshed) or, if the original truly never
  reached the server, a fresh success — in neither case is `pay-error` shown for a merely
  unknown (not yet confirmed-refused) outcome.
- **R114** (behaviour, limit). "No background polling, live synchronization, or recovery
  across page reloads is required. The same balance refresh rules apply to the available and
  held amounts introduced below." — Acceptance: absence of background polling/live sync/
  reload-recovery is not a defect; `wallet-refresh`'s latest-wins rule (R111) and the
  uncertain-outcome handling (R113) apply identically to `wallet-available`/`wallet-held`
  once authorizations exist.

## Existing clients after an upgrade

- **R115** (compatibility). "A stage-2 service must accept an export produced by the same
  team's stage-1 service." — Acceptance: `POST /_test/import` with a stage-1
  (`format_version: 1`) export body succeeds (204), and every stage-1 guarantee in
  `stage-1.md` §10/R78-R85 holds against the resulting state.
- **R116** (compatibility). "A browser signed in before that export/import upgrade must
  remain signed in afterwards." — Acceptance: a bearer token obtained pre-import still
  authenticates (`GET /me` 200, not 401) immediately post-import.
- **R117** (compatibility). "Existing pending requests remain payable through the request
  screen." — Acceptance: a `pending` request seeded/created pre-import is still payable
  (via UI and API) post-import, with `available` correctly computed against any imported
  holds.
- **R118** (compatibility, retry). "A payment whose response was lost before export remains
  retryable after import with the same body and key; the UI must recover the original
  payment and refresh the imported balance." — Acceptance: replaying the same
  `Idempotency-Key`+body post-import returns the original 201-turned-200 response (stage-1
  R82/R91 behavior extended across the upgrade boundary), and the UI's retry path (R113)
  recovers and displays that original payment without moving money again.
- **R119** (compatibility, limit). "These requirements apply when import completes between
  browser requests; migration during an in-flight request is not required. No page reload or
  new screen is required. The form and pending retry identity must survive the upgrade." —
  Acceptance: import occurring concurrently with an in-flight request from the browser is out
  of scope (no assertion made on that interleaving); the pay form's stored key/body (for a
  not-yet-confirmed retry) is not reset by the import event itself.

## Authorizations and captures — concept and money invariants

- **R120** (behaviour). "A payment may be **authorised** now and **captured** later, for the
  full amount or less. An authorisation places a *hold* on the payer's wallet: it reserves
  money without moving it. Capturing moves the money; a final capture also releases whatever
  was not captured. Nonfinal captures keep the remainder held. An open authorisation expires
  and releases its remainder on its own." — Acceptance: creating an authorization changes
  `held`/`available` but not `total`; a capture changes `total` (moves money) as well as
  `held`/`available`; an authorization past `expires_at` behaves as releasing its remainder
  without any explicit client call.
- **R121** (behaviour, concurrency). "The sum of all wallet `total` values always equals the
  total seeded by the last reset. A hold moves no money; payments, settlements and captures
  transfer money between wallets." — Acceptance: money-invariant #1 (conservation on `total`)
  holds under any mix of authorize/capture/void/expiry alongside stage-1 operations; only
  payments, settlements and captures ever change any wallet's `total`.
- **R122** (concurrency, behaviour). "`available = total − held` must never be negative. Held
  funds cannot fund new payments, authorizations or settlement net debits. Captures may spend
  the money reserved for them." — Acceptance: money-invariant #2; `available` is never
  observed negative even transiently; a payment/authorization/settlement whose debit would
  push a wallet's `available` below zero is refused (409 `insufficient_funds`) rather than
  applied; a capture up to its authorization's held remainder always succeeds on funds grounds
  regardless of the payer's unrelated `available`.
- **R123** (concurrency, retry, behaviour). "Cumulative captures must not exceed the
  authorized amount. Each idempotent capture moves money once. A closed hold cannot be
  captured again." — Acceptance: money-invariant #3; sum of an authorization's capture
  amounts never exceeds its original `amount`; a replayed capture key moves money once (not
  per replay); a `captured`/`voided`/`expired` authorization rejects further captures
  (409, R147).

## Existing API changes

- **R124** (interface, behaviour, compatibility). "`GET /me` keeps `balance`, and `balance`
  **equals `total`**. `available` and `held` are new fields beside it. With no open holds,
  `balance`, `total` and `available` agree and `held` is zero, and every earlier behaviour is
  unchanged." — Acceptance: see R138 for the exact response shape; with zero open holds for
  a wallet, `balance == total == available` and `held == 0`.
- **R125** (behaviour). "`POST /payments` remains an immediate transfer. It must not leave an
  intermediate hold or require a separate capture." — Acceptance: a `POST /payments` call
  never creates an `authorizations` entry or a transient hold; money moves in the same step
  as stage 1.
- **R126** (behaviour, compatibility). "Every `409 insufficient_funds` in stage 1 — on
  `POST /payments`, `POST /requests/{id}/pay` and settlements — is now evaluated against
  `available`. With no open holds, the result is unchanged." — Acceptance: each of those
  three endpoints' funds check compares against `total − held`, not raw `total`; with
  `held == 0` for the relevant wallet(s), behavior is byte-identical to stage 1.
- **R127** (behaviour, limit). "Paying a request remains immediate. Authorizing a request is
  out of scope." — Acceptance: `POST /requests/{id}/pay` still performs an immediate payment
  (stage-1 R63-R66 unchanged); there is no endpoint to authorize (rather than pay) a request.
- **R128** (compatibility). "`POST /splits` is unchanged." — Acceptance: stage-1 R71-R74
  behavior, including the no-balance-check rule, is unmodified by stage 2.
- **R129** (interface, retry, compatibility). "There are now seven idempotent write paths:
  stage 1's five, authorizations and captures. The same replay rules apply independently to
  each." — Acceptance: `POST /authorizations` and `POST /authorizations/{id}/capture` each
  follow stage-1 §7's full replay/reuse/first-use/body-equality rules (R48-R54), scoped
  per-user, per-method+path+key, independently of the other five write paths and of each
  other.

## Model — fixture

- **R130** (interface, compatibility). "The fixture gains a service-wide default lifetime and
  an `authorizations` array." — example fixture fields: `authorization_ttl_seconds`,
  `authorizations: [{id, from_user_id, to_user_id, amount, note, visibility, status,
  expires_at}]` — Acceptance: `POST /_test/reset` accepts a fixture with these fields and
  seeds authorizations accordingly.
- **R131** (behaviour, limit, error). "`authorization_ttl_seconds` applies to every
  authorisation created through the API. It defaults to 600 when omitted. If supplied, it
  must be a positive integer number of seconds. Seeded authorisations carry their own
  absolute `expires_at` instead." — Acceptance: an API-created authorization's `expires_at`
  is `created_at + authorization_ttl_seconds` (default 600s if the fixture omitted the
  field); a non-positive or non-integer `authorization_ttl_seconds` in the reset fixture is
  a reset error (422 `validation_failed`, consistent with A13's pattern); seeded
  authorizations ignore the service TTL and use their own `expires_at` verbatim.
- **R132** (behaviour). "A user's seeded `balance` is still `total`. **`available` is
  derived, never seeded** — the service subtracts the seeded open holds itself." —
  Acceptance: the fixture never supplies `available`/`held` directly; the service computes
  them from `balance` (→`total`) minus the sum of that user's unexpired `open` seeded
  authorizations (plus any created later).
- **R133** (error, limit). "A sum of seeded unexpired open holds larger than that user's
  `balance` is a reset error: `422 validation_failed` from `POST /_test/reset`, changing
  nothing, exactly like a negative seeded balance." — Acceptance: such a fixture is rejected
  422, and `POST /_test/reset` leaves prior state completely untouched (same rule as
  stage-1 R15/A13 negative-balance handling).
- **R134** (interface). "Seeded `status` is `open`, `captured`, `voided` or `expired`. Only
  `open` holds anything." — Acceptance: seeded `captured`/`voided`/`expired` authorizations
  contribute nothing to `held`; only `open` (and unexpired, per R136) ones do.
- **R135** (compatibility). "An earlier fixture may omit `authorizations` altogether;
  omission means an empty list." — Acceptance: a stage-1-shaped fixture (no
  `authorizations` key) resets successfully with zero seeded authorizations and
  `held == 0` for every user.
- **R136** (time, behaviour, interface). "An authorization whose `expires_at` is at or before
  now is `expired` and holds no funds. Reads and writes must reflect expiry even if no
  request occurred at the deadline. `GET /authorizations` must show `status: "expired"`, and
  `GET /me` must include the released remainder in `available`." — Acceptance: expiry is
  computed against wall-clock time on every read/write path (no explicit "expire" call
  needed, no reliance on a background sweep having already run); a stored `open`
  authorization whose clock-computed state is expired reports `status: "expired"` from
  `GET /authorizations` and contributes 0 to `held` in every concurrent `GET /me`/write that
  observes it after the deadline.
- **R137** (limit). "Seeded expiry times are at least an hour from reset time, in the past or
  future; newly created authorizations may have shorter lifetimes." — Acceptance: fixtures
  used by the suite won't probe expiry windows under an hour for seeded data; no requirement
  to reject a shorter seeded `expires_at` — this simply bounds what test fixtures will send.

## `GET /me`

- **R138** (interface). Response shape: `user_id, display_name, handle, balance, total,
  available, held, currency, minor_units` — "`balance` and `total` are always equal. `held`
  is the sum of open holds, and `available` is `total − held`, never negative." — Acceptance:
  exact field set and equality/derivation rules; supersedes/refines R124 with the concrete
  shape.

## `POST /authorizations`

- **R139** (interface, retry). "`Idempotency-Key` is required. The caller is the payer."
  Body `to_handle, amount, note?, visibility?` — "`note` and `visibility` are optional with
  the same defaults as `POST /payments`." 201 body: `authorization_id, from_user_id,
  from_handle, to_user_id, to_handle, amount, captured_amount:0, currency, note, visibility,
  status:"open", expires_at, payment_id:null, created_at` — "`expires_at` is `created_at`
  plus `authorization_ttl_seconds`." — Acceptance: exact shape/defaults (`note` default
  `""`, `visibility` default `"public"`, matching stage-1 R56); `expires_at` computed from
  the service's (fixture-set or default-600) TTL at creation time, not from any client input.
- **R140** (error). Case table: caller's `available` below `amount` → 409
  `insufficient_funds`; `amount` <1, >1e9, or non-integer → 422 `validation_failed`;
  `to_handle` == caller's own handle → 422 `self_payment`; `note` >200 chars, or
  `visibility` neither `public` nor `private` → 422 `validation_failed`; unknown handle →
  404 `not_found` — Acceptance: exact status+code per case, mirroring stage-1's
  `POST /payments` case table (R57) with `available` substituted for balance.
- **R141** (behaviour). "An open authorisation is **not** a feed item and never appears in
  `GET /activity`." — Acceptance: `GET /activity` never returns an authorization; only the
  payment created by a later capture (R143) can appear there.

## `POST /authorizations/{id}/capture`

- **R142** (interface, retry). "`Idempotency-Key` is required. Only the receiver (the `to`
  party) may capture." Body `{amount?}` — "`amount` is optional and defaults to the
  authorisation's remaining amount. As on `POST /requests/{id}/pay`, **a replay must send the
  identical body** — `{}` and `{"amount": 2000}` are different JSON values even when they
  mean the same capture, so reusing a key across the two is `409 idempotency_key_reuse` per
  `stage-1.md` §7." — Acceptance: identical-to-stage-1 strict JSON-value body equality
  (design.md §6's type-aware comparison); an omitted-`amount` capture and an
  explicit-remaining-amount capture under the same key are treated as different bodies.
- **R143** (interface, behaviour). "Returns `201` with the created **payment**, in exactly the
  shape `POST /payments` returns, with `authorization_id` set to this authorisation and
  `request_id: null`. The payment's `amount` is the captured amount; its `note` and
  `visibility` are copied from the authorisation; it appears in the activity feed by the
  ordinary visibility rule. Payments created without an authorisation carry
  `authorization_id: null`; their existing `request_id` semantics are unchanged." —
  Acceptance: stage-1's payment shape (R56) gains an `authorization_id` field, `null` on
  every pre-existing payment-producing path (payments, request-pay, settlements); a capture's
  resulting payment's `note`/`visibility` are copied, not client-supplied; it obeys the
  stage-1 feed-visibility rule (R26-R29) exactly.
- **R144** (behaviour). "By default the authorisation becomes `captured`, carries
  `captured_amount` and `payment_id`, and **releases the uncaptured remainder immediately**:
  capturing 1500 of 2000 returns 500 to the payer's `available` in the same step." —
  Acceptance: a default (final) capture below the full amount both moves the captured amount
  and releases the rest of the hold atomically — `available` reflects both effects after one
  request, never an intermediate state with only one applied.
- **R145** (error). "**Default: one final capture per authorisation.** A second capture after
  a final capture is `409 authorization_not_open`." — Acceptance: a first-use capture with
  default `final` (true) closes the authorization; any subsequent capture attempt (different
  idempotency key) on that authorization is 409 `authorization_not_open`.
- **R146** (behaviour, interface). "**Extended capture mode.** To keep the remainder held,
  send `{"amount": 700, "final": false}`. `final` is boolean, default `true`, so earlier
  single-capture requests retain their behavior. With `final: false` and an uncaptured
  remainder, status stays `open`; further captures are allowed up to that remainder.
  Capturing the entire remainder closes it even with `final: false`. A final capture closes
  it and releases any remainder. `capture_exceeds_authorization` compares with the
  **remaining** amount; omitted amount defaults to that remainder. `captured_amount` is
  cumulative; `payment_id` is the latest capture; `payment_ids` lists every capture in order.
  Every authorization response adds `remaining_amount`: the amount still held, zero when
  closed. Void and expiry can close a partially captured authorization, release only the
  remainder, and preserve all capture records. New fields do not change idempotency body
  equality." — Acceptance: multi-capture sequences accumulate correctly (`captured_amount`
  sum, `payment_ids` in capture order, `payment_id` == last element); `422
  capture_exceeds_authorization` compares the requested amount against the *current*
  remaining (not the original `amount`); a `final:false` capture of the exact remainder
  closes the authorization (status becomes `captured`); void/expiry on a partially-captured
  authorization releases only what remains held, leaving `captured_amount`/`payment_ids`
  intact; `remaining_amount` and `payment_ids` participate in the response shape (the source
  does not require echoing `final` itself in any response — see A23); the idempotency
  body-equality check (stage-1 §7) still compares only the *request* body, so these new
  *response* fields never affect replay matching regardless.
- **R147** (error). Case table: authorization not `open` → 409 `authorization_not_open`;
  `expires_at` at or before now → 409 `authorization_expired`; `amount` above the
  authorisation's uncaptured remainder → 422 `capture_exceeds_authorization`; `amount` below
  1, or not an integer → 422 `validation_failed`; caller not the receiver → 403 `forbidden`;
  unknown authorisation → 404 `not_found` — Acceptance: exact status+code per case; "not
  open" (stored status) and "expired" (clock-computed on a stored-`open` record) are
  distinct, separately-triggerable cases (see R136).

## `POST /authorizations/{id}/void`

- **R148** (interface, behaviour, error). "**Only the payer may void** — the `from` party
  releasing their own hold. No idempotency key, like decline and cancel." "`200` with the
  authorisation, `status: "voided"`, the hold released. Voiding an already-voided
  authorisation is `200` with the current state. A `captured` or `expired` one is
  `409 authorization_not_open`." — Acceptance: no `Idempotency-Key` required or consulted
  (extends stage-1 A6 — see A15); repeat-void of an already-`voided` authorization is `200`,
  not an error; a `captured` authorization *or* a clock-expired one both give
  `409 authorization_not_open` (not `authorization_expired` — that code is capture-only,
  per R147).
- **R149** (error, behaviour). "For an existing authorization, capture and void return `403
  forbidden` when the caller is not the permitted party, including callers who are neither
  party. `GET /authorizations` returns only authorizations involving the caller." —
  Acceptance: a third-party caller (neither payer nor receiver) gets 403 on capture/void, not
  404; `GET /authorizations` never returns an authorization where the caller is neither
  `from_user_id` nor `to_user_id`.

## `GET /authorizations`

- **R150** (interface). "Authorisations where the caller is the payer or the receiver, and no
  others. Newest first by `created_at`." Query: `direction` (`outgoing`=caller is payer,
  `incoming`=caller is receiver, absent=both), `status` (one of the four, or absent=all).
  "`limit`, `offset` and `has_more` behave exactly as on `GET /requests`." — Acceptance:
  same pagination/filter semantics as stage-1 R69/R70 (defaults, ranges, `has_more`,
  invalid-value 422), applied to the authorization list and its `direction`/`status`
  vocabulary; response envelope and item shape per A21 (source states filters/pagination
  but not the response body itself).
- **R151** (time, behaviour). "An authorisation expired by the clock matches `expired`, never
  `open`." — Acceptance: `?status=open` never returns a clock-expired authorization even if
  its stored status field is still `"open"`; `?status=expired` does return it.

## UI — `/authorizations` and wallet additions

- **R152** (interface). "A new route `/authorizations`, and the wallet gains two numbers. The
  UI and the API share `/authorizations`: serve HTML for `Accept: text/html` and JSON
  otherwise, as for `/requests`." — Acceptance: same content-negotiation rule as R95,
  applied to `/authorizations`.
- **R153** (interface, behaviour). `data-testid` table: `wallet-balance` ("Formatted `total`,
  retaining the existing display and `data-amount`"); `wallet-available` ("Formatted
  `available`, with `data-amount`. **Present this as the headline number** — it is what the
  user can actually spend"); `wallet-held` ("Formatted `held`, with `data-amount`. Absent
  when `held` is zero") — Acceptance: `wallet-balance` continues to mean `total` (R103's
  format applies); `wallet-available` is the visually primary figure on `/` (ties to R97);
  `wallet-held` is present iff `held > 0` for the current user.
- **R154** (interface). `data-testid` table: `authorize-handle`, `authorize-amount`,
  `authorize-note`, `authorize-visibility`, `authorize-submit` ("The authorise form. Same
  input rules as the pay form"); `authorize-error` ("Shown when the authorisation is
  refused, including insufficient available funds") — Acceptance: `authorize-amount` follows
  R104's decimal-parsing rule; a 409 `insufficient_funds` (available-based, R140) on submit
  shows `authorize-error`.
- **R155** (interface). `data-testid` table: `authorization-list` (container, "Children
  newest first in the DOM"); `authorization-item-{authorization_id}`
  (`data-status="{status}"`); `authorization-amount-{id}`; `authorization-captured-{id}`
  ("Present only when `status` is `captured`"); `authorization-expires-{id}` ("Text is the
  RFC 3339 `expires_at`"); `authorization-capture-amount-{id}` ("Decimal input, pre-filled
  with the remaining amount. Present only on an incoming `open` authorisation");
  `authorization-capture-{id}` ("Button. Present only on an incoming `open` authorisation");
  `authorization-void-{id}` ("Button. Present only on an outgoing `open` authorisation");
  `authorization-error` ("Shown when a capture or a void is refused"); `empty-authorizations`
  — Acceptance: exact presence rules per status/direction (an "open" status here means
  clock-unexpired open, per R151); `authorization-capture-amount-{id}`'s pre-filled value
  equals the current `remaining_amount` (R146).
- **R156** (behaviour). "The UI must reflect seeded and newly created holds. Show available
  funds as the user's spending balance, including immediately after reset with open holds."
  — Acceptance: immediately after a `POST /_test/reset` that seeds open holds for the signed-
  in user (on next login/session), `wallet-available` reflects those holds without requiring
  any authorization to be created or captured first.

## Concurrent operations

- **R157** (concurrency). "Concurrent requests must produce the same results as executing
  them one at a time in some order, and the requirements above hold at every read." —
  Acceptance: under concurrent authorize/capture/void/expiry/payment/settlement traffic, the
  observed outcome always matches *some* serial ordering of the same requests (linearizable
  write path, per design.md's single-critical-section rule extended to the two new write
  paths and to void/expiry's read-time computation), and every money invariant (R121-R123,
  plus stage-1 R1-R3) holds at every intermediate read.

## Assumptions

- **A14**. Validation order within `POST /authorizations` and `POST /authorizations/{id}/
  capture` follows the same pattern as stage-1 A1/A2: field-shape/format errors first, then
  resource existence (404 unknown handle/authorization), then permission (`403 forbidden`
  for capture's receiver-only and void's payer-only checks, which must follow existence since
  they need the resolved record), then resource-state (`409 authorization_not_open`/
  `authorization_expired`), then amount-vs-remainder (`422 capture_exceeds_authorization`),
  then funds (`409 insufficient_funds` on `POST /authorizations`) last — a single fixed,
  documented order per endpoint, consistently applied. Reasoning: stage-2.md's case tables,
  like stage-1's, list cases without stating precedence beyond what logically must hold
  (existence before state, state before amount-vs-remainder since "remainder" is only
  meaningful for an open, unexpired authorization); A1's "any single deterministic order is
  acceptable" applies identically here.
- **A15**. No `Idempotency-Key` handling applies to `POST /authorizations/{id}/void`
  (explicitly "No idempotency key, like decline and cancel," stage-2.md). A client-supplied
  key on void is ignored entirely — not read, not claimed, not consumed — exactly extending
  A6's reasoning: void sits outside the now-seven named idempotent write paths (R129 lists
  authorizations and captures as the two *added* idempotent paths; void is not among them),
  so it has no mechanism to interact with the idempotency table.
- **A16**. The body-type gate of stage-1 A8 (a write-path body that parses as valid JSON but
  whose top-level value is not a JSON object is `400 malformed_request`, rejected before
  authentication and before any idempotency-key interaction) applies identically to
  `POST /authorizations` and `POST /authorizations/{id}/capture`, the two new idempotent
  write paths. Reasoning: R129 states "the same replay rules apply independently to each" of
  the seven idempotent write paths; A8's gate is part of that same §7-derived machinery
  (stage-1 design.md §5 step 1), not an endpoint-specific carve-out, so it extends to any
  endpoint added to the idempotent-write-path set.
- **A17**. R97's "coherent, presentation-ready consumer finance product... calm, trustworthy
  character" and R98's "easy to scan... understandable without interpreting raw API data"
  are graded qualitatively (by the reviewer's product-quality read of the running UI), not by
  a single mechanical assertion; the tester's acceptance suite checks the concrete, testable
  sub-rules stated elsewhere in this document (R99's contrast/label/focus/no-scroll rules,
  R97's available-is-primary ordering, R98's per-state visual distinctness via CSS/DOM
  inspection) and treats the remaining descriptive language as satisfied by design review,
  not an automated pass/fail. Reasoning: the source text itself frames these as qualitative
  product direction ("aim for," "should be," "feel like"), distinct from the mechanically
  testable `data-testid`/format/behavior rules that surround them.
- **A18**. R98's "expose technical identifiers only where they help the user" governs
  user-visible *text content*, not `data-testid` attribute values or `data-*` attributes
  (`data-amount`, `data-status`, `data-visibility`) — those necessarily encode ids/handles/
  raw values for integration testing (R96) and are not rendered to the user as text.
  Reasoning: R96 explicitly requires exposing ids/handles/statuses in `data-testid`/`data-*`
  attributes for every screen; reading R98 to forbid that would directly contradict R96, so
  the conservative resolution scopes R98 to visible text only. This same scoping excludes
  `authorization-expires-{id}` from R98's "timestamps for people first" clause: R155
  explicitly requires that element's *text* to be "the RFC 3339 `expires_at`" verbatim, a
  specific per-element rule that overrides R98's general preference for that one element
  only (every other displayed timestamp still follows R98's people-first formatting).
  Reasoning: the same specific-overrides-general pattern already used throughout this
  document (e.g. R57/A2's endpoint-specific field rules over the general error table).
- **A19**. `pay-uncertain` (named only in R113's prose, with no table row elsewhere in
  stage-2.md) is a required `data-testid` element on `/`, governed by the same
  presence/text rules as the screen's other conditional-error elements (`pay-error`): absent
  by default, present with nonempty text exactly when a pay response is lost/unconfirmed per
  R113, and cleared on a subsequent confirmed outcome. Reasoning: the spec names it as a
  concrete element the UI "must" show, using the same `data-testid`-attribute convention as
  every explicitly tabled element; the omission from a table is treated as the same kind of
  abbreviation stage-1's A-series already accepts for spec silences, not as license to skip
  implementing it.
- **A20**. The `wallet-balance` definition repeated in R153 ("Formatted `total`, retaining
  the existing display and `data-amount`") is the same element as R101's `wallet-balance`,
  not a second, conflicting one — R153 merely confirms that adding `wallet-available`/
  `wallet-held` does not change `wallet-balance`'s pre-existing meaning. Reasoning: stated
  explicitly by "retaining the existing display."
- **A21**. `GET /authorizations`'s response is `{"authorizations": [...], "has_more": bool}`;
  each item is exactly the authorization representation used elsewhere (R139's `POST
  /authorizations` 201 shape plus R146's `captured_amount`/`remaining_amount`/`payment_id`/
  `payment_ids`) — the same "one representation, used everywhere" principle stage-1 R56
  already established for payments. Reasoning: the source states R150's filters/pagination
  but never an explicit response envelope; the closest sibling endpoint, `GET /requests`
  (stage-1 R69), uses the `{"<plural>": [...], "has_more": bool}` envelope with its
  create-response item shape reused verbatim, and stage-2.md gives no indication
  `GET /authorizations` deviates from that established pattern.
- **A22**. Seeded authorizations: (a) a seeded `status: "expired"` record is accepted and
  stored internally as `"open"` (design.md §3 — `"expired"` is never a stored value) only
  when its `expires_at` is at or before reset time; a seeded `"expired"` record whose
  `expires_at` is in the future is a contradictory fixture value and a reset error (`422
  validation_failed`, changing nothing — same family as R133); (b) a seeded `"captured"` or
  `"voided"` record not supplying `captured_amount`/a capture-payment defaults to
  `captured_amount: 0`, `payment_ids: []` (the fixture format has no field to supply either,
  same gap A12 already accepts for stage-1 seeded request statuses); (c) a seeded
  authorization with `from_user_id == to_user_id`, or referencing an unknown user id, is a
  reset error (`422 validation_failed`, changing nothing — same one-code-for-fixture-shape-
  defects pattern as A13). Reasoning: each case mirrors an existing stage-1/stage-2
  assumption's conservative pattern for a fixture value the spec's example doesn't cover,
  applied here for consistency rather than inventing a new error code or silently accepting
  an internally-contradictory or dangling-reference fixture.
- **A23**. `POST /authorizations/{id}/capture`'s response does not echo the request's
  `final` field — only `remaining_amount` and `payment_ids` are new response fields (R146).
  Reasoning: the source states "Every authorization response adds `remaining_amount`" and
  separately establishes `payment_ids`, but at no point shows or requires `final` appearing
  in any response body; `final` is a request-only field, like `amount` on the same endpoint
  is present in the request but not echoed back under its request name.
- **A24**. `final` supplied with a non-boolean JSON type (e.g. `"final": "yes"`) on
  `POST /authorizations/{id}/capture` is `400 malformed_request`, not `422
  validation_failed`. Reasoning: stage-2.md states no endpoint-specific override for
  `final`'s type (unlike `amount`, which has an explicit 422 case), so it falls to the
  general stage-1 §5/R40 rule: a field of the wrong JSON type with no endpoint-specific
  override is 400, not 422 — the same general-rule fallback A9 already applies to
  settlement-entry field types.
- **A25**. The `authorize-*` form (`authorize-handle`/`amount`/`note`/`visibility`/`submit`,
  `authorize-error`) is rendered on `/authorizations`, alongside `authorization-list`, not
  on `/`. Reasoning: the source's "## UI" section introduces "a new route
  `/authorizations`" immediately before tabling the authorize-form and list testids
  together, and explicitly scopes `authorization-list` to that route ("Container on
  `/authorizations`"); nothing in R94's original route table (which predates authorizations
  entirely) claims the form for `/`, so the more specific, later section's framing governs.
- **A26**. `logout-button` is visible on every authenticated screen (`/`, `/requests`,
  `/split`, `/authorizations`), the same presence rule R100 states explicitly for
  `current-user`/`current-handle`. Reasoning: R100 tables `logout-button` alongside those
  two elements without repeating "visible on every screen when signed in" verbatim, but a
  signed-in user needs a way to sign out from any screen they can reach; reading the
  omission as "logout-button exists on only one unspecified screen" would leave no stated
  screen for it at all, which is not a coherent reading of a "must" requirement.
- **A27**. `POST /authorizations`'s worked example, where the 201 body shows
  `"expires_at": "2026-09-24T13:10:00+00:00"` equal to `"created_at"` of the same value, is
  an abbreviated/illustrative example and does not override the normative sentence
  immediately following it, "`expires_at` is `created_at` plus
  `authorization_ttl_seconds`" (R139) — `expires_at` is always strictly
  `created_at + authorization_ttl_seconds`, never equal to `created_at` unless the service's
  TTL were (invalidly) zero. Reasoning: stated normative rules govern over examples
  throughout this document (e.g. stage-1's rounding table is normative while endpoint JSON
  samples elsewhere are illustrative); an example that contradicts an adjacent explicit
  formula is the example's abbreviation, not a second rule.
- **A28** (recorded post-verification, reviewer finding). Server-rendered authenticated page
  routes (`/`, `/requests`, `/split`, `/authorizations`) authenticate via a session cookie
  (`pocketful_token`, the bearer token URL-encoded, `path=/; SameSite=Lax`) that the client
  script sets via `document.cookie` after a successful `POST /auth/login` or
  `/auth/signup` — the server itself never sends `Set-Cookie`; the API's bearer-token
  contract (stage-1 §6) is unchanged for every JSON endpoint. A client that does not execute
  the page's JavaScript (a pure-HTTP client with no cookie jar primed from that script) will
  not see authenticated content on a server-rendered page load, by design — this is not a
  product defect. Reasoning: nothing in stage-2.md specifies the session-establishment
  mechanism for a full page navigation (which cannot carry a custom `Authorization` header);
  R96/"integration testing" and the spec's own UI-testing framing, plus the fact that
  developer's Playwright (JS-executing) e2e suite passes 46/46 against every authenticated
  route, indicate the intended testing mode executes the page's script like a real browser
  does. Changing the server to also set `Set-Cookie` on login — purely to satisfy a
  pure-HTTP black-box suite — would be a behavior change whose only justification is a check
  result, which the run's "never add behaviour whose only justification is a check result"
  rule forecloses; instead, a black-box HTTP suite exercising an authenticated page route
  must replicate the same cookie (name, value, encoding) the client script sets.
