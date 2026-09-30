from ..errors import ApiError, parse_amount, parse_note, parse_visibility, require_string
from .. import state as state_module
from ..state import STATE_LOCK, Payment, new_id


def payment_json(state, payment):
    return {
        "payment_id": payment.id,
        "from_user_id": payment.from_user_id,
        "from_handle": state.users[payment.from_user_id].handle,
        "to_user_id": payment.to_user_id,
        "to_handle": state.users[payment.to_user_id].handle,
        "amount": payment.amount,
        "currency": state.currency,
        "note": payment.note,
        "visibility": payment.visibility,
        "request_id": payment.request_id,
        "settlement_id": payment.settlement_id,
        "created_at": payment.effective_at,
    }


def move_money(state, from_user, to_user, amount, note, visibility, request_id=None,
               settlement_id=None, created_at=None):
    stamp = created_at or state_module.now_iso()
    from_user.balance -= amount
    to_user.balance += amount
    payment = Payment(
        id=new_id("p"),
        from_user_id=from_user.id,
        to_user_id=to_user.id,
        amount=amount,
        note=note,
        visibility=visibility,
        request_id=request_id,
        settlement_id=settlement_id,
        effective_at=stamp,
        recorded_at=stamp,
        seq=state.next_seq(),
    )
    state.payments.append(payment)
    return payment


def create_payment(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        to_handle = require_string(body, "to_handle")
        amount = parse_amount(body.get("amount"))
        note = parse_note(body)
        visibility = parse_visibility(body)
        if to_handle not in state.handles:
            raise ApiError(404, "not_found", "no user has that handle")
        to_user = state.users[state.handles[to_handle]]
        if to_user.id == fresh.id:
            raise ApiError(422, "self_payment", "cannot pay yourself")
        if fresh.balance < amount:
            raise ApiError(409, "insufficient_funds", "balance is below amount")
        payment = move_money(state, fresh, to_user, amount, note, visibility)
        return 201, payment_json(state, payment)