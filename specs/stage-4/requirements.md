# Stage 4 requirements — pocketful: refunds and batch corrections

Source: `we-are-devs/pocketful/spec/stage-4.md` (full text pasted into every handoff), which
states "All requirements from stages 1–3 continue to apply." All of `specs/stage-1/requirements.md`
(R1-R93, A1-A13), `specs/stage-2/requirements.md` (R94-R157, A14-A28) and
`specs/stage-3/requirements.md` (R158-R251, A29-A38) therefore stay in force by reference; this
document numbers only stage 4's additions and changes, continuing from R252/A39. Section
references such as §5 and §7 refer to `stage-1.md`, as earlier stage docs establish. Kind
values: behaviour, error, limit, concurrency, retry, time, compatibility, interface.

## Idempotent write paths (overview)

- **R252** (interface). "All requirements from stages 1–3 continue to apply... There are ten
  idempotent write paths: stage 1's five, authorizations and captures from stage 2, corrections
  from stage 3, and refunds and correction batches in this stage." — Acceptance: exactly ten
  distinct (method, path) routes require `Idempotency-Key` and exhibit replay-returns-200
  behaviour: `POST /payments`, `/requests`, `/requests/{id}/pay`, `/splits`, `/settlements`
  (stage 1's five); `POST /authorizations`, `/authorizations/{id}/capture` (stage 2's two);
  `POST /payments/{id}/corrections` (stage 3's one); `POST /payments/{id}/refunds`,
  `/correction-batches` (this stage's two).

## Refunds — request, authorization and target validation

- **R253** (interface, retry). "`POST /payments/{payment_id}/refunds`, body `{"amount": 200}`,
  requires an idempotency key." — Acceptance: the route requires the `Idempotency-Key` header
  under the stage-1 §7 rule (missing/empty → 400 `missing_idempotency_key`).
- **R254** (error). "Unknown payment is 404." — Acceptance: a `payment_id` that does not exist
  (or is not visible to the caller, same "unknown" convention as stage-1/3) is 404 `not_found`,
  checked before the receiver-identity check (A39).
- **R255** (error). "Only the original receiver may refund, else 403 `forbidden`." —
  Acceptance: an authenticated caller who is not the target payment's `to_user_id` (including
  its original sender) gets 403 `forbidden`.
- **R256** (error). "Refunds of refunds give 422 `invalid_refund_target`." — Acceptance: if the
  target payment's own `refund_of` is non-null (the target is itself a refund), the request is
  rejected 422 `invalid_refund_target`, checked immediately after the permission check (A39),
  mirroring stage-3 A32's precedent of checking linkage-immutability right after 403.
- **R257** (behaviour, interface). "The target may be a direct payment, request payment or
  capture, but never a refund." — Acceptance: refunding a plain payment, a request-linked
  payment (`request_id` set) or a capture (`authorization_id` set) all succeed subject to the
  other rules in this section; only a `refund_of`-linked target is rejected (R256) — a capture
  is refundable even though it is correction-immutable (R266).
- **R258** (limit, error). "Invalid amount is 422 `validation_failed`." — Acceptance: `amount`
  must be a JSON integer in `[1, 1000000000]` (A40); missing, out-of-range or non-integer-valued
  is 422 `validation_failed`; wrong JSON type (e.g. a string) is 400 `malformed_request` per the
  stage-1 §5 general rule.
- **R259** (limit, error). "Refunds cumulatively may not exceed the payment's current corrected
  amount: 422 `refund_exceeds_payment`." — Acceptance: the sum of every existing refund payment
  with `refund_of` equal to the target, plus the new amount, must be ≤ the target's current
  (latest-revision) amount; otherwise 422 `refund_exceeds_payment`, no state change.

## Refunds — money movement, shape and replay

- **R260** (behaviour, interface). "A refund is a new payment in the opposite direction, with
  `refund_of` naming the target, `request_id: null`, `authorization_id: null`, and the original
  note/visibility." — Acceptance: the created payment has `from_user_id = target.to_user_id`,
  `to_user_id = target.from_user_id`, `refund_of = target.id`, `request_id = null`,
  `authorization_id = null`, `note = target.note`, `visibility = target.visibility`, and its own
  fresh revision-1 amount equal to the refund amount.
- **R261** (interface, retry). "Return 201 with that payment; replay returns 200 with the
  original body." — Acceptance: success is 201 with the new refund payment's representation
  (R264 shape); replaying the same idempotency key and byte-equal body returns 200 with the
  identical original body; a different body under the same key is 409 `idempotency_key_reuse`
  per the general rule (stage-1 §7).
- **R262** (behaviour, error, concurrency). "It moves existing money from the receiver's
  **available** funds, or fails 409 `insufficient_funds`, atomically." — Acceptance: under the
  single global critical section, if `available(target.to_user_id)` at commit time is less than
  the refund amount, return 409 `insufficient_funds` with no state change; otherwise debit
  `target.to_user_id.balance` and credit `target.from_user_id.balance` by the amount, create the
  refund payment, and commit the idempotency record, all in the same atomic step.
- **R263** (behaviour). "Refunds never reopen a request or authorization or restore a released
  hold." — Acceptance: refunding a request-linked or capture-linked payment leaves the
  originating `Request.status` and `Authorization.status`/`captured_amount`/`payment_ids`
  completely unchanged; no hold is recreated and no `available()` headroom is freed beyond the
  ordinary effect of the balance movement itself.
- **R264** (interface, compatibility). "Other payments have `refund_of: null`." — Acceptance:
  every payment representation (creation response, replay body, receipt, activity entry,
  statement entry) includes a `refund_of` field: the target's `payment_id` for a refund
  payment, `null` for every other payment.

## Corrections — immutability and funds extensions

- **R265** (compatibility). "Stage-3 corrections remain available for ordinary direct/request
  payments." — Acceptance: `POST /payments/{id}/corrections` continues to work unchanged (stage-3
  R183-R220) for payments with `settlement_id == null`, `authorization_id == null` and
  `refund_of == null`.
