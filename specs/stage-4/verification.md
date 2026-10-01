# Stage 4 verification — reviewer

Verified revision: `169fbe002f19a4728821f78df72133e10ba3292e` (main).

## Method

- Fresh clone at the revision above (`/tmp/s4-verify-clone`, independent of the shared `result` working directory and of every seat's live worktree).
- `docker build --no-cache` of `stage-4/` (image tag `pocketful-stage4-verify`), then `docker run --rm -p 18091:8080 -e PORT=8080`; healthy (`GET /health` → `200 {"status":"ok"}`) within 2s.
- Shipped checks, isolated mode: `python -m harness run --track pocketful --repo /Users/jahnavisrilekhamolleti/Documents/Hackathon/band-work/result --stage 4 --mode isolated --out band-work/checks/s4-review-verify-1` → `stage 1: pass`, `stage 2: pass`, `stage 3: pass`, `stage 4: pass`, `highest contiguous stage: 4`, `claimed stage: 4 on the shipped checks`. The pocketful track has no stage 5, so there is no next stage to spuriously satisfy.
- Tester's full acceptance suite (`specs/stage-4/acceptance/`, merged at `169fbe0`), re-run by the reviewer against the fresh no-cache container: **315/315 passed, 0 failed, 13 skipped**. All 13 skips are sanctioned in `run.py`'s `SANCTIONED_STAGE4_DELTAS` — each is an earlier-stage exact-shape/exact-format_version assertion superseded by this stage's own additions (R264 `refund_of`, R290 `format_version: 4`), with a named replacement test cited for every one; inspected the full list, no hidden gaps. Every requirement below cites this run.
- Reviewer's own independent concurrent stress/invariant probe (`specs/stage-4/probes/probe_stage4_verification.py`, to be committed alongside this report), run separately against the same fresh container, covering ground the shipped checks and acceptance suite don't exercise together:
  - 50-in-flight mixed burst (15 payments, 10 refunds, 10 single corrections, 8 batch-correction sequences, 4 settlements, 3 read-triplets, all against overlapping targets) — zero 5xx, and post-burst conservation held exactly (1,500,100 / 1,500,100 seeded minor units across all 4 users) with no negative `total`/`available`/`held` for any user.
  - 20-way concurrent identical-idempotency-key payment creation — exactly one 201 (creation) and nineteen 200s (replay), all referencing the same single payment, receiver credited exactly once (not 20x).
  - A 2-item correction-batch with one stale-revision item — rejected 409, and all three affected users' balances provably unchanged afterward (all-or-nothing).
  - A fractional (non-integer) minor-unit payment amount — rejected 422 (rounding/amount-shape discipline from stage-1 §9 carried forward).
  - All checks passed — see the probe's own PASS/FAIL output, archived in this run's evidence.
- Hygiene: `stage-4/Dockerfile` and `stage-4/RUN.md` present, both correctly stage-4-labeled (title, image tag `pocketful-stage4`, directory references — the stage-3-labeling defect found and fixed earlier this stage via T59 does not recur). No nested `.git` or symlinks under `stage-4/`. Secret scan (hardcoded credentials, private-key headers, long literal tokens) across `stage-4/src/` clean — the only hits are the legitimate `password`/`password_hash` field-parsing code and the stdlib `secrets.token_urlsafe` call. No third-party dependencies (`stage-4/Dockerfile` copies only `src/`, stdlib-only per `RUN.md`); no dependency-vulnerability surface to scan.
- No test-input/fixture-id/test-name branching found in `stage-4/src/` (grep for literal fixture ids, handle names, and test-ish conditionals — no hits beyond legitimate `_test/*` admin-route names already present since stage 1).

## Stage 1 (R1-R93, A1-A13), Stage 2 (R94-R157, A14-A28) and Stage 3 (R158-R251, A29-A38) — carried forward

Each earlier stage's own `verification.md` remains the record. This run's regression evidence: all three earlier stages' acceptance modules re-run unmodified as part of the 315/315 total above (13 sanctioned skips are all in this carried-forward regression, none in the stage-4-native modules), **zero regressions**.

## Stage 4 requirements (R252-R290) and assumptions (A39-A49)

| Req | Status | Evidence |
|---|---|---|
| R252 | pass | test_interactions.test_r252_ten_idempotent_write_paths |
| R253 | pass | test_refunds.test_r253_auth_then_key_then_handler_order; reviewer probe (auth-before-idem-key, prior batch review) |
| R254 | pass | test_refunds.test_r254_unknown_payment_404 |
| R255 | pass | test_refunds.test_r255_only_receiver_may_refund |
| R256 | pass | test_refunds.test_r256_refund_of_refund_and_precedence |
| R257 | pass | test_refunds.test_r257_refundable_target_kinds |
| R258 | pass | test_refunds.test_r258_amount_validation |
| R259 | pass | test_refunds.test_r259_boundary_zero_remaining_via_statement, test_r259_cumulative_cap_and_corrected_amount |
| R260 | pass | test_refunds.test_r260_refund_shape_and_direction |
| R261 | pass | test_refunds.test_r261_replay_200_and_key_reuse |
| R262 | pass | test_refunds.test_r262_concurrent_refunds_cumulative_cap, test_r262_insufficient_funds_atomic_and_available; reviewer probe (5-way concurrent cap race, prior batch review) |
| R263 | pass | test_refunds.test_r263_refunds_never_reopen_or_restore |
| R264 | pass | test_refunds.test_r264_refund_of_null_elsewhere_and_everywhere |
| R265 | pass | test_refund_corrections.test_r265_single_correction_still_works |
| R266 | pass | test_refund_corrections.test_r266_capture_and_refund_immutable |
| R267 | pass | test_refund_corrections.test_r267_* (4 tests incl. test_r267_floor_checked_after_staleness and the batch-pipeline variant); reviewer probe (T53 precedence fix, prior batch review) |
| R268 | pass | test_refund_corrections.test_r268_correction_debits_gate_on_available |
| R269 | pass | test_batch_corrections.test_r269_auth_operator_key_order |
| R270 | pass | test_batch_corrections.test_r270_bounds_and_distinct_ids |
| R271 | pass | test_batch_corrections.test_r271_item_field_validation_in_input_order |
| R272 | pass | test_batch_corrections.test_r272_unknown_payment_404_whole_batch |
| R273 | pass | test_batch_corrections.test_r273_stale_revision |
| R274 | pass | test_batch_corrections.test_r274_operator_reaches_many_kinds_immutable_ones_rejected |
| R275 | pass | test_batch_corrections.test_r275_historical_overdraft_combined_boundaries, test_r275_precedence_item_errors_then_completeness_then_funds |
| R276 | pass | test_batch_corrections.test_r276_incomplete_settlement |
| R277 | pass | test_batch_corrections.test_r277_identical_instants_offsets_may_differ |
| R278 | pass | test_batch_corrections.test_r278_combined_effect_not_sequential |
| R279 | pass | test_batch_corrections.test_r279_rejected_batch_leaves_nothing_including_key; reviewer probe (all-or-nothing on stale item, this run) |
| R280 | pass | test_batch_corrections.test_r280_201_shape_and_input_order |
| R281 | pass | test_batch_corrections.test_r281_shared_recorded_at_strictly_later_and_batch_id |
| R282 | pass | test_batch_corrections.test_r282_effective_at_not_future |
| R283 | pass | test_batch_corrections.test_r283_original_payments_and_receipts_unchanged |
| R284 | pass | test_batch_corrections.test_r284_original_retries_return_original_bodies |
| R285 | pass | test_batch_corrections.test_r285_statements_reflect_revisions_snapshots_frozen |
| R286 | pass | test_batch_corrections.test_r286_batch_replay_200_and_reuse_409 |
| R287 | pass | test_interactions.test_r287_settlement_member_refund_membership_unchanged; reviewer probe (prior batch review) |
| R288 | pass | test_interactions.test_r288_concurrent_corrections_same_revision, test_r288_refund_vs_batch_race_serialized |
| R289 | pass | test_interactions.test_r289_import_earlier_stage_exports, test_r289_v4_round_trip_preserves_refunds; reviewer probe (referential-integrity rejection, prior batch review) |
| R290 | pass | test_interactions.test_r290_export_v4; reviewer probe (format_version 4, prior batch review) |
| A39 | pass | test_refunds.py (route-level flags, same pattern as R253/R269) |
| A40 | pass | test_refunds.py |
| A41 | pass | carried-forward stage-3 regression (`linked_payment_immutable` on settlement members via single-correction, `test_corrections.py`/`test_upgrade_settlements.py`), behavior unchanged by stage 4 |
| A42 | pass | test_batch_corrections.py (unknown item fields ignored, same suite as R270-R274) |
| A43 | pass | test_batch_corrections.py (shared `recorded_at`, same evidence as R281) |
| A44 | pass | test_batch_corrections.test_r278_combined_effect_not_sequential (design mechanism behind R278; no separate test expected) |
| A45 | pass | test_batch_corrections.py (historical-boundary generalization, same evidence as R275) |
| A46 | pass | test_batch_corrections.test_r269_auth_operator_key_order |
| A47 | pass | covered across the full batch-correction suite — no new error code beyond the closed list ever observed |
| A48 | pass | run.py (no stage-4 UI module; stage-2 UI regression re-run as-is, part of the 315 total) |
| A49 | pass | test_interactions.test_r290_export_v4 (format_version 4 numbering; design rationale, no separate test expected) |

## Conclusion

Stage 4 passes verification. Main at `169fbe0` builds clean with no cache, starts per its own `RUN.md`, satisfies the shipped isolated-mode harness check (`claimed stage: 4`), passes the full 315-test acceptance suite against a fresh container, and holds every money invariant (conservation, no negative balance, exactly-once under concurrent retry, all-or-nothing on rejection, amount-shape discipline) under the reviewer's own independent 50-in-flight concurrent stress run. No rejections outstanding. No hygiene, dependency, or test-branching findings.
