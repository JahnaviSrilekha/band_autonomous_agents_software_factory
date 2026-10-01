from ..errors import ApiError, parse_amount, parse_note, parse_visibility
from .. import state as state_module
from ..state import STATE_LOCK, Settlement, new_id
from .payments import move_money, payment_json


def _entry_string(entry, field):
    value = entry.get(field)
    if not isinstance(value, str):
        raise ApiError(422, "validation_failed", f"{field} must be a string")
    return value


def create_settlement(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        transfers = body.get("transfers")
        if transfers is None or not isinstance(transfers, list):
            raise ApiError(422, "validation_failed", "transfers must be an array")
        if not 1 <= len(transfers) <= 32:
            raise ApiError(422, "validation_failed", "transfers must contain 1 to 32 entries")
        parsed = []
        for entry in transfers:
            if not isinstance(entry, dict):
                raise ApiError(422, "validation_failed", "each transfer must be an object")
            from_handle = _entry_string(entry, "from_handle")
            to_handle = _entry_string(entry, "to_handle")
            amount = parse_amount(entry.get("amount"))
            note = parse_note(entry)
            visibility = parse_visibility(entry)
            from_user_id = state.handles.get(from_handle)
            if from_user_id is None:
                raise ApiError(404, "not_found", "no user has that handle")
            to_user_id = state.handles.get(to_handle)
            if to_user_id is None:
                raise ApiError(404, "not_found", "no user has that handle")
            if from_user_id == to_user_id:
                raise ApiError(422, "self_payment", "self-transfer is not allowed")
            parsed.append((from_user_id, to_user_id, amount, note, visibility))
        deltas = {}
        for from_user_id, to_user_id, amount, _note, _visibility in parsed:
            deltas[from_user_id] = deltas.get(from_user_id, 0) - amount
            deltas[to_user_id] = deltas.get(to_user_id, 0) + amount
        now = state_module.now_dt()
        for user_id, delta in deltas.items():
            if state.users[user_id].balance + delta - state_module.held(state, user_id, now) < 0:
                raise ApiError(409, "insufficient_funds", "settlement is not collectively affordable")
        stamp = state_module.now_iso()
        settlement_id = new_id("st")
        payments = []
        for index, (from_user_id, to_user_id, amount, note, visibility) in enumerate(parsed):
            payment = move_money(
                state,
                state.users[from_user_id],
                state.users[to_user_id],
                amount,
                note,
                visibility,
                settlement_id=settlement_id,
                created_at=stamp,
            )
            payments.append(payment)
        settlement = Settlement(
            id=settlement_id,
            operator_id=fresh.id,
            transfers=body.get("transfers"),
            payment_ids=[p.id for p in payments],
            committed_at=stamp,
            seq=state.next_seq(),
        )
        state.settlements[settlement_id] = settlement
        return 201, {
            "settlement_id": settlement_id,
            "committed_at": stamp,
            "payments": [payment_json(state, p) for p in payments],
        }