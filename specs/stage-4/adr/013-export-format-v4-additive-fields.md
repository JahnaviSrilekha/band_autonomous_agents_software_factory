# ADR-013: Export format v4 adds two optional fields; no version-branching on read

## Context

R289/R290 require format_version 4 to carry `refund_of` (per payment) and
`correction_batch_id` (per revision), while still accepting format_version 1-3 exports that
have neither key at all.

## Options

1. Branch on `format_version` inside `_payment_from_json`/`_revisions_from_json` the way
   `format_version >= 3` already gates whether `revisions` exists at all (stage-3 ADR-010),
   explicitly defaulting `refund_of`/`correction_batch_id` only for versions `< 4`.
2. Treat both fields as unconditionally optional regardless of version: `entry.get("refund_of")`
   and `item.get("correction_batch_id")`, defaulting to `None` whenever absent — which is
   every version before v4, and is also a legal (if unusual) value a v4 export could choose to
   omit for a non-refund/non-batch record.

## Decision

Option 2.

## Consequences

- No new `if format_version >= 4` branch is needed anywhere in `export_import.py` — unlike
  `revisions`, whose *absence* means something different pre/post stage-3 (no revision
  concept existed at all) and genuinely needs version-gated synthesis (ADR-010), `refund_of`/
  `correction_batch_id` are simple optional fields whose absence always means the same thing
  ("not a refund" / "not from a batch"), in every format version, including v4 itself for
  ordinary payments and single corrections.
- Referential integrity for `refund_of` (must name a payment that exists) is checked with a
  running `payment_ids_seen` set built during the same single forward pass over the payments
  array — relying on the export always listing a refund after its target, which holds because
  a refund payment cannot be created before its target exists (R256/R260) and the export's
  payment order is creation (`seq`) order (stage-1 design). A two-pass "load everything, then
  validate cross-references" rewrite was considered and rejected as unnecessary extra
  complexity for a property the write path already guarantees.
- A hand-written or adversarial import fixture naming a `refund_of` that is a later array
  entry (out of creation order) is rejected 422 `validation_failed` by the forward-pass
  check, same as an unknown reference — stricter than "last-write-wins," but consistent with
  every other cross-reference check in `export_import.py` (`request_id`, `authorization_id`,
  `settlement_id`), none of which tolerate forward references either.
