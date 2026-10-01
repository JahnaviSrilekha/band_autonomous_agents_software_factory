# Stage 3 report — pocketful: statements and payment corrections

**Verified revision:** `5a4beac` (reviewer's independent stage verification,
`specs/stage-3/verification.md`). `main` has since advanced to `2111892` with one
docs-only/cosmetic follow-up on top (T50, the `stage-3/RUN.md` rewrite, and its task-list
bookkeeping) — functionally harmless (commands are directory-relative), does not change
verified product behavior, and was itself re-confirmed clean by the reviewer at merge
(`main` now `2111892`).

**Result: PASS.** Stage 3 is verified. Does not satisfy stage 4 (confirmed by reviewer).

## Timeline (all 2026-10-01 CEST, continuing directly from stage 2's `b9bd074` PASS at 02:36)

| Step | Time |
|---|---|
| `stage-3/` carried forward from verified `stage-2/`; requirements.md (R158-R251, A29-A33), design.md + ADR-008/009/010, tasks.md (T39-T49) written and committed | 04:10 – 04:16 (commit `a0c76ee`) |
| Handoffs sent to `@developer` and `@tester`; `@reviewer` asked to merge docs | 04:17 |
| Reviewer merged docs (`main` → `a0c76ee`) | ~04:18 |
| Tester's completeness review (8 findings, one substantive: the `created_at`-vs-`effective_at` conflict between the `as_of` and `known_at` sections for corrected payments) received and amended in one round (A34-A38; R159/R165-R167/R173/R174/R192/R210/R220/R226/R228/R248/A29 fixes) | amended, merged `main` → `439cd5a` at 04:27 |
| Developer batch 1 (T39-T42: revision data model, corrections endpoint, funds checks, revisions endpoint) handed off | 04:18; committed through 04:52 (tip `7f48de6`), reviewed 05:04 |
| Tester's black-box acceptance suite (94 stage-3 tests covering R158-R251/A29-A38 + stage-1/2 regression) committed and merged | `main` → `7c1854b` at ~05:01 |
| Developer batch 2 (T43-T44: `GET /me` temporal queries, historical holds) handed off | ~05:30s, tip `3fcb4ef`/`309b376` |
| Developer batch 3 (T45-T47: `GET /statement`, snapshots, settlement/export v3) handed off | ~06:00s, tip `6733acf` |
| Developer batch 4 (T48-T49: concurrency hardening, full self-verification) handed off — completes T39-T49 | ~06:15, tip `d8a1104` |
| **Reviewer review pipeline stalled** — batch 1 sent 05:04, reviewer showed idle with zero stage-3 activity (no probe/verdict/merge) through four batch handoffs and ~2h20m of elapsed time, despite being directly addressed each time. Coordinator sent a consolidated nudge (all four batches, branch/commit detail) at 07:24; reviewer resumed within the minute, confirmed independently that `main` was already a clean ancestor of `developer-stage3` (the stall was not a merge-conflict or delivery issue) | nudge 07:24; reviewer resumed 07:24 |
| Reviewer ran the full batch review (unit suite + tester's acceptance suite against a built container + own probes): 247/269 acceptance tests passed, 22 failed | reported ~08:08–08:15 |
| **Reviewer rejected `developer-stage3@d8a1104`** — two genuine product defects (R203/R204: a correction mutated the stored original payment response and activity-feed entry instead of leaving them unchanged; R214: `GET /me`/`GET /statement` didn't echo a supplied `known_at`) plus 4 bugs in the tester's own acceptance suite (import NameError, double-`.json()` crash, two stage-2-regression tests not updated for the sanctioned `closed_at` shape delta, bearer-token reuse across an in-test reset). Reviewer addressed `@developer` and `@tester` directly with full repro evidence | rejection ~08:08–08:15 |
| Tester fixed all 4 suite bugs | `main` → `2d5dec2` at 08:27 |
| Developer fixed both product defects (R203/R204, R214) | `fc57495` at 08:46 |
| Developer resubmitted with a self-found list of 18 additional "suite defect" claims (traced from a 251/269 local run). Coordinator independently verified each against `requirements.md` before forwarding anything: 4 confirmed and forwarded to tester (bad `test_r247` fixture violating A29; two `as_of`-inclusivity expectation errors contradicting R165's literal wording; an `R227 has_more` miscalculation), 1 forwarded unverified (an `R160` ordering claim the coordinator couldn't confirm from the summary alone), 1 held back and sent back to the developer because their own arithmetic was internally inconsistent (claimed `9500+200=9000`) rather than being accepted at face value — this one turned out, on checking the actual committed test source directly, to already match (`9300-500+200=9000`, unchanged by the tester) — a description error, not a bug on either side | developer resubmission 08:46–08:50; coordinator verification & routing 08:50–08:56; resolved 09:00 |
| Tester verified/fixed the 4 confirmed items, swept the whole suite for the token-reuse pattern, re-ran full suite against an isolated archive build of `fc57495`: **267/267 passed, 0 failed, 12 sanctioned skips** | `main` → `9d5e831` at 08:54 |
| Developer merged the verified suite tip back into `developer-stage3` | `0313387` at 09:03 |
| Reviewer merged `developer-stage3` into `main` (clean ff, diff exactly the expected src/tests, no acceptance-suite deletions or doc reversions) | `main` → `0313387` at ~09:08 |
| Coordinator formally requested full stage-3 verification | 09:23 |
| **Reviewer: independent stage verification — fresh clone (not any seat's live worktree, a deliberate lesson carried from this stage's own review process), `docker build --no-cache`, isolated harness run, full acceptance-suite re-run, independent concurrency/conservation/historical-view stress probes, hygiene sweep** | reported 09:33 (verification commit `5a4beac`) |
| One non-blocking hygiene finding (`stage-3/RUN.md` an unedited stage-2 copy) routed to developer as T50, same pattern as stage 2's T38 | routed 09:34; `main` → `255f0ad` (task row) 09:34, `3786ead` (fix) 09:35, merged `main` → `2111892` ~09:37 |

Total elapsed: ~04:10 to ~09:37 (≈5h27m), across one requirements-amendment round, one
genuine two-defect rejection (fixed same-session), one real multi-batch review-pipeline
stall (~2h20m, resolved by coordinator escalation, not caused by any lost work), and one
round of coordinator-arbitrated suite-vs-product defect triage. See Rejections below.

## Check results (reviewer's independent stage verification, `5a4beac`)

- Fresh clone (not a seat's live worktree), `docker build --no-cache`, started per `RUN.md`.
- Shipped harness, isolated mode (`band-work/checks/s3-review-final-1`): stage 1
  **pass 147/147**, stage 2 **pass 35/35**, stage 3 **pass 6/6**, stage 4 overshoot correctly
  **fail**, `claimed stage: 3`.
- Tester's full acceptance suite re-run against the fresh container: **267/267 passed, 0
  failed, 12 sanctioned skips** (the sanctioned `format_version`/`closed_at`-shape deltas
  per ADR-010/stage-2). Every R158-R251/A29-A38 id has a passing test; stage-1/2 regression
  clean.
- Reviewer's own independent concurrency stress probes (separate from the tester's and
  developer's): 10-way race on a same-`expected_revision` correction (exactly one 201, nine
  409 `stale_revision`, zero 5xx — R231); a 13-way mixed load followed by conservation checks
  across 4 views including 2 historical `as_of` + 1 `known_at` view (300000/300000 held
  exactly, no negative `total`/`available` anywhere — R202/R246); an invalid concurrent reset
  (negative-balance fixture) correctly rejected 422 with prior state provably intact
  (all-or-nothing — A29/R182).
- Hygiene: Dockerfile/RUN.md present, no nested repo/symlinks, secret scan clean, no
  shipped-test-input/fixture-id branching found in `src/`. One non-blocking finding
  (`RUN.md` stage-2 copy) — fixed post-verification as T50, re-confirmed clean at merge.

## Requirement coverage

All 94 stage-3 requirements (R158-R251) and all 10 stage-3 assumptions (A29-A38) have
passing evidence in `specs/stage-3/acceptance/` (267/267 at the verified revision) and
recorded reasoning in `specs/stage-3/requirements.md` (`main`, current). Stage-1's
R1-R93/A1-A13 and stage-2's R94-R157/A14-A28 remain verified by reference and were
re-confirmed via the stage-1/2 regression suites passing unmodified against `stage-3/`.

## Assumptions

A29-A33 recorded at initial spec-writing (seeded-history-consistency error code; imported
pre-v3 exports' synthesized revision 1; `GET /statement`'s non-echoed `from`/`to`;
correction validation order; no stated revision-count limit). A34-A38 recorded during the
tester's round-1 completeness review: **A34** (substantive) resolves a real wording conflict
between the source's `as_of` section (keyed on `created_at`) and its `known_at` section
(keyed on selected-revision `effective_at`) for corrected payments — the uncorrected case
uses `created_at` by construction (revision 1's `effective_at == created_at`), the corrected
case uses the selected revision's `effective_at` throughout; A35 (seeded authorization
`created_at` validation/ordering); A36 (per-endpoint query-parameter recognition —
`as_of` ignored on `GET /statement`, `from`/`to`/`snapshot` ignored on `GET /me`); A37 (`id`
tie-break is lexicographic string comparison); A38 (import invalidates snapshot tokens via
the same reset-epoch mechanism as reset).

## Rejections and decisions

1. **Completeness-review round (tester, one round, per mandate).** 8 findings, all
   resolved: A34 was substantive (a genuine requirements-vs-requirements wording conflict,
   not implementation-dependent); A35-A38 were scoping/citation gaps; two were pure wording
   fixes (A29's "zero/declared" → "opening balance," R192's over-claimed field exclusivity).
   None narrowed or contradicted the source text.
2. **Batch rejection (reviewer → developer), real and substantive.** Two genuine defects:
   R203/R204 (a correction mutated the original payment's displayed amount in the activity
   feed and stored responses, instead of leaving the original untouched while balances still
   moved) and R214 (`known_at` not echoed). Both reproduced by the reviewer with the tester's
   actual acceptance suite against a built container before rejecting — the most thorough
   batch review of any stage so far. Fixed in one commit (`fc57495`) within 30 minutes of
   the rejection landing.
3. **Review-pipeline stall (procedural, no work lost).** The reviewer went idle for ~2h20m
   after the first stage-3 batch handoff (05:04–07:24), despite four separate, correctly
   addressed batch handoffs accumulating. Unlike stage 2's stall (a crossed message that
   simply went unseen), this one showed no visible activity at all and the reviewer's own
   session reported idle — consistent with a genuine delivery/scheduling gap rather than a
   missed message. The coordinator's consolidated nudge (one message covering all four
   outstanding batches, rather than four separate resends) resolved it within a minute of
   being sent. No work was lost or redone; the only cost was elapsed time.
