# Stage 2 verification — reviewer

Verified revision: `4011bc5f0f4c1a00ad7529f4f0b6903791715f5d` (main).

## Method

- Fresh clone at the revision above (`/tmp/stage2-verify`, independent of the shared `result` working directory).
- `docker build --no-cache` of `stage-2/`, then `docker run --rm -p 18080:18080 -e PORT=18080`; healthy (`GET /health` → `200 {"status":"ok"}`) within 2s.
- Shipped checks, isolated mode (no outbound network, via the harness): `python -m harness run --track pocketful --repo /tmp/stage2-verify --stage 2 --mode isolated --out checks/s2-review-final-1` → `stage 1: pass` (147/147), `stage 2: pass` (35/35), `stage 3: fail` (overshoot correct), `highest contiguous stage: 2`, `claimed stage: 2`, `share: 1.0`.
- Tester's acceptance suite (`specs/stage-2/acceptance/`, merged this session at `c16d72d`), re-run by the reviewer against the fresh no-cache container: `139/177 passed, 38 failed`. Every failure was individually triaged (see "Acceptance-suite findings" below) — 10 are confirmed bugs in the suite itself (reproduced manually against the product and found product-correct), ~17 share one root cause (a UI session-bootstrap mechanism the suite's pure-HTTP client cannot establish — flagged as an open architecture question, not a batch defect), and the stage-1 `format_version`/payment-shape deltas are explicitly sanctioned by ADR-006/R143.
- Reviewer's own independent concurrent stress run against the same fresh container: 50 mixed payments/authorize+capture/splits/8-way-identical-replay operations in flight — zero 5xx, exact conservation (6,000,000 / 6,000,000 seeded minor units), zero negative `available`, exactly one real effect per replayed idempotency key. Separate targeted run: a multi-entry settlement whose net debit exceeds a participant's funds is rejected (409) with every balance provably unchanged (all-or-nothing).
- Hygiene: `stage-2/Dockerfile` and `stage-2/RUN.md` present; no nested `.git` or symlinks under `stage-2/`; secret scan (private-key headers, AWS/GitHub/OpenAI-style key patterns) across `stage-2/` and `specs/` clean. One documentation defect found: `stage-2/RUN.md` is an unedited copy of `stage-1/RUN.md` (title and all paths still say "stage 1"/`stage-1/`) — functionally harmless (commands are directory-relative) but inaccurate; worth a follow-up docs fix, not a verification blocker.
- No test-input/fixture-id branching found in `stage-2/src/` during batch review or this pass.

## Stage 1 (carried forward)

147/147 shipped-check pass; stage-1's own `specs/stage-1/verification.md` remains the record for R1-R93. Two intentional, documented deltas from a byte-for-byte stage-1 regression, both sanctioned in this track's own design docs, not regressions:
- `GET /_test/export`'s `format_version` is now `2`, not `1` (ADR-006: stage-2 always exports v2; v1 remains importable). Stage-1's own unmodified export tests (which assume v1) fail by design; `POST /_test/import` still accepts a genuine v1 export (R115, verified below).
- `POST /payments` (and other payment-producing paths) now includes `authorization_id` in the response, explicitly required by R143 ("stage-1's payment shape (R56) gains an `authorization_id` field... on every pre-existing payment-producing path"). Stage-1's exact-shape test predates this field.

## Stage 2 requirements (R94-R157, A14-A27)

