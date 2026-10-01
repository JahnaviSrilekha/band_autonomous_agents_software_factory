# Pocketful — stage 2 black-box acceptance suite

Derived solely from `specs/stage-2/requirements.md` (R94-R157, A14-A27) and the
stage-1 requirements it carries forward (R1-R93, A1-A13). Never from the
implementation or the shipped checks. Stdlib only; talks to the running service
over HTTP (API + `Accept: text/html` pages parsed as DOM against the required
`data-testid` hooks).

## Run

```sh
python3 specs/stage-2/acceptance/run.py http://127.0.0.1:8080
```

`BASE_URL` env var works too. Options: `--list`, `--filter SUB`,
`--skip-stage1`. Every test resets state first (stage-2 fixture via
`POST /_test/reset`), so it runs repeatedly and in any order against a freshly
started container.

By default the suite first re-runs the stage-1 acceptance modules
(`specs/stage-1/acceptance/test_*.py`, unmodified) against this service —
stage-1 requirements remain in force by reference, so a stage-2 regression of
any stage-1 flow fails here. Two documented stage-2 deltas supersede nine
stage-1 assertions (stage-2 exports `format_version: 2` per ADR-006; the
payment shape gains `authorization_id` per R143) — the runner skips exactly
those with the sanctioning requirement as the recorded reason (`SKIP` lines;
the stage-1 folder itself is accepted history and stays unedited).

Latest evidence (branch `tester-stage2`, fix pass after verification): run
against the verified stage-2 implementation — **168 passed, 0 failed, 9
skipped** (the sanctioned deltas above). Session priming follows A28: the
client mirrors the `pocketful_token` cookie contract that the page script
establishes, so pure-HTTP UI checks observe authenticated server-rendered
pages exactly as the harness's DOM driver does.

## Coverage

### Stage-1 (carried by reference)

R1-R93 → the 94 `stage1.*` regression tests (see `specs/stage-1/acceptance/README.md`
for that table).

### Stage 2

