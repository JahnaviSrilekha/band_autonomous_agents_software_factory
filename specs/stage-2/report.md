# Stage 2 report — pocketful: wallet screens and payment authorizations

**Verified revision:** `4011bc5f0f4c1a00ad7529f4f0b6903791715f5d` (reviewer's independent
stage verification, `specs/stage-2/verification.md`, committed at `b9bd074`). `main` has
since advanced to `8b9667b` with three docs-only/cosmetic follow-ups on top (A28, the
`RUN.md` fix, and its task-list bookkeeping) — none change verified product behavior.

**Result: PASS.** Stage 2 is verified and ready for stage 3 to begin.

## Timeline

| Step | Time |
|---|---|
| Stage-2 dispatch received; `stage-2/` carried forward from verified `stage-1/`; requirements.md (R94-R157, A14-A20), design.md + ADR-005/006/007, tasks.md (T20-T36) written and committed | 20:38 – 20:49 (commit `c53b785`) |
| Handoffs sent to `@developer` and `@tester`; `@reviewer` asked to merge docs | 20:50 |
| Reviewer merged initial docs (`main` → `c53b785`) | ~20:50 |
| Developer batch 1 (T20-T21: authorization model, fixture seeding, `GET /me`) handed off | 21:15 (`16b7e268`) |
| Reviewer: batch 1 accepted and merged (`main` → `8940624`) | ~21:2x |
| Tester's completeness review (8 findings: `GET /authorizations` shape, seeded-expired contradictions, R98/R155 timestamp conflict, over-claimed `final` in responses, non-bool `final` code, R104 gap, element placement, example-vs-rule precedence) received and amended in one round (A21-A27; R104/R133/R146/R150/A18 fixes) | amended, merged `main` → `2db982d` |
| Developer batch 2 (T22-T26: authorizations/capture/void/list, available-based funds checks) handed off | 21:46 (`7915e214`) |
| Tester's black-box acceptance suite (83 stage-2 tests + 94 stage-1 regression) committed and merged | `main` → `c16d72d` |
| Developer batch 3 (T27: export/import v2) handed off | 22:01 (`5592f411`) |
| Tester found T20's reset validation incomplete against A22 (contradictory seeded authorizations); coordinator added T37 and routed to developer | ~22:17 – 22:18; merged `main` → `a9373b5` |
| Developer batch 4 (T28-T33: full UI — six server-rendered routes, static JS, upgrade continuity) handed off | 00:32 (`1a792983`) |
| Developer batch 5 (T34-T36: concurrency hardening, a11y sweep, full-stage self-verification) handed off, completing T20-T36 | 00:57 (`aeecf085`) |
| **Reviewer rejected batch 2** (two defects: `payment_ids` omitted from authorization responses; non-boolean `final` returned 422 instead of 400) — crossed with developer's batch 3/4/5 messages and went unseen for ~3h until the coordinator's stalled-pipeline escalation surfaced it | rejection sent ~21:5x; surfaced & relayed ~00:59 |
| Developer: both batch-2 defects fixed, plus T37, in one commit; combined re-review requested | 01:17 (`dd90de6`) – 01:22 (`f23480df`) |
| Developer merged `main` into `developer-stage2`, flipped T37's row `done` | ~01:32 – 01:38 (`4011bc5`) |
| Reviewer: batches 2-5 + amendment + T37 reviewed together and merged (`main` → `4011bc5`) | ~01:4x – 02:2x |
| Reviewer: independent stage verification — fresh no-cache build, isolated-mode harness, tester's suite re-run and fully triaged (139/177, every failure explained), independent concurrency stress run | reported ~02:3x (report `b9bd074`) |
| Coordinator recorded A28 (UI session-cookie architecture) per reviewer's finding; routed `@tester` to adapt suite, `@developer` for the `RUN.md` cosmetic fix (T38) | ~02:38 – 02:41; merged `main` → `c2b2d33` |
| Developer: T38 (`RUN.md` rewrite) committed and merged | ~02:56 (`606c59c`) |
| Coordinator: T38 task-list row added and merged | `main` → `8b9667b` |

Total elapsed: ~20:38 to ~03:00 (≈6h20m) across one requirements-amendment round, one
genuinely rejected-then-fixed batch, and one real review-pipeline stall caused by a crossed
message (see Rejections below) — not by any seat being idle.

## Check results (reviewer's independent stage verification, `b9bd074`)

- Fresh clone, `docker build --no-cache`, healthy within 2s.
- Shipped harness, isolated mode: stage 1 **pass 147/147**, stage 2 **pass 35/35**, stage 3
  overshoot correctly **fail**, `claimed stage: 2`, share `1.0`.