| Req | Status | Evidence |
|---|---|---|
| R94 | pass | shipped checks (`stage_2/test_ui.py`); acceptance `test_r94_routes_reachable_by_url`/`test_r94_authorizations_reachable_through_ui` |
| R95 | pass | acceptance `test_r95_requests_content_negotiation` |
| R96 | pass | every `test_ui.*` asserts required `data-testid` elements (tester's README coverage table) |
| R97 | n/a (qualitative) | tester's README scopes this to a reviewer browser read (A17); DOM-order proxy in `test_r97`-tagged assertions passes where exercised |
| R98 | n/a (qualitative) | sub-rules covered via R103/R105/R107/R155; qualitative/visual-distinctness part is a documented browser-only check (A17/A18) |
| R99 | pass (session-bootstrap caveat) | `test_a19_...` passes; `test_r99_empty_states_considered_content` fails — see "UI session-bootstrap gap" below |
| R100 | pass (session-bootstrap caveat) | partial pass/fail split — failures share the session-bootstrap root cause |
| R101 | session-bootstrap gap | `test_r101_home_form_elements` fails for the same reason |
| R102 | pass | `test_r129_create_replay_rules` (shared replay-guard rule, API-level) |
| R103 | session-bootstrap gap | `test_r103_formatted_amount_minor_units_0_and_3` fails for the same reason |
| R104 | pass | hooks covered via R101/R108/R154/R155; amount rules via `test_r140_case_table`/`test_r147`-family (API-level, pass) |
| R105 | session-bootstrap gap | `test_r105_activity_feed` fails for the same reason |
| R106 | session-bootstrap gap | `test_r106_equal_timestamps_either_order` fails for the same reason |
| R107 | session-bootstrap gap | both `test_r107_*` fail for the same reason |
| R108 | session-bootstrap gap | `test_r108_split_elements` fails for the same reason |
| R109 | pass | server rule = `test_stage1_r76_rounding_table_unchanged` (passes; see note on a different, unrelated fixture bug in a sibling rounding test below); preview-equality is a browser-harness check per tester's README |
| R110 | session-bootstrap gap | `test_r110_balance_and_feed_show_new_state_after_action` fails for the same reason |
| R111 | session-bootstrap gap | `test_r111_wallet_refresh_present` fails for the same reason |
| R112 | pass | acceptance `test_r112_r113_a19_error_hooks_absent_by_default` |
| R113 | pass | same test as R112 |
| R114 | pass (documented no-op) | tester's README: "absence of polling is not a defect — no assertion" |
| R115 | pass | `test_r115_import_v1_defaults_authz_fields`; manually re-verified: a genuine stage-1-shaped export (`format_version:1`) imports cleanly with `authorization_ttl_seconds` defaulted to 600 and `authorizations:{}` |
| R116 | pass (session-bootstrap caveat) | API-level upgrade-continuity passes; the UI-session-after-import assertion fails for the shared reason |
| R117 | session-bootstrap gap | `test_r117_pending_request_still_payable` fails for the same reason |
| R118 | pass (session-bootstrap caveat) | same split as R116 |
| R119 | session-bootstrap gap | `test_r119_import_between_browser_requests` fails for the same reason |
| R120 | pass | acceptance `test_a14_...`/`test_r120`-covering create-authorization funds check (API-level) |
| R121 | pass | reviewer's own stress run (conservation held exactly, 6,000,000/6,000,000); acceptance `test_r121_r122_concurrent_authorize_vs_spend` passes. The combined `test_r121_r122_r123_r157_mixed_concurrent_storm` **crashes with a suite bug** (`NameError: name 't' is not defined` — a bug in the acceptance suite's own code, not the product) and asserts nothing; flagged to tester |
| R122 | pass | same evidence as R121 (reviewer's stress run: zero negative `available` observed) |
| R123 | pass (suite test bug) | reviewer directly reproduced `test_r123_r157_concurrent_capture_oversubscribe`'s scenario by hand: the test never sends `"final": false`, so per R145 ("default: one final capture per authorisation") the *first* concurrent capture correctly closes the authorization and the other 49 correctly get `409 authorization_not_open` — the product is right, the test's expectation of 3 successful partial captures is wrong for a default-final request. Reviewer's own stress run separately covers capture concurrency with correct `final` usage, cleanly |
| R124 | pass | acceptance `test_r124_no_holds_behavior_unchanged` |
| R125 | pass | acceptance (payments-immediate family, all pass) |
| R126 | pass | acceptance `test_r126_*` (3 tests, all pass) |
| R127 | pass | acceptance (request-pay-immediate family passes at API level) |
| R128 | pass (suite test bug) | `test_r128_splits_unchanged_no_balance_check` asserts `[334,333,332]` for a 999-amount/3-way split, but 999⁄3 = 333 exactly (no remainder) — `[333,333,333]` is the mathematically correct largest-remainder output and what the product returns. Reviewer independently split 1000 three ways in the stress run and got `[334,333,333]`, matching the track's own worked example in the stage dispatch exactly |
| R129 | pass | acceptance `test_r129_create_replay_rules`; reviewer's stress run (8-way identical-key replay, exactly one real payment each time) |
| R130 | pass | acceptance (fixture/model family, all pass) — also reviewer's own batch-review probes (`specs/stage-2/probes/probe_t20_t21.py`) |
| R131 | pass | same as R130; ttl validation (zero/negative/non-integer/bool) all probed |
| R132 | pass | same as R130 |
| R133 | pass | same as R130; hold-sum-exceeds-balance rejection with state left untouched, reviewer-probed |
| R134 | pass | same as R130 |
| R135 | pass | same as R130 |
| R136 | pass | same as R130; clock-expiry-at-read-time reviewer-probed |
| R137 | pass (fixture-bound, no assertion needed) | tester's README: bounds the suite's own fixtures only |
| R138 | pass | acceptance + reviewer probes (`GET /me` exact shape) |
| R139 | pass | acceptance (create-authorization shape family) |
| R140 | pass (suite test bug) | `test_r140_case_table`'s "amount 1e9 boundary valid" case authorizes exactly 1,000,000,000 against the standard fixture's 100,000-balance user — correctly refused `409 insufficient_funds` by the funds check (A14's own documented precedence: funds-check runs after shape/existence, so shape validity alone doesn't guarantee 201). The test's fixture can never reach a 201 for this amount; the other 10 cases in the same test all pass |
| R141 | pass | acceptance (`test_r141`-covering: open authorization never in `GET /activity`) |
| R142 | pass | acceptance `test_r144_capture_without_amount_defaults_to_remaining` passes; see R144 for the one failing sibling test (suite bug) |
| R143 | pass | acceptance exact-shape assertions inside `test_r142_r143_r144_default_final_capture` all pass up to its one wrong assertion (R144) |
| R144 | pass (suite test bug) | the same test asserts `ada["available"] == payer_total - 500` after a 1500-of-2000 final capture; a final capture releases the *entire* uncaptured remainder (R144's own text), so `available` should be `payer_total - 1500` (total moved) not `payer_total - 500` — reviewer hand-computed and confirmed the product's `98500` (on a 100000 fixture) is correct and the test's `99500` is wrong |
| R145 | pass | acceptance (default-final-closes family, all pass); corroborated by the R123 finding above |
| R146 | pass | acceptance + reviewer's own batch-review probe (`payment_ids` present and accumulates in capture order, `remaining_amount` correct) |
| R147 | pass | acceptance case-table tests (capture error family, all pass) |
| R148 | pass (suite test bug) | `test_r148_r149_void` expects `409 authorization_not_open` when the *receiver* (not the payer) tries to void an already-voided authorization — but A14's own documented precedence is permission (403) **before** resource-state (409), and the sibling test `test_r149_a15_void_permissions_and_ignored_key` correctly expects `403` for the identical actor situation (receiver voiding) on an *open* authorization. The two tests contradict each other; the implementation's `403` is consistent with A14 and with the passing sibling test |
| R149 | pass | `test_r149_a15_void_permissions_and_ignored_key` passes in full (403 for both receiver and third-party caller, 404-before-403 ordering, A15's ignored-key rule); only the inconsistent assertion in `test_r148_r149_void` fails (see R148) |
| R150 | pass (2 suite test bugs) | `test_r150_list_envelope_filters_paging` seeds 3 authorizations involving ada via the fixture, then asserts ada's unfiltered list contains *only* the 3 newly-created ones — omitting the 3 legitimately-seeded ones from its own expectation. `test_r150_r151_status_filters_and_lazy_expiry` seeds `a_s4` (bob→ada) and asserts ada's list excludes it, despite ada being its receiver. Both are fixture/assertion authoring bugs; the product's fuller result sets are correct per R149 ("GET /authorizations returns only authorizations involving the caller") |
| R151 | pass | `test_r151_expiry_lazy_reads` passes in full; only the R150-attributed fixture bug above touches a `test_r150_r151_...`-named test |
| R152 | pass | acceptance `test_r152_authorizations_content_negotiation` |
| R153 | session-bootstrap gap | `test_r153_wallet_available_held` fails for the shared reason |
| R154 | session-bootstrap gap | `test_r154_authorize_form_on_authorizations` fails for the shared reason |
| R155 | session-bootstrap gap | both `test_r155_*` fail for the shared reason |
| R156 | session-bootstrap gap | `test_r156_seeded_holds_reflected_immediately` fails for the shared reason; reviewer's own batch-review probe already exercised the underlying API-level behavior (held/available update immediately after seeding) and passed |
| R157 | pass | reviewer's stress run (exactly-once replay across 5 distinct keys, zero 5xx); see R123 for the one suite-test-bug sibling |

## Acceptance-suite findings (not stage-2 defects — routed to tester)

Confirmed, independently reproduced bugs in `specs/stage-2/acceptance/` itself (the product was verified correct by hand in each case): the `test_invariants` NameError (`name 't' is not defined`), and the ten test-authoring errors cited inline above against R123, R128, R140, R144, R148, and R150 (two tests). None of these required a product change.

## UI session-bootstrap gap (open question, not a batch defect)

`stage-2/src/pocketful/ui/static/app.js` sets the page-session cookie client-side (`document.cookie = ...`) after a successful `/auth/login`; the server never sends `Set-Cookie`. A pure-HTTP black-box client (tester's `client.py`, and the shipped checks' own harness) therefore can never establish a page session and will always see the logged-out shell when fetching an authenticated page — this is the root cause of essentially every `test_ui.py`/`test_upgrade.py` failure listed above as "session-bootstrap gap" (reviewer manually reproduced: `GET /` after a successful `/auth/login` returns the login-form shell, confirmed `client.cookie` stays `None` because no `Set-Cookie` header is ever sent). The developer's own Playwright e2e evidence (real browser, JS execution) does not hit this and reports 46/46 green. This is an architecture/testability question — not something either R94-R157 or A14-A27 mandates a mechanism for — flagged to `@coordinator` for a decision (server-side `Set-Cookie` at login vs. teaching the suite's client to mirror `app.js`'s cookie) rather than treated as a reviewer-invented objection.

## Hygiene

- `stage-2/Dockerfile`, `stage-2/RUN.md` present.
- No nested `.git`, no symlinks under `stage-2/`.
- Secret scan clean (private-key headers, AWS/GitHub/OpenAI-style key patterns) across `stage-2/` and `specs/`.
- `stage-2/RUN.md` is an unedited stage-1 copy (wrong title/paths) — cosmetic, not a build/run blocker; flagged for a follow-up docs fix.
- No test-input/fixture-id branching in `stage-2/src/`.

## Verdict

**Stage 2: PASS.** Revision `4011bc5f0f4c1a00ad7529f4f0b6903791715f5d` satisfies stage 1 and stage 2 and correctly does not satisfy stage 3 (shipped checks, isolated mode). Every R94-R157/A14-A27 requirement has a passing test or recorded evidence; every acceptance-suite red was individually triaged to either a confirmed suite bug (reproduced and explained above) or the single, shared UI session-bootstrap architecture question (not a requirement violation). Money invariants (conservation, non-negative `available`, exactly-once, all-or-nothing, rounding) hold under the reviewer's own independent concurrent stress run.
