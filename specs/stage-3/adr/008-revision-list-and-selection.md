# ADR-008: Append-only revision list per payment, with a single selection function

## Context

R178/R192/R193 require every payment to carry an immutable, strictly-recorded-time-ordered
revision history; R208/R210 require `known_at` queries to pick one revision per payment (the
latest recorded at or before `known_at`) and then use *that* revision's `effective_at` for
ordering. Two time axes (`recorded_at`, `effective_at`) must never be conflated, and R203/
R205 require every original revision, including the very first, to stay exactly as returned.

## Options

1. Store only the current amount plus a separate correction log, reconstructing "amount as
   of recorded time X" by replaying the log on every historical query.
2. Store the full ordered list of `Revision` objects directly on `Payment` (`revisions[0]` is
   always revision 1), and centralize selection in one `selected_revision(payment, known_at)`
   function (design.md §6) that every historical code path calls.

## Decision

Option 2. `Payment.revisions` is the single source of truth; nothing is derived by replaying
a separate log.

## Consequences

- `GET /payments/{id}/revisions` (R205) is a direct serialization of `revisions`, not a
  reconstruction — it cannot drift from what `selected_revision` sees.
- Centralizing selection in one function (design.md §6) is what makes R208's "contributes
  nothing if not yet recorded" and R210's "effective time governs ordering" hold everywhere
  consistently; every call site (statement, `GET /me`, historical-overdraft scan) shares it,
  so a future change to the selection rule touches one place.
- `revisions` strictly increasing in `recorded_at` (R193) is enforced at append time (design
  §5 step 8 runs under the same lock as the stale-revision check), not by a later sort — the
  list is append-only and already time-ordered by construction.
- Cost: a payment with many corrections keeps every revision in memory indefinitely (no
  compaction). Acceptable — no limit on revision count is stated (A33), and the harness's
  scale does not require compaction.
