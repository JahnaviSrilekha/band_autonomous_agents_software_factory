# Stage 4 design — pocketful

Implements `specs/stage-4/requirements.md` (this commit) on top of stage 1-3's design
(`specs/stage-1/design.md`, `specs/stage-2/design.md`, `specs/stage-3/design.md`), all carried
forward by reference below. See `adr/011-*.md` onward for stage-4's significant decisions;
`adr/001-010` (stages 1-3) still apply unchanged.

## 1. Stack

Unchanged: Python 3.12, standard library only. No new runtime dependency, no new UI
(stage-4.md adds no routes/screens/`data-testid`s — API-only, per A48).

## 2. Process model

Unchanged: one `ThreadingHTTPServer`, one process-wide `threading.RLock` (`STATE_LOCK`)
guarding all mutable state, held for the full duration of every handler. This now also covers
refund creation and correction-batch validation+commit — a refund, a batch, and any read
(statement, revisions, `GET /me`) can never interleave partway.

## 3. Data model (in-memory) — additions

```
Payment (extension to stage-3 design §3):
  refund_of: str | None     # target payment_id if this payment IS a refund, else None

Revision (extension):
  correction_batch_id: str | None   # the batch id if this revision came from
                                    # POST /correction-batches, else None (always None for
                                    # revision 1 and for single-correction revisions)
```

No new top-level `State` collection is needed. A correction batch has no standalone record:
its `correction_batch_id` lives only on the revisions it created, and its 201/200 response body
is already preserved verbatim by the existing idempotency mechanism (`run_idempotent`) — adding
a parallel `state.correction_batches` dict would duplicate data `IdempotencyRecord` already
owns, with no new read endpoint (R280/R286 cover it) to justify the duplication.

`Payment.__init__` gains `refund_of=None` as a trailing keyword parameter; `Revision.__init__`
gains `correction_batch_id=None` likewise. Every existing call site (`move_money`,
`make_revision_1`, `_payment_from_json`, reset-fixture seeding) is unaffected by the new
defaulted parameter. `Revision.to_json()` adds `"correction_batch_id": self.correction_batch_id`
to its output (R281). `payment_json()` (`handlers/payments.py`) adds `"refund_of":
payment.refund_of` (R264, R287).

