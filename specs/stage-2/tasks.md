# Stage 2 tasks

Repository root for stage 2 deliverable: `stage-2/` (copied from verified stage-1, same
layout: `Dockerfile`, `RUN.md`, `src/`). All Python files live under
`stage-2/src/pocketful/`. Task ids continue stage-1's numbering (`T1`-`T19` are stage 1,
already `done`, carried forward unchanged in `stage-2/`). Status starts `pending`;
developer flips to `in_progress`/`done` as work proceeds and commits each task
individually.

## Batch 1 — authorization data model, fixture/reset, `GET /me`

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T20 | R130,R131,R132,R133,R134,R135,R136,R137 | `src/pocketful/state.py`, `src/pocketful/reset.py` | T3 | `POST /_test/reset` with the stage-2 example fixture (incl. `authorization_ttl_seconds`, `authorizations`) → 204; omitted fixture fields default per R131/R135; seeded unexpired open holds summing above a user's balance → 422, state unchanged (R133); non-positive/non-integer `authorization_ttl_seconds` → 422; a stage-1-shaped fixture (no `authorizations` key) still resets cleanly | done | 1 |
| T21 | R138,R121,R122,design.md§9 | `src/pocketful/state.py` (`is_live_hold`/`held`/`available`), `src/pocketful/handlers/me.py` | T20 | `GET /me` returns `balance,total,available,held` exactly per R138; with zero open holds `balance==total==available` and `held==0`; a seeded open hold reduces `available` immediately after reset with no API call in between (R156); a clock-expired (but stored-`open`) hold contributes 0 to `held` | done | 1 |

## Batch 2 — authorization endpoints, existing-endpoint funds-check update

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T22 | R120,R139,R140,R141,A14,A16 | `src/pocketful/handlers/authorizations.py` (create) | T21,T4 | Idempotent write per §7/R129; full case table from R140; response shape/defaults from R139; created authorization never appears in `GET /activity` (R141); a hold reserves without moving money (R120) | done | 2 |
| T23 | R142,R143,R144,R145,R146,R147,A14 | `src/pocketful/handlers/authorizations.py` (capture) | T22 | Strict body-equality replay (`{}` vs `{"amount":N}` differ, R142); default final-capture releases remainder atomically (R144); second capture after final → 409 (R145); extended mode (`final:false`) accumulates `captured_amount`/`payment_ids`, `remaining_amount` correct, exact-remainder capture closes even with `final:false` (R146); full case table from R147, `authorization_not_open` vs `authorization_expired` distinguished correctly; resulting payment has exact `POST /payments` shape plus `authorization_id` set, `note`/`visibility` copied, feed-visible by ordinary rule (R143) | done | 2 |
| T24 | R148,R149,A15 | `src/pocketful/handlers/authorizations.py` (void) | T22 | No idempotency key consulted (client-supplied one ignored, A15); payer-only; repeat-void of voided → 200; captured/expired → 409 `authorization_not_open`; non-party caller → 403 (R149) | pending | 2 |
| T25 | R150,R151 | `src/pocketful/handlers/authorizations.py` (list) | T22,T23,T24 | `direction`/`status`/`limit`/`offset`/`has_more` filter matrix identical semantics to `GET /requests`; a clock-expired stored-`open` record matches `status=expired`, never `status=open` (R151); only authorizations involving the caller are ever returned (R149) | pending | 2 |
| T26 | R124,R125,R126,R127,R128,R122,R143 | `src/pocketful/handlers/payments.py`, `src/pocketful/handlers/requests.py`, `src/pocketful/handlers/settlements.py` | T21 | `POST /payments`, `POST /requests/{id}/pay`, `POST /settlements` funds checks now compare against `available` (R126); with zero holds, every stage-1 case-table test for these three endpoints still passes unchanged (R124); `POST /payments` still never creates a hold (R125); `POST /splits` untouched (R128); payment shape gains `authorization_id` field, `null` on every non-capture path (R143) | pending | 2 |

## Batch 3 — export/import v2

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T27 | R115,R130,R131,R132,R135 | `src/pocketful/handlers/export_import.py` | T20,T22,T23,T24 | Export emits `format_version:2` with `authorization_ttl_seconds`/`authorizations` (incl. `captured_amount`/`payment_ids` on partially-captured records); import accepts `format_version:1` (defaults `authorization_ttl_seconds=600`, `authorizations={}`, then loads the rest exactly as stage-1 T18 already verified) and `format_version:2`; export→import round trip on a state with open/captured/voided/expired authorizations is a behavioral no-op; unknown version still 422, unchanged | pending | 3 |

