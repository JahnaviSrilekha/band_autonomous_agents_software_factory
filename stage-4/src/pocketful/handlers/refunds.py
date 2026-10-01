import math

from ..errors import ApiError
from .. import state as state_module
from ..state import STATE_LOCK, Payment, new_id
from .corrections import _find_payment, _visible_to
from .payments import payment_json


def _parse_refund_amount(body):
    if "amount" not in body:
        raise ApiError(422, "validation_failed", "amount is required")
    value = body["amount"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "malformed_request", "amount must be an integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ApiError(422, "validation_failed", "amount must be an integer")
        value = int(value)
    if value < 1 or value > 1000000000:
        raise ApiError(422, "validation_failed",
                       "amount must be between 1 and 1000000000")
    return int(value)


def create_refund(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        payment = _find_payment(state, params["id"])
        if payment is None or not _visible_to(payment, fresh.id):
            raise ApiError(404, "not_found", "no such payment")
        if fresh.id != payment.to_user_id:
            raise ApiError(403, "forbidden",
                           "only the original receiver may refund a payment")
        if payment.refund_of is not None:
            raise ApiError(422, "invalid_refund_target", "a refund cannot be refunded")
        amount = _parse_refund_amount(body)
        if (state_module.refunded_total(state, payment.id) + amount
                > payment.revisions[-1].amount):
            raise ApiError(422, "refund_exceeds_payment",
                           "cumulative refunds exceed the payment's current amount")
        now = state_module.now_dt()
        if state_module.available(state, payment.to_user_id, now) < amount:
            raise ApiError(409, "insufficient_funds",
                           "available funds are below the refund amount")
        stamp = state_module.now_iso()
        state.users[payment.to_user_id].balance -= amount
        state.users[payment.from_user_id].balance += amount
        refund = Payment(
            id=new_id("p"),
            from_user_id=payment.to_user_id,
            to_user_id=payment.from_user_id,
            amount=amount,
            note=payment.note,
            visibility=payment.visibility,
            request_id=None,
            settlement_id=None,
            effective_at=stamp,
            recorded_at=stamp,
            seq=state.next_seq(),
            refund_of=payment.id,
        )
        state.payments.append(refund)
        return 201, payment_json(state, refund)