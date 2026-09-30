from ..errors import ApiError, parse_amount, parse_note, require_string
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