4. **Suite-vs-product defect triage (developer → coordinator → tester), a new pattern for
   this track.** After fixing the two genuine defects, the developer self-reported 18
   additional failures as suite bugs. Rather than relaying this claim to the tester
   unverified, the coordinator checked each one directly against `requirements.md` (and, for
   one case, the actual committed test source) before routing: 4 confirmed real suite bugs
   (forwarded and fixed), 1 forwarded as flagged-but-unconfirmed, and 1 **not** forwarded —
   the developer's own supporting arithmetic for a money-invariant test
   (`test_exactly_once_concurrent_identical_corrections`) didn't add up (`9500+200` doesn't
   equal the `9000` they cited), which is exactly the kind of claim that could mask a real
   defect in the correction money-movement path if accepted at face value. Holding it back
   until the developer re-verified — and then independently confirming against the actual
   test source rather than trusting either side's restated description — resolved it as a
   description error (the developer had omitted that the account's balance already carried a
   prior-in-test state of 9300, not a clean 10000) with no change needed on either side.
5. **T50 (reviewer-initiated, cosmetic, post-verification).** `stage-3/RUN.md` was an
   unedited copy of stage-2's (same defect class as stage 2's own T38) — flagged as a
   hygiene note, not a verification blocker. Fixed same-session; re-confirmed clean by the
   reviewer at merge.

## Open gaps

None known. Every requirement has passing evidence; both rejection rounds were resolved
with verified fixes, not scope reduction.
