# Stage 3 verification — reviewer

Verified revision: `0313387b08de85af038ea47805140c927e1653eb` (main).

## Method

- Fresh clone at the revision above (`/Users/jahnavisrilekhamolleti/Documents/Hackathon/band-work/verify-stage3-fresh`, independent of the shared `result` working directory and of every seat's live worktree — a lesson from this stage's batch reviews, where building from a live worktree once picked up another seat's uncommitted work-in-progress).
- `docker build --no-cache` of `stage-3/` (image tag `pocketful-stage2` — see hygiene finding below), then `docker run --rm -p 18090:8080 -e PORT=8080`; healthy (`GET /health` → `200 {"status":"ok"}`) within 2s.
- Shipped checks, isolated mode: `python -m harness run --track pocketful --repo <fresh-clone> --stage 3 --mode isolated --out band-work/checks/s3-review-final-1` → `stage 1: pass` (147/147), `stage 2: pass` (35/35), `stage 3: pass` (6/6), `stage 4: fail` (overshoot correct), `highest contiguous stage: 3`, `claimed stage: 3`.
- Tester's full acceptance suite (`specs/stage-3/acceptance/`, merged this session, last fix at `9d5e831`), re-run by the reviewer against the fresh no-cache container: **267/267 passed, 0 failed, 12 skipped** (all 12 skips sanctioned — `format_version: 3` per ADR-010, recorded with reasons in `run.py`). Every requirement below cites this run.
- Reviewer's own independent concurrent stress/invariant probe (`specs/stage-3/probes/probe_stage3_verification.py`), run separately against the same fresh container: 10-way concurrent identical-expected-revision correction race (exactly one 201, nine 409, zero 5xx — R231); 13-way mixed concurrent load (payments, statement reads, temporal `/me`, activity) followed by conservation/no-negative checks across four views including two historical `as_of` points and one `known_at` point — conservation held exactly (300000/300000 seeded minor units) and no negative `total`/`available` at any view (R202/R246); a deliberately invalid concurrent reset (negative seeded balance) rejected 422 with prior state (users, sessions) provably untouched (all-or-nothing, A29/R182). All checks passed — see the probe's own PASS/FAIL output, archived in this run's evidence.
- Hygiene: `stage-3/Dockerfile` and `stage-3/RUN.md` present; no nested `.git` or symlinks under `stage-3/`; secret scan (private-key headers, API/secret-key patterns, AWS access-key IDs) across the full repo clean. **One documentation defect found, same class as stage 2's**: `stage-3/RUN.md` is an unedited copy of `stage-2/RUN.md` — title ("Pocketful — stage 2: build and run"), the `docker build -t pocketful-stage2` command, and the `stage-2/` directory references are all still stage-2-labeled. Functionally harmless (commands are directory-relative, which is how this verification ran them unmodified), but inaccurate; worth a follow-up docs fix, not a verification blocker.
- No test-input/fixture-id/test-name branching found in `stage-3/src/` (`grep` for literal fixture ids, handle names, and test-ish conditionals — no hits).

## Stage 1 (R1-R93, A1-A13) and Stage 2 (R94-R157, A14-A28) — carried forward

Both stages' own `specs/stage-1/verification.md` and `specs/stage-2/verification.md` remain the record. This run's regression evidence: stage-1 85 PASS + 9 sanctioned SKIP (format_version/payment-shape deltas, same ones recorded at stage 2), stage-2 82 PASS + 1 sanctioned SKIP, **zero regressions** — all bundled into the 267/267 total above. The two backward-citations inside `specs/stage-3/requirements.md` (stage-1 R83, stage-2 R106) are prose references to already-regression-tested behaviour, not new stage-3 ids; no separate stage-3 test was expected or needed for them.

## Stage 3 requirements (R158-R251, A29-A38)

| Req | Status | Evidence |
|---|---|---|
| R158 | pass | test_timestamps.test_r158_created_at_on_every_payment_representation |
| R159 | pass | test_timestamps.test_r159_activity_ordering_unchanged_by_correction |
| R160 | pass | test_timestamps.test_r160_seeded_created_at_and_reset_default |
| R161 | pass | test_timestamps.test_r161_future_seeded_created_at_422_no_state_change |
| R162 | pass | test_timestamps.test_r162_fixture_balance_unchanged_by_loading_seeded_payments |
| R163 | pass | test_me_temporal.test_r163_as_of_validation |
| R164 | pass | test_me_temporal.test_r164_plain_me_reports_current_corrected_values |
| R165 | pass | test_me_temporal.test_r165_as_of_inclusive_uncorrected, .test_r165_as_of_same_instant_tie |
| R166 | pass | test_me_temporal.test_r166_as_of_after_latest_returns_current |
| R167 | pass | test_me_temporal.test_r167_as_of_before_earliest_returns_opening |
| R168 | pass | test_me_temporal.test_r168_as_of_echoed_exactly |
| R169 | pass | test_statement.test_r169_route_requires_auth |
| R170 | pass | test_statement.test_r170_from_to_defaults |
| R171 | pass | test_statement.test_r171_limit_offset_as_requests |
| R172 | pass | test_statement.test_r172_response_shape, .test_r172_r173_entries_oldest_first_and_tie_by_id |
| R173 | pass | test_statement.test_r172_r173_entries_oldest_first_and_tie_by_id |
| R174 | pass | test_statement.test_r174_opening_closing_balances |
| R175 | pass | test_statement.test_r175_full_window_delta_invariant |
| R176 | pass | test_statement.test_r176_pagination_stable |
| R177 | pass | test_statement.test_r177_statement_privacy |
| R178 | pass | test_corrections.test_r178_revision1_of_api_payment |
| R179 | pass | test_corrections.test_r179_seeded_revision1_uses_seeded_created_at |
| R180 | pass | test_me_temporal.test_r167_as_of_before_earliest_returns_opening (opening via fixture math) |
| R181 | pass | stage-1 regression (new accounts at zero) + test_corrections fixtures |
| R182/A29 | pass | test_corrections: seeded fixtures replay nonnegative; A29-negative fixture rejected in stage-1 R15 family (regression); reviewer's own probe (negative seeded balance → 422, prior state intact) |
| R183 | pass | test_corrections.test_r183_requires_idempotency_key |
| R184 | pass | test_corrections.test_r184_non_sender_403_unknown_404 |
| R185 | pass | test_corrections.test_r185_all_fields_required |
| R186 | pass | test_corrections.test_r186_expected_revision_rules |
| R187 | pass | test_corrections.test_r187_amount_rules, .test_r187_zero_reverses_entire_payment |
| R188 | pass | test_corrections.test_r188_reason_rules |
| R189 | pass | test_corrections.test_r189_effective_at_rules |
| R190 | pass | test_corrections.test_r190_unknown_body_fields_ignored_not_422 (catch-all family exercised by R185-R189 cases) |
| R191 | pass | test_corrections.test_r191_correction_changes_neither_parties_nor_visibility |
| R192 | pass | test_corrections.test_r192_201_response_shape |
| R193 | pass | test_corrections.test_r193_recorded_times_strictly_increase; test_invariants (fuzz + stress) |
| R194 | pass | test_corrections.test_r194_stale_revision; test_invariants.test_r201_fuzz_* |
| R195 | pass | test_corrections.test_r195_replay_returns_original_revision |
| R196 | pass | test_corrections.test_r196_same_key_different_body |
| R197 | pass | test_corrections.test_r197_delta_moves_between_same_wallets, .test_r197_zero_delta_appends_revision_moves_nothing |
| R198 | pass | test_corrections.test_r198_current_unaffordable_insufficient_funds |
| R199 | pass | test_corrections.test_r199_historical_overdraft_total |
| R200 | pass | test_corrections.test_r200_combined_effect_at_same_instant |
| R201 | pass | test_corrections.test_r198_*/.test_r199_* (state preserved); test_invariants.test_r201_fuzz_corrections_state_stays_consistent |
| R202 | pass | test_me_temporal.test_r202_historical_conservation_grid; test_invariants.test_r202_* + grid after every load/fuzz step; reviewer's own probe (conservation across 4 views incl. 2 historical, 1 known_at) |
| R203 | pass | test_corrections.test_r203_original_payment_and_idempotent_responses_unchanged |
| R204 | pass | test_corrections.test_r204_activity_unchanged_by_correction; test_timestamps.test_r159_* |
| R205 | pass | test_corrections.test_r205_revisions_listing |
| R206 | pass | test_corrections.test_r206_revisions_visibility |
| R207 | pass | test_me_temporal.test_r207_known_at_accepted_on_me_and_statement |
| R208 | pass | test_holds.test_r238_all_four_money_fields_one_view (known_at selection); test_me_temporal.test_r209_* |
| R209 | pass | test_me_temporal.test_r209_omission_means_everything_known |
| R210 | pass | test_me_temporal.test_a34_corrected_inclusion_governed_by_effective_at; test_statement.test_r215_* |
| R211 | pass | test_statement.test_r174_* (half-open) + test_me_temporal.test_r165_* (inclusive), combined in test_holds views |
| R212 | pass | test_me_temporal.test_r212_future_instants_accepted |
| R213 | pass | test_me_temporal.test_r213_known_at_invalid_422 |
| R214 | pass | test_me_temporal.test_r214_known_at_echoed_exactly |
| R215 | pass | test_statement.test_r215_ordering_by_selected_effective_at |
| R216 | pass | test_statement.test_r172_response_shape, .test_r217_* |
| R217 | pass | test_statement.test_r217_payment_amount_is_selected_amount |
| R218 | pass | test_statement.test_r218_zero_amount_revision_zero_delta_entry |
| R219 | pass | test_statement.test_r219_exactly_one_entry_per_payment |
| R220 | pass | test_statement.test_r220_uncorrected_statement_unchanged; test_me_temporal.test_r220_* |
| R221 | pass | test_snapshots.test_r221_snapshot_on_first_read |
| R222 | pass | test_snapshots.test_r222_r223_snapshot_freezes_result |
| R223 | pass | test_snapshots.test_r222_r223_snapshot_freezes_result |
| R224 | pass | test_snapshots.test_r224_snapshot_param_combinations |
| R225 | pass | test_snapshots.test_r225_unknown_other_user_and_stale_tokens |
| R226 | pass | test_snapshots.test_r226_token_valid_until_reset |
| R227 | pass | test_snapshots.test_r227_paging_no_mutation_has_more |
| R228 | pass | test_statement.test_r228_unrecognized_params_ignored; test_statement.test_a36_*; test_me_temporal.test_a36_* |
| R229 | pass | test_statement.test_r229_live_window_membership_moves |
| R230 | pass | test_snapshots.test_r228_r230_snapshot_stable_under_concurrent_writes |
| R231 | pass | test_invariants.test_r231_stress_concurrent_same_expected_revision; reviewer's own probe (10-way race, exactly one 201/nine 409, zero 5xx) |
| R232 | pass | test_upgrade_settlements.test_r232_settlement_receipts_and_privacy_unchanged |
| R233 | pass | test_upgrade_settlements.test_r233_settlement_member_revision_uses_committed_at |
| R234 | pass | test_upgrade_settlements.test_r234_settlement_member_correction_422 |
| R235 | pass | test_upgrade_settlements.test_r235_import_v1_export, .test_r236_import_v2_export_with_authorizations |
| R236 | pass | test_upgrade_settlements.test_r236_import_v2_export_with_authorizations |
| R237 | pass | test_upgrade_settlements.test_r237_live_capture_correction_422, .test_r236_* (imported capture) |
| R238 | pass | test_holds.test_r238_all_four_money_fields_one_view |
| R239 | pass | test_holds.test_r239_capture_timeline_nonfinal, .test_r239_final_capture_and_void_release_at_event_time |
| R240 | pass | test_holds.test_r240_expiry_at_expires_at |
| R241 | pass | test_holds.test_r241_r242_future_expiry_known_at_creation |
| R242 | pass | test_holds.test_r241_r242_future_expiry_known_at_creation |
| R243 | pass | test_holds.test_r243_without_as_of_uses_request_start |
| R244 | pass | test_holds.test_r244_closed_at |
| R245 | pass | test_holds.test_r238_* (historical total per view); test_me_temporal.test_r202_* |
| R246 | pass | test_holds.test_r246_historical_overdraft_via_available; reviewer's own probe (no negative total/available at 4 views) |
| R247 | pass | test_holds.test_r247_insufficient_funds_precedence |
| R248 | pass | test_holds.test_r248_seeded_open_hold_created_at |
| R249 | pass | test_holds.test_r249_statement_money_movements_only |
| R250 | pass | test_holds.test_r250_capture_appears_once_with_link; test_snapshots.test_r251_* |
| R251 | pass | test_snapshots.test_r251_snapshot_stable_under_lifecycle_actions |
| A30 | pass | test_upgrade_settlements.test_r235_import_v1_export (synthesis), .test_export_v3_round_trip |
| A31 | pass | applied throughout: shape asserts are presence-based; no from/to echo asserted |
| A32 | pass | test_corrections.test_r196_* (idempotency before field validation), .test_a32_linked_payment_immutability_before_field_shape |
| A33 | pass | test_corrections.test_a33_no_correction_count_cap; test_invariants fuzz |
| A34 | pass | test_me_temporal.test_a34_corrected_inclusion_governed_by_effective_at; test_corrections.test_a34_*; test_statement.test_r215_* |
| A35 | pass | test_holds.test_a35_seeded_authz_created_at_validation_and_ordering |
| A36 | pass | test_me_temporal.test_a36_*; test_statement.test_a36_*; test_snapshots.test_r224_* (as_of with snapshot ok) |
| A37 | pass | test_statement.test_r172_r173_entries_oldest_first_and_tie_by_id |
| A38 | pass | test_snapshots.test_a38_import_invalidates_snapshots; test_upgrade_settlements.test_export_v3_round_trip |
| Invariants (mandate) | pass | test_invariants (all four tests): conservation incl. historical views, no negative money, exactly-once, no 5xx at 50 in flight, all-or-nothing fuzz; reviewer's own independent probe (separate 10-way + 13-way concurrent runs, see Method) |

## Verdict

**PASS.** Stage 3 (T39-T49, R158-R251, A29-A38) is complete, fast-forward-merged to `main` at `0313387`, every requirement id has a passing test or recorded evidence, stage-1/2 regression is clean, the reviewer's independent stress probe confirms conservation/no-negative/exactly-once/all-or-nothing under concurrency including historical views, and the service does not satisfy stage 4. One non-blocking hygiene defect (stage-3/RUN.md mislabeled as stage 2) reported for a follow-up docs fix.
