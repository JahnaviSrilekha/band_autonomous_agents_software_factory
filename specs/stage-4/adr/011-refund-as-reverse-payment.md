# ADR-011: A refund is a plain `Payment` row with `refund_of` set, not a new entity

## Context

R260 requires a refund to be "a new payment in the opposite direction, with `refund_of`
naming the target". R263/R264 require refunds to behave like ordinary payments everywhere
except: they can't themselves be refunded (R256) or corrected (R266), and they must carry a
backward link to their target.

## Options

1. A new `Refund` class/collection (`state.refunds`), referencing a target payment id, with
   its own balance-movement logic duplicated from `move_money`.
2. A `Payment` with one new nullable field, `refund_of`, created through the existing
   `move_money` primitive (direction reversed: target's receiver is now the mover's
   `from_user_id`).

## Decision

Option 2.

## Consequences

- Every place that already renders a payment (`payment_json`, activity feed, statement
  entries, receipts) handles a refund for free — it is a `Payment` — once `refund_of` is
  added to `payment_json`'s output (R264). No parallel rendering path to keep in sync.
- Conservation (money invariant) falls out of reusing `move_money`'s paired debit/credit,
  exactly as for a settlement transfer or a capture — no new arithmetic to re-prove.
- The two refund-specific rules (R256 "no refund of a refund", R266 "refunds are
  correction-immutable") become one-line predicates on the existing object
  (`payment.refund_of is not None`) rather than type checks against a second class.
- Cost: `refunded_total` (the cumulative-cap sum, R259/R267) must scan `state.payments` for
  `refund_of == target_id` rather than following a dedicated reverse index. At this track's
  scale (seeded fixtures, harness-driven load, not a production ledger) a linear scan under
  the existing `STATE_LOCK` is simpler and sufficiently fast; a reverse-index map would be a
  premature optimization with no requirement driving it.
