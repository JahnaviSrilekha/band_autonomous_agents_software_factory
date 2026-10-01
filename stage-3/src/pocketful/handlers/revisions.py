from ..errors import ApiError
from .. import state as state_module
from ..state import STATE_LOCK


def list_revisions(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        payment_id = params["id"]
        payment = next((p for p in state.payments if p.id == payment_id), None)
        if payment is None or (payment.from_user_id != fresh.id
                               and payment.to_user_id != fresh.id):
            raise ApiError(404, "not_found", "no such payment")
        return 200, {"revisions": [r.to_json() for r in payment.revisions]}