- **R266** (error). "Captures and refund payments cannot themselves be corrected: 422
  `linked_payment_immutable`." — Acceptance: `POST /payments/{id}/corrections` on a payment with
  `authorization_id != null` OR `refund_of != null` is rejected 422 `linked_payment_immutable`
  (extends stage-3's existing `authorization_id` check to also cover `refund_of`).
- **R267** (limit, error). "A correction cannot reduce a payment below its already-refunded
  amount: 422 `refund_exceeds_payment`." — Acceptance: a correction whose new `amount` is less
  than the sum of refunds already issued against that payment is rejected 422
  `refund_exceeds_payment`, state unchanged; this applies to both the single-correction endpoint
  and every item of a correction batch.
- **R268** (behaviour). "Correction debits are checked against available funds." — Acceptance:
  reaffirms stage-3's `check_correction_funds` (R197/R199) continues to gate every correction
  (single or batched) after refunds exist, using the debtor's available funds at commit time,
  including holds and the effect of prior refunds.

## Batch corrections — request, authorization and per-item validation

- **R269** (interface, retry, error). "`POST /correction-batches` requires a settlement operator
  and an idempotency key, with the same 401/403 rules as settlements." — Acceptance: the route
  requires `Idempotency-Key` (R252-style) and a bearer token for a user in
  `settlement_operator_ids`; no/invalid token is 401 `unauthenticated`; an authenticated
  non-operator is 403 `forbidden` — checked at the same point in the request pipeline as
  `/settlements` (route-level `operator=True`, before body validation; A46).
- **R270** (limit, error). "corrections contains 1..32 objects with distinct payment_ids, else
  422 `validation_failed`." — Acceptance: `body.corrections` must be a JSON array of 1 to 32
  objects; fewer, more, a non-array, or any two objects sharing the same `payment_id` is 422
  `validation_failed`.
- **R271** (interface). "Every item has the ordinary correction fields and validation." —
  Acceptance: each item is validated with the same per-field rules as a single correction:
  `expected_revision` (stage-3 R186), `amount` (R187), `effective_at` (R189 — RFC 3339, not
  later than now), `reason` (R188); a field-level violation on any item is 422
  `validation_failed` (or 400 `malformed_request` for a wrong JSON type), reported in input
  order (R275).
- **R272** (error). "Unknown payment is 404." — Acceptance: an item naming a `payment_id` that
  does not exist is 404 `not_found` for the whole batch.
- **R273** (error, concurrency). "a stale expected revision is 409 `stale_revision`." —
  Acceptance: an item whose `expected_revision` does not equal that payment's current latest
  revision number is 409 `stale_revision` for the whole batch; state unchanged (R279).
- **R274** (behaviour, error). "The operator may correct ordinary, request and settlement
  payments, but captures and refunds remain immutable." — Acceptance: unlike the
  single-correction endpoint, `/correction-batches` does not require the caller to be any
  payment's original sender; it accepts any item payment with `authorization_id == null` and
  `refund_of == null` (including `settlement_id != null` payments); an item naming a captured or
  refund-target payment is 422 `linked_payment_immutable` (same code as R266).

## Batch corrections — settlement completeness and error precedence

- **R275** (interface, error). "Error precedence is: item errors in input order, settlement
  completeness, resulting current available funds, then historical total and available funds at
  every effective/event boundary." — Acceptance: when a batch request has more than one
  violation, the response reflects the first found in this order: (1) per-item structural/
  field/not-found/stale-revision/immutability errors (R270-R274), scanned in the request's
  array order; (2) settlement-completeness (R276) and cross-member effective-instant consistency
  (R277); (3) R278's combined current-availability check; (4) R268/R267-style historical
  overdraft/availability checks (A45) at every effective/event boundary. Stage (1) is evaluated
  for every item (collecting violations in index order and reporting the first) before any of
  (2)-(4) runs.
- **R276** (behaviour, error). "Correcting any settlement member requires including every member
  of that settlement, else 422 `incomplete_settlement`." — Acceptance: if any item's payment
  belongs to a settlement (`settlement_id != null`), every other `payment_id` in that
  settlement's `payment_ids` must also appear as an item in the same batch request, else 422
  `incomplete_settlement`.
- **R277** (limit, error, time). "Members of one settlement must have identical effective
  instants (offset spellings may differ), else 422 `validation_failed`." — Acceptance: when a
  batch corrects every member of a settlement, all of those items' `effective_at` values must
  parse (RFC 3339) to the identical instant; differing offset spellings of the same instant are
  accepted; any two members resolving to different instants is 422 `validation_failed`.
- **R278** (behaviour, concurrency). "Affordability is determined by the combined effect of all
  proposed revisions." — Acceptance: the "resulting current available funds" check computes
  each affected user's net balance delta as the sum of every proposed revision's delta touching
  that user — not evaluated item-by-item against intermediate state — then requires
  `available(now) >= 0` for every debited party under that combined delta; insufficient combined
  funds is 409 `insufficient_funds` for the whole batch.
- **R279** (behaviour, concurrency). "A rejected batch leaves history, balances and idempotency
  records unchanged." — Acceptance: if any check in R275's precedence fails, no payment revision
  is appended, no balance changes, and the idempotency key is freed (not committed) — matching
  the general "a failed request frees the key" rule.

## Batch corrections — success, replay and compatibility

- **R280** (interface). "Return 201 with `correction_batch_id`, `recorded_at` and `revisions` in
  input order." — Acceptance: success is 201 with `correction_batch_id` (a fresh id),
  `recorded_at`, and `revisions`: an array in the same order as the request's `corrections`
  array, one entry per item shaped like a single correction's 201 body (stage-3 R192) plus
  `correction_batch_id`.
- **R281** (behaviour, time). "All new revisions share `recorded_at`, strictly later than the
  previous `recorded_at` of every member; each revision also exposes
  `correction_batch_id`." — Acceptance: every revision created by one batch call carries an
  identical `recorded_at` string, chosen strictly later than the maximum of all affected
  payments' pre-batch latest `recorded_at` (A43); every revision's JSON (stage-3 R192 shape,
  `GET /payments/{id}/revisions`) includes `correction_batch_id` set to this batch's id (`null`
  for revisions not created by a batch).
