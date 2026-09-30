# Stage 1 report — pocketful: payments and settlements

**Verified revision:** `1d76d56691800e69090db6e228ebcb76c056cf48` (main tip, includes
`specs/stage-1/verification.md` authored by `@reviewer`).

**Result: PASS.** Stage 1 is verified and ready for stage 2 to begin.

## Timeline

| Step | Start | End |
|---|---|---|
| Task dispatch (requirements.md, design.md, 4 ADRs, tasks.md written and committed) | 16:17 | 16:21:40 (commit `6326ce3`) |
| Handoffs sent to `@developer` and `@tester`; reviewer asked to merge docs | 16:24 | 16:24 |
| Tester completeness review (13 findings) received and amended (A8-A13, R13/R56/R75/R82 fixes, A6 clarified, design.md §5/§6 fixes, tasks.md coverage fixes) | 16:38 | 16:40:59 (commit `f3e9519`) |
| Developer implementation, batch 1 (T1-T4: server/errors, Dockerfile/RUN.md, state/reset, idempotency chokepoint) | 17:06:47 | 17:21:42 |
| Reviewer: batch 1 review and merge | 17:21:42 | 17:29:15 (`5a1e27f`) |
| Tester: first acceptance-suite commit (94 tests) | — | 17:11:01 (`c398c98`) |
| Developer implementation, batches 2-5 (T5-T19: auth, payments/requests, splits/settlements, export/import, concurrency hardening) | 17:40:35 | 18:53:43 (`fbbb8a2`) |
| Reviewer: batch 2-5 reviews (accepted on the merits each time) and final merge, including one recurring git-hygiene blocker (see Rejections) | 17:4x | 19:00 (approx., merge to `fbbb8a2`) |
| Tester: acceptance suite iterated against the live built container, rebased twice to track main's tip, final green run | 17:11 | 19:10:41 (`066bb54`, 94/94 green) |
| Reviewer: independent stage verification (fresh no-cache build, isolated-mode harness run, suite re-run, 400-request/50-thread stress test, hygiene scan) | — | 20:25:10 (`1d76d566`) |

Total elapsed: ~16:17 to 20:25 (≈4h8m), across two coordinator report-amendment rounds and
one multi-round git-hygiene recovery.

## Check results (reviewer's independent stage verification, `1d76d566`)

- Shipped harness, isolated mode (no outbound network): stage 1 **pass 147/147**, stage 2
  overshoot line correctly **fail**, `claimed stage: 1`, share `1.0`.
- Tester's acceptance suite (94 tests, covering every requirement's stated invariants,
  including the concurrency/idempotency/rounding/settlement invariants) re-run against a
  fresh `--no-cache` build: **94/94 green**.
- Reviewer's own independent concurrency stress run: 400 mixed payments/requests/settlements/
  activity-reads across 50 in-flight threads — **zero 5xx, exact conservation (10000/10000
  seeded minor units), zero negative balances.**
- Hygiene: build artifact and run doc present; no nested repo or symlinks; full-repo secret
  scan clean; no shipped-test-input or fixture-id branching found in `stage-1/src`; no
  stage-2+ feature leakage found.

## Requirement coverage

All 93 requirements (R1-R93) and 13 assumptions (A1-A13) have passing evidence, one row each,
written up in `specs/stage-1/verification.md` (committed at `1d76d566`). Requirements
originate from `specs/stage-1/requirements.md` (commit `f3e9519`, amended from the original
`6326ce3` per the tester's completeness review — see Rejections/amendments below).

## Assumptions

A1-A13, recorded with source-text reasoning, in `specs/stage-1/requirements.md`. Notably:
A1/A2 (validation order where the spec is silent), A8 (non-object write-path body → 400,
no idempotency interaction), A9 (settlement entry shape defects → 422, not 400), A11 (email
matching is case-sensitive). None were contested by the tester's acceptance suite or the
reviewer's stress testing.

## Rejections and amendments

1. **Completeness-review round (tester, one round, per mandate).** 13 findings: 6 needed a
   recorded decision before tests could be deterministic (non-object body handling, missing
   `settlement_id` on the general payment shape, settlement entry wrong-type precedence, the
   A6 decline/cancel key-ignoring rule, signup field rules, email case-sensitivity), 3 were
   acceptance-criterion gaps (`/health` body, `/activity` `has_more`, post-import login), 4
   were minor (2 fixture/seed edge cases, a `tasks.md` coverage-claim bug, and a real
   **design bug**: the original idempotency "same body" comparison used bare Python `==`,
   which treats `True == 1` — fixed to a JSON-type-aware comparator before any code was
   written against it). All 13 were resolved in one amendment commit (`f3e9519`) and
   propagated to both `@developer` and `@tester` before implementation of the affected
   endpoints (idempotency, payments, auth, settlements) began.
2. **Git-hygiene recovery (developer branch, four rounds).** Batches 2, 3 and 4 each passed
   review on the merits on first submission — no code or requirement rejections at any
   point — but could not be merged because `dev-stage1` never advanced past its pre-batch-1
   base commit while `main` moved forward with the reviewer's batch-1 acceptance commit. The
   reviewer asked for a rebase after batch 2, again after batch 3, and again after batch 4.
   The coordinator intervened directly after the third recurrence with the exact git commands;
   the fix landed (merge commit `cfaebc2`) around the same time as the third ask, and a
   subsequent hardening commit (`fbbb8a2`, freeing an idempotency claim on any exception
   rather than only `ApiError`, per a reviewer review note — not a rejection, an
   improvement) briefly reopened the same ancestor gap once more before the final merge.
   Total effect on the schedule: none of the five batches' *content* was ever rejected or
   reworked; the four-round delay was entirely git-branch hygiene, and no task was split per
   the three-strikes rule since it was never the same *requirement* failing, just the same
   merge precondition unmet.
3. **Tester branch, one rebase.** The tester's acceptance suite was first built and run green
   against `main@cfaebc2`; by the time it was ready to merge, `main` had advanced one commit
   (`fbbb8a2`). Flagged proactively by the coordinator before the reviewer attempted the
   merge; the tester rebased once and re-ran green (94/94) against the new tip. No suite
   defect was found on this occasion — process-only.
4. **Tester's own suite-side bugs (self-reported, not a rejection of the service).** The
   tester's first live run against the built container surfaced defects in the *test suite
   itself* (error-code argument confusion, an unfunded test payer, an underfunded test
   operator, an `expect_ok().json()` slip) — the service returned spec-correct status/code on
   every one of those paths. Fixed in the suite, not the service.

## Open gaps

None identified. Every requirement has a passing test per the reviewer's coverage table; the
reviewer's independent stress run and hygiene scan found nothing further.
