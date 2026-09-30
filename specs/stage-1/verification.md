# Stage 1 verification — reviewer

Verified revision: `066bb5481f08049ca1ed6b33e5c5c2ae2b96ef43` (main).

## Method

- Fresh clone at the revision above (`/Users/jahnavisrilekhamolleti/Documents/Hackathon/band-work/review-verify`).
- `docker build --no-cache` of `stage-1/`, then `docker run --rm -p 8091:8080 -e PORT=8080` per `stage-1/RUN.md`; healthy (`GET /health` → `200 {"status":"ok"}`) within 2s.
- Shipped checks, isolated mode (no outbound network, via the harness): `python -m harness run --track pocketful --repo .../result --stage 1 --mode isolated --out checks/s1-review-final-1` → `stage 1: pass` (147/147), `stage 2: fail` (overshoot correct), `claimed stage: 1`, `share: 1.0`.
- Tester's acceptance suite (`specs/stage-1/acceptance/`, merged this session from `tester-stage1@066bb54`), re-run by the reviewer against the fresh no-cache build: `94/94 passed, 0 failed`.
- Reviewer's own independent concurrent stress run against the same fresh build: 400 mixed payments/requests/settlements/activity-reads, 50 in-flight threads — zero 5xx, exact conservation (10000/10000 seeded minor units), zero negative balances observed.
- Hygiene: `stage-1/Dockerfile` and `stage-1/RUN.md` present; no nested `.git` or symlinks under `stage-1/`; secret scan across the full repo at this revision clean (one flagged string was a test fixture password, not a credential); no test-input/fixture-id branching found in `stage-1/src/`; no stage-2+ features present (no as-of/historical/refund/multi-currency code).
- Every row below is backed by: the shipped checks (container-level, R6-R13 family), the tester's acceptance suite (HTTP black-box, majority of rows — see `specs/stage-1/acceptance/README.md`'s coverage table, re-verified fresh above), and/or the reviewer's own batch-review black-box probes recorded in `specs/stage-1/probes/batch1-t1-t4.md` and this session's live checks (export/import round-trip, idempotency body-equality, settlement net-affordability, concurrency).

## Requirements