| Req | Tests |
|---|---|
| R94 | ui.r94_routes_reachable_by_url, ui.r94_authorizations_reachable_through_ui |
| R95 | ui.r95_requests_content_negotiation |
| R96 | every ui.* test (required testids asserted per element) |
| R97 | ui.r153_wallet_available_held (available-as-headline DOM-order proxy); qualitative whole (A17) = reviewer browser read |
| R98 | concrete sub-rules via R103/R105/R107/R155 format tests; state-distinctness/qualitative (A17, A18) = reviewer browser read |
| R99 | ui.r99_inputs_labeled_everywhere, ui.r99_bundled_assets_no_cdn (viewport meta, no CDN), ui.r99_empty_states_considered_content, ui.r99_navigation_consistent; scroll/focus/contrast at 375px+desktop = reviewer browser check |
| R100 | ui.r100_signup_login_elements, ui.r100_current_user_handle_logout_every_screen (A26) |
| R101 | ui.r101_home_form_elements |
| R102 | authorizations.r129_create_replay_rules (same-key/body resubmit never double-debits — §7); UI resubmit guard = browser harness on the same API rule |
| R103 | ui.r103_formatted_amount_minor_units_0_and_3; amount texts in ui.r101/r105/r107/r153/r155 |
| R104 | hooks in ui.r101/r108/r154/r155 (error elements); client-side zero-request rejection = browser harness; API-side amount rules = r140/r147 case tables |
| R105 | ui.r105_activity_feed |
| R106 | ui.r106_equal_timestamps_either_order (no order asserted) |
| R107 | ui.r107_requests_screen, ui.r107_empty_requests_iff_both_empty |
| R108 | ui.r108_split_elements |
| R109 | server rule = invariants.stage1_r76_rounding_table_unchanged; preview-equality = browser harness (same documented table) |
| R110 | ui.r110_balance_and_feed_show_new_state_after_action, ui.r107 (post-pay status) |
| R111 | ui.r111_wallet_refresh_present (hook + form retention surface); latest-wins = browser harness |
| R112 | hooks (ui.r112_r113_a19_error_hooks_absent_by_default); API refusals = changed_paths.r126_*; UX refresh = browser harness |
| R113 | hooks (A19); retry API rules = authorizations.r129/r142; uncertain UX = browser harness |
| R114 | absence-of-polling is not a defect — no assertion (documented) |
| R115 | upgrade.r115_import_stage1_export, upgrade.r82_r115_login_password_preserved, upgrade.r115_import_v1_defaults_authz_fields |
| R116 | upgrade.r116_pre_import_token_still_authenticated, upgrade.r118_r116_ui_signed_in_and_consistent_after_import |
| R117 | upgrade.r117_pending_request_still_payable |
| R118 | upgrade.r118_lost_response_retry_after_import (real stage-1 export fixture: fixtures/stage1_upgrade.json) |
| R119 | upgrade.r119_import_between_browser_requests (API-visible parts); UI form/retry-identity survival = browser harness |
| R120 | authorizations.r120_r121_hold_reserves_without_moving; capture/expiry tests below |
| R121 | invariants.r121_r122_r123_r157_mixed_concurrent_storm, invariants.r121_r122_concurrent_authorize_vs_spend, authorizations.r120_r121, upgrade.r119 round trip |
| R122 | storm (reader threads assert available≥0 per read), r121_r122_concurrent_authorize_vs_spend, changed_paths.r126_* |
| R123 | storm, invariants.r123_r157_concurrent_capture_oversubscribe, invariants.r3_r52_r157_concurrent_identical_exactly_once_seven_paths (path 7) |
| R124 | authorizations.r124_r138_me_shape_and_holds, changed_paths.r124_no_holds_behavior_unchanged |
| R125 | changed_paths.r125_payments_never_leave_holds |
| R126 | changed_paths.r126_payments/request_pay/settlements_check_available |
| R127 | changed_paths.r127_request_pay_immediate_no_authorize |
| R128 | changed_paths.r128_splits_unchanged_no_balance_check, invariants.stage1_r76_rounding_table_unchanged |
| R129 | authorizations.r129_create_replay_rules, r142_capture_body_equality, invariants.r3_r52_r157...seven_paths (all seven) |
| R130 | authorizations.r130_r135_fixture_accepts_authz_fields, r130_unknown_fixture_fields_ignored |
| R131 | authorizations.r131_ttl_default_600_when_omitted, r131_ttl_from_fixture_applies_to_api_created, r131_ttl_must_be_positive_integer |
| R132 | authorizations.r132_available_derived_never_seeded |
| R133 | authorizations.r133_seeded_holds_above_balance_rejected |
| R134 | authorizations.r134_a22_only_open_holds_anything |
| R135 | authorizations.r130_r135 (omission part) |
| R136 | authorizations.r151_expiry_lazy_reads, r136_r147_capture_on_expired_409_expired, r157_r146_expiry_preserves_partial_capture_records, storm (ttl=2) |
| R137 | bounds the suite's own fixtures (no test; seeded times ≥1h) |
| R138 | authorizations.r124_r138_me_shape_and_holds (exact field set) |
| R139 | authorizations.r139_create_shape_and_defaults, r139_note_visibility_explicit (A27: ttl delta asserted, not the example) |
| R140 | authorizations.r140_case_table, a14_precedence_shape_before_existence_before_self_before_funds |
| R141 | authorizations.r141_authorization_never_in_activity |
| R142 | authorizations.r142_capture_body_equality, r144_capture_without_amount_defaults_to_remaining |
| R143 | authorizations.r142_r143_r144_default_final_capture, r143_authorization_id_null_on_other_paths |
| R144 | authorizations.r142_r143_r144_default_final_capture |
| R145 | authorizations.r145_second_capture_after_final_409 |
| R146 | authorizations.r146_extended_multi_capture, r146_capture_exceeds_compares_remaining, r146_exact_remainder_final_false_closes, r146_void_after_partial_releases_remainder_preserves_records, r157_r146_expiry_preserves_partial_capture_records |
| R147 | authorizations.r147_case_table, r147_a14_permission_before_state, r136_r147_capture_on_expired_409_expired |
| R148 | authorizations.r148_r149_void, void-of-expired in r136_r147 (not_open, not expired) |
| R149 | authorizations.r149_a15_void_permissions_and_ignored_key (A15), list isolation in r150_r151 |
| R150 | authorizations.r150_list_envelope_filters_paging, r150_r151_status_filters_and_lazy_expiry (A21 envelope) |
| R151 | authorizations.r150_r151..., r151_expiry_lazy_reads, ui.r155 (expired data-status) |
| R152 | ui.r152_authorizations_content_negotiation |
| R153 | ui.r153_wallet_available_held (A20) |
| R154 | ui.r154_authorize_form_on_authorizations (A25) |
| R155 | ui.r155_authorization_list_presence_rules, ui.r155_capture_prefill_tracks_remaining |
| R156 | ui.r156_seeded_holds_reflected_immediately |
| R157 | invariants.r121_r122_r123_r157_mixed_concurrent_storm (6×50 mixed ops, readers interleaved, invariants after every wave), r3_r52_r157 (50-way identical bursts, 7 paths), r123_r157_oversubscribe, r121_r122_concurrent_authorize_vs_spend |
| A14 | authorizations.a14_precedence..., r147_a14_permission_before_state |
| A15 | authorizations.r149_a15_void_permissions_and_ignored_key |
| A16 | authorizations.a16_non_object_body_400 (+ capture non-object in r147_case_table) |
| A21 | client.get_authz_list envelope check; upgrade.r119 (v2 export), ui.r152 |
| A22 | authorizations.a22_expired_seed_past_expires_accepted, a22_contradictory_seeds_rejected, r134 (captured/voided defaults) |
| A23 | exact-key-set assertions in authorizations.r139/r142_r143 (no `final` in responses) |
| A24 | authorizations.a24_final_wrong_type_400 |
| A25 | ui.r154 (form on /authorizations), ui.r94 (reachable through UI) |
| A26 | ui.r100_current_user_handle_logout_every_screen |
| A27 | authorizations.r131_ttl_* (normative rule asserted) |

## Browser-only remainder (reviewer/harness, not this suite)

These are specified as in-browser JS behaviours or visual qualities; this suite
asserts their hooks, the API rules beneath them, and everything mechanically
checkable over HTTP+DOM. A real-browser pass must additionally check:

- R97/R98 qualitative qualities and per-state visual distinctness (A17)
- R99 no horizontal scroll / visible focus / AA contrast at 375px and desktop widths
- R102 unchanged-resubmit sends no second payment; R104 client-side rejection with zero requests
- R109 preview shares == submitted shares; R111 latest-refresh-wins under out-of-order responses
- R112 refused payment shows pay-error + refresh + preserved inputs; stale pay button disappears
- R113 lost-response shows pay-uncertain, same-key retry resolves once
- R119 UI pay-form/retry identity survives an import between requests