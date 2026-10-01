# ADR-010: Export format v3 adds `revisions`; older exports synthesize revision 1 on import

## Context

R235 requires a stage-3 service to accept stage-1 (`format_version: 1`) and stage-2
(`format_version: 2`) exports, neither of which has any revision concept. R178/R179 require
every payment to have at least a revision 1 whose `amount`/`effective_at`/`recorded_at`
derive from its `created_at`.

## Options

1. Keep payments without a `revisions` list internally for imported pre-v3 data, and
   special-case every revision-aware code path (`selected_revision`, R205's endpoint) to
   fall back to the payment's bare `amount`/`created_at` when `revisions` is absent.
2. Synthesize an explicit revision 1 for every payment at import time (and at native seeding,
   reusing the same synthesis function — design §10's "one function, two callers"), so every
   payment in memory always has a non-empty `revisions` list regardless of origin.

## Decision

Option 2.

## Consequences

- Every revision-aware code path (ADR-008's `selected_revision`, `GET /payments/{id}/
  revisions`) has exactly one shape to handle — a non-empty list — with no "is this payment
  pre-v3" branch anywhere outside the import/reset loader. This keeps ADR-008's "one
  selection function, one invariant" property intact across upgrade boundaries instead of
  letting it leak into every caller.
- The reset-fixture loader and the import loader for `format_version: 1`/`2` share the same
  synthesis function (`created_at`/`amount` → revision 1), so a seeded payment and an
  imported pre-v3 payment are indistinguishable in memory afterward — satisfying R179's
  "seeded payment's supplied `created_at` is also its original recorded/effective time" and
  A30 by the same code path, not two parallel implementations that could drift apart.
- Cost: import of a very old, very large export does a bit more work up front (one synthetic
  `Revision` object per payment) instead of deferring it. Negligible at the harness's scale,
  and avoids a lazy-synthesis path's own concurrency reasoning (synthesizing under the same
  import-time lock acquisition is simpler than synthesizing on first historical read of an
  old payment, which would need its own guard against double-synthesis under concurrent
  reads).
- `statement_snapshots` is deliberately *not* part of the export format (design §10): an
  import already starts a fresh `reset_epoch`, which alone invalidates any snapshot tokens
  a client might present post-import, consistently with R226's "no storage survival across
  container restarts is required" — exporting snapshot state would be work spent on
  something the spec already allows to be dropped.
