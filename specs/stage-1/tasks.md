# Stage 1 tasks

Repository root for stage 1 deliverable: `stage-1/` (Dockerfile, RUN.md, `src/`). All Python
files live under `stage-1/src/pocketful/`. Status starts `pending`; developer flips to
`in_progress`/`done` as work proceeds and commits each task individually.

## Batch 1 — foundation (server, state, errors, idempotency chokepoint, container)

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T1 | R5,R6,R7,R8,R12,R16,R35,R36,R37,R40,R42 | `src/pocketful/server.py`, `src/pocketful/errors.py`, `src/pocketful/__main__.py` | — | `GET /health` (before reset) does not 500; unknown route → 404 `not_found`; every error response matches `{"error":{"code","message"}}`; integer amounts round-trip exactly with no float rounding error (R5); an out-of-range-but-correctly-typed field gives 422 not 400 (R37) | done | 1 |
| T2 | R6,R8,R9,R10,R11,R13 | `Dockerfile`, `RUN.md` | T1 | `docker build` + documented run command; `GET /health` returns 200 within 60s with no network | pending | 1 |
| T3 | R14,R15,R17,R31,R32,R33,R34,R84,A5 | `src/pocketful/state.py`, `src/pocketful/reset.py` | T1 | `POST /_test/reset` with the spec's example fixture → 204; `GET /me` for a seeded user (after login) matches fixture; negative-balance fixture → 422, prior state untouched; repeated reset works | done | 1 |
| T4 | R48,R49,R50,R51,R52,R53,R54,R56(shape only) | `src/pocketful/idempotency.py` | T1,T3 | Unit tests: fresh key → claim+execute; replay same body → stored response, no re-execution; same key diff body → 409; failed (4xx) attempt frees key; concurrent identical requests against a fake mutator → exactly one execution | done | 1 |

## Batch 2 — identity and auth

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T5 | R19,R20,R21,R43,R44,R47 | `src/pocketful/auth.py` (signup) | T3 | Signup happy path → 201 shape; email taken → 409; short password → 422; bad email format → 422; derived-handle collision → 409 `handle_taken`, no user created; stored password is a scrypt hash, not plaintext; new user's balance is 0 and can immediately receive a payment/request (R21) | pending | 2 |
| T6 | R43,R44,R46 | `src/pocketful/auth.py` (login) | T5 | Login happy path → 200 same shape as signup; wrong password/unknown email → 401; two logins for same user → two independently valid tokens | done | 2 |
| T7 | R45,R55 | `src/pocketful/middleware.py`, `src/pocketful/handlers/me.py` | T6 | `GET /me` with valid token → exact shape; missing/garbage/unknown token → 401 on `/me` and on a write endpoint stub | done | 2 |

## Batch 3 — payments and requests

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T8 | R4,R22,R38,R56,R57,R58,R59,R18,R30 | `src/pocketful/handlers/payments.py` | T4,T7 | Full case table from R57; atomic debit/credit (no partial state on failure); note round-trips unicode/emoji byte-for-byte; conservation holds after N concurrent payments (sum unchanged); money never created/destroyed — no path other than debit+credit between existing wallets changes a balance (R4); amount/note/visibility type overrides are 422 not 400 (R38) | pending | 3 |
| T9 | R23,R24,R25,R60,R61,R62 | `src/pocketful/handlers/requests.py` (create) | T7 | Case table from R61; over-balance request created as `pending`, no balance check | done | 3 |
| T10 | R63,R64,R65,R66 | `src/pocketful/handlers/requests.py` (pay) | T8,T9 | Case table from R65; pay body defaults + strict body-equality on replay (R63); replay-after-paid returns 200 original payment, no `409 request_not_pending` | done | 3 |
| T11 | R67,R68 | `src/pocketful/handlers/requests.py` (decline/cancel) | T9 | Decline/cancel happy path, repeat-of-same-terminal-state → 200, wrong-party → 403, wrong-status → 409 | done | 3 |
| T12 | R69,R70 | `src/pocketful/handlers/requests.py` (list) | T9,T10,T11 | `direction`/`status`/`limit`/`offset` filter matrix; `has_more` correctness; invalid query values → 422 (R39) | done | 3 |
| T13 | R26,R27,R28,R29,R75 | `src/pocketful/handlers/activity.py` | T8,T10 | Feed-visibility matrix (sender/receiver/public/private/third-party) exactly matches R26/R29; requests and splits never appear | done | 3 |

## Batch 4 — splits and settlements

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T14 | R76,R77 | `src/pocketful/shares.py` | T1 | All 5 table rows from R76 exact; order-dependence (reordering `participant_handles` moves the extra unit) | done | 4 |
| T15 | R71,R72,R73,R74 | `src/pocketful/handlers/splits.py` | T9,T14 | Case table from R73; caller-only split → `requests: []`; shares sum to amount and cover every participant in order; requests cover every non-caller participant | done | 4 |
| T16 | R86,R87,R88,R89,R90,R91,R92,R93 | `src/pocketful/handlers/settlements.py` | T8 | No-token → 401; non-operator → 403; per-entry errors (unknown handle/self-transfer/malformed) take precedence over collective affordability, in input order; net-affordability check (not sequential); all-or-nothing on rejection (idempotency key freed, no payments created); replay → 200 original; settlement payments carry `settlement_id`, null `request_id`, shared `created_at`==`committed_at` | done | 4 |

## Batch 5 — export/import, concurrency hardening, verification

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T17 | R78,R81 | `src/pocketful/handlers/export_import.py` (export) | T3..T16 | Export returns `track`,`format_version:1`,`state`; snapshot is atomic (concurrent write during export does not torn-read) | done | 5 |
| T18 | R78,R79,R80,R82,R83,R84,R85 | `src/pocketful/handlers/export_import.py` (import) | T17 | Export→import round trip is a behavioral no-op; invalid JSON → 400; wrong track/version/invalid state → 422, no change; old token still authenticates post-import; a completed idempotency key still replays; a previously-4xx-failed key is still a fresh first-use post-import | done | 5 |
| T19 | R1,R2,R3,R41,R42,R10 | (no new files — hardening pass across all handlers) | T1..T18 | `python -m harness run --track pocketful --stage 1` (host mode) green; then `--mode isolated` green, ending `claimed stage: 1` with the stage-2 overshoot line `fail`; a manual ≥50-concurrent-request burst against `/payments`/`/settlements` shows no negative balance, conservation holds, no 5xx | done | 5 |

## Coverage

Every requirement R1-R93 and assumption A1-A13 is referenced by at least one task above,
verified by grepping the `reqs` column (fixed 2026-09-30 after the tester's completeness
review flagged R4, R5, R21, R37, R38 as unreferenced — now in T8, T1, T5, T1, T8
respectively). A1/A2 are cross-cutting, applied in T8-T10,T15-T16 per design.md §10; A3 is
T13; A4 is T3; A5 is T3; A6 is T11; A7 is T5; A8 is T1/T4 (body-type gate before idempotency
resolution); A9 is T16; A10-A11 are T5; A12-A13 are T3.
