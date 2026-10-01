# ADR-009: Statement snapshots are fully materialized at creation, not re-evaluated queries

## Context

R222 requires a `snapshot` token to "freeze" selected revisions, window, balances and
entries at the instant of the first read; R223/R230/R251 require paging that token, and
reading it after later payments/corrections/lifecycle events, to return the *exact* original
result, unaffected by anything that happened afterward.

## Options

1. Store a `snapshot` as a *query descriptor* (the resolved `from`/`to`/`known_at`/user) and
   re-run the statement algorithm against current state whenever it's paged, trusting that
   `known_at` alone makes the result reproducible.
2. Fully materialize the result (entries, both balances, resolved `to`) once, at creation
   time, and store that; a paged read of a snapshot token is a pure slice of stored data, no
   recomputation.

## Decision

Option 2 (design.md §8 step 5).

## Consequences

- Option 1 looks sufficient at first (a fixed `known_at` ought to make the computation
  reproducible) but is not: a *new* correction recorded after the snapshot, with an
  `effective_at` inside the snapshot's window but a `recorded_at` still ≤ the snapshot's
  `known_at`, would be invisible to `known_at`-based reconstruction only if `known_at` were
  re-evaluated against a clock that doesn't move — which requires storing the *original*
  `known_at` value anyway. Materializing the result directly sidesteps this edge case
  entirely rather than relying on reasoning about it being airtight.
- Satisfies R230/R251 "remain unchanged" by construction: there is no code path that writes
  into a stored `Snapshot.entries` after creation (design §3's data model note), so there is
  nothing to accidentally get wrong by a future change to the live computation.
- Memory cost: one full entry list per issued snapshot token, held until reset (R226 already
  accepts this — "no storage survival across container restarts is required," implying
  in-memory, epoch-scoped storage is expected). No snapshot is ever created implicitly beyond
  one per non-snapshot `GET /statement` call; a client that never reads a first page without
  paging never accumulates tokens.
- `reset_epoch` tagging (design §3) means a stale-epoch snapshot token is rejected without
  needing to actively purge `statement_snapshots` synchronously inside the reset critical
  section — reset/import can simply bump the epoch counter.