| Req | Status | Evidence |
|---|---|---|
| R1 | pass | Conservation exact under reviewer's 50-thread/400-op stress run (10000/10000); also `test_stress.test_mixed_concurrent_operations_invariants`, `test_splits.test_conservation_after_paying_splits` |
| R2 | pass | Zero negative balances in reviewer's stress run; `test_payments.test_concurrent_same_sender_never_negative` |
| R3 | pass | `test_idempotency.test_concurrent_identical_exactly_once`, `test_requests.test_request_moves_money_at_most_once`; reviewer verified 300/50-thread burst earlier (all 201, no double-spend) |
| R4 | pass | `test_payments.test_self_payment_and_unknown_handle`, `test_payments.test_insufficient_funds_no_trace` |
| R5 | pass | `test_payments.test_amount_integral_numeric_forms`, `test_payments.test_amount_bounds_and_types` |
| R6 | pass | shipped checks (container build/run); `stage-1/Dockerfile` reviewed, no external deps |
| R7 | pass | shipped checks; single container, no orchestration required |
| R8 | pass | shipped checks + reviewer's own `docker run -e PORT=8080` |
| R9 | pass | `docker build --no-cache` succeeded with no runtime network; reviewer confirmed offline `docker run` |
| R10 | pass | client.py enforces 5s/10s timeouts; no violations observed |
| R11 | pass | reviewer's isolated-mode run (no outbound network) passed |
| R12 | pass | reviewer confirmed `0.0.0.0:$PORT` binding via mapped port 8091 |
| R13 | pass | `test_health_reset.test_health_exact_body`; reviewer confirmed `{"status":"ok"}` exactly |
| R14 | pass | `test_health_reset.test_reset_replaces_all_state`, `test_reset_repeated` |
| R15 | pass | `test_health_reset.test_reset_negative_balance_422_state_unchanged`; reviewer probe in batch-1 review |
| R16 | pass | `test_health_reset.test_unknown_request_fields_and_query_params_ignored`, `test_timestamps_rfc3339_with_offset` |
| R17 | pass | `test_health_reset.test_reset_minor_units_domain` |
| R18 | pass | `test_payments.test_amount_integral_numeric_forms`, `test_idempotency.test_canonical_body_equality` |
| R19 | pass | `test_auth.test_derived_handle_rule` |
| R20 | pass | `test_auth.test_derived_handle_rule`, `test_derived_handle_collision`; reviewer probe in batch-2 review |
| R21 | pass | `test_auth.test_new_user_zero_balance_and_receivable` |
| R22 | pass | `test_requests.test_pay_happy_and_payer_choice`, `test_payments.test_payment_happy_shape` |
| R23 | pass | `test_requests.test_decline_lifecycle`, `test_cancel_lifecycle` |
| R24 | pass | `test_requests.test_request_creation_ignores_payer_balance`, `test_pay_error_table` |
| R25 | pass | `test_requests.test_pay_happy_and_payer_choice`, `test_feed.test_requests_never_in_feed` |
| R26 | pass | `test_feed.test_feed_iff_rule` |
| R27 | pass | `test_feed.test_requests_never_in_feed` |
| R28 | pass | `test_feed.test_split_not_a_feed_item` |
| R29 | pass | `test_feed.test_private_hidden_from_third_party_not_receiver` |
| R30 | pass | `test_payments.test_amount_bounds_and_types` |
| R31 | pass | `test_health_reset.test_seeded_users_login_and_balances_verbatim` |
| R32 | pass | `test_health_reset.test_seeded_users_login_and_balances_verbatim` |
| R33 | pass | `test_health_reset.test_seeded_users_login_and_balances_verbatim`; reviewer probe in batch-1 review |
| R34 | pass | `test_health_reset.test_reset_minor_units_domain` |
| R35 | pass | every `expect_error()` call in the acceptance suite asserts this shape |
| R36 | pass | covered across R40/R44/R57/R61/R65/R67/R68/R70/R73/R80/R88 rows |
| R37 | pass | `test_auth.test_signup_error_table`, `test_payments.test_amount_bounds_and_types` |
| R38 | pass | `test_payments.test_amount_bounds_and_types`, `test_note_and_visibility_rules` |
| R39 | pass | `test_requests.test_requests_listing_validation`, `test_feed.test_activity_validation` |
| R40 | pass | `test_payments.test_amount_bounds_and_types`, `test_idempotency.test_non_object_body_400_before_auth_and_key` |
| R41 | pass | `test_idempotency.test_key_length_bounds`, `test_requests.test_requests_listing_validation` |
| R42 | pass | `test_stress.test_no_5xx_under_concurrent_burst`; reviewer's own 400-op stress run, zero 5xx |
| R43 | pass | `test_auth.test_signup_login_shapes` |
| R44 | pass | `test_auth.test_signup_error_table`, `test_derived_handle_collision` |
| R45 | pass | `test_auth.test_missing_or_bad_token_401` |
| R46 | pass | `test_auth.test_multiple_tokens_concurrent_sessions` |
| R47 | pass | `test_auth.test_passwords_not_stored_plaintext` (black-box via export) |
| R48 | pass | `test_idempotency.test_missing_and_empty_key_on_every_write_path` |
| R49 | pass | `test_idempotency.test_key_scoped_per_user` |
| R50 | pass | `test_idempotency.test_canonical_body_equality`, `test_same_key_same_body_other_path_is_first_use` |
| R51 | pass | `test_idempotency.test_first_use_201_replay_200_diff_body_409`, `test_key_reusable_after_4xx_failure` |
| R52 | pass | `test_idempotency.test_concurrent_identical_exactly_once` |
| R53 | pass | `test_idempotency.test_replay_after_balance_change`, `test_requests.test_pay_replay_after_paid` |
| R54 | pass | `test_idempotency.test_claimed_key_resolved_before_field_validation` |
| R55 | pass | `get_me` shape asserted throughout; reviewer probe in batch-2 review confirmed exact shape live |
| R56 | pass | `test_payments.test_payment_happy_shape`, `test_payment_defaults` |
| R57 | pass | `test_payments.test_amount_bounds_and_types`, `test_self_payment_and_unknown_handle`, `test_insufficient_funds_no_trace` |
| R58 | pass | `test_payments.test_concurrent_same_sender_never_negative`, `test_insufficient_funds_no_trace` |
| R59 | pass | `test_payments.test_note_verbatim_unicode`; reviewer's own emoji round-trip probe in batch-3 review |
| R60 | pass | `test_requests.test_request_create_shape_and_defaults` |
| R61 | pass | `test_requests.test_request_error_table` |
| R62 | pass | `test_requests.test_request_creation_ignores_payer_balance` |
| R63 | pass | `test_requests.test_pay_body_equality_strict`; reviewer's own `{}` vs `{"visibility":"public"}` probe in batch-3 review |
| R64 | pass | `test_requests.test_pay_happy_and_payer_choice` |
| R65 | pass | `test_requests.test_pay_error_table` |
| R66 | pass | `test_requests.test_pay_replay_after_paid`; reviewer's own replay-after-paid probe (balance held at 940 across 3 calls) |
| R67 | pass | `test_requests.test_decline_lifecycle` |
| R68 | pass | `test_requests.test_cancel_lifecycle` |
| R69 | pass | `test_requests.test_requests_listing_and_filters` |
| R70 | pass | `test_requests.test_requests_listing_validation` |
| R71 | pass | `test_splits.test_split_shape_and_request_creation`, `test_split_caller_omitted` |
| R72 | pass | `test_splits.test_split_shape_and_request_creation` |
| R73 | pass | `test_splits.test_split_error_table` |
| R74 | pass | `test_splits.test_split_caller_only_valid`, `test_split_no_balance_checks` |
| R75 | pass | `test_feed.test_feed_order_and_paging`, `test_activity_validation` |
| R76 | pass | `test_splits.test_rounding_table_exact` (all 5 rows); reviewer independently verified `compute_shares` divmod logic against the table in batch-4 review |
| R77 | pass | `test_splits.test_split_order_dependence`, `test_split_shares_independent`, `test_conservation_after_paying_splits` |
| R78 | pass | `test_export_import.test_export_unauthenticated_shape`, `test_round_trip_is_a_noop` |
| R79 | pass | `test_export_import.test_round_trip_is_a_noop`, `test_import_replacement_not_merge` |
| R80 | pass | `test_export_import.test_import_errors_leave_destination_unchanged`; reviewer probed wrong track/version/non-object/missing-state in batch-5 review |
| R81 | pass | `test_export_import.test_export_is_atomic_read_only_snapshot`; reviewer's own export-then-mutate-then-compare probe in batch-5 review |
| R82 | pass | `test_export_import.test_import_preserves_tokens_login_replays_and_failed_keys`; reviewer's own live round-trip (old token, old password, completed-key replay, zero extra money) in batch-5 review |
| R83 | pass | `test_export_import.test_import_replacement_not_merge`; reviewer confirmed reset-then-import restores exactly, no merge artifacts |
| R84 | pass | `test_export_import.test_reset_clears_imported_state` |
| R85 | pass | no persistence dependency anywhere in the source or suite (in-memory `State` only) |
| R86 | pass | `test_settlements.test_operator_permissions`, `test_settlement_operator_id_in_fixture_default` |
| R87 | pass | `test_settlements.test_settlement_happy_shape`, `test_transfers_bounds_and_shape` |
| R88 | pass | `test_settlements.test_entry_rules_and_defaults`, `test_entry_errors_precede_affordability_in_input_order` |
| R89 | pass | `test_settlements.test_net_affordability_not_sequential`; reviewer's own net-unaffordable-batch probe in batch-4 review |
| R90 | pass | `test_settlements.test_insufficient_collective_all_or_nothing`; reviewer verified both balances unchanged after a rejected settlement, then a fresh 201 on key reuse |
| R91 | pass | `test_settlements.test_settlement_happy_shape` |
| R92 | pass | `test_settlements.test_settlement_feed_visibility`, `test_settlement_replay` |
| R93 | pass | `test_export_import.test_import_preserves_settlement_membership` |
| A1/A2 | pass | fixed per-endpoint validation order verified by reviewer code-read against `design.md` §10 in batch-3/4 reviews; no ordering-dependent test failures |
| A3 | pass | `test_feed.test_feed_order_and_paging` crosses a second boundary without asserting same-second order |
| A4 | pass | in-memory `State` only, no disk/db dependency in `stage-1/src` |
| A5 | pass | `test_health_reset.test_reset_minor_units_domain` |
| A6 | pass | `test_requests.test_supplied_key_on_decline_cancel_ignored`; reviewer confirmed decline/cancel routes carry no `idem=True` |
| A7 | pass | `test_auth.test_signup_error_table` |
| A8 | pass | `test_idempotency.test_non_object_body_400_before_auth_and_key`; reviewer's own array/null-body probes in batch-1 review |
| A9 | pass | `test_settlements.test_transfers_bounds_and_shape` |
| A10 | pass | `test_auth.test_signup_error_table` |
| A11 | pass | `test_auth.test_email_case_sensitivity_login`; reviewer's own `A@x.com`-collides-on-handle probe in batch-2 review |
| A12 | pass | all fixtures in the suite and reviewer's probes seed `pending` only; no contrary case found |
| A13 | pass | `test_health_reset.test_reset_currency_validation`; reviewer's own missing-currency probe in batch-1 review |

## Overall

**Stage 1: PASS.** All 93 requirements and 13 assumptions have passing evidence. Shipped checks
147/147 (isolated mode, `claimed stage: 1`, stage-2 overshoot correctly `fail`). Tester's acceptance
suite 94/94 against a fresh no-cache build. Reviewer's independent 50-thread/400-operation mixed
stress run: zero 5xx, exact conservation, zero negative balances. Hygiene clean (build file, run
doc, no nested repo/links, no secrets, no test-input branching, no stage-2+ leakage).
