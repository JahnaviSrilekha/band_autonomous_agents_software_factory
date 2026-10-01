# Pocketful stage-4 acceptance suite

Black-box acceptance tests for stage 4 (refunds and batch corrections).
Every test talks to the running service over HTTP only — no product code is
imported, no implementation fixture is read. Targets: R252-R290 and A39-A49
of `specs/stage-4/requirements.md`, with stage-1/2/3 (R1-R251, including the
stage-1 §9 rounding table) regression carried in the same run.

## Run

```sh
python3 specs/stage-4/acceptance/run.py [BASE_URL]
```

`BASE_URL` defaults to `$BASE_URL` or `http://127.0.0.1:8080`. Stdlib only;
Python 3.10+. Every test resets the service first, so the suite is repeatable
and order-independent. `--skip-regression` runs only stage-4 modules;
`--filter SUB` selects by name; `--list` prints test names.

Build and start the service under test first (see `stage-4/RUN.md`):

```sh
docker build -t pocketful-stage4 stage-4 && docker run --rm -p 8080:8080 -e PORT=8080 pocketful-stage4
```

Stage 4 adds no routes, screens or `data-testid`s beyond the JSON API (A48:
no new UI surface), so there is no stage-4 UI module; the carried-forward
stage-2 UI module runs as the UI regression.

## Coverage

| Requirement | Tests |
|---|---|
| R252 | test_interactions.test_r252_ten_idempotent_write_paths (all ten routes: missing key 400 + replay 200) |
| R253 | test_refunds.test_r253_auth_then_key_then_handler_order |
| R254 | test_refunds.test_r254_unknown_payment_404, .test_r253_auth_then_key_then_handler_order |
| R255 | test_refunds.test_r255_only_receiver_may_refund |
| R256 | test_refunds.test_r256_refund_of_refund_and_precedence |
| R257 | test_refunds.test_r257_refundable_target_kinds |
| R258 | test_refunds.test_r258_amount_validation |
| R259 | test_refunds.test_r259_cumulative_cap_and_corrected_amount, .test_r259_boundary_zero_remaining_via_statement |
| R260 | test_refunds.test_r260_refund_shape_and_direction |
| R261 | test_refunds.test_r261_replay_200_and_key_reuse |
| R262 | test_refunds.test_r262_insufficient_funds_atomic_and_available, .test_r262_concurrent_refunds_cumulative_cap |
| R263 | test_refunds.test_r263_refunds_never_reopen_or_restore |
| R264 | test_refunds.test_r264_refund_of_null_elsewhere_and_everywhere |
| R265 | test_refund_corrections.test_r265_single_correction_still_works |
| R266 | test_refund_corrections.test_r266_capture_and_refund_immutable |
| R267 | test_refund_corrections.test_r267_correction_cannot_dip_below_refunded, .test_r267_concurrent_refund_vs_correction, .test_r267_floor_applies_after_multiple_refunds, .test_r267_floor_checked_after_staleness |
| R268 | test_refund_corrections.test_r268_correction_debits_gate_on_available |
| R269 | test_batch_corrections.test_r269_auth_operator_key_order |
| R270 | test_batch_corrections.test_r270_bounds_and_distinct_ids |
| R271 | test_batch_corrections.test_r271_item_field_validation_in_input_order |
| R272 | test_batch_corrections.test_r272_unknown_payment_404_whole_batch |
| R273 | test_batch_corrections.test_r273_stale_revision, .test_r267_floor_checked_after_staleness_in_batch (staleness-before-floor sub-order, design sec6/sec7) |
| R274 | test_batch_corrections.test_r274_operator_reaches_many_kinds_immutable_ones_rejected |
| R275 | test_batch_corrections.test_r275_precedence_item_errors_then_completeness_then_funds, .test_r275_historical_overdraft_combined_boundaries |
| R276 | test_batch_corrections.test_r276_incomplete_settlement |
| R277 | test_batch_corrections.test_r277_identical_instants_offsets_may_differ |
| R278 | test_batch_corrections.test_r278_combined_effect_not_sequential |
| R279 | test_batch_corrections.test_r279_rejected_batch_leaves_nothing_including_key |
| R280 | test_batch_corrections.test_r280_201_shape_and_input_order |
| R281 | test_batch_corrections.test_r281_shared_recorded_at_strictly_later_and_batch_id |
| R282 | test_batch_corrections.test_r282_effective_at_not_future |
| R283 | test_batch_corrections.test_r283_original_payments_and_receipts_unchanged |
| R284 | test_batch_corrections.test_r284_original_retries_return_original_bodies |
| R285 | test_batch_corrections.test_r285_statements_reflect_revisions_snapshots_frozen |
| R286 | test_batch_corrections.test_r286_batch_replay_200_and_reuse_409 |
| R287 | test_interactions.test_r287_settlement_member_refund_membership_unchanged |
| R288 | test_interactions.test_r288_concurrent_corrections_same_revision, .test_r288_refund_vs_batch_race_serialized |
| R289 | test_interactions.test_r289_import_earlier_stage_exports, .test_r289_v4_round_trip_preserves_refunds |
| R290 | test_interactions.test_r290_export_v4 |
| Money invariants (concurrent/retried load: conservation, no negative money, exactly-once, all-or-nothing, refund caps, shared batch recorded_at, no 5xx) | test_invariants.test_invariants_mixed_writes_fuzz |
| Stage-1 §9 rounding table (carried regression) | stage1.test_splits.test_rounding_table_exact and the full stage-1/2/3 modules via default run |
| R1-R251 regression (carried) | stage1.*, stage2.*, stage3.* modules via default run (sanctioned supersessions printed as SKIP with reasons) |