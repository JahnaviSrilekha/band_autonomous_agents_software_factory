from ..errors import (
    ApiError, parse_amount, parse_limit_offset, parse_note, parse_visibility, query_value,
    require_string,
)
from .. import state as state_module
from ..state import STATE_LOCK, Request, new_id

REQUEST_STATUSES = ("pending", "paid", "declined", "cancelled")


def request_json(state, request):
    return {
        "request_id": request.id,
        "requester_id": request.requester_id,
        "requester_handle": state.users[request.requester_id].handle,
        "payer_id": request.payer_id,
        "payer_handle": state.users[request.payer_id].handle,
        "amount": request.amount,
        "currency": state.currency,
        "note": request.note,
        "status": request.status,
        "payment_id": request.payment_id,
        "created_at": request.created_at,
    }


def create_request(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        payer_handle = require_string(body, "payer_handle")
        amount = parse_amount(body.get("amount"))
        note = parse_note(body)
        if payer_handle not in state.handles:
            raise ApiError(404, "not_found", "no user has that handle")
        payer = state.users[state.handles[payer_handle]]
        if payer.id == fresh.id:
            raise ApiError(422, "self_request", "cannot request from yourself")
        request = Request(
            id=new_id("rq"),
            requester_id=fresh.id,
            payer_id=payer.id,
            amount=amount,
            note=note,
            status="pending",
            payment_id=None,
            created_at=state_module.now_iso(),
            seq=state.next_seq(),
        )
        state.requests[request.id] = request
        return 201, request_json(state, request)


def pay_request(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        visibility = parse_visibility(body)
        request = state.requests.get(params["id"])
        if request is None:
            raise ApiError(404, "not_found", "no such request")
        if request.payer_id != fresh.id:
            raise ApiError(403, "forbidden", "only the payer may pay this request")
        if request.status != "pending":
            raise ApiError(409, "request_not_pending", "request is not pending")
        now = state_module.now_dt()
        if state_module.available(state, fresh.id, now) < request.amount:
            raise ApiError(409, "insufficient_funds", "available funds are below amount")
        requester = state.users[request.requester_id]
        from .payments import move_money, payment_json

        payment = move_money(state, fresh, requester, request.amount, request.note,
                             visibility, request_id=request.id)
        request.status = "paid"
        request.payment_id = payment.id
        return 201, payment_json(state, payment)


def decline_request(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        request = state.requests.get(params["id"])
        if request is None:
            raise ApiError(404, "not_found", "no such request")
        if request.payer_id != fresh.id:
            raise ApiError(403, "forbidden", "only the payer may decline this request")
        if request.status == "declined":
            return 200, request_json(state, request)
        if request.status != "pending":
            raise ApiError(409, "request_not_pending", "request is not pending")
        request.status = "declined"
        return 200, request_json(state, request)


def cancel_request(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        request = state.requests.get(params["id"])
        if request is None:
            raise ApiError(404, "not_found", "no such request")
        if request.requester_id != fresh.id:
            raise ApiError(403, "forbidden", "only the requester may cancel this request")
        if request.status == "cancelled":
            return 200, request_json(state, request)
        if request.status != "pending":
            raise ApiError(409, "request_not_pending", "request is not pending")
        request.status = "cancelled"
        return 200, request_json(state, request)


def list_requests(user, body, params, query):
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
        if status is not None and status not in REQUEST_STATUSES:
            raise ApiError(422, "validation_failed", "unknown status value")
        items = [r for r in state.requests.values()
                 if r.requester_id == fresh.id or r.payer_id == fresh.id]
        if direction == "incoming":
            items = [r for r in items if r.payer_id == fresh.id]
        elif direction == "outgoing":
            items = [r for r in items if r.requester_id == fresh.id]
        if status is not None:
            items = [r for r in items if r.status == status]
        items.sort(key=lambda r: (r.created_at, r.seq), reverse=True)
        page = items[offset:offset + limit]
        return 200, {
            "requests": [request_json(state, r) for r in page],
            "has_more": len(items) > offset + limit,
        }
