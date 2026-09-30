# ADR-004: Export/import state format v1

## Context

§10 requires `state` to be "implementation-defined" and opaque to the caller, but this
service's own import must accept its own export unchanged (R78), and later stages must accept
every earlier stage's export (per the run's technical direction). The export must let a retry
after an upgrade still replay the original response (R82), so idempotency records and tokens
must be part of the exported state, not derived/reconstructed.

## Decision

`state` is a direct JSON serialization of the in-memory `State` object described in design.md
§3 (a "dump the object graph" approach), tagged with the sibling top-level `format_version: 1`
(not nested inside `state`, so future stages can sniff the version without deserializing an
unknown internal shape). Every field listed in design.md §3 is included verbatim: `users`
(with `password_hash`, not plaintext), `tokens`, `payments`, `requests`, `splits`,
`settlements`, `idempotency` (as a list of records, each with key/caller/method/path/body/
original status+body), and `settlement_operator_ids`.

## Consequences

- Because the dump is the same shape the service already keeps in memory, no separate
  serialize/deserialize schema has to be hand-maintained in parallel with the data model —
  reducing the chance the export silently drops a field a later requirement depends on.
- A later stage that adds fields to `State` can still accept a stage-1 export by defaulting
  any field absent from the imported JSON (forward compatibility is a later-stage concern to
  design when that stage's shape is known — not implemented here, per "leave room for later
  stages without implementing them").
- Because `format_version` sits outside `state`, an import handler can reject an unknown
  version with `422 validation_failed` (R80) before attempting to interpret `state` at all.
