# Stage 3 design — pocketful

Implements `specs/stage-3/requirements.md` (this commit) on top of stage 1's design
(`specs/stage-1/design.md`) and stage 2's design (`specs/stage-2/design.md`), both carried
forward by reference below. See `adr/008-*.md` onward for stage-3's significant decisions;
`adr/001-007` (stages 1-2) still apply unchanged.

## 1. Stack

Unchanged from stage-1/2 design §1: Python 3.12, standard library only. Stage 3 adds no new
runtime dependency and no new UI (stage-3.md states no routes, screens or `data-testid`
additions — it is API-only).

## 2. Process model

Unchanged from stage-1/2 design §2: one `ThreadingHTTPServer`, one process-wide
`threading.RLock` (`STATE_LOCK`) guarding all mutable state, held for the full duration of
every handler including reads. This now also covers: appending a correction revision, every
`GET /statement`/`GET /me?as_of=…&known_at=…` computation, and snapshot-token creation/lookup
— a statement read and a concurrent correction can never interleave partway.

## 3. Data model (in-memory) — additions

```
Payment (extension to stage-2 design §3):
  revisions: list[Revision]     # revisions[0] is revision 1, always present

Revision: revision (int, 1-based), amount (int), effective_at (datetime),
          recorded_at (datetime), reason (str)   # revision 1's reason == ""

State (additions):
  statement_snapshots: dict[snapshot_token -> Snapshot]

Snapshot: owner_user_id, reset_epoch, opening_balance, closing_balance,
          entries (fully materialized, in order), resolved_to (the defaulted `to`)
```

A payment's "current" values (`amount`, and anything derived from it) are always
`revisions[-1]`'s. `GET /payments/{id}/revisions` (R205) returns `revisions` verbatim,
JSON-serialized, oldest first — no separate storage needed. `closed_at` (R244) is derived,
not stored: `None` while `is_live_hold` (stage-2 design §9) is true, else the event instant
already tracked for capture/void (payment's/void's own timestamp) or `expires_at` for clock
expiry — see §9 below, extended.

**Reset epoch.** `statement_snapshots` is cleared on every `POST /_test/reset` and
`POST /_test/import` (R226: "tokens last until reset"); each snapshot is tagged with the
`reset_epoch` counter already incremented by those calls (reusing the mechanism, if any,
from stage-1/2; otherwise a new monotonically-increasing `int` on `State`, bumped by both
calls) so a token presented after a later reset is unambiguously stale → 404 `not_found`
(R225) without needing to physically wipe the dict synchronously inside every reset path's
critical section — a stale-epoch check at lookup time is sufficient and simpler.

**Settlement member revisions** (R233): a settlement member payment's revision 1 sets
`effective_at = recorded_at = committed_at` (the settlement's shared commit instant from
stage-1 design), not the member payment's own `created_at` if that ever differed — in
practice stage-1 already sets each member's `created_at` to `committed_at`, so this is the
existing field reused, not a new one.

## 4. Invariants and where they are enforced — additions