`Payment.append_revision` gains a trailing `correction_batch_id=None` parameter, passed straight
to the new `Revision`; its existing recorded-time tie-break (bump by one microsecond if the
supplied `recorded_at` would not be strictly later than that payment's own last revision) is
**unchanged** — ADR-012 explains why the batch path never triggers it.

## 4. Invariants and where they are enforced — additions

| Invariant | Enforcement |
|---|---|
| A refund moves money exactly once, atomically with the record (R260-R262) | `create_refund` runs its existence/permission/target-type/amount/cap checks, then `available()` check, then the balance mutation and `Payment` append, all inside one `STATE_LOCK` acquisition with no intermediate release — same "claim key → validate → mutate → commit" shape as every other idempotent write (stage-1 design §5). |
| A refund never exceeds the payment's current amount, cumulatively (R259, R267) | One function, `refunded_total(state, payment_id)`, sums existing refund payments for a target; it is the *only* place both `create_refund` (checking the new refund against the cap) and `create_correction`/batch corrections (checking a new amount against the floor) read that sum — no second implementation to drift. |
| Captures and refunds are correction-immutable (R266, R274) | `_is_correction_immutable(payment)` (`payment.authorization_id is not None or payment.refund_of is not None`) replaces the stage-3 inline `authorization_id`-only check and is the single predicate called by both `create_correction` and the batch per-item validator — one place, both callers. |
| Batch all-or-nothing (R279) | The batch handler validates *every* item and *every* cross-item/funds/historical check before mutating anything; no revision is appended and no balance changes until every check in R275's precedence has passed for the whole batch — mirrors stage-1 design §5's settlement pattern ("collect, validate everything, then commit") rather than stage-3's single-correction per-item-immediate-commit shape, because a batch has no single item to commit until all are known-good. |
| Combined affordability reflects every proposed revision at once (R278, A44) | `check_batch_current_funds` builds one `{user_id: net_delta}` map by summing every item's delta before checking any `available()`, instead of calling the existing single-payment `check_correction_funds` once per item against intermediate state. |
| Combined historical affordability (R275 step 4, A45) | `check_batch_historical_funds` generalizes stage-3's `_check_historical_overdraft` from one payment's two parties to the full set of parties touched by any batch item, scanning one shared timeline — see §6. |
| Settlement completeness and shared-instant consistency (R276, R277) | `check_settlement_completeness` and `check_members_effective_consistency` run as their own precedence step (R275 step 2), after every item's own validation (step 1) and before any funds check (steps 3-4), each a pure function over the parsed item list with no side effects — so a failure here, like any earlier step, leaves state untouched. |
| Shared `recorded_at` across one batch's revisions (R281, A43) | `compute_batch_recorded_at(state, payment_ids)` is called exactly once per batch, strictly after every validation step has passed and before any `append_revision` call; its result (`max(now, every affected payment's latest recorded_at) + 1 microsecond`) is passed identically to every `append_revision` call in that batch. |
| Exactly-once under concurrent batch/single races on the same payment (R288) | Both `create_correction` and the batch handler check `expected_revision` against `len(payment.revisions)` inside the same `STATE_LOCK` acquisition that performs the append — identical mechanism to stage-3 R231, now shared by two call sites instead of one. |
| Refunds don't reopen requests/authorizations (R263) | `create_refund` never touches `state.requests` or `state.authorizations`; it only reads the target `Payment`'s `request_id`/`authorization_id` to carry forward `note`/`visibility`, and only ever calls the balance-moving primitive on the two `User` objects plus appends one new `Payment` — there is no code path back into request/authorization state from a refund. |

## 5. Write-path algorithm — `POST /payments/{payment_id}/refunds`

Route: `auth=True, idem=True` (not `operator`), matching stage-1's five plain idempotent
writes. Inside `run_idempotent` (key already resolved/claimed before this runs, per the
track-wide "parse → authenticate → resolve key → validate" order, stage-1 design §5):

1. Re-check `fresh = state.users.get(user.id)` (401 if session invalidated, stage-wide
   pattern).
2. Resolve the target: `payment = _find_payment(state, params["id"])`; 404 `not_found` if
   missing or not visible (R254).
3. 403 `forbidden` if `fresh.id != payment.to_user_id` (R255).
4. 422 `invalid_refund_target` if `payment.refund_of is not None` (R256) — positioned right
   after the permission check, same slot stage-3 A32 used for its immutability check.
5. Parse and validate `amount` (R258, A40): integer in `[1, 1000000000]`.
6. 422 `refund_exceeds_payment` if `refunded_total(state, payment.id) + amount >
   payment.revisions[-1].amount` (R259).
7. 409 `insufficient_funds` if `available(state, payment.to_user_id, now) < amount` (R262).
8. Commit: debit `payment.to_user_id`, credit `payment.from_user_id`, append a new `Payment`
   with `from_user_id=payment.to_user_id`, `to_user_id=payment.from_user_id`,
   `refund_of=payment.id`, `request_id=None`, `authorization_id=None`,
   `note=payment.note`, `visibility=payment.visibility` (R260). Return 201.

Steps 2-7 run read-only against live state; step 8 is the only mutation, so a failure at any
earlier step leaves state untouched (same shape as every other idempotent write — failure
frees the idempotency key per the existing `run_idempotent` exception handling, R254-R259
compatible with that without change).

## 6. Write-path algorithm — `POST /correction-batches`

Route: `auth=True, operator=True, idem=True` (A46) — identical flags to `/settlements`, so the
existing route-level 401/403 check (`server.py`, before `idem`/body parsing) is reused verbatim
for R269; no new authorization code.

Pipeline, in the exact order of R275:

**Step 0 — shape.** `corrections` is a JSON array of 1-32 objects (R270); collect
`payment_id`s and reject on any duplicate (422 `validation_failed`).

**Step 1 — item errors, input order.** Iterate items by index. For the first item that fails
any of the following, return that error immediately (R271-R274):
1. Field shape: `payment_id` (string), `expected_revision`, `amount`, `effective_at`, `reason`
   — reusing `corrections.py`'s existing `_parse_expected_revision`/`_parse_amount`/
   `_parse_reason`/`_parse_effective_at` helpers unchanged, one call per item.
2. Existence: `payment = _find_payment(state, payment_id)` — 404 `not_found` if missing
   (R272; no visibility filter — the operator role, not sender/receiver identity, authorizes
   batch corrections, R274).
3. Immutability: `_is_correction_immutable(payment)` (§4) — 422 `linked_payment_immutable`
   (R266 code, reused).
4. Staleness: `expected_revision != len(payment.revisions)` — 409 `stale_revision` (R273).
5. Floor: `refunded_total(state, payment.id) > amount` — 422 `refund_exceeds_payment` (R267).

(Corrected per reviewer's stage-4 batch-2 finding: staleness before floor, matching §7's
single-correction order below — neither R267 nor R273 pins this sub-order, but the two
endpoints should agree on it for the mechanically same violation shape instead of silently
diverging.)

Step 1 fully resolves every item (payment object + parsed fields) before step 2 begins; it
does not interleave with steps 2-4's cross-item or funds checks (R275's "item errors... before
settlement completeness").

**Step 2 — settlement completeness and consistency.** Over the fully-resolved item list:
- `check_settlement_completeness`: for every item whose payment has `settlement_id is not
  None`, every other `payment_id` in `state.settlements[settlement_id].payment_ids` must also
  be present among the batch's items — else 422 `incomplete_settlement` (R276).
- `check_members_effective_consistency`: for each settlement fully covered by the batch, every
  member item's parsed `effective_dt` must be equal — else 422 `validation_failed` (R277).

**Step 3 — combined current funds.** `check_batch_current_funds(state, items, now)` (§4, A44):
build `{user_id: net_delta}` from every item's `amount - payment.revisions[-1].amount` (sign
per stage-3 R197: increase debits `from_user_id`, decrease debits `to_user_id`), then for every
user with a negative combined effect on their own balance, require
`available(state, user_id, now) + their_delta >= 0`; else 409 `insufficient_funds` (R278).

**Step 4 — combined historical funds.** `check_batch_historical_funds(state, items, now)`
(§4, A45): generalizes stage-3's `_check_historical_overdraft` to the full set of parties
touched by any item — one shared `(user_id, instant) -> delta` movement map covering every
item's proposed revision plus every unrelated payment/authorization event for those same
parties, replayed in instant order; a negative running total or negative
`total - historical_held(...)` at any instant is 409 `historical_overdraft` (same code as
stage-3 R199, reused).

**Commit** (only after every step passes, R279): compute `recorded_at =
compute_batch_recorded_at(state, [item.payment for item in items])` once (A43); for each item
in input order, `payment.append_revision(amount, effective_at, recorded_at, reason,
correction_batch_id=batch_id)` and apply its balance delta (reusing
`corrections.py`'s `_move_correction_delta`). Return 201 with `correction_batch_id`,
`recorded_at`, and `revisions` (one entry per item, input order, R280).

## 7. Correction endpoint — extensions shared with batch

`corrections.py#create_correction` changes in two places only:
- Its immutability guard (`payment.settlement_id is not None or payment.authorization_id is
  not None`) is replaced by `payment.settlement_id is not None or
  _is_correction_immutable(payment)` — i.e. it still blocks settlement members (A41,
  unchanged single-endpoint behaviour) and now also blocks refunds via the shared predicate
  (R266).
