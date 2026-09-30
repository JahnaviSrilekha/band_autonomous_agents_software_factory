from .. import state as state_module
from ..state import STATE_LOCK


def get_me(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users[user.id]
        return 200, {
            "user_id": fresh.id,
            "display_name": fresh.display_name,
            "handle": fresh.handle,
            "balance": fresh.balance,
            "currency": state.currency,
            "minor_units": state.minor_units,
        }