- Tester's acceptance suite (83 stage-2 + 94 stage-1 regression tests) re-run against the
  fresh container: 139/177 stage-2 — every one of the 38 reds individually triaged: 10 are
  confirmed bugs in the suite itself (reproduced by hand against the product, product found
  correct — a `NameError` crash, and nine test-authoring errors against R123/R128/R140/R144/
  R148/R150), ~17 share one root cause (a UI session-established-by-client-JS mechanism a
  pure-HTTP client can't bootstrap — resolved as A28, not a product defect), and the rest are
  the two sanctioned stage-1 deltas (`format_version: 2`, `authorization_id` in payment
  shape) per ADR-006/R143.
- Reviewer's own independent concurrency stress run: 50 mixed payments/authorize+capture/
  splits/8-way-identical-replay operations in flight — **zero 5xx, exact conservation
  (6,000,000/6,000,000 seeded minor units), zero negative `available`, exactly one real
  effect per replayed idempotency key**; a separate targeted all-or-nothing settlement-
  rejection check left every balance provably unchanged.
- Hygiene: Dockerfile/RUN.md present (RUN.md's stage-1-copy defect fixed post-verification,
  T38); no nested repo/symlinks; secret scan clean; no shipped-test-input/fixture-id
  branching found.

## Requirement coverage

All 64 stage-2 requirements (R94-R157) and all 28 stage-2 assumptions (A14-A28) have
passing evidence or recorded reasoning, in `specs/stage-2/verification.md` (`b9bd074`) and
`specs/stage-2/requirements.md` (`8b9667b`). Stage-1's R1-R93/A1-A13 remain verified by
reference (`specs/stage-1/verification.md`) and were re-confirmed via the 94-test stage-1
regression suite passing unmodified against `stage-2/`.

## Assumptions

A14-A27 recorded during the requirements-amendment round (validation order for the two new
idempotent endpoints; void's no-idempotency-key rule extended from A6; the body-type gate
extended from A8; qualitative UI language scoped to its testable sub-rules; `data-testid`
attributes exempted from the people-first-formatting rule; the missing `pay-uncertain`
testid; `GET /authorizations`'s response envelope; seeded-authorization edge cases;
non-boolean `final`'s error code; element placement for the authorize form and
`logout-button`; the worked example vs. the `expires_at` formula). **A28** recorded
post-verification from the reviewer's own finding: the UI's session cookie is set by
client-side JavaScript after login, not by the server — intentional, confirmed correct for
a JS-executing client (developer's Playwright e2e, 46/46), not changed to chase a pure-HTTP
suite's pass rate (see Rejections/decisions below).

## Rejections and decisions

1. **Completeness-review round (tester, one round, per mandate).** 8 findings, all
   resolved: 4 needed a recorded decision before tests could be deterministic (`GET
   /authorizations` response shape, seeded-expired contradictions, the over-claimed `final`
   response field, element placement), 3 were small requirement-text gaps (R104's missing
   capture-amount input, R133's citation, the R98/R155 timestamp conflict), 1 was an
   illustrative-example-vs-rule precedence note. None narrowed or contradicted the source
   text; all are recorded as A21-A27.
2. **Batch 2 rejection (reviewer → developer), real and substantive.** Two genuine defects:
   `payment_ids` missing from every authorization response (R146), and a non-boolean
   `final` returning the wrong error code (422 instead of 400, A24). Both reproduced by the
   reviewer with an independent black-box probe before rejecting. **What went wrong
   procedurally:** the rejection reply crossed with the developer's subsequent batch 3/4/5
   handoff messages and was never seen; the developer, having received no reply to five
   consecutive handoffs over several hours, correctly reported a stalled review pipeline per
   the 15-minute/escalation rule. The coordinator's own first response to that report was
   also mistaken — checking `git log main` and concluding the pipeline was genuinely silent,
   rather than first asking the reviewer whether a reply had in fact been sent. The reviewer
   corrected this immediately, the rejection was relayed in full, and the developer fixed
   both defects in a single commit (`dd90de6`) alongside the already-pending T37 fix. No
   work was lost; the only cost was elapsed time (the batch-2-to-fix gap).
3. **T37 (coordinator-initiated, small scope).** Tester's acceptance suite found that T20's
   landed reset-fixture validation didn't cover all of assumption A22 (future-dated seeded
   `"expired"` authorizations, and self-authorization/unknown-user-id seeds, were wrongly
   accepted instead of rejected 422). Routed to developer as a small, scoped addition to the
   same file; fixed alongside the batch-2 defects.
4. **T38 (reviewer-initiated, cosmetic, post-verification).** `stage-2/RUN.md` was an
   unedited copy of stage-1's (wrong title/paths) — flagged as a hygiene note, not a
   verification blocker, by the reviewer's own PASS report. Fixed same-session.
5. **UI session-bootstrap architecture question (reviewer-initiated, resolved by
   coordinator, no product change).** ~17 of the acceptance suite's 38 reds shared one root
   cause: the UI authenticates server-rendered page loads via a cookie that client-side
   JavaScript sets after login, which a pure-HTTP black-box client never establishes. The
   reviewer correctly declined to call this a requirement violation (stage-2.md specifies no
   session-establishment mechanism for a full page navigation) and flagged it as an open
   decision. The coordinator recorded it as A28 and explicitly declined to add a
   server-side `Set-Cookie` purely to satisfy the black-box suite — the developer's own
   Playwright (JS-executing) end-to-end suite already passes 46/46 against every affected
   route, indicating the intended test mode executes the page's script like a real browser,
   and changing product behavior whose only justification is a check result is foreclosed by
   the run's own mandate. The tester was routed to adapt the suite's authenticated-page-route
   tests to replicate `app.js`'s cookie contract instead.