- One new check, `refunded_total(state, payment.id) > amount` → 422 `refund_exceeds_payment`
  (R267), inserted immediately after the staleness check (`expected_revision`) and before
  `check_correction_funds` — now the same relative position as the batch pipeline's step 1,
  item 5 (§6, corrected), keeping the two endpoints' internal check order consistent even
  though one is per-item and the other is a single call.

No other line of `create_correction` changes; `check_correction_funds`/
`_check_historical_overdraft` (stage-3 design §9) are reused unmodified for the single-payment
path (R268).

## 8. Export/import — format v4 (extends stage-3 design §10)

`handle_export` emits `format_version: 4`. `state_to_json`'s payment entries add `"refund_of":
payment.refund_of`; revision entries (already present since v3) add `"correction_batch_id":
revision.correction_batch_id`.

`handle_import` accepts `format_version` 1-4 (R289). `_payment_from_json` reads
`entry.get("refund_of")` (absent/`null` → `None`, uniformly across every version — no
version branch needed, since the key is simply never present before v4); if non-null, it must
be a string already present in the running `payment_ids_seen` set accumulated as the payments
loop processes entries in array order — the export always lists a refund after its target
(creation order = `seq` order, and a refund is always created strictly after its target
exists), so a single forward pass suffices without a two-pass reference-resolution rewrite
(ADR-013). `_revisions_from_json` reads `item.get("correction_batch_id")` per revision, same
absent-means-`None` rule, no version check needed (format_version ≥ 3 is already required to
have `revisions` at all, per stage-3's existing guard).

## 9. What stage 4 deliberately does not build

- No `GET /correction-batches/{id}` or any other new read endpoint — the spec asks only for
  the 201/200 batch response and the existing `GET /payments/{id}/revisions` to expose
  `correction_batch_id` (A48).
- No UI changes — refunds and correction batches are API-only this stage (A48).
- No new idempotency-record fields or export top-level keys beyond the two additive payment/
  revision fields — `IdempotencyRecord`'s existing shape already round-trips a refund's or a
  batch's original response body unchanged (stage-1 design §7, unmodified).
