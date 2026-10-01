from .. import state as state_module
from ..state import STATE_LOCK, parse_rfc3339


def _temporal(query):
    from ..errors import query_value

    as_of_raw = query_value(query, "as_of")
    known_raw = query_value(query, "known_at")
    as_of = (parse_rfc3339(as_of_raw, "as_of", require_offset=True)
             if as_of_raw is not None else None)
    known_at = (parse_rfc3339(known_raw, "known_at", require_offset=True)
                if known_raw is not None else None)
    return as_of_raw, as_of, known_raw, known_at


def get_me(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users[user.id]
        as_of_raw, as_of, known_raw, known_at = _temporal(query)
        now = state_module.now_dt()
        if as_of is None and known_at is None:
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
        cutoff = as_of if as_of is not None else now
        balance = state_module.historical_balance(state, fresh.id, cutoff, known_at)
        held = state_module.historical_held(state, fresh.id, cutoff, known_at)
        payload = {
            "user_id": fresh.id,
            "display_name": fresh.display_name,
            "handle": fresh.handle,
            "balance": balance,
            "total": balance,
            "available": balance - held,
            "held": held,
            "currency": state.currency,
            "minor_units": state.minor_units,
        }
        if as_of_raw is not None:
            payload["as_of"] = as_of_raw
        if known_raw is not None:
            payload["known_at"] = known_raw
        return 200, payload