# Pocketful stage-3 acceptance suite

Black-box acceptance tests for stage 3 (statements and payment corrections).
Every test talks to the running service over HTTP only — no product code is
imported, no fixture of the implementation is read. Targets: R158-R251 and
A29-A38 of `specs/stage-3/requirements.md`, with stage-1 (R1-R93) and stage-2
(R94-R157) regression carried in the same run.

## Run

```sh
python3 specs/stage-3/acceptance/run.py [BASE_URL]
```

`BASE_URL` defaults to `$BASE_URL` or `http://127.0.0.1:8080`. Stdlib only;
Python 3.10+. Every test resets the service first, so the suite is repeatable
and order-independent. `--skip-regression` runs only stage-3 modules;
`--filter SUB` selects by name; `--list` prints test names.

Stage 3 adds no routes, screens or `data-testid`s (stage-3.md is API-only), so
there is no stage-3 UI module; the carried-forward stage-2 UI module runs as
the UI regression. The stage-2 suite's visual-only sub-rules (R99/A17 browser
checks) remain reviewer browser checks as recorded there.

## Coverage

| Requirement | Tests |
|---|---|
| R158 | test_timestamps.test_r158_created_at_on_every_payment_representation |
| R159 | test_timestamps.test_r159_activity_ordering_unchanged_by_correction |
| R160 | test_timestamps.test_r160_seeded_created_at_and_reset_default |
| R161 | test_timestamps.test_r161_future_seeded_created_at_422_no_state_change |
| R162 | test_timestamps.test_r162_fixture_balance_unchanged_by_loading_seeded_payments |
| R163 | test_me_temporal.test_r163_as_of_validation |
| R164 | test_me_temporal.test_r164_plain_me_reports_current_corrected_values |
| R165 | test_me_temporal.test_r165_as_of_inclusive_uncorrected, .test_r165_as_of_same_instant_tie |
| R166 | test_me_temporal.test_r166_as_of_after_latest_returns_current |
| R167 | test_me_temporal.test_r167_as_of_before_earliest_returns_opening |
| R168 | test_me_temporal.test_r168_as_of_echoed_exactly |
| R169 | test_statement.test_r169_route_requires_auth |
| R170 | test_statement.test_r170_from_to_defaults |
| R171 | test_statement.test_r171_limit_offset_as_requests |
| R172 | test_statement.test_r172_response_shape, .test_r172_r173_entries_oldest_first_and_tie_by_id |
| R173 | test_statement.test_r172_r173_entries_oldest_first_and_tie_by_id |
| R174 | test_statement.test_r174_opening_closing_balances |
| R175 | test_statement.test_r175_full_window_delta_invariant |
| R176 | test_statement.test_r176_pagination_stable |
| R177 | test_statement.test_r177_statement_privacy |
| R178 | test_corrections.test_r178_revision1_of_api_payment |
| R179 | test_corrections.test_r179_seeded_revision1_uses_seeded_created_at |
| R180 | test_me_temporal.test_r167_as_of_before_earliest_returns_opening (opening via fixture math) |
| R181 | stage-1 regression (new accounts at zero) + test_corrections fixtures |
| R182/A29 | test_corrections: seeded fixtures replay nonnegative; A29-negative fixture rejected in stage-1 R15 family (regression) |
| R183 | test_corrections.test_r183_requires_idempotency_key |
| R184 | test_corrections.test_r184_non_sender_403_unknown_404 |
| R185 | test_corrections.test_r185_all_fields_required |
| R186 | test_corrections.test_r186_expected_revision_rules |
| R187 | test_corrections.test_r187_amount_rules, .test_r187_zero_reverses_entire_payment |
| R188 | test_corrections.test_r188_reason_rules |
| R189 | test_corrections.test_r189_effective_at_rules |
| R190 | test_corrections.test_r190_unknown_body_fields_ignored_not_422 (catch-all family exercised by R185-R189 cases) |
| R191 | test_corrections.test_r191_correction_changes_neither_parties_nor_visibility |
| R192 | test_corrections.test_r192_201_response_shape |
| R193 | test_corrections.test_r193_recorded_times_strictly_increase; test_invariants (fuzz + stress) |
| R194 | test_corrections.test_r194_stale_revision; test_invariants.test_r201_fuzz_* |
| R195 | test_corrections.test_r195_replay_returns_original_revision |
| R196 | test_corrections.test_r196_same_key_different_body |
| R197 | test_corrections.test_r197_delta_moves_between_same_wallets, .test_r197_zero_delta_appends_revision_moves_nothing |
| R198 | test_corrections.test_r198_current_unaffordable_insufficient_funds |
| R199 | test_corrections.test_r199_historical_overdraft_total |
| R200 | test_corrections.test_r200_combined_effect_at_same_instant |
| R201 | test_corrections.test_r198_*/.test_r199_* (state preserved); test_invariants.test_r201_fuzz_corrections_state_stays_consistent |
| R202 | test_me_temporal.test_r202_historical_conservation_grid; test_invariants.test_r202_* + grid after every load/fuzz step |
| R203 | test_corrections.test_r203_original_payment_and_idempotent_responses_unchanged |
| R204 | test_corrections.test_r204_activity_unchanged_by_correction; test_timestamps.test_r159_* |
| R205 | test_corrections.test_r205_revisions_listing |
| R206 | test_corrections.test_r206_revisions_visibility |
| R207 | test_me_temporal.test_r207_known_at_accepted_on_me_and_statement |
| R208 | test_holds.test_r238_all_four_money_fields_one_view (known_at selection); test_me_temporal.test_r209_* |
| R209 | test_me_temporal.test_r209_omission_means_everything_known |
| R210 | test_me_temporal.test_a34_corrected_inclusion_governed_by_effective_at; test_statement.test_r215_* |
| R211 | test_statement.test_r174_* (half-open) + test_me_temporal.test_r165_* (inclusive), combined in test_holds views |
| R212 | test_me_temporal.test_r212_future_instants_accepted |
| R213 | test_me_temporal.test_r213_known_at_invalid_422 |
| R214 | test_me_temporal.test_r214_known_at_echoed_exactly |
| R215 | test_statement.test_r215_ordering_by_selected_effective_at |
| R216 | test_statement.test_r172_response_shape, .test_r217_* |
| R217 | test_statement.test_r217_payment_amount_is_selected_amount |
| R218 | test_statement.test_r218_zero_amount_revision_zero_delta_entry |
| R219 | test_statement.test_r219_exactly_one_entry_per_payment |
| R220 | test_statement.test_r220_uncorrected_statement_unchanged; test_me_temporal.test_r220_* |
| R221 | test_snapshots.test_r221_snapshot_on_first_read |
| R222 | test_snapshots.test_r222_r223_snapshot_freezes_result |
| R223 | test_snapshots.test_r222_r223_snapshot_freezes_result |
| R224 | test_snapshots.test_r224_snapshot_param_combinations |
| R225 | test_snapshots.test_r225_unknown_other_user_and_stale_tokens |
| R226 | test_snapshots.test_r226_token_valid_until_reset |
| R227 | test_snapshots.test_r227_paging_no_mutation_has_more |
| R228 | test_statement.test_r228_unrecognized_params_ignored; test_statement.test_a36_*; test_me_temporal.test_a36_* |
| R229 | test_statement.test_r229_live_window_membership_moves |
| R230 | test_snapshots.test_r228_r230_snapshot_stable_under_concurrent_writes |
| R231 | test_invariants.test_r231_stress_concurrent_same_expected_revision |
| R232 | test_upgrade_settlements.test_r232_settlement_receipts_and_privacy_unchanged |
| R233 | test_upgrade_settlements.test_r233_settlement_member_revision_uses_committed_at |
| R234 | test_upgrade_settlements.test_r234_settlement_member_correction_422 |
| R235 | test_upgrade_settlements.test_r235_import_v1_export, .test_r236_import_v2_export_with_authorizations |
| R236 | test_upgrade_settlements.test_r236_import_v2_export_with_authorizations |
| R237 | test_upgrade_settlements.test_r237_live_capture_correction_422, .test_r236_* (imported capture) |
| R238 | test_holds.test_r238_all_four_money_fields_one_view |
| R239 | test_holds.test_r239_capture_timeline_nonfinal, .test_r239_final_capture_and_void_release_at_event_time |
| R240 | test_holds.test_r240_expiry_at_expires_at |
| R241 | test_holds.test_r241_r242_future_expiry_known_at_creation |
| R242 | test_holds.test_r241_r242_future_expiry_known_at_creation |
| R243 | test_holds.test_r243_without_as_of_uses_request_start |
| R244 | test_holds.test_r244_closed_at |
| R245 | test_holds.test_r238_* (historical total per view); test_me_temporal.test_r202_* |
| R246 | test_holds.test_r246_historical_overdraft_via_available |
| R247 | test_holds.test_r247_insufficient_funds_precedence |
| R248 | test_holds.test_r248_seeded_open_hold_created_at |
| R249 | test_holds.test_r249_statement_money_movements_only |
| R250 | test_holds.test_r250_capture_appears_once_with_link; test_snapshots.test_r251_* |
| R251 | test_snapshots.test_r251_snapshot_stable_under_lifecycle_actions |
| A30 | test_upgrade_settlements.test_r235_import_v1_export (synthesis), .test_export_v3_round_trip |
| A31 | applied throughout: shape asserts are presence-based; no from/to echo asserted |
| A32 | test_corrections.test_r196_* (idempotency before field validation), .test_a32_linked_payment_immutability_before_field_shape |
| A33 | test_corrections.test_a33_no_correction_count_cap; test_invariants fuzz |
| A34 | test_me_temporal.test_a34_corrected_inclusion_governed_by_effective_at; test_corrections.test_a34_*; test_statement.test_r215_* |
| A35 | test_holds.test_a35_seeded_authz_created_at_validation_and_ordering |
| A36 | test_me_temporal.test_a36_*; test_statement.test_a36_*; test_snapshots.test_r224_* (as_of with snapshot ok) |
| A37 | test_statement.test_r172_r173_entries_oldest_first_and_tie_by_id |
| A38 | test_snapshots.test_a38_import_invalidates_snapshots; test_upgrade_settlements.test_export_v3_round_trip |
| Invariants (mandate) | test_invariants (all four tests): conservation incl. historical views, no negative money, exactly-once, no 5xx at 50 in flight, all-or-nothing fuzz |

## Sanctioned regression deltas (runner SKIPs)

- The service now exports `format_version: 3` (ADR-010): stage-1 export-shape
  tests and stage-2's `test_r119_import_between_browser_requests` v2-format
  assertion are skipped with recorded reasons; the v3 export/round-trip and
  v1/v2 import behavior are asserted in `test_upgrade_settlements`.
- All other stage-1/stage-2 tests run unmodified as regression.

## Deliberately not asserted (source leaves unspecified)

- Whether a snapshot-paged response again includes a `snapshot` field (R221
  says "first" read); the frozen content is asserted, the token's presence on
  paged reads is not.
- Per-entry shape of `GET /payments/{id}/revisions` beyond the five named
  fields (presence-only per A31's principle); per-entry `payment_id` unasserted.
- A seeded `created_at` exactly equal to the reset instant (legal — the
  omission case); not separately constructed.
- The specific `closed_at` value of seeded `captured`/`voided` holds (fixture
  supplies no event time; R248 says the lifecycle need not be reconstructed).
- `GET /statement` echoes of `from`/`to` (A31: not required, not asserted).