- **R282** (limit, error, time). "Effective times cannot be later than now." — Acceptance: same
  per-item rule as stage-3 R189, reaffirmed for batch items; a future `effective_at` on any item
  is 422 `validation_failed` for that item (R271/R275 stage 1).
- **R283** (behaviour). "Original payments and receipts never change." — Acceptance: a payment's
  `payment_json`/receipt representation (stage-3 R203-style) continues to show the original
  revision-1 amount after any batch correction; only revision history and balances change.
- **R284** (compatibility, retry). "Original payment and settlement retries return their
  original bodies." — Acceptance: replaying the idempotency key of the original `POST
  /payments`, `/requests/{id}/pay`, `/splits` or `/settlements` request that created a
  now-corrected payment still returns that original 200/201 body, unchanged by later
  corrections or batches.
- **R285** (behaviour, compatibility). "New statements reflect the new revisions; earlier
  snapshot tokens continue to page their frozen entries." — Acceptance: reaffirms stage-3
  R221-R230 snapshot semantics: a `GET /statement` taken after a batch correction reflects the
  new revision amounts; a snapshot token issued before the batch continues to page the
  balances/entries frozen at its own creation, byte-identical to before.
- **R286** (retry, interface). "Replays return the original batch response with 200." —
  Acceptance: replaying `POST /correction-batches` with the same key and byte-equal body returns
  200 with the original 201 body (`correction_batch_id`, `recorded_at`, `revisions` unchanged); a
  different body under the same key is 409 `idempotency_key_reuse`; the same replay also applies
  after an export/import upgrade (stage-1 R78-85-style stored-idempotency-record carry-over).

## Settlement, refund and concurrency interactions; compatibility

- **R287** (behaviour, compatibility). "A settlement payment may be refunded under the existing
  refund rules, but refunds never change settlement membership." — Acceptance: refunding a
  settlement member succeeds under R253-R264 unchanged; the originating `Settlement.payment_ids`
  and `transfers` are untouched.
- **R288** (concurrency). "Concurrent corrections sharing any expected payment revision cannot
  both succeed." — Acceptance: under concurrent single-correction and/or batch-correction
  requests that name the same `payment_id` with the same `expected_revision`, exactly one
  commits (the others get 409 `stale_revision`), proven under the single global critical section
  (design.md).
- **R289** (compatibility, interface). "A stage-4 service must accept exports produced by the
  same team's stages 1–3, retaining settlement membership, corrections and snapshots." —
  Acceptance: `POST /_test/import` accepts `format_version` 1, 2 and 3 (unchanged stage-3
  synthesis rules, R232-R237) as well as this stage's `format_version` 4; after importing any
  stage-1/2/3 export, settlement membership, correction revision history and (for v3) statement
  snapshot/epoch behaviour are preserved exactly as stage-3 defined, with every imported payment
  defaulting `refund_of` to `null` and every imported revision defaulting `correction_batch_id`
  to `null` (A30-style synthesis, since those formats predate refunds/batches).
- **R290** (compatibility, interface). Track-wide direction: "Export carries a version; every
  stage imports every earlier stage's export... includes every stored idempotency record... and
  every session token." — Acceptance: `GET /_test/export`'s `format_version: 4` payload includes,
  for every payment, `refund_of`, and for every revision, `correction_batch_id`, alongside
  everything stage-3's v3 export already carried (stage-3 ADR-010), taken under one
  `STATE_LOCK`-held atomic snapshot.

## Assumptions

- **A39**. The refund endpoint's error precedence is not stated as explicitly as the batch
  endpoint's (R275). Reasoning: stage-3 A32 established, for the structurally similar single
  correction endpoint, the order existence(404) → permission(403) → linkage-immutability(422,
  checked immediately after permission) → body field-shape(422) → stale-state(409) →
  funds(409). Assumption: `POST /payments/{id}/refunds` follows the same shape: 404 `not_found`
  (R254) → 403 `forbidden` (R255) → 422 `invalid_refund_target` (R256, the refund-of-refund
  check, positioned like stage-3's immutability check) → 422 `validation_failed` (R258, amount
  shape) → 422 `refund_exceeds_payment` (R259, cumulative cap) → 409 `insufficient_funds`
  (R262).
- **A40**. R258 ("invalid amount is 422 `validation_failed`") does not state `amount`'s bounds.
  Reasoning: every other amount field in the track (`parse_amount` in `errors.py`, used by
  payments/requests/splits/settlements) uses `[1, 1000000000]`; refunds are payments in the
  opposite direction and a zero or negative refund has no meaning distinct from "no refund".
  Assumption: refund `amount` must be a JSON integer in `[1, 1000000000]`, same family and same
  bounds as every other payment-amount field.
- **A41**. The spec does not give an error code for calling the *single*-correction endpoint on
  a settlement member, only stating batch corrections may reach settlement members (R274) and
  that "ordinary single-payment corrections remain available for nonmembers." Reasoning:
  stage-3's existing `create_correction` already rejects any payment with `settlement_id !=
  null` as 422 `linked_payment_immutable` (same check as its `authorization_id` guard).
  Assumption: that existing single-endpoint behaviour is retained unchanged — settlement members
  stay unreachable via `POST /payments/{id}/corrections` (422 `linked_payment_immutable`) and
  are only correctable via `/correction-batches`; no new code path is added to the single
  endpoint for settlement payments.
- **A42**. "Unknown fields are ignored" for correction-batch items is explicit, but the spec
  does not restate it for the top-level body. Reasoning: `/settlements`' existing transfer-entry
  parsing (`_entry_string`) already ignores unlisted keys without a strict key-set check, the
  established convention for array-of-object bodies in this track. Assumption: both batch item
  objects and the top-level `{"corrections": [...]}` body silently ignore any key other than
  `payment_id`, `expected_revision`, `amount`, `effective_at`, `reason`; no "unknown field"
  error is introduced.
- **A43**. "All new revisions share `recorded_at`, strictly later than the previous `recorded_at`
  of every member" must compose with stage-3's per-payment `append_revision`, which (independent
  of batching) bumps `recorded_at` by one microsecond if a tie would otherwise occur against
  *that same payment's* prior revision. Reasoning: the "share" requirement is a cross-item
  constraint within one batch, not a per-payment one; as long as the single `recorded_at` chosen
  for the batch is already strictly later than every affected payment's own latest `recorded_at`
  before any revision is appended, no payment can trigger its own tie-breaking bump. Assumption:
  the batch handler computes one `recorded_at` = `max(now, each affected payment's latest
  recorded_at + 1 microsecond)` once, up front, and passes that identical value to every
  revision it appends in that batch.
- **A44**. R278's "combined effect" check needs a concrete mechanism. Reasoning: stage-3's
  `check_correction_funds`/`_check_historical_overdraft` evaluate one proposed revision against
  the live state; generalizing to N simultaneous proposed revisions means computing, for every
  user touched by any item, the sum of that user's deltas across all items (not applying them
  one-by-one), then checking `available(now)` with that combined delta applied once. Assumption:
  this combined-delta computation (R278) and its historical-boundary generalization (A45) are
  implemented as new functions parallel to `check_correction_funds`, not by calling the
  existing single-correction funds check once per item.
- **A45**. R275's "historical total and available funds at every effective/event boundary" step
  must also generalize `_check_historical_overdraft` from one payment to N. Reasoning: same
  rationale as A44 — evaluating N proposed revisions' historical effect one at a time could pass
  checks that the simultaneous combination would fail (or vice versa) at a shared boundary
  instant. Assumption: the historical check builds one combined movement timeline across every
  party touched by any item in the batch (as stage-3's function does per-payment for its two
  parties), evaluated after R278 passes.
- **A46**. "Same 401/403 rules as settlements" is explicit. Reasoning: `/settlements` uses the
  route table's `operator=True` flag (`server.py`), checked after `auth=True` and before
  `idem=True`/body parsing (R no-token → 401 `unauthenticated`; authenticated non-operator → 403
  `forbidden`, from `state.settlement_operator_ids`). Assumption: `/correction-batches` is
  registered with the identical `auth=True, operator=True, idem=True` route flags and check
  order, not a bespoke re-implementation.
- **A47**. The spec states "the existing codes apply: `linked_payment_immutable`,
  `refund_exceeds_payment`, `insufficient_funds`, `historical_overdraft`" for batch corrections.
  Reasoning: this is an explicit closed list. Assumption: no new error code beyond
  `refund_exceeds_payment`, `invalid_refund_target` and `incomplete_settlement` is introduced in
  this stage; every other failure mode reuses an existing stage-1/2/3 code with its established
  meaning.
- **A48**. The spec does not ask for new read-side filters or UI surfaces for refunds or
  correction batches (only `GET /payments/{id}/revisions` is mentioned, unchanged, to expose
  `correction_batch_id`). Reasoning: stage 2's UI requirements list only pay/refresh/
  request/split actions; stage 4's text does not extend that list. Assumption: no new UI page,
  button or query parameter is added for refunds or correction batches; they are API-only in
  this stage, consistent with "do not implement later stages' features" applied in reverse (do
  not add unrequested surface now either).
- **A49**. Export `format_version` numbering is not named by the spec beyond "this adds one
  idempotent write path" and the backward-compatibility sentence (R289). Reasoning: stage-3
  minted `format_version: 3` (ADR-010) for its own additions; following that precedent, this
  stage's additions (`refund_of`, `correction_batch_id`) mint `format_version: 4`. Assumption:
  `GET /_test/export` always emits `format_version: 4`; `POST /_test/import` accepts 1-4.
