from .. import state as state_module
from ..state import STATE_LOCK


def get_me(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users[user.id]
        now = state_module.now_dt()
        held = state_module.held(state, fresh.id, now)
        return 200, {
            "user_id": fresh.id,
            "display_name": fresh.display_name,
            "handle": fresh.handle,
            "balance": fresh.balance,
            "total": fresh.balance,
            "available": fresh.balance - held,
            "held": held,
            "currency": state.currency,
            "minor_units": state.minor_units,
        }