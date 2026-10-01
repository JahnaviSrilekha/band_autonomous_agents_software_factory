from ..errors import ApiError, parse_limit_offset, query_value
from .. import state as state_module
from ..state import (
    STATE_LOCK, as_dt, historical_balance, parse_rfc3339, selected_revision,
)


def _instant_param(query, name):
    raw = query_value(query, name)
    if raw is None:
        return None
    return parse_rfc3339(raw, name, require_offset=True)


def build_statement(state, user_id, from_dt, to_dt, known_at):
    selected = []
    for payment in state.payments:
        if payment.from_user_id != user_id and payment.to_user_id != user_id:
            continue
        revision = selected_revision(payment, known_at)
        if revision is None:
            continue
        effective = as_dt(revision.effective_at)
        if from_dt is not None and effective < from_dt:
            continue
        if to_dt is not None and effective >= to_dt:
            continue
        selected.append((effective, payment.id, payment, revision))
    selected.sort(key=lambda item: (item[0], item[1]))
    opening = (state.users[user_id].opening_balance if from_dt is None
               else historical_balance(state, user_id, from_dt, known_at, inclusive=False))
    closing = (state.users[user_id].opening_balance if to_dt is None
               else historical_balance(state, user_id, to_dt, known_at, inclusive=False))
    from .payments import payment_json

    entries = []
    running = opening
    for effective, _payment_id, payment, revision in selected:
        delta = revision.amount if payment.to_user_id == user_id else -revision.amount
        running += delta
        payload = payment_json(state, payment)
        payload["amount"] = revision.amount
        entries.append({
            "payment": payload,
            "delta": delta,
            "balance_after": running,
            "revision": revision.revision,
            "effective_at": revision.effective_at,
            "recorded_at": revision.recorded_at,
        })
    return opening, closing, entries


def _paged(entries, limit, offset):
    return entries[offset:offset + limit], len(entries) > offset + limit


def get_statement(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        snapshot_token = query_value(query, "snapshot")
        if snapshot_token is not None:
            if (query_value(query, "from") is not None
                    or query_value(query, "to") is not None
                    or query_value(query, "known_at") is not None):
                raise ApiError(422, "validation_failed",
                               "snapshot paging accepts only limit and offset")
            limit, offset = parse_limit_offset(query)
            stored = state.statement_snapshots.get(snapshot_token)
            if (stored is None or stored["owner_user_id"] != fresh.id
                    or stored["reset_epoch"] != state.reset_epoch):
                raise ApiError(404, "not_found", "no such snapshot")
            page, has_more = _paged(stored["entries"], limit, offset)
            return 200, {
                "opening_balance": stored["opening_balance"],
                "entries": page,
                "closing_balance": stored["closing_balance"],
                "has_more": has_more,
            }
        from_dt = _instant_param(query, "from")
        to_dt = _instant_param(query, "to")
        known_raw = query_value(query, "known_at")
        known_at = (parse_rfc3339(known_raw, "known_at", require_offset=True)
                    if known_raw is not None else None)
        limit, offset = parse_limit_offset(query)
        now = state_module.now_dt()
        to = to_dt if to_dt is not None else now
        opening, closing, entries = build_statement(state, fresh.id, from_dt, to, known_at)
        token = state_module.new_id("snap")
        state.statement_snapshots[token] = {
            "owner_user_id": fresh.id,
            "reset_epoch": state.reset_epoch,
            "opening_balance": opening,
            "closing_balance": closing,
            "entries": entries,
            "resolved_to": to.isoformat(),
        }
        page, has_more = _paged(entries, limit, offset)
        payload = {
            "opening_balance": opening,
            "entries": page,
            "closing_balance": closing,
            "has_more": has_more,
            "snapshot": token,
        }
        if known_raw is not None:
            payload["known_at"] = known_raw
        return 200, payload