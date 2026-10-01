# Stage 3 requirements — pocketful: statements and payment corrections

Source: `we-are-devs/pocketful/spec/stage-3.md` (full text pasted into every handoff), which
states "the requirements from stages 1 and 2 continue to apply, with the additions below."
All of `specs/stage-1/requirements.md` (R1-R93, A1-A13) and `specs/stage-2/requirements.md`
(R94-R157, A14-A28) therefore stay in force by reference; this document numbers only stage
3's additions and changes, continuing from R158/A29. Section references such as §5 and §7
refer to `stage-1.md`, as stage-3.md itself directs. Kind values: behaviour, error, limit,
concurrency, retry, time, compatibility, interface.

## Payment timestamps

- **R158** (interface, time). "Every payment's `created_at` is an RFC 3339 instant with an
  offset identifying when it moved money. Every endpoint returning a payment includes it." —
  Acceptance: every payment representation returned by any endpoint (`POST /payments`,
  `GET /activity`, `GET /requests`, `POST /splits`, settlements, captures, `GET /statement`)
  carries `created_at` as an RFC 3339 instant with an explicit offset.
- **R159** (time, compatibility). "`GET /activity` retains its existing ordering by this
  field." — Acceptance: stage-1's `GET /activity` ordering rule (newest/oldest per stage-1
  R57-R60) is unchanged and keyed on `created_at`, unaffected by corrections (R206 below
  keeps corrections out of the feed).
- **R160** (behaviour, time). "Seeded payments may supply `created_at`; omission uses reset
  time, before subsequent API-created payments." — Acceptance: a reset fixture's payment
  entries accept an optional `created_at`; when absent, the loader assigns the reset instant;
  a seeded payment's `created_at` is always ≤ every payment created afterward via the API in
  the same run.
