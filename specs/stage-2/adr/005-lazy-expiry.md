# ADR-005: Lazy, read-time expiry — no background sweep thread

## Context

R136 requires "reads and writes must reflect expiry even if no request occurred at the
deadline," and R151 requires `GET /authorizations?status=open` to never return a
clock-expired record. A held amount must stop counting against `held` the instant its
`expires_at` passes, with no client action required.

## Options

1. A background thread that periodically scans `authorizations` and flips expired `open`
   records to a stored `"expired"` status.
2. Compute expiry on demand: every read of an authorization's effective status/held
   contribution compares `expires_at` against `datetime.now(timezone.utc)` at that moment;
   nothing is ever stored as `"expired"`.

## Decision

Option 2 (design.md §9's `is_live_hold`). A stored `Authorization.status` is only ever
`"open"`, `"captured"` or `"voided"`; "expired" is a computed view, never a fourth stored
value.

## Consequences

- Satisfies R136 exactly and trivially: there is no sweep interval to lag behind, so
  "reflects expiry even if no request occurred at the deadline" holds by construction — the
  very next read recomputes against current time.
- Avoids a second thread contending for `STATE_LOCK` on a timer, which would otherwise need
  its own reasoning about interaction with the single-critical-section rule (design.md §2);
  a lazy read-time check needs no new concurrency reasoning at all, since it runs inside the
  same lock acquisition the handler already holds.
- Cost: every `held`/`available` computation is `O(that user's authorizations)` instead of
  `O(1)` against a maintained running total. Acceptable at the harness's scale (§9); noted
  as the tradeoff if a later stage's scale requirements ever change this.
- `GET /authorizations?status=open` must call the same `is_live_hold` check the write paths
  use (not a separate/duplicated expiry condition), so the two can never disagree about
  whether a given record currently holds money.
