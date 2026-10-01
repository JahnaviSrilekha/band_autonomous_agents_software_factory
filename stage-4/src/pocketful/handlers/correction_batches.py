from ..errors import ApiError
from .. import state as state_module
from ..state import STATE_LOCK, _is_correction_immutable, new_id
from .corrections import (
    _find_payment, _move_correction_delta, _parse_amount, _parse_effective_at,
    _parse_expected_revision, _parse_reason,
)

MAX_BATCH_ITEMS = 32


def _parse_items(state, body):
    corrections = body.get("corrections")
    if not isinstance(corrections, list):
        raise ApiError(422, "validation_failed", "corrections must be an array")
    if not 1 <= len(corrections) <= MAX_BATCH_ITEMS:
        raise ApiError(422, "validation_failed",
                       f"corrections must contain 1 to {MAX_BATCH_ITEMS} items")
    seen = set()
    for entry in corrections:
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each correction must be an object")
        payment_id = entry.get("payment_id")
        if not isinstance(payment_id, str):
            raise ApiError(422, "validation_failed", "payment_id must be a string")
        if payment_id in seen:
            raise ApiError(422, "validation_failed",
                           "corrections must name distinct payments")
        seen.add(payment_id)
    items = []
    for entry in corrections:
        payment_id = entry["payment_id"]
        expected_revision = _parse_expected_revision(entry)
        amount = _parse_amount(entry)
        reason = _parse_reason(entry)
        effective_at, effective_dt = _parse_effective_at(entry)
        payment = _find_payment(state, payment_id)
        if payment is None:
            raise ApiError(404, "not_found", f"no such payment: {payment_id}")
        if _is_correction_immutable(payment):
            raise ApiError(422, "linked_payment_immutable",
                           "captured and refund payments cannot be corrected")
        if expected_revision != len(payment.revisions):
            raise ApiError(409, "stale_revision",
                           "expected_revision does not match the payment's latest revision")
        if state_module.refunded_total(state, payment.id) > amount:
            raise ApiError(422, "refund_exceeds_payment",
                           "amount would reduce the payment below its refunded total")
        items.append({"payment": payment, "amount": amount, "reason": reason,
                      "effective_at": effective_at, "effective_dt": effective_dt,
                      "revision": None})
    return items


def correction_item_json(item):
    revision = item["revision"]
    return {
        "payment_id": item["payment"].id,
        "revision": revision.revision,
        "amount": revision.amount,
        "effective_at": revision.effective_at,
        "recorded_at": revision.recorded_at,
        "reason": revision.reason,
        "correction_batch_id": revision.correction_batch_id,
    }


def check_settlement_completeness(state, items):
    item_payment_ids = {item["payment"].id for item in items}
    settlements_checked = set()
    for item in items:
        settlement_id = item["payment"].settlement_id
        if settlement_id is None or settlement_id in settlements_checked:
            continue
        settlements_checked.add(settlement_id)
        settlement = state.settlements.get(settlement_id)
        if settlement is None:
            raise ApiError(422, "incomplete_settlement",
                           "settlement members must all be corrected together")
        for member_id in settlement.payment_ids:
            if member_id not in item_payment_ids:
                raise ApiError(422, "incomplete_settlement",
                               "settlement members must all be corrected together")


def check_members_effective_consistency(items):
    by_settlement = {}
    for item in items:
        settlement_id = item["payment"].settlement_id
        if settlement_id is None:
            continue
        by_settlement.setdefault(settlement_id, []).append(item)
    for members in by_settlement.values():
        first_dt = members[0]["effective_dt"]
        for member in members[1:]:
            if member["effective_dt"] != first_dt:
                raise ApiError(422, "validation_failed",
                               "settlement members must share one effective instant")


def create_correction_batch(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        items = _parse_items(state, body)
        check_settlement_completeness(state, items)
        check_members_effective_consistency(items)
        now = state_module.now_dt()
        proposals = [(item["payment"], item["amount"], item["effective_dt"])
                     for item in items]
        state_module.check_batch_current_funds(state, proposals, now)
        state_module.check_batch_historical_funds(state, proposals, now)
        batch_id = new_id("cb")
        recorded_at = state_module.compute_batch_recorded_at(
            state, [item["payment"] for item in items])
        for item in items:
            payment = item["payment"]
            old_amount = payment.revisions[-1].amount
            item["revision"] = payment.append_revision(
                item["amount"], item["effective_at"], recorded_at, item["reason"],
                batch_id)
            _move_correction_delta(state, payment, item["amount"] - old_amount)
        return 201, {
            "correction_batch_id": batch_id,
            "recorded_at": recorded_at,
            "revisions": [correction_item_json(item) for item in items],
        }