# ADR-012: Batch corrections check combined affordability once, not per item sequentially

## Context

R278 states affordability "is determined by the combined effect of all proposed revisions."
R275 gives a strict precedence: item errors, then settlement completeness, then *resulting
current* available funds, then *historical* total/available funds at every boundary. A batch
may touch several payments sharing a party (e.g. two corrections both debiting the same
user), so checking each item's funds impact against live state one at a time — as stage-3's
single-correction `check_correction_funds` does — would let an early item's check pass or
fail based on an intermediate state that no committed world ever has, since nothing commits
until every item clears every step (R279).

## Options

1. Reuse `check_correction_funds` once per item, applying each item's delta to a scratch copy
   of balances before checking the next item, folding items into an evolving simulated state.
2. Compute one `{user_id: net_delta}` map summing every item's proposed delta up front, then
   check each affected user's `available(now) + net_delta >= 0` exactly once; separately,
   compute one combined historical timeline (generalizing stage-3's `_check_historical_overdraft`
   from two parties to the full set touched by the batch) and scan it once.

## Decision

Option 2.

## Consequences

- Matches R278's text directly: "the combined effect of all proposed revisions" is computed
  as a single combined delta, not as an order-dependent fold over a simulated sequence of
  intermediate states that the batch's all-or-nothing semantics (R279) says never exist.
- A batch where item A debits user X by 100 and item B credits user X by 100 is correctly
  affordable even if X's live `available()` is 0 and neither item would be affordable in
  isolation against a sequential simulation that checked A before B's credit landed — exactly
  the kind of case "combined effect" is written to cover.
- Historical boundary checking (R275 step 4) reuses the same combined-delta philosophy:
  `check_batch_historical_funds` builds one shared `(user_id, instant) -> delta` map across
  every item's proposed revision plus every other payment/authorization event touching the
  same parties, rather than calling stage-3's two-party function once per item (which would
  re-scan the same unrelated payments N times and could mis-order same-instant deltas across
  items belonging to different payments).
- Cost: a new pair of functions (`check_batch_current_funds`, `check_batch_historical_funds`)
  that cannot simply call stage-3's single-payment versions as black boxes — some duplication
  of the scanning logic, parameterized over N parties instead of 2. Judged worth it because
  correctness of "combined effect" cannot be expressed as N independent two-party calls.
