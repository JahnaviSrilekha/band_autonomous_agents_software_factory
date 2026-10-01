import math

from ..errors import ApiError
from .. import state as state_module
from ..state import STATE_LOCK, _is_correction_immutable, parse_rfc3339


def _find_payment(state, payment_id):
    for payment in state.payments:
        if payment.id == payment_id:
            return payment
    return None


def _visible_to(payment, user_id):
    return (payment.from_user_id == user_id or payment.to_user_id == user_id
            or payment.visibility == "public")


def _parse_expected_revision(body):
    if "expected_revision" not in body:
        raise ApiError(422, "validation_failed", "expected_revision is required")
    value = body["expected_revision"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "malformed_request", "expected_revision must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ApiError(422, "validation_failed", "expected_revision must be an integer")
        value = int(value)
    if value < 1:
        raise ApiError(422, "validation_failed",
                       "expected_revision must be a positive integer")
    return int(value)


def _parse_amount(body):
    if "amount" not in body:
        raise ApiError(422, "validation_failed", "amount is required")
    value = body["amount"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "malformed_request", "amount must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ApiError(422, "validation_failed", "amount must be an integer")
        value = int(value)
    if value < 0 or value > 1000000000:
        raise ApiError(422, "validation_failed",
                       "amount must be between 0 and 1000000000")
    return int(value)


def _parse_reason(body):
    if "reason" not in body:
        raise ApiError(422, "validation_failed", "reason is required")
    value = body["reason"]
    if not isinstance(value, str):
        raise ApiError(422, "validation_failed", "reason must be a string")
    if not 1 <= len(value) <= 200:
        raise ApiError(422, "validation_failed",
                       "reason must be between 1 and 200 characters")
    return value


def _parse_effective_at(body):
    if "effective_at" not in body:
        raise ApiError(422, "validation_failed", "effective_at is required")
    value = body["effective_at"]
    effective_dt = parse_rfc3339(value, "effective_at", require_offset=True)
    if effective_dt > state_module.now_dt():
        raise ApiError(422, "validation_failed",
                       "effective_at must not be in the future")
    return value, effective_dt


def _move_correction_delta(state, payment, delta):
    if delta == 0:
        return
    if delta > 0:
        state.users[payment.from_user_id].balance -= delta
        state.users[payment.to_user_id].balance += delta
    else:
        state.users[payment.to_user_id].balance -= -delta
        state.users[payment.from_user_id].balance += -delta


def create_correction(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        payment = _find_payment(state, params["id"])
        if payment is None or not _visible_to(payment, fresh.id):
            raise ApiError(404, "not_found", "no such payment")
        if payment.from_user_id != fresh.id:
            raise ApiError(403, "forbidden",
                           "only the original sender may correct a payment")
        if payment.settlement_id is not None or _is_correction_immutable(payment):
            raise ApiError(422, "linked_payment_immutable",
                           "linked payments cannot be corrected")
        expected_revision = _parse_expected_revision(body)
        amount = _parse_amount(body)
        _parse_reason(body)
        effective_at, effective_dt = _parse_effective_at(body)
        if expected_revision != len(payment.revisions):
            raise ApiError(409, "stale_revision",
                           "expected_revision does not match the payment's latest revision")
        if state_module.refunded_total(state, payment.id) > amount:
            raise ApiError(422, "refund_exceeds_payment",
                           "amount would reduce the payment below its refunded total")
        state_module.check_correction_funds(state, payment, amount, effective_dt,
                                            state_module.now_dt())
        old_amount = payment.revisions[-1].amount
        revision = payment.append_revision(amount, effective_at, state_module.now_iso(),
                                           body["reason"])
        _move_correction_delta(state, payment, amount - old_amount)
        return 201, {
            "payment_id": payment.id,
            "revision": revision.revision,
            "amount": revision.amount,
            "effective_at": revision.effective_at,
            "recorded_at": revision.recorded_at,
            "reason": revision.reason,
        }
