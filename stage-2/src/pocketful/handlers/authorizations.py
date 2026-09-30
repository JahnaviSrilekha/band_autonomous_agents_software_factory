import datetime

from ..errors import (
    ApiError, parse_amount, parse_limit_offset, parse_note, parse_visibility, query_value,
    require_string,
)
from .. import state as state_module
from ..state import (
    AUTHORIZATION_STATUSES, STATE_LOCK, Authorization, effective_status, is_live_hold,
    new_id, remaining_amount,
)


def authorization_json(state, auth, now):
    return {
        "authorization_id": auth.id,
        "from_user_id": auth.from_user_id,
        "from_handle": state.users[auth.from_user_id].handle,
        "to_user_id": auth.to_user_id,
        "to_handle": state.users[auth.to_user_id].handle,
        "amount": auth.amount,
        "captured_amount": auth.captured_amount,
        "currency": state.currency,
        "note": auth.note,
        "visibility": auth.visibility,
        "status": effective_status(auth, now),
        "expires_at": auth.expires_at,
        "payment_id": auth.payment_ids[-1] if auth.payment_ids else None,
        "created_at": auth.created_at,
        "remaining_amount": remaining_amount(auth, now),
    }


def create_authorization(user, body, params, query):
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
            raise ApiError(422, "self_payment", "cannot authorize to yourself")
        now = state_module.now_dt()
        if state_module.available(state, fresh.id, now) < amount:
            raise ApiError(409, "insufficient_funds", "available funds are below amount")
        expires_dt = now + datetime.timedelta(seconds=state.authorization_ttl_seconds)
        authorization = Authorization(
            id=new_id("a"),
            from_user_id=fresh.id,
            to_user_id=to_user.id,
            amount=amount,
            note=note,
            visibility=visibility,
            status="open",
            captured_amount=0,
            payment_ids=[],
            created_at=now.isoformat(),
            expires_at=expires_dt.isoformat(),
            expires_dt=expires_dt,
            seq=state.next_seq(),
        )
        state.authorizations[authorization.id] = authorization
        return 201, authorization_json(state, authorization, now)


def capture_authorization(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        authorization = state.authorizations.get(params["id"])
        if authorization is None:
            raise ApiError(404, "not_found", "no such authorization")
        if authorization.to_user_id != fresh.id:
            raise ApiError(403, "forbidden", "only the receiver may capture this authorization")
        now = state_module.now_dt()
        if authorization.status != "open":
            raise ApiError(409, "authorization_not_open", "authorization is not open")
        if authorization.expires_dt <= now:
            raise ApiError(409, "authorization_expired", "authorization has expired")
        if "amount" in body:
            amount = parse_amount(body["amount"])
        else:
            amount = None
        final = body.get("final", True)
        if not isinstance(final, bool):
            raise ApiError(422, "validation_failed", "final must be a boolean")
        remaining = remaining_amount(authorization, now)
        if amount is None:
            amount = remaining
        if amount > remaining:
            raise ApiError(422, "capture_exceeds_authorization",
                           "capture amount exceeds the uncaptured remainder")
        from .payments import move_money, payment_json

        payment = move_money(
            state,
            state.users[authorization.from_user_id],
            state.users[authorization.to_user_id],
            amount,
            authorization.note,
            authorization.visibility,
            authorization_id=authorization.id,
        )
        authorization.captured_amount += amount
        authorization.payment_ids.append(payment.id)
        if final or authorization.captured_amount >= authorization.amount:
            authorization.status = "captured"
        return 201, payment_json(state, payment)


def void_authorization(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        authorization = state.authorizations.get(params["id"])
        if authorization is None:
            raise ApiError(404, "not_found", "no such authorization")
        if authorization.from_user_id != fresh.id:
            raise ApiError(403, "forbidden", "only the payer may void this authorization")
        now = state_module.now_dt()
        if authorization.status == "voided":
            return 200, authorization_json(state, authorization, now)
        if authorization.status != "open" or authorization.expires_dt <= now:
            raise ApiError(409, "authorization_not_open", "authorization is not open")
        authorization.status = "voided"
        return 200, authorization_json(state, authorization, now)


def list_authorizations(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        direction = query_value(query, "direction")
        status = query_value(query, "status")
        limit, offset = parse_limit_offset(query)
        if direction is not None and direction not in ("incoming", "outgoing"):
            raise ApiError(422, "validation_failed", "direction must be incoming or outgoing")
        if status is not None and status not in AUTHORIZATION_STATUSES:
            raise ApiError(422, "validation_failed", "unknown status value")
        now = state_module.now_dt()
        items = [a for a in state.authorizations.values()
                 if a.from_user_id == fresh.id or a.to_user_id == fresh.id]
        if direction == "incoming":
            items = [a for a in items if a.to_user_id == fresh.id]
        elif direction == "outgoing":
            items = [a for a in items if a.from_user_id == fresh.id]
        if status is not None:
            items = [a for a in items if effective_status(a, now) == status]
        items.sort(key=lambda a: (a.created_dt, a.seq), reverse=True)
        page = items[offset:offset + limit]
        return 200, {
            "authorizations": [authorization_json(state, a, now) for a in page],
            "has_more": len(items) > offset + limit,
        }