# Stage 4 final report — pocketful

**Verified revision:** `9acfae4` (main) — fresh no-cache Docker build, isolated-mode harness run
(`claimed stage: 4`), tester's full acceptance suite re-run clean (315/315, 13 sanctioned skips),
and the reviewer's own independent 50-in-flight invariant stress probe, all passing. Full method
and per-requirement evidence: `specs/stage-4/verification.md` (committed at this revision).

## Platform-recovery note

This stage was dispatched and substantially built in a prior room (`bdda4f1d-54f6-4f79-bd92-6a2019b9a91e`),
which hit Band's 10,000-message-per-room limit at 14:01 CEST on 2026-10-01. Messages sent after
that point were rejected, so the handoff of developer's batch 3 and batch 4 work to the reviewer
never arrived, even though the work itself was already committed. The current room
(`85fa6a57-f6fd-4fd6-b7d2-e151ec977338`) continued the same stage: state was rebuilt from `git log`,
branches/worktrees and `specs/stage-4/tasks.md` in the result repository — not from memory — before
any further routing.

## Timeline

| Time (2026-10-01, CEST) | Step |
|---|---|
| 12:50:54 | Carry forward verified stage-3 deliverable into `stage-4/` (830efbe) |
| 12:55:01 | `requirements.md` written: R252-R290, A39-A49 (062a2f4) |
| 12:58:07 | `design.md` + ADR-011/012/013 (cb82394) |
| 12:59:20 | `tasks.md`: T51-T59 across 4 batches (690723a) |
| ~13:00 | Dispatch to developer and tester (old room; exact send time lost to the message cap) |
| 13:23:51 | T51 (refunds) committed by developer |
| 13:46:07 | T52-T54 (correction extensions, correction-batches route) committed; accepted by reviewer — main at 5325ff6 |
| **14:01:00** | **Old room hits the 10,000-message cap; later handoffs rejected and never delivered** |
| 14:01–14:37 | Developer continues unobserved: T55/T56 (compatibility/export v4), T57 (concurrency hardening) and a flakiness fix, T59 (RUN.md hygiene) — all committed to `developer-stage4`, never handed to the reviewer |
| 16:18–16:20 | **Recovery**: new room confirmed; state rebuilt from git (not memory); found coordinator-docs-stage4 already had the requirements amendment and the design.md sec6/sec7 fix (floor-vs-staleness contradiction) from before the cap; found developer-stage4 already had all of T51-T59 complete. Re-dispatched: reviewer asked to merge docs + batch 3 + batch 4; tester asked to rebase onto the docs fix; developer notified no rework needed |
| 16:28:42 | Reviewer merges coordinator-docs-stage4 + developer-stage4 batch 3 (T55-T56) + batch 4 (T57-T59) into main; own black-box probe passes; 530 unit tests pass |
| 16:38 | **Rejection**: tester finds a real precedence defect — `correction_batches.py` checked `refund_exceeds_payment` (422) before `stale_revision` (409), contradicting the resolved design (staleness before floor in both endpoints) |
| 16:39:50 | Routed to developer as top-priority task, ahead of all other work, with exact file/line and repro |
| 16:47:34 | Developer fix committed (0b5a610): swapped check order in `correction_batches.py`, 3 new unit tests, full suite 533/533 |
| 16:55:11 | Fix forwarded to reviewer |
| 17:01:33 | Reviewer merges fix + independent probe; 533 unit tests pass |
| ~17:04 | Tester reports suite green, but against a locally-rebuilt service rather than the committed branch tip |
| 17:32:26 | No reviewer response to tester's merge request after 28 minutes — identical handoff resent per the waiting rule |
| ~17:33 | Reviewer catches the gap: `tester-stage4`'s committed tip hadn't actually merged main's latest commits; confirms a clean additive merge and requests it from tester directly |
| 17:33:04 | `tester-stage4` properly merged into main (169fbe0) — reviewer independently re-runs the suite against the real merged tip: 315/315 |
| 17:38:22 | Stage verification requested |
| 17:43:44 | **Reviewer reports PASS** — verified revision 9acfae4 |

## Check results

- Shipped checks, isolated mode: stage 1/2/3/4 all `pass`; `claimed stage: 4 on the shipped checks`.
  Pocketful has no stage 5, so there is no overshoot case to check.
- Full unit suite at the verified tip: 533 tests, all pass.
- Tester's acceptance suite, re-run by the reviewer against a fresh no-cache container: 315/315
  passed, 0 failed, 13 skipped — every skip sanctioned and cross-referenced in `run.py`'s
  `SANCTIONED_STAGE4_DELTAS` (superseded by this stage's `refund_of`/`format_version: 4` additions).

## Requirement coverage

All 39 stage-4 requirements (R252-R290) and 11 assumptions (A39-A49) mapped to passing evidence in
`specs/stage-4/verification.md`. Stages 1-3 (R1-R251, A1-A38) carried forward and regression-tested
with zero regressions (same 315/315 run).

## Money invariants — independent evidence (reviewer's verification probe)

- Conservation: 50-in-flight mixed burst (payments, refunds, single and batch corrections,
  settlements, concurrent reads) — seeded total 1,500,100 minor units in, 1,500,100 out, exactly,
  across all 4 users.
- No negative money: no `total`/`available`/`held` ever negative across the burst.
- Exactly once: 20-way concurrent identical-idempotency-key payment creation → one 201, nineteen
  identical 200 replays, receiver credited exactly once.
- All or nothing: a 2-item correction-batch with one stale-revision item → rejected 409, all
  affected balances provably unchanged.
- Rounding/shape discipline: fractional minor-unit amount rejected 422.
- Zero 5xx across every run.

## Assumptions

A1-A38 (stages 1-3) remain in force by reference. A39-A49 (stage 4, refunds, correction-batches,
export v4) recorded in `specs/stage-4/requirements.md`; none were revised during this stage.

## Rejections and what they changed

One rejection this stage:

- **Batch-correction precedence defect** (found by tester, 16:38 CEST): `correction_batches.py`'s
  per-item validator raised `refund_exceeds_payment` (422) before `stale_revision` (409), diverging
  from the resolved design (staleness before floor, matching the single-correction endpoint).
  Routed to developer ahead of all other work. Fixed in commit 0b5a610: check order swapped, 3 new
  unit tests added (stale+floor-violating → 409 wins; fresh+floor-violating → 422; stale+floor-ok →
  409). Verified independently by the reviewer both via unit tests and a dedicated probe. No further
  occurrences; not a three-strikes case.

One process gap, not a requirement rejection: tester's first green report (17:04) was against a
locally-rebuilt service rather than the actual `tester-stage4` branch tip, which still only
merge-based at the pre-fix docs commit. The reviewer caught this by checking merge-base before
merging, requested the real merge from tester, and re-verified 315/315 against the properly merged
tip (169fbe0) before proceeding.

## Open gaps

None. No rejections outstanding, no sanctioned skip without a named replacement, no stage-5 features
implemented ahead of scope (pocketful stage 4 is the final stage of this track).

## Stage duration

Start (carry-forward) 12:50:54 → verified 17:43:44 on 2026-10-01: 4h 53m elapsed, including the
room-cap outage and recovery (approximately 14:01-16:18, ~2h 17m of which the work continued
unobserved but undelivered) and one rejection-fix cycle (16:38-17:01, 23 minutes).
