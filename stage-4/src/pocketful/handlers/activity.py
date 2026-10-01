from ..errors import ApiError, parse_limit_offset
from .. import state as state_module
from ..state import STATE_LOCK
from .payments import payment_json


def visible_payments(state, user):
    return [p for p in state.payments
            if p.visibility == "public"
            or p.from_user_id == user.id
            or p.to_user_id == user.id]


def list_activity(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        limit, offset = parse_limit_offset(query)
        items = visible_payments(state, fresh)
        items.sort(key=lambda p: (p.effective_at, p.seq), reverse=True)
        page = items[offset:offset + limit]
        return 200, {
            "payments": [payment_json(state, p) for p in page],
            "has_more": len(items) > offset + limit,
        }