- **R161** (error, limit). "A seeded `created_at` in the future gives `422
  validation_failed` from `POST /_test/reset`, with no state change." — Acceptance: a fixture
  payment whose `created_at` is later than the reset instant is rejected 422, and the reset
  call makes no state change (same all-or-nothing fixture-validation rule as stage-1/stage-2
  seed errors).
- **R162** (behaviour, limit). "A fixture's `balance` remains the balance after all seeded
  payments. Loading those payments must not change that balance." — Acceptance: loading a
  fixture's seeded payment history is bookkeeping only (builds revision-1 history and
  `created_at` ordering); it must not apply any additional debit/credit beyond the fixture's
  stated `balance` fields — the ending balance equals the fixture's declared `balance`
  exactly, not `balance` plus or minus the seeded payments' net effect a second time.

## `GET /me` as of an instant

- **R163** (interface, time, error). "`as_of` is optional and is an RFC 3339 instant with an
  offset. Anything else — a naive local time, a bare date, an empty value — is 422
  `validation_failed`." — Acceptance: `GET /me?as_of=<RFC3339-with-offset>` is accepted; a
  naive local time (no offset), a bare date (`2026-09-24`), or `as_of=` (empty) each give 422
  `validation_failed`.
- **R164** (behaviour, compatibility). "Without temporal query parameters the response
  retains the existing money fields and reports current corrected values." — Acceptance: a
  plain `GET /me` (no `as_of`, no `known_at`) returns `balance`/`total`/`available`/`held`
  reflecting the current state including the latest revision of every payment (i.e. current
  corrected values, not just original amounts).
- **R165** (behaviour, time). "With it, `balance` is the caller's balance as it stood at that
  instant: the balance after every payment of theirs with `created_at` at or before `as_of`,
  and before every payment after it. A payment made at exactly `as_of` counts as having
  happened." — Acceptance: `balance` at `as_of` equals the opening balance plus the net effect
  of every one of the caller's payments whose `created_at <= as_of`; a payment with
  `created_at == as_of` is included.
- **R166** (behaviour, time). "An `as_of` at or after the latest payment returns the current
  balance." — Acceptance: an `as_of` at or after the caller's most recent payment's
  `created_at` yields the same `balance` as a plain (no `as_of`) request.
- **R167** (behaviour, time). "An `as_of` before the earliest payment returns the opening
  balance — what the wallet held before anything moved." — Acceptance: an `as_of` earlier
  than the caller's first payment returns the account's opening balance (R181/R182 define how
  opening balances are derived), independent of any payment.
- **R168** (interface, time). "The response carries `as_of` back, exactly as given." —
  Acceptance: a `GET /me?as_of=X` response includes `as_of` equal to the exact string `X`
  from the request (not reformatted/re-serialized).

## `GET /statement`

- **R169** (interface). Route `GET /statement?from=<instant>&to=<instant>&limit=50&offset=0`.
  — Acceptance: the route exists, requires authentication like every other wallet endpoint,
  and accepts the four named query parameters.
- **R170** (behaviour, time). "Both `from` and `to` are optional; `from` defaults to the
  opening of the wallet and `to` to now." — Acceptance: omitting `from` includes every payment
  from account opening; omitting `to` includes every payment up to (not including) the instant
  the request is processed.
- **R171** (interface, compatibility). "`limit` and `offset` behave exactly as in
  `GET /requests`." — Acceptance: same shared ranges (`limit` 1-200, `offset` ≥ 0, stage-1
  §5 table), same `has_more` semantics as stage-1's `GET /requests`.
- **R172** (interface, behaviour). Response shape: `{"opening_balance": int, "entries":
  [{"payment": {...}, "delta": int, "balance_after": int}, ...], "closing_balance": int,
  "has_more": bool}` — "Returns the payments the caller sent or received in the half-open
  window `[from, to)`, oldest first, each with the caller's balance immediately after it." —
  Acceptance: the response matches this shape exactly; `entries` is ordered oldest-first;
  every entry's `payment` is the full payment representation (R158 et al.) with the caller's
  `delta` and `balance_after` alongside it. (No `from`/`to` echo is required — the response
  shape example shows none; see A31.)
- **R173** (behaviour, limit). "1. Entries are ordered by `created_at` ascending, then
  payment `id` ascending for ties." — Acceptance: for two entries with equal `created_at`,
  the one with the lexicographically/numerically smaller `id` (per stage-1's id ordering
  convention) appears first.
- **R174** (behaviour, time). "2. `opening_balance` is the balance immediately before `from`.
  `closing_balance` is the balance immediately before `to`." — Acceptance: `opening_balance`
  equals the caller's balance computed the same way as R165 at instant `from` but *excluding*
  any payment with `created_at == from` (immediately before, not at-or-before); `closing_balance`
  is the same computed at `to`, excluding any payment at exactly `to` (consistent with the
  half-open `[from, to)` window of R172).
- **R175** (concurrency, limit). "3. `opening_balance` plus all `delta` values in the full
  window must equal `closing_balance`. A sent payment has a negative `delta`; a received
  payment has a positive `delta`." — Acceptance: statement invariant — summing every entry's
  `delta` across the *entire* window (not just the returned page) and adding to
  `opening_balance` yields exactly `closing_balance`; a payment where the caller is the sender
  has `delta < 0` (or `delta == 0` only for a zero-amount correction revision, R220); a payment
  where the caller is the receiver has `delta > 0`.
- **R176** (limit, interface). "4. Pagination must not change an entry's `balance_after` or
  the window's opening and closing balances. These values describe the full window regardless
  of `limit` and `offset`." — Acceptance: requesting the same window with different
  `limit`/`offset` pairs returns `opening_balance`/`closing_balance` identical across all
  pages, and each entry's `balance_after` identical to its value on any other page containing
  it.
- **R177** (behaviour, interface). "Only payments sent or received by the caller appear in
  their statement, including when other payments are public. The activity-feed visibility
  rules do not apply to statements." — Acceptance: a statement never includes a third-party
  payment even if that payment is `visibility: public`; a statement always includes every
  payment the caller sent or received regardless of its `visibility`.

## Effective time, recorded time, and corrections — data model

- **R178** (behaviour, time). "Every payment has a revision history. Revision 1 has `amount`
  as originally paid and `effective_at = recorded_at = created_at`." — Acceptance: every
  payment, from creation, has an implicit or explicit revision 1 whose `amount` is the
  original payment amount and whose `effective_at`/`recorded_at` both equal `created_at`.
- **R179** (behaviour, time). "A seeded payment's supplied `created_at` is also its original
  recorded/effective time; omission uses reset time." — Acceptance: a seeded payment's
  revision 1 `effective_at`/`recorded_at` equal its `created_at` (R160) exactly, whatever that
  resolved to.
- **R180** (behaviour, limit). "Opening balances equal seeded ending balances minus the net
  effect of original seeded payments. Corrections must not change those opening balances." —
  Acceptance: an account's opening balance (used by R167/R174) is computed once at seed/reset
  time as `fixture.balance - net(seeded payments as originally seeded)`, and is never
  recomputed or altered by a later correction, however many revisions a seeded payment
  acquires.
- **R181** (behaviour, limit). "New accounts open at zero." — Acceptance: a user created via
  `POST /auth/signup` (no seeded history) has an opening balance of `0`.
- **R182** (limit, error). "Seeded history is consistent and nonnegative." — Acceptance: see
  A29 for the error given when a fixture's seeded payment history would, applied in
  `created_at` order from each account's opening balance, make any account negative at any
  point.

## Corrections — request and validation

- **R183** (interface, retry). "`POST /payments/{payment_id}/corrections` requires an
  idempotency key and the original sender." — Acceptance: the route requires
  `Idempotency-Key` under the stage-1 §7 rules (missing/empty → 400
  `missing_idempotency_key`); only the payment's original sender may call it successfully.
- **R184** (error). "An authenticated non-sender gets 403 `forbidden`; unknown payment gets
  404." — Acceptance: an authenticated user who is not the payment's sender (including the
  receiver) gets 403 `forbidden`; a `payment_id` that does not exist (or is not visible —
  same as "unknown" per stage-1 convention) gets 404 `not_found`.
- **R185** (interface). Request body: `{"expected_revision": 1, "amount": 400,
  "effective_at": "2026-09-20T12:00:00+00:00", "reason": "corrected amount"}`. "All fields are
  required." — Acceptance: a body missing any of `expected_revision`, `amount`,
  `effective_at`, `reason` is 422 `validation_failed`.
- **R186** (limit, error). "Revision is a positive integer." — Acceptance: `expected_revision`
  must be a JSON integer ≥ 1; zero, negative, non-integer or non-numeric values are 422
  `validation_failed` (wrong JSON type, e.g. a string, is 400 `malformed_request` per the
  stage-1 §5 general rule, consistent with A24's precedent for `final`).
- **R187** (limit, error). "amount is an integer 0..1000000000 (zero reverses the entire
  payment)." — Acceptance: `amount` must be a JSON integer in `[0, 1000000000]`; out-of-range
  is 422 `validation_failed`; `amount: 0` is a valid correction that reverses the payment's
  entire effect from its effective time onward; wrong JSON type is 400 `malformed_request`
  (stage-1 §5 general rule, as for `amount` elsewhere — endpoint-specific field rules
  precedent, stage-1 §5).
- **R188** (limit, error). "reason is a string of 1..200 characters." — Acceptance: `reason`
  must be a string of length 1-200; empty string, too-long string, or non-string is 422
  `validation_failed` (non-string is listed among stage-1's endpoint-specific 422 field rules,
  same family as `note`).
- **R189** (limit, error, time). "effective time is an RFC 3339 instant not later than now." —
  Acceptance: `effective_at` must be an RFC 3339 instant with offset, and not later than the
  instant the request is processed; a future `effective_at`, or a malformed/naive instant, is
  422 `validation_failed`.
- **R190** (error). "Invalid input is 422 `validation_failed`." — Acceptance: general
  fallback, consistent with stage-1 §5's catch-all, for any correction-body rule violation not
  given a more specific code above.
- **R191** (behaviour). "Correction changes neither parties nor visibility." — Acceptance: a
  correction never changes a payment's `from_user_id`/`to_user_id`/`visibility`; these fields
  are absent from the correction body and untouched by its effect.
- **R192** (interface, behaviour). "It appends an immutable revision, returning 201 with
  `payment_id`, `revision`, `amount`, `effective_at`, server-assigned `recorded_at`, and
  `reason`." — Acceptance: a successful correction returns 201 with exactly these fields;
  `revision` is `expected_revision + 1`; `recorded_at` is server-assigned (not client-supplied)
  and is an RFC 3339 instant.
- **R193** (time, concurrency). "Recorded times for one payment strictly increase." —
  Acceptance: for any payment, revision N+1's `recorded_at` is strictly later than revision
  N's `recorded_at`, for every N, even under concurrent correction attempts (only one can
  succeed per R197 below).
- **R194** (error, concurrency). "A stale expected revision gives 409 `stale_revision`." —
  Acceptance: a correction whose `expected_revision` does not equal the payment's current
  latest revision number is rejected 409 `stale_revision`, state unchanged.
- **R195** (retry, behaviour). "Successful replay returns that original revision with 200
  even after newer revisions." — Acceptance: replaying a correction request (same
  idempotency key, same body) after the request originally succeeded returns 200 with the
  same `revision`/`amount`/`effective_at`/`recorded_at`/`reason` as the original 201, even if
  later corrections (under different keys) have since been applied to the same payment.
- **R196** (retry, error). "Different body with the same key is 409
  `idempotency_key_reuse`." — Acceptance: same as stage-1 §7's general idempotency rule,
  applied to corrections: a different body under a previously-used key is 409
  `idempotency_key_reuse`, no state change.

## Corrections — money movement and failure modes

- **R197** (behaviour, concurrency). "The difference from the previous amount moves between
  the same two wallets in the same atomic step. Increasing the amount debits the original
  sender; decreasing it debits the original receiver." — Acceptance: a correction from amount
  A to amount B (A, B being the payment's amount immediately before and after this
  correction) moves `|B - A|` between the same `from_user_id`/`to_user_id` pair as the
  original payment, atomically with recording the new revision; if `B > A` the sender is
  debited `B - A` (receiver credited); if `B < A` the receiver is debited `A - B` (sender
  credited).
- **R198** (error, behaviour). "A currently unaffordable debit gives 409
  `insufficient_funds`." — Acceptance: if the party being debited by this correction (R197)
  cannot currently afford it (their `available`, per the stage-2 definition, would go
  negative *now*), the correction is rejected 409 `insufficient_funds`, state unchanged.
- **R199** (error, time, concurrency). "Otherwise, if any user's corrected balance is negative
  at any effective-time boundary, return 409 `historical_overdraft`." — Acceptance: if the
  current-affordability check (R198) passes, but replaying every known revision's effective
  movements in effective-time order would make any involved user's historical `total` negative
  at any instant, the correction is rejected 409 `historical_overdraft`, state unchanged.
- **R200** (time, behaviour). "Balances at a boundary include the combined effect of all
  movements at that instant." — Acceptance: when two or more movements share the same
  effective instant, the historical-overdraft check (R199) evaluates their combined (summed)
  effect at that instant, not each movement checked in isolation against an intermediate
  state.
- **R201** (concurrency, behaviour). "Either failure preserves balances, revision history,
  statements and idempotency state." — Acceptance: a correction rejected with
  `insufficient_funds` or `historical_overdraft` leaves every wallet balance, every payment's
  revision history, every statement/snapshot, and all idempotency records exactly as before
  the attempt (no partial revision appended, no idempotency key claimed as if first-used for
  retry purposes beyond the standard "failed request frees the key" rule).
- **R202** (concurrency, limit). "The sum of balances must equal the seeded total in every
  historical view." — Acceptance: money-invariant extension — for any `as_of`/`known_at`
  combination, the sum of every user's historical `total` at that view equals the total
  seeded by the last reset (conservation holds in every historical view, not just the
  current one).

## Corrections — immutability and auditability

- **R203** (behaviour, compatibility). "The original payment and every original idempotent
  response remain unchanged." — Acceptance: a correction never mutates the stored original
  201/200 response bodies for the original `POST /payments` (or equivalent creating call) or
  any of its replays; those continue to return their original bodies verbatim.
- **R204** (behaviour, compatibility). "`GET /activity` continues to display the original
  payment; correction records are not new feed payments." — Acceptance: `GET /activity` never
  gains a new entry because of a correction; the existing entry for the original payment is
  unaffected by R158's feed-ordering rule (its `created_at` does not change).
- **R205** (interface). "`GET /payments/{payment_id}/revisions` returns `{"revisions":
  [...]}` in revision order, including revision 1 (`reason: ""`)." — Acceptance: the route
  returns every revision (1..N) in ascending order, each with
  `revision`/`amount`/`effective_at`/`recorded_at`/`reason`; revision 1's `reason` is the
  empty string `""` (it was never an explicit correction).
- **R206** (error). "Only the two parties can read it; a third party gets 404 even for a
  public payment. No token is 401." — Acceptance: `GET /payments/{id}/revisions` is 401
  `unauthenticated` with no/invalid token; 404 `not_found` for any authenticated caller who is
  neither the sender nor the receiver, even when the payment's `visibility` is `public`; 200
  for the sender or receiver.

## `known_at` — point-in-time knowledge queries

- **R207** (interface, time). "`GET /me` and `GET /statement` accept optional `known_at`, an
  RFC 3339 instant with offset." — Acceptance: both routes accept a `known_at` query
  parameter of this format, independent of `as_of`/`from`/`to`.
- **R208** (behaviour, time). "For each payment, select its latest revision recorded at or
  before `known_at`; if none was yet recorded, that payment contributes nothing." —
  Acceptance: for a given `known_at`, a payment's "selected revision" is the highest-numbered
  revision whose `recorded_at <= known_at`; if even revision 1's `recorded_at > known_at`
  (the payment itself wasn't yet recorded), the payment is excluded entirely from the
  `known_at` view.
- **R209** (behaviour, compatibility). "Omission means everything known when the read
  begins." — Acceptance: a request without `known_at` behaves as if `known_at` were set to
  the instant the request started processing — i.e. the latest revision of every payment,
  which matches current behavior (R164).
- **R210** (behaviour, time). "Then apply selected revisions according to their effective
  times." — Acceptance: once a revision is selected per payment (R208), its contribution to
  balance/statement computations is ordered and evaluated by its `effective_at`, not its
  `recorded_at` or the payment's `created_at`.
- **R211** (compatibility, behaviour). "`as_of` retains its inclusive meaning; a statement
  retains its half-open window." — Acceptance: combining `known_at` with `as_of` (R165's
  at-or-before, inclusive-at-exact-instant rule) or with `from`/`to` (R172's half-open
  `[from, to)` rule) does not change those instant-comparison semantics — only which
  revision's `effective_at` is being compared changes.
- **R212** (limit, time). "Both query instants may be in the future." — Acceptance:
  `as_of`/`from`/`to` and `known_at` are each independently accepted even when later than the
  current server time; no special error for a future instant beyond the existing
  format-validation rules (R163/R189).
- **R213** (error). "Invalid/empty instants are 422." — Acceptance: a malformed or empty
  `known_at` value is 422 `validation_failed` (same rule as `as_of`, R163).
- **R214** (interface, time). "Echo supplied `known_at` exactly." — Acceptance: a response to
  a request that included `known_at` includes it back as the exact string supplied (same rule
  as R168 for `as_of`).

## `known_at` — statement ordering and shape

- **R215** (behaviour, time). "Statement ordering is now by selected `effective_at`, then
  payment id." — Acceptance: when a statement reflects selected revisions (whether or not
  `known_at` was explicitly supplied), `entries` are ordered by each entry's selected
  revision's `effective_at` ascending, then `payment.id` ascending for ties (generalizing
  R173).
- **R216** (interface). "Each entry retains `payment`, `delta` and `balance_after`, and adds
  the selected `revision`, `effective_at` and `recorded_at`." — Acceptance: every statement
  entry includes `revision`, `effective_at`, `recorded_at` in addition to R172's
  `payment`/`delta`/`balance_after`.
- **R217** (behaviour). "`payment.amount` is the selected amount for this statement." —
  Acceptance: the `amount` field inside a statement entry's embedded `payment` object reflects
  the selected revision's `amount` (R208), not necessarily the original (revision-1) amount.
- **R218** (behaviour, limit). "Zero-amount revisions still appear as entries with zero
  delta." — Acceptance: a payment whose selected revision has `amount: 0` (a full-reversal
  correction, R187) still produces a statement entry, with `delta: 0`.
- **R219** (behaviour). "No correction is counted alongside the revision it replaces." —
  Acceptance: a statement never includes two entries for the same payment at different
  revisions — exactly one entry per payment per statement read, for its selected revision.
- **R220** (compatibility). "With no corrections and no `known_at`, previous behavior is
  unchanged." — Acceptance: a payment never corrected, read without `known_at`, produces
  statement/`GET /me` results identical to R158-R177's uncorrected behavior.

## Stable statement pagination

- **R221** (interface, retry). "Every first `GET /statement` response additionally returns
  an opaque `snapshot` token." — Acceptance: any `GET /statement` call that is not itself
  paging via `snapshot` (i.e. a "first" read of a window) returns a `snapshot` field in its
  body, an opaque string.
- **R222** (behaviour, time). "It freezes the caller's selected revisions, window, balances,
  entries and default `to` at that read." — Acceptance: once issued, a `snapshot` token's
  underlying result (which revisions were selected, the resolved `from`/`to` window including
  a defaulted `to`, `opening_balance`/`closing_balance`, and the full entry list) is fixed at
  the instant of that first read and never recomputed.
- **R223** (interface, retry). "`GET /statement?snapshot=<token>&limit=...&offset=...` pages
  that exact result, even after payments or corrections." — Acceptance: paging with
  `snapshot` + `limit`/`offset` returns slices of the frozen result from R222, unaffected by
  any payment or correction that happens after the snapshot was taken.
- **R224** (error, limit). "Only limit and offset may accompany a snapshot; supplying `from`,
  `to` or `known_at` with it gives 422 `validation_failed`." — Acceptance: a request
  combining `snapshot` with any of `from`/`to`/`known_at` is 422 `validation_failed`
  (`limit`/`offset` are the only parameters allowed alongside `snapshot`).
- **R225** (error). "Unknown token, another user's token, or a token from before reset gives
  404 `not_found`." — Acceptance: an invalid/unrecognized `snapshot` string, a snapshot
  belonging to a different authenticated user, or a snapshot issued in a previous reset epoch,
  each give 404 `not_found`.
- **R226** (limit, compatibility). "Tokens last until reset. No storage survival across
  container restarts is required." — Acceptance: a snapshot token remains valid for the
  remainder of the current reset epoch; it need not survive a process/container restart
  (in-memory storage, consistent with stage-1 design §1's overall in-memory model).
- **R227** (limit, interface). "Paging changes neither balances nor entries; the final
  partial page and offsets beyond the end must report `has_more` correctly." — Acceptance:
  paging a snapshot (or a live, non-snapshot window) never mutates state; the last partial
  page reports `has_more: false`; an `offset` at or beyond the entry count returns an empty
  `entries` list with `has_more: false`.
- **R228** (compatibility). "Unrecognized query parameters remain ignored under stage 1's
  general rule." — Acceptance: stage-1's "ignore unknown query parameters" rule continues to
  apply to `GET /statement` (and `GET /me`) for any parameter not named in this document.
- **R229** (behaviour, time). "A correction may move a payment into or out of a statement
  window." — Acceptance: re-querying a live (non-snapshot) statement window after a
  correction changes a payment's selected `effective_at` can add or remove that payment from
  the window's `entries`, reflected on the next non-snapshot read.
- **R230** (concurrency). "Existing snapshots remain unchanged during concurrent payments or
  corrections." — Acceptance: a payment or correction that lands concurrently with, or after,
  an issued snapshot never changes that snapshot's frozen result (R222/R223), even if the
  change would have moved a payment into or out of the window.
- **R231** (concurrency, error). "Concurrent corrections using the same expected revision
  cannot both succeed." — Acceptance: when two correction requests for the same payment, both
  specifying the same `expected_revision`, race, exactly one succeeds (201) and the other
  observes the now-stale revision and gets 409 `stale_revision` (not two successful
  corrections both applied against the same prior revision).

## Settlement history

- **R232** (compatibility, behaviour). "Stage-1 settlements retain their original receipts
  and privacy rules." — Acceptance: stage-1's settlement receipt shape and visibility rules
  are unchanged by stage 3's addition of corrections/statements.
- **R233** (behaviour, time). "Each member's original revision uses its shared `committed_at`
  as both `effective_at` and `recorded_at`." — Acceptance: for a settlement's linked member
  payments, revision 1's `effective_at` and `recorded_at` both equal the settlement's
  `committed_at` (not each member payment's own possibly-different `created_at`, if any such
  distinction exists — the settlement's single shared commit instant governs both).
- **R234** (error, limit). "Single-payment corrections reject settlement members with 422
  `linked_payment_immutable`." — Acceptance: calling `POST /payments/{id}/corrections` on a
  payment that is a settlement member gives 422 `linked_payment_immutable`, state unchanged.
- **R235** (compatibility, limit). "A stage-3 service must accept exports produced by the
  same team's stage-1 or stage-2 service." — Acceptance: `POST /_test/import` with a
  `format_version: 1` or `format_version: 2` export (per stage-1/stage-2 design) loads
  successfully and the resulting state is usable under every stage-3 feature (statements,
  corrections, as-of/known-at queries) exactly as if it had been seeded natively — see A30 for
  revision/timestamp defaulting on upgrade.
- **R236** (compatibility, behaviour). "The ledger must import and account for authorizations
  and captures." — Acceptance: an imported stage-2 export's `authorizations` (open, captured,
  voided, expired) are loaded and continue to behave per stage-2 rules; captures already
  present in the imported export are treated as ordinary (if immutable, R237) payments for
  statement/correction purposes.
- **R237** (error, limit, compatibility). "Captures are immutable linked payments: a
  correction of a capture gives 422 `linked_payment_immutable`." — Acceptance: calling
  `POST /payments/{id}/corrections` on a payment created by an authorization capture (its
  `authorization_id` is non-null, stage-2 R143) gives 422 `linked_payment_immutable`, same
  code and behavior as R234 for settlement members.

## Historical holds

- **R238** (interface, time). "For `GET /me?as_of=T&known_at=K`, all four money fields
  describe that same view: `balance = total`, `available = total - held`." — Acceptance:
  when `as_of` and/or `known_at` are supplied, `balance`, `total`, `available`, and `held` are
  all computed consistently as of that combined view — not a mix of historical money fields
  with current hold state.
- **R239** (behaviour, time). "A hold starts at authorization creation; nonfinal capture
  reduces it at capture time; final capture, void or expiry releases the remainder at that
  event's time." — Acceptance: the historical `held` computation treats each authorization's
  contribution as starting at its creation event and changing at each subsequent
  capture/void/expiry event, each at that event's own time, not retroactively.
- **R240** (time). "Expiry takes effect at `expires_at`." — Acceptance: for historical-hold
  purposes, an authorization's clock-expiry event time is exactly its `expires_at`, consistent
  with stage-2's lazy-expiry computation (stage-2 design §9) extended to a historical view.
- **R241** (time, behaviour). "Events other than clock expiry are known at their
  server-assigned event time. Once creation is known, the expiry deadline is known too." —
  Acceptance: for `known_at` purposes, a capture/void's "recorded" instant is its own
  server-assigned event time; but the fact that an authorization *will* expire at
  `expires_at` is knowable as soon as the authorization's creation itself is known (no
  separate "the expiry was recorded" event needed).
- **R242** (behaviour, time). "For queries beyond now, an open hold expires at its
  deadline." — Acceptance: an `as_of` later than the current time still applies clock-expiry
  to a currently-open hold if `as_of >= expires_at`.
- **R243** (behaviour, time). "Without `as_of`, use the instant the request began." —
  Acceptance: for `held`/`available` computation (current, non-historical `GET /me`), the
  reference "now" is the instant request processing started (consistent with stage-2 design
  §9's existing behavior, restated here for the historical-views context).
- **R244** (interface). "Authorizations expose `closed_at` (null while open; event time when
  closed)." — Acceptance: every authorization representation gains a `closed_at` field: `null`
  while the hold is live (open and unexpired), and the event's instant (capture time, void
  time, or `expires_at` for clock expiry) once closed.
- **R245** (time, compatibility). "Historical `total` follows stage-3 effective/recorded-time
  rules." — Acceptance: a historical `total` (via `as_of`/`known_at`) is computed from
  selected revisions applied in effective-time order (R208/R210), exactly as the money fields
  elsewhere in this document.
- **R246** (error, time). "A correction is rejected with 409 `historical_overdraft` if it
  makes either total or available negative at any past effective/event boundary, under the
  latest known revisions." — Acceptance: extends R199 — the historical-overdraft check
  considers both `total` and `available` (i.e. hold events too) at every past boundary, not
  just `total`.
- **R247** (error, behaviour). "Current unaffordable debits still take precedence as
  `insufficient_funds`." — Acceptance: confirms R198's precedence — if the current-affordability
  check fails, the response is `insufficient_funds`, and the historical-overdraft check
  (R199/R246) is never reached.
- **R248** (behaviour, limit, time). "Seeded open holds are assumed created at reset unless
  `created_at` is supplied; seeded closed holds need not reconstruct a prior lifecycle." —
  Acceptance: a seeded authorization's creation event time, for historical purposes, is the
  reset instant unless the fixture supplies `created_at`; a seeded already-closed hold
  (captured/voided) need not have a synthetic creation-then-close history reconstructed — its
  `closed_at`/state may be taken as given without an earlier "open" interval being modeled.
- **R249** (behaviour, interface). "`GET /statement` still contains money movements only:
  authorization, release and expiry are not payments." — Acceptance: a statement's `entries`
  never include a hold-only event (creation, void, expiry) that did not move money; only
  payments (including captures) appear.
- **R250** (behaviour, interface). "Captures appear exactly once with their links." —
  Acceptance: a capture-created payment appears exactly once in a statement (not once per
  partial capture step beyond its own entry, and not duplicated for both parties' statements
  beyond the normal sender/receiver appearance), carrying its `authorization_id` link
  (stage-2 R143).
- **R251** (concurrency, behaviour). "Old snapshots remain unchanged after any lifecycle
  action or correction." — Acceptance: extends R230 — an authorization lifecycle event
  (capture/void/expiry) occurring after a statement snapshot was taken does not change that
  snapshot's frozen result, same guarantee as for corrections.

## Assumptions

- **A29**. R182's "seeded history is consistent and nonnegative" states a precondition but not
  the error it produces if violated. Reasoning: this is the same family as stage-1's negative
  seeded-balance rule (stage-1 R15/A13) and stage-2's seeded-authorization-validation errors
  (A22) — both reject the whole reset/import with 422 `validation_failed` and no state change.
  Assumption: a fixture whose seeded payment history, replayed in `created_at` order from each
  account's zero/declared opening point, would make any account negative at any point is
  rejected 422 `validation_failed` from `POST /_test/reset` (or import), with no state change,
  same as R161's future-`created_at` case.
- **A30**. The spec does not state what revision/timestamp history an imported stage-1 or
  stage-2 export's payments receive, since those formats have no revision concept. Reasoning:
  R178/R179 define revision 1's `effective_at`/`recorded_at` as equal to `created_at`; an
  imported payment already has a `created_at` (stage-1 design). Assumption: on import of a
  `format_version: 1` or `2` export, every existing payment (including captures) is given an
  implicit revision 1 with `amount`/`effective_at`/`recorded_at` derived from its existing
  `amount`/`created_at`, exactly as if it had been seeded natively (R179) — no revision history
  is lost or needs reconstruction beyond this.
- **A31**. `GET /statement`'s response shape (R172) does not include `from`/`to` echo fields,
  unlike `GET /me`'s explicit `as_of` echo (R168) and the `known_at` echo (R214). Reasoning:
  the worked example in stage-3.md shows only `opening_balance`/`entries`/`closing_balance`/
  `has_more` (plus `snapshot`, R221); the spec is explicit elsewhere (`as_of`, `known_at`) when
  it wants an echo and is silent here. Assumption: `GET /statement` is not required to echo
  `from`/`to` in its response body; the suite will not assert their presence or absence beyond
  the stated fields, per the "test only what the source requires" principle (tester's stage-2
  item 4 precedent).
- **A32**. Validation order within `POST /payments/{id}/corrections` is not fully specified:
  the spec states idempotency-key handling (R183, inheriting stage-1 §7's "key resolved before
  field validation or current-resource checks"), field-shape rules (R186-R190), resource
  existence/permission (R184), and state/funds checks (R194/R198/R199), but not their relative
  order beyond idempotency-key-first. Reasoning: stage-2 design §12 established existence(404)
  → permission(403) → state(409) → amount-validation(422) → funds(409) for the structurally
  similar capture/void endpoints; a positive-sender-identity check needs the payment resolved
  first, so existence/permission naturally precede content-dependent checks. Assumption, same
  conservative-reading latitude as stage-1 A1: after idempotency-key resolution, the order is
  existence (404) → permission (403) → body field-shape (422, R186-R190) → stale-revision (409,
  R194) → current-affordability (409 `insufficient_funds`, R198) → historical-overdraft (409
  `historical_overdraft`, R199) → settlement/capture immutability (422
  `linked_payment_immutable`, R234/R237) checked immediately after existence/permission (it is
  a resource-shape fact, not a body-content fact, so it is checked before field-shape, right
  after permission) — any single deterministic order satisfying the explicitly stated
  precedences (idempotency-key first; R247's current-before-historical) is acceptable; the
  suite asserts only the explicitly stated precedences, not this full chain, except where a
  single input triggers two of these conditions simultaneously, in which case this order
  governs.
- **A33**. The spec does not state an upper bound on how many revisions a payment may
  accumulate, nor a rate/count limit on corrections. Reasoning: no limit is stated anywhere in
  stage-3.md, and stage-1/2 only impose limits where explicitly written. Assumption: no
  additional limit beyond what's stated; a payment may be corrected arbitrarily many times
  within a run, each appending one more revision.