| Invariant | Enforcement |
|---|---|
| Conservation across historical views (R202) | `historical_total(user, effective_cutoff, known_at)` (§9) sums the same `_debit`/`_credit`-equivalent deltas as the live ledger, just filtered to selected revisions (§6) and ordered by `effective_at` — summing it over every user at a fixed `(effective_cutoff, known_at)` telescopes to the seeded total by the same algebraic argument as the live invariant (every movement is a paired debit+credit, corrections included: R197's correction delta is itself a paired debit+credit). |
| Correction atomicity (R197, R201) | A correction runs through the same "claim idempotency key → validate → mutate → commit" single critical section as every other idempotent write (stage-1 design §5), extended at §5 below; the revision append and the balance delta happen in the same `STATE_LOCK` acquisition, so a reader never observes a new revision without its money movement or vice versa. |
| `historical_overdraft` / `insufficient_funds` precedence (R198, R247) | `_check_correction_funds` (§9) always evaluates current-affordability first and returns immediately on failure; the historical-boundary scan only runs if that passes — a single function, not two independently-ordered checks, so the precedence can't be accidentally reversed by call-site ordering. |
| Snapshot immutability (R222, R230, R251) | A `Snapshot` fully materializes `entries` (not a query descriptor re-evaluated later) at creation time, under `STATE_LOCK`; subsequent corrections/payments/lifecycle events mutate only live state, never an existing `Snapshot` object — there is no code path that writes into `statement_snapshots[token].entries` after creation. |
| Exactly-once correction under concurrent same-revision races (R231) | `expected_revision` is checked against `len(payment.revisions)` inside the same lock acquisition as the append, exactly as a capture's amount-vs-remainder check is (stage-2 design §4) — the second of two racing requests observes the already-incremented length and gets `stale_revision`. |
| Linearizability (carried from stage-2 R157) | Unchanged: single `STATE_LOCK` for every state-touching handler, read or write. |

## 5. Write-path algorithm — `POST /payments/{id}/corrections`

Extends stage-1 design §5 (parse → authenticate → resolve idempotency key → validate →
mutate, one lock acquisition) as the service's eighth idempotent write path (R183). Order of
the validate step, per requirements.md A32:

1. Resolve `payment_id` → 404 `not_found` if no such payment exists (or not visible to this
   caller — same "unknown" convention as elsewhere).
2. Permission → 403 `forbidden` if caller is not the original sender.
3. Linked-payment immutability → 422 `linked_payment_immutable` if the payment is a
   settlement member (R234) or a capture (`authorization_id is not None`, R237).
4. Body field-shape (`expected_revision` positive-int, `amount` 0..1e9 int, `reason` 1..200
   chars, `effective_at` valid RFC 3339 not later than now) → 422 `validation_failed` per
   field, 400 `malformed_request` for a wrong JSON type (R186/R187).
5. Stale-revision → 409 `stale_revision` if `expected_revision != len(payment.revisions)`.
6. Current-affordability → 409 `insufficient_funds` (§9's `_check_correction_funds`, current
   branch).
7. Historical-overdraft → 409 `historical_overdraft` (§9's `_check_correction_funds`,
   historical branch) — only reached if step 6 passes.
8. Commit: append the new `Revision`, move `|Δamount|` between the original
   `from_user_id`/`to_user_id` per R197's debit/credit direction rule, all inside the single
   lock acquisition already held since idempotency-key resolution.

## 6. Revision selection (`known_at`) and effective-time ordering

```python
def selected_revision(payment: Payment, known_at: datetime | None) -> Revision | None:
    if known_at is None:
        return payment.revisions[-1]
    eligible = [r for r in payment.revisions if r.recorded_at <= known_at]
    return eligible[-1] if eligible else None   # None => contributes nothing (R208)
```

Every historical computation (`GET /me?as_of&known_at`, `GET /statement?...&known_at`)
first calls `selected_revision` per payment, discards payments with `None`, then evaluates
the survivors using their *selected* revision's `effective_at` for ordering/inclusion and
`amount` for delta/balance math (R210, R217). This single function is the only place
`recorded_at` is ever compared against `known_at` — every other comparison in the historical
path uses `effective_at`, preventing the two time axes from being accidentally mixed.

With no corrections ever applied to a payment, `selected_revision` always returns
`revisions[0]` whose `effective_at == created_at`, so this reduces exactly to stage-1/2's
existing `created_at`-ordered behavior (R220) — no special-casing needed for the
uncorrected path.

## 7. `GET /me?as_of&known_at` and historical balance

```python
def historical_balance(user_id, as_of, known_at, now):
    cutoff = as_of if as_of is not None else now
    kn = known_at  # None => "everything recorded so far" per selected_revision
    bal = state.users[user_id].opening_balance          # R180
    for p in payments_involving(user_id):
        rev = selected_revision(p, kn)
        if rev is None or rev.effective_at > cutoff:
            continue
        bal += rev.amount if p.to_user_id == user_id else -rev.amount
    return bal
```

`opening_balance` (R180) is computed once, at reset/import, as
`fixture.balance - net(seeded payments as originally seeded)`, and stored on `User` — never
recomputed from corrections, satisfying R180's "corrections must not change opening
balances" without needing to special-case corrections inside `historical_balance` itself
(a correction only ever changes which revision `selected_revision` returns for payments
*after* that fixed starting point).

`held`/`available` historically (R238-R243) extend stage-2 design §9's `is_live_hold`
with an explicit `at` instant (defaulting to `now`, R243) instead of always using
`datetime.now()`:

```python
def is_live_hold_at(a: Authorization, at: datetime, known_at: datetime | None) -> bool:
    created = a.created_at if (known_at is None or a.created_at <= known_at) else None
    if created is None:
        return False   # creation itself not yet known at `known_at`
    closed = closed_at(a, known_at)   # None, or the resolved close instant
    return (closed is None or closed > at) and created <= at
```

(The `is_live_hold_at`/`closed_at` pair collapses to stage-2's existing `is_live_hold` when
`at == now` and `known_at is None`.) `closed_at(a, known_at)` returns `None` if the hold is
still open as of `known_at`'s knowledge (R241: capture/void known at their own recorded
event time; expiry known as soon as creation is known, R241's second sentence), else the
earliest of: the capture/void event's own time (if recorded ≤ `known_at`), or `expires_at`
(if `at ≥ expires_at` and creation is known — R240/R242, "events other than clock expiry
are known at their event time; once creation is known, expiry is too").

## 8. `GET /statement` and snapshots

`statement(user, from_, to, known_at, limit, offset)`:

1. Resolve `from_` (default: user's opening instant, i.e. no lower bound) and `to` (default:
   `now`, captured once at the start of this call — R170, R222's "freezes ... default `to`").
2. For every payment involving `user`, compute `selected_revision(p, known_at)` (§6); keep
   those with a selected revision whose `effective_at` is in `[from_, to)` (half-open, R172)
   — ties broken by `payment.id` (R173/R215).
3. `opening_balance` = `historical_balance(user, as_of=from_ minus epsilon semantics: strictly
   before `from_`, i.e. exclude `effective_at == from_`, known_at, now)` — implemented as
   `historical_balance` with a strict-`<` cutoff comparison variant, since R174 is
   "immediately before `from`" (exclusive) unlike `as_of`'s inclusive rule (R165) for
   `GET /me`. `closing_balance` is the same strict-`<` computation at `to`.
4. Walk the filtered, ordered list computing each entry's running `balance_after` from
   `opening_balance` forward — entries and both balances describe the *full* window,
   computed once, independent of `limit`/`offset` (R176).
5. If this call did not itself come from a `snapshot` parameter: materialize a `Snapshot`
   (full entry list, both balances, resolved `to`) under a fresh opaque token
   (`uuid4().hex`), store it tagged with the current `reset_epoch`, and include `snapshot` in
   the response (R221). A `snapshot`-driven call looks up the stored `Snapshot` instead of
   recomputing steps 1-4 at all — this is what makes R223/R230 hold structurally (there is no
   recomputation to drift).
6. Slice `entries` (from the freshly computed list, or the stored `Snapshot.entries`) by
   `limit`/`offset`, set `has_more`.

`GET /statement?snapshot=X` with any of `from`/`to`/`known_at` present is rejected 422
before step 1 even runs (R224) — a simple presence check, no interaction with the main
algorithm.

## 9. `POST /payments/{id}/corrections` — funds checks

```python
def _check_correction_funds(payment, new_amount, now):
    old_amount = payment.revisions[-1].amount
    delta = new_amount - old_amount
    debtor = payment.from_user_id if delta > 0 else payment.to_user_id
    if delta != 0 and available(debtor, now) < abs(delta):      # R198, stage-2 `available`
        raise InsufficientFunds()
    # Historical scan (R199/R200/R246): only if current check passed.
    for boundary in effective_time_boundaries(payment.from_user_id, payment.to_user_id,
                                               hypothetical_new_revision=(new_amount, ...)):
        if historical_total(boundary.user, boundary.at) < 0 or \
           historical_available(boundary.user, boundary.at) < 0:
            raise HistoricalOverdraft()
```

`effective_time_boundaries` enumerates every instant at which either party's historical
`total`/`available` could change under the hypothetical new revision (every existing
revision's `effective_at` for both parties, plus every hold event instant, plus the new
revision's own `effective_at`), combining same-instant movements per R200 before comparing
against zero. This reuses `historical_balance`/`is_live_hold_at` (§§6-7) rather than a
separate computation, so the "what does history look like" logic has one implementation.

## 10. Export/import — format v3 (extends stage-2 design §10)

`state`'s JSON shape gains, per payment: `revisions` (list of
`{revision, amount, effective_at, recorded_at, reason}`). `State` gains
`statement_snapshots` is **not** exported — snapshots are explicitly epoch-scoped and "no
storage survival across container restarts is required" (R226); an import starts a fresh
reset epoch, which alone invalidates any snapshot tokens a client might still hold (§3).
Stage 3 exports `format_version: 3`.

**Import version negotiation**: `POST /_test/import` accepts `format_version` `1`, `2`, or
`3`.
- `format_version: 3` → load `revisions` directly from each payment's JSON.
- `format_version: 1` or `2` → no `revisions` key exists on any payment; synthesize revision
  1 for every payment from its existing `amount`/`created_at` (A30), then proceed with the
  rest of that version's field-by-field load exactly as stage-1/2 design already specify
  (stage-2's `authorization_ttl_seconds`/`authorizations` defaulting for `format_version: 1`
  still applies unchanged).
- Any other `format_version` → 422 `validation_failed`, no change (unchanged rule).

`POST /_test/reset` builds each seeded payment's revision 1 directly from the fixture's
`created_at` (R160/R179) using the same synthesis path as a `format_version: 1/2` import for
consistency — one function, two callers.

## 11. What stage 3 deliberately does not build

No multi-payment/batch corrections (only one payment, one revision step per call); no
correction of a correction's own metadata (a correction is itself immutable once recorded —
only a *further* correction, i.e. a new revision, can change the amount again); no
persistence of `statement_snapshots` across reset/import (R226); no UI changes (stage-3.md
adds no routes, screens or testids — carried-forward stage-2 UI is untouched); no
multi-currency; still no background expiry-sweeping thread (stage-2 design §9's lazy model,
now parameterized by `at`/`known_at`, remains the only expiry mechanism).
