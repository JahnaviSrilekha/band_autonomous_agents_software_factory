# ADR-006: Export/import format v2 — additive fields, v1 still importable

## Context

R115 requires stage 2 to accept a stage-1 (`format_version: 1`) export unchanged. Stage 2
also needs to export its own new state (`authorization_ttl_seconds`, `authorizations`) so
that a later stage — or a re-import into another stage-2 instance — doesn't lose open
holds. Stage-1's ADR-004 already anticipated this: "A later stage that adds fields to
`State` can still accept a stage-1 export by defaulting any field absent from the imported
JSON."

## Options

1. Keep `format_version: 1` and silently add the two new fields to `state`, relying on
   "unknown fields are ignored" (stage-1 §3.4) — but that convention is stated for *request*
   bodies, not the opaque export/import `state` object, and doesn't address what a stage-1
   export (missing the new fields) should default to on import.
2. Bump to `format_version: 2` for stage-2's own exports; accept both `1` and `2` on
   import, defaulting the two new fields when importing a `1`.

## Decision

Option 2 (design.md §10). Stage 2 emits `format_version: 2`. `POST /_test/import` accepts
`1` or `2`; importing `1` defaults `authorization_ttl_seconds = 600` and
`authorizations = {}` — the same defaults R131/R135 already specify for an omitted fixture
field — then loads the rest exactly as stage-1 §9 specifies. Any other version is still
`422 validation_failed`, unchanged from stage-1 R80.

## Consequences

- R115 ("accept an export produced by the same team's stage-1 service") is satisfied
  without stage-1 changing at all — the negotiation lives entirely on stage-2's import
  side, so the already-verified stage-1 artifact needs no retroactive edit.
- A future stage importing a stage-2 `format_version: 2` export has an unambiguous version
  tag to branch on, continuing the seam ADR-004 opened.
- Version-specific defaulting logic is small (two fields, both with an already-specified
  default) and lives in one place (the import loader), not scattered across handlers.
