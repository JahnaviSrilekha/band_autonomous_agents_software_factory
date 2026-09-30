from ..errors import ApiError, parse_amount, parse_note
from .. import state as state_module
from ..state import STATE_LOCK, Request, Split, new_id
from ..shares import compute_shares


def create_split(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        fresh = state.users.get(user.id)
        if fresh is None:
            raise ApiError(401, "unauthenticated", "session no longer valid")
        amount = parse_amount(body.get("amount"))
        handles = body.get("participant_handles")
        if handles is None:
            raise ApiError(422, "validation_failed", "participant_handles is required")
        if not isinstance(handles, list):
            raise ApiError(400, "malformed_request", "participant_handles must be an array")
        for handle in handles:
            if not isinstance(handle, str):
                raise ApiError(400, "malformed_request", "participant_handles entries must be strings")
        if len(handles) == 0:
            raise ApiError(422, "validation_failed", "participant_handles must not be empty")
        if len(set(handles)) != len(handles):
            raise ApiError(422, "validation_failed", "participant_handles must not contain duplicates")
        note = parse_note(body)
        participants = []
        for handle in handles:
            user_id = state.handles.get(handle)
            if user_id is None:
                raise ApiError(404, "not_found", "no user has that handle")
            participants.append(state.users[user_id])
        shares = compute_shares(amount, len(handles))
        stamp = state_module.now_iso()
        split = Split(
            id=new_id("sp"),
            caller_id=fresh.id,
            amount=amount,
            note=note,
            participant_handles=list(handles),
            shares=list(shares),
            request_ids=[],
            created_at=stamp,
            seq=state.next_seq(),
        )
        created_requests = []
        for handle, participant, share in zip(handles, participants, shares):
            if participant.id == fresh.id:
                continue
            request = Request(
                id=new_id("rq"),
                requester_id=fresh.id,
                payer_id=participant.id,
                amount=share,
                note=note,
                status="pending",
                payment_id=None,
                created_at=stamp,
                seq=state.next_seq(),
            )
            state.requests[request.id] = request
            split.request_ids.append(request.id)
            created_requests.append(request)
        state.splits[split.id] = split
        from .requests import request_json

        return 201, {
            "split_id": split.id,
            "amount": split.amount,
            "currency": state.currency,
            "note": split.note,
            "shares": [{"handle": handle, "amount": share}
                       for handle, share in zip(handles, shares)],
            "requests": [request_json(state, request) for request in created_requests],
            "created_at": split.created_at,
        }