## Batch 4 — UI

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T28 | R94,R95,R96,R100,R99 (labels/focus/contrast baseline) | `src/pocketful/ui/` (base template, static-file handler, CSS), `src/pocketful/handlers/auth_pages.py` (`/signup`,`/login`) | T5,T6 | `/signup`,`/login` render with every R100 testid; `auth-error` shown only on failure; `current-user`/`current-handle`/`logout-button` present once signed in; `/static/app.js` served with no outbound network reference (no CDN links) | pending | 4 |
| T29 | R101,R102,R103,R104,R105,R106,R111,R112,R113,R114 | `src/pocketful/handlers/wallet_page.py` (`/`), `src/pocketful/ui/static/app.js` (idempotency-key derivation, sequence numbers, decimal parsing) | T28,T8,T9,T21 | Pay/request forms + `activity-list` render all R101/R105 testids; unchanged resubmit → no second payment (R102); `wallet-refresh` latest-response-wins under out-of-order replies (R111); a refused payment (another client spent funds first) shows `pay-error`+refresh+preserved inputs (R112); a simulated lost response shows `pay-uncertain`, retries with identical key+body, resolves to exactly one money movement (R113); decimal parsing rejects excess-precision/non-numeric client-side with zero requests sent (R104) | pending | 4 |
| T30 | R107 | `src/pocketful/handlers/requests_page.py` (`/requests`) | T28,T10,T11,T12 | `incoming-list`/`outgoing-list` + all R107 testids; pay/decline buttons only on pending incoming, cancel only on pending outgoing; `request-error` on refusal; `empty-requests` iff both lists empty | pending | 4 |
| T31 | R108,R109 | `src/pocketful/handlers/split_page.py` (`/split`), `app.js` (client-side `compute_shares`) | T28,T14,T15 | `split-preview` shares equal server's `compute_shares` result for the same inputs and equal the actually-submitted split's `shares` (R109); all R108 testids present, `split-handles` comma-order preserved into `participant_handles` order | pending | 4 |
| T32 | R152,R153,R154,R155,R156,R97,R98,R99 | `src/pocketful/handlers/authorizations_page.py` (`/authorizations`), `wallet_page.py` (add `wallet-available`/`wallet-held`) | T29,T25,T23,T24 | All R152-R155 testids present with exact per-status/per-direction presence rules; `wallet-available` visually primary once `held>0` (R97); `wallet-held` absent when `held==0`; immediately-post-reset seeded holds reflected with no prior API call (R156); 375px/desktop no horizontal scroll, labeled inputs, visible focus, AA contrast on this route (R99) | pending | 4 |
| T33 | R116,R117,R118,R119 | `app.js` (retry-identity persistence), `handlers/export_import.py` (session/token continuity check) | T27,T29 | A token obtained pre-import still authenticates post-import (R116); a pending request seeded pre-import stays payable post-import (R117); a pay request whose response was lost pre-export, replayed with the same UI-stored key+body post-import, recovers the original payment via the same `pay-uncertain`→retry UI path and moves money once (R118) | pending | 4 |

## Batch 5 — concurrency hardening, accessibility pass, verification

| id | reqs | files | deps | done test | status | batch |
|---|---|---|---|---|---|---|
| T34 | R121,R122,R123,R157,R110 | (no new files — hardening pass across `authorizations.py`, `payments.py`, `requests.py`, `settlements.py`) | T22..T33 | 50-concurrent mixed burst (payments/requests/settlements/authorizations/captures/voids) — conservation on `total` holds, `available` never observed negative, cumulative captures never exceed `amount`, no double-capture on concurrent identical capture keys, zero 5xx; post-action same-page refresh never shows stale-then-jumps-back state (R110) | pending | 5 |
| T35 | R99 (full sweep) | `src/pocketful/ui/` (CSS/templates, cross-route) | T28,T29,T30,T31,T32 | Every required route (`/`,`/requests`,`/split`,`/signup`,`/login`,`/authorizations`) checked at 375px and a conventional desktop width: no horizontal scroll, every input has a visible label, keyboard focus is visible, text/control contrast ≥ AA, empty/loading/error states present, consistent nav across routes | pending | 5 |
| T36 | R1-R157 (full-stage verification) | (no new files) | T20..T35 | `python -m harness run --track pocketful --stage 2` (host mode) green; then `--mode isolated` green, ending `claimed stage: 2` with the stage-3 overshoot line `fail`; manual ≥50-concurrent burst confirms every money invariant (R1-R3 stage-1 + R121-R123 stage-2); stage-1's full acceptance suite still passes unmodified against `stage-2/` (compatibility) | pending | 5 |

## Coverage

Every stage-2 requirement R94-R157 and assumption A14-A20 is referenced by at least one
task above (T20-T36), verified by grepping the `reqs` column. R97/R98/R99's qualitative
sub-clauses (A17) are covered by T32/T35's acceptance criteria to the extent they are
mechanically testable; the remaining descriptive language is satisfied by reviewer design
read, per A17. Stage-1 requirements R1-R93 remain covered by T1-T19 (carried forward,
`done`, unmodified in `stage-2/` except where T26/T27 explicitly touch shared files —
those tasks' done-tests re-run the relevant stage-1 case tables to confirm no regression).
