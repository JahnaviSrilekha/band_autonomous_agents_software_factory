# Stage 1 acceptance suite (black-box, HTTP-only)

Drives a running pocketful stage-1 container over HTTP only. Derived from the
stage-1 source spec and `specs/stage-1/requirements.md` — never from the
implementation or the shipped harness checks.

## Run

```sh
python3 specs/stage-1/acceptance/run.py http://127.0.0.1:8080
```

`BASE_URL` defaults to `$BASE_URL` or `http://127.0.0.1:8080`. One command, no
dependencies (Python 3 stdlib only). Every test resets the service via
`POST /_test/reset` first, so the suite is repeatable and order-independent.
`python3 run.py --list` prints all test names.

Per-request timeouts follow R10: 5 s, 10 s for `/_test/*` endpoints, so
violations surface as failures.

## Coverage table

| Req | Requirement | Tests |
|---|---|---|
| R1 | Balance conservation | test_payments.test_concurrent_same_sender_never_negative, test_splits.test_conservation_after_paying_splits, test_stress.test_mixed_concurrent_operations_invariants |
| R2 | No negative balance | test_payments.test_concurrent_same_sender_never_negative, test_stress.test_mixed_concurrent_operations_invariants |
| R3 | Money moves at most once per request | test_idempotency.test_concurrent_identical_exactly_once, test_requests.test_request_moves_money_at_most_once, test_stress.test_mixed_concurrent_operations_invariants |
| R4 | Money only between existing wallets | test_payments.test_self_payment_and_unknown_handle, test_payments.test_insufficient_funds_no_trace, test_stress (conservation) |
| R5 | Exact integer minor units | test_payments.test_amount_integral_numeric_forms, test_payments.test_amount_bounds_and_types |
| R6-R11 | Dockerfile/RUN.md, containerized delivery, resource limits | verified at container level by the stage harness (docker build/run, network isolation, 50-in-flight, 60 s healthy); not observable over HTTP alone |
| R12 | Listen on 0.0.0.0:$PORT | verified at container level (harness maps $PORT); suite targets the mapped address |
| R13 | /health 200 {"status":"ok"} | test_health_reset.test_health_exact_body, test_health_reset.test_health_needs_no_auth |
| R14 | Reset replaces state, repeatable, unauthenticated | test_health_reset.test_reset_replaces_all_state, test_health_reset.test_reset_repeated, test_health_reset.test_reset_unauthenticated_and_id_shapes |
| R15 | Negative fixture balance → 422, no change | test_health_reset.test_reset_negative_balance_422_state_unchanged |
| R16 | JSON/charset, RFC3339+offset, unknown fields/params ignored, opaque ids | test_health_reset.test_unknown_request_fields_and_query_params_ignored, test_health_reset.test_timestamps_rfc3339_with_offset, test_requests (feed shapes) |
| R17 | One currency, minor_units echo | test_health_reset.test_reset_minor_units_domain |
| R18 | Integral numeric amounts (1000/1000.0/1e3) | test_payments.test_amount_integral_numeric_forms, test_idempotency.test_canonical_body_equality |
| R19 | Handle uniqueness/regex/immutable | test_auth.test_derived_handle_rule, test_payments.test_self_payment_and_unknown_handle |
| R20 | Derived handle rule + collision | test_auth.test_derived_handle_rule, test_auth.test_derived_handle_collision |
| R21 | New user balance 0, immediately usable | test_auth.test_new_user_zero_balance_and_receivable |
| R22 | Payment atomic, direct or via request | test_requests.test_pay_happy_and_payer_choice, test_payments.test_payment_happy_shape |
| R23 | Request state machine, party permissions | test_requests.test_decline_lifecycle, test_requests.test_cancel_lifecycle |
| R24 | Request may exceed balance; pay-time 409; payable later | test_requests.test_request_creation_ignores_payer_balance, test_requests.test_pay_error_table |
| R25 | Visibility on payment, chosen by payer | test_requests.test_pay_happy_and_payer_choice, test_feed.test_requests_never_in_feed |
| R26 | Feed iff-rule | test_feed.test_feed_iff_rule |
| R27 | Requests never in feed; /requests two-party only | test_feed.test_requests_never_in_feed, test_requests.test_requests_listing_and_filters |
| R28 | Split not a feed item | test_feed.test_split_not_a_feed_item |
| R29 | Private hidden from third, seen by both parties | test_feed.test_private_hidden_from_third_party_not_receiver, test_feed.test_visibility_identical_to_both_parties |
| R30 | amount ≤ 1e9; ±2⁵³ exact | test_payments.test_amount_bounds_and_types |
| R31 | Fixture shape | test_health_reset.test_seeded_users_login_and_balances_verbatim |
| R32 | Seeded users log in immediately | test_health_reset.test_seeded_users_login_and_balances_verbatim |
| R33 | Balances post-seeded-payment, no replay | test_health_reset.test_seeded_users_login_and_balances_verbatim |
| R34 | minor_units ∈ {0,2,3} | test_health_reset.test_reset_minor_units_domain |
| R35 | Error body shape | every expect_error() call in all modules |
| R36 | Status/code table | R36 cases across modules (see R40, R44, R57, R61, R65, R67, R68, R70, R73, R80, R88 rows) |
| R37 | Correct type, invalid value → 422 | test_auth.test_signup_error_table, test_payments.test_amount_bounds_and_types |
| R38 | Endpoint-specific 422 overrides (amount/note/visibility) | test_payments.test_amount_bounds_and_types, test_payments.test_note_and_visibility_rules |
| R39 | Query params plain decimal digits | test_requests.test_requests_listing_validation, test_feed.test_activity_validation |
| R40 | 400 reserved for parse/wrong-type | test_payments.test_amount_bounds_and_types, test_requests.test_request_error_table, test_idempotency.test_non_object_body_400_before_auth_and_key |
| R41 | Key 1-255, limit 1-200, offset ≥ 0 | test_idempotency.test_key_length_bounds, test_requests.test_requests_listing_validation, test_feed.test_activity_validation |
| R42 | No 5xx under load | test_stress.test_no_5xx_under_concurrent_burst, test_stress.test_mixed_concurrent_operations_invariants |
| R43 | Signup/login shapes | test_auth.test_signup_login_shapes |
| R44 | Signup/login error table | test_auth.test_signup_error_table, test_auth.test_derived_handle_collision |
| R45 | Bearer required elsewhere | test_auth.test_missing_or_bad_token_401 |
| R46 | Tokens don't expire; multi-session | test_auth.test_multiple_tokens_concurrent_sessions |
| R47 | Passwords hashed (black-box via export) | test_auth.test_passwords_not_stored_plaintext |
| R48 | Five idempotent write paths | test_idempotency.test_missing_and_empty_key_on_every_write_path |
| R49 | Key scoped to user | test_idempotency.test_key_scoped_per_user |
| R50 | Replay definition, cross-path, canonical JSON | test_idempotency.test_canonical_body_equality, test_idempotency.test_same_key_same_body_other_path_is_first_use |
| R51 | Idempotency situation table | test_idempotency.test_first_use_201_replay_200_diff_body_409, test_idempotency.test_key_reusable_after_4xx_failure |
| R52 | Concurrent identical: one 201, rest 200, once | test_idempotency.test_concurrent_identical_exactly_once, test_idempotency.test_concurrent_same_key_different_body |
| R53 | Replay after change, no mutation | test_idempotency.test_replay_after_balance_change, test_requests.test_pay_replay_after_paid |
| R54 | Key resolved before validation (order) | test_idempotency.test_claimed_key_resolved_before_field_validation, test_idempotency.test_auth_precedes_key_resolution |
| R55 | GET /me shape | test_health_reset.test_reset_replaces_all_state (via get_me throughout) |
| R56 | POST /payments shape/defaults incl. settlement_id null | test_payments.test_payment_happy_shape, test_payments.test_payment_defaults |
| R57 | /payments error table | test_payments.test_amount_bounds_and_types, test_payments.test_self_payment_and_unknown_handle, test_payments.test_insufficient_funds_no_trace, test_payments.test_note_and_visibility_rules |
| R58 | Atomic debit+credit, no trace on failure | test_payments.test_concurrent_same_sender_never_negative, test_payments.test_insufficient_funds_no_trace |
| R59 | Note verbatim, unicode byte-for-byte | test_payments.test_note_verbatim_unicode |
| R60 | POST /requests shape/defaults | test_requests.test_request_create_shape_and_defaults |
| R61 | /requests error table | test_requests.test_request_error_table |
| R62 | No balance check at request creation | test_requests.test_request_creation_ignores_payer_balance |
| R63 | Pay body visibility-only; strict replay equality | test_requests.test_pay_body_equality_strict, test_requests.test_pay_happy_and_payer_choice |
| R64 | Pay returns payment with request_id; request paid | test_requests.test_pay_happy_and_payer_choice |
| R65 | Pay error table | test_requests.test_pay_error_table |
| R66 | Pay replay after paid | test_requests.test_pay_replay_after_paid |
| R67 | Decline semantics | test_requests.test_decline_lifecycle |
| R68 | Cancel semantics | test_requests.test_cancel_lifecycle |
| R69 | /requests filters, paging, has_more | test_requests.test_requests_listing_and_filters |
| R70 | /requests validation | test_requests.test_requests_listing_validation |
| R71 | Split creates per-participant requests | test_splits.test_split_shape_and_request_creation, test_splits.test_split_caller_omitted |
| R72 | Split 201 shape, shares order/sum | test_splits.test_split_shape_and_request_creation |
| R73 | Split error table | test_splits.test_split_error_table |
| R74 | Caller-only split valid; no balance checks | test_splits.test_split_caller_only_valid, test_splits.test_split_no_balance_checks |
| R75 | /activity paging/has_more, newest first | test_feed.test_feed_order_and_paging, test_feed.test_activity_validation |
| R76 | Rounding table (all 5 rows), 0-share request | test_splits.test_rounding_table_exact, test_splits.test_zero_share_still_creates_request |
| R77 | Order dependence; independence; conservation after splits | test_splits.test_split_order_dependence, test_splits.test_split_shares_independent, test_splits.test_conservation_after_paying_splits |
| R78 | Export shape, import accepts unchanged | test_export_import.test_export_unauthenticated_shape, test_export_import.test_round_trip_is_a_noop |
| R79 | Import atomic replacement, repeat, 204 | test_export_import.test_round_trip_is_a_noop, test_export_import.test_import_replacement_not_merge |
| R80 | Import errors (400/422), no change | test_export_import.test_import_errors_leave_destination_unchanged |
| R81 | Export atomic read-only snapshot | test_export_import.test_export_is_atomic_read_only_snapshot |
| R82 | Preserve tokens/login/replays/failed keys | test_export_import.test_import_preserves_tokens_login_replays_and_failed_keys |
| R83 | Import removes destination data | test_export_import.test_import_replacement_not_merge |
| R84 | Reset clears imported state | test_export_import.test_reset_clears_imported_state |
| R85 | Ephemeral state acceptable | container-level concern; no persistence asserted or required by the suite |
| R86 | Operator permission scope | test_settlements.test_operator_permissions, test_settlements.test_settlement_operator_id_in_fixture_default |
| R87 | Settlements body, 1..32, defaults | test_settlements.test_settlement_happy_shape, test_settlements.test_transfers_bounds_and_shape |
| R88 | Settlement error table, entry precedence | test_settlements.test_entry_rules_and_defaults, test_settlements.test_entry_errors_precede_affordability_in_input_order, test_settlements.test_transfers_bounds_and_shape |
| R89 | Net affordability | test_settlements.test_net_affordability_not_sequential, test_settlements.test_insufficient_collective_all_or_nothing |
| R90 | All-or-nothing, failed attempt frees key | test_settlements.test_insufficient_collective_all_or_nothing |
| R91 | Settlement 201 shape/linkage | test_settlements.test_settlement_happy_shape |
| R92 | Constituents' feed visibility; replay | test_settlements.test_settlement_feed_visibility, test_settlements.test_settlement_replay |
| R93 | Reset/import preserve settlements | test_export_import.test_import_preserves_settlement_membership, test_export_import.test_import_preserves_tokens_login_replays_and_failed_keys |
| A1/A2 | Documented validation order | respected by tests; only unambiguous combinations asserted |
| A3 | Same-second order unconstrained | test_feed.test_feed_order_and_paging crosses a second boundary |
| A4 | In-memory state | no persistence dependency in the suite |
| A5 | minor_units out of set → 422 | test_health_reset.test_reset_minor_units_domain |
| A6 | Key ignored on decline/cancel | test_requests.test_supplied_key_on_decline_cancel_ignored |
| A7 | Signup validation order | test_auth.test_signup_error_table (each case asserted independently) |
| A8 | Non-object body → 400 before auth/key | test_idempotency.test_non_object_body_400_before_auth_and_key |
| A9 | Settlement wrong-type → 422 | test_settlements.test_transfers_bounds_and_shape |
| A10 | Signup required fields/type rules | test_auth.test_signup_error_table (missing/type cases via R36/R40) |
| A11 | Email case-sensitive | test_auth.test_email_case_sensitivity_login, test_auth.test_signup_error_table |
| A12 | Seed pending requests only | all fixtures seed pending only |
| A13 | currency missing/non-string → 422 | test_health_reset.test_reset_currency_validation |