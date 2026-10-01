from ..errors import ApiError
from .. import state as state_module
from ..state import (
    AUTHORIZATION_STATUSES, STATE_LOCK, Authorization, IdempotencyRecord, Payment, Request,
    Revision, Settlement, Split, State, User, parse_rfc3339,
)
from ..reset import HANDLE_RE, _fixture_amount, _fixture_string, _fixture_ttl


def state_to_json(state):
    return {
        "currency": state.currency,
        "minor_units": state.minor_units,
        "authorization_ttl_seconds": state.authorization_ttl_seconds,
        "seq": state.seq,
        "settlement_operator_ids": sorted(state.settlement_operator_ids),
        "users": [
            {"id": u.id, "email": u.email, "password_hash": u.password_hash,
             "display_name": u.display_name, "handle": u.handle, "balance": u.balance}
            for u in state.users.values()
        ],
        "tokens": [{"token": token, "user_id": user_id}
                   for token, user_id in state.tokens.items()],
        "payments": [
            {"id": p.id, "seq": p.seq, "from_user_id": p.from_user_id,
             "to_user_id": p.to_user_id, "amount": p.amount, "note": p.note,
             "visibility": p.visibility, "request_id": p.request_id,
             "settlement_id": p.settlement_id, "effective_at": p.effective_at,
             "recorded_at": p.recorded_at, "authorization_id": p.authorization_id,
             "refund_of": p.refund_of,
             "revisions": [r.to_json() for r in p.revisions]}
            for p in state.payments
        ],
        "requests": [
            {"id": r.id, "seq": r.seq, "requester_id": r.requester_id,
             "payer_id": r.payer_id, "amount": r.amount, "note": r.note,
             "status": r.status, "payment_id": r.payment_id, "created_at": r.created_at}
            for r in state.requests.values()
        ],
        "authorizations": [
            {"id": a.id, "seq": a.seq, "from_user_id": a.from_user_id,
             "to_user_id": a.to_user_id, "amount": a.amount, "note": a.note,
             "visibility": a.visibility, "status": a.status,
             "captured_amount": a.captured_amount, "payment_ids": list(a.payment_ids),
             "created_at": a.created_at, "expires_at": a.expires_at,
             "closed_event_at": (a.closed_event_dt.isoformat()
                                 if a.closed_event_dt is not None else None)}
            for a in state.authorizations.values()
        ],
        "splits": [
            {"id": s.id, "seq": s.seq, "caller_id": s.caller_id, "amount": s.amount,
             "note": s.note, "participant_handles": s.participant_handles,
             "shares": s.shares, "request_ids": s.request_ids, "created_at": s.created_at}
            for s in state.splits.values()
        ],
        "settlements": [
            {"id": st.id, "seq": st.seq, "operator_id": st.operator_id,
             "transfers": st.transfers, "payment_ids": st.payment_ids,
             "committed_at": st.committed_at}
            for st in state.settlements.values()
        ],
        "idempotency": [
            {"user_id": rec.user_id, "method": rec.method, "path": rec.path, "key": rec.key,
             "request_body": rec.request_body, "response_status": rec.response_status,
             "response_body": rec.response_body}
            for rec in state.idempotency.values()
        ],
    }


def _require_list(payload, field):
    value = payload.get(field)
    if not isinstance(value, list):
        raise ApiError(422, "validation_failed", f"{field} must be an array")
    return value


def state_from_json(payload, format_version):
    state = State()
    currency = payload.get("currency")
    if not isinstance(currency, str) or not currency:
        raise ApiError(422, "validation_failed", "currency must be a non-empty string")
    state.currency = currency
    minor_units = payload.get("minor_units")
    if isinstance(minor_units, bool) or not isinstance(minor_units, (int, float)):
        raise ApiError(422, "validation_failed", "minor_units must be a number")
    if isinstance(minor_units, float) and not minor_units.is_integer():
        raise ApiError(422, "validation_failed", "minor_units must be an integer")
    if int(minor_units) not in (0, 2, 3):
        raise ApiError(422, "validation_failed", "minor_units must be 0, 2 or 3")
    state.minor_units = int(minor_units)
    state.authorization_ttl_seconds = _fixture_ttl(payload)
    seq = payload.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise ApiError(422, "validation_failed", "seq must be a non-negative integer")
    state.seq = seq
    for operator_id in _require_list(payload, "settlement_operator_ids"):
        if not isinstance(operator_id, str):
            raise ApiError(422, "validation_failed", "settlement_operator_ids entries must be strings")
        state.settlement_operator_ids.add(operator_id)
    for entry in _require_list(payload, "users"):
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each user must be an object")
        user_id = _fixture_string(entry, "id")
        email = _fixture_string(entry, "email")
        password_hash = _fixture_string(entry, "password_hash")
        display_name = _fixture_string(entry, "display_name")
        handle = _fixture_string(entry, "handle")
        if not HANDLE_RE.match(handle):
            raise ApiError(422, "validation_failed", "handle must match ^[a-z0-9_]{1,20}$")
        if user_id in state.users or handle in state.handles or email in state.emails:
            raise ApiError(422, "validation_failed", "duplicate user id, handle or email")
        balance = _fixture_amount(entry.get("balance"), 0, "balance")
        user = User(user_id, email, password_hash, display_name, handle, balance)
        state.users[user_id] = user
        state.handles[handle] = user_id
        state.emails[email] = user_id
    for entry in _require_list(payload, "tokens"):
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each token must be an object")
        token = _fixture_string(entry, "token")
        user_id = _fixture_string(entry, "user_id")
        if user_id not in state.users:
            raise ApiError(422, "validation_failed", "token references an unknown user")
        state.tokens[token] = user_id
    for entry in _require_list(payload, "requests"):
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each request must be an object")
        request = _request_from_json(state, entry)
        state.requests[request.id] = request
    for entry in _authorization_list(payload):
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each authorization must be an object")
        authorization = _authorization_from_json(state, entry, format_version)
        state.authorizations[authorization.id] = authorization
    payment_ids_seen = set()
    for entry in _require_list(payload, "payments"):
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each payment must be an object")
        payment = _payment_from_json(state, entry, format_version, payment_ids_seen)
        state.payments.append(payment)
        payment_ids_seen.add(payment.id)
    _apply_imported_opening_balances(state)
    state.reset_epoch += 1
    for entry in _require_list(payload, "splits"):
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each split must be an object")
        split = _split_from_json(state, entry)
        state.splits[split.id] = split
    for entry in _require_list(payload, "settlements"):
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each settlement must be an object")
        settlement = _settlement_from_json(state, entry)
        state.settlements[settlement.id] = settlement
    for entry in _require_list(payload, "idempotency"):
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each idempotency record must be an object")
        record = _idempotency_from_json(state, entry)
        state.idempotency[(record.user_id, record.method, record.path, record.key)] = record
    return state


def _apply_imported_opening_balances(state):
    net = {user_id: 0 for user_id in state.users}
    for payment in state.payments:
        net[payment.from_user_id] -= payment.amount
        net[payment.to_user_id] += payment.amount
    for user_id, user in state.users.items():
        user.opening_balance = user.balance - net[user_id]


def _request_from_json(state, entry):
    request_id = _fixture_string(entry, "id")
    requester_id = _fixture_string(entry, "requester_id")
    payer_id = _fixture_string(entry, "payer_id")
    if requester_id not in state.users or payer_id not in state.users:
        raise ApiError(422, "validation_failed", "request references an unknown user")
    amount = _fixture_amount(entry.get("amount"), 0, "request amount")
    note = entry.get("note", "")
    if not isinstance(note, str):
        raise ApiError(422, "validation_failed", "note must be a string")
    status = entry.get("status")
    if not isinstance(status, str):
        raise ApiError(422, "validation_failed", "status must be a string")
    payment_id = entry.get("payment_id")
    if payment_id is not None and not isinstance(payment_id, str):
        raise ApiError(422, "validation_failed", "payment_id must be a string or null")
    created_at = entry.get("created_at")
    if not isinstance(created_at, str):
        raise ApiError(422, "validation_failed", "created_at must be a string")
    record_seq = entry.get("seq")
    if isinstance(record_seq, bool) or not isinstance(record_seq, int):
        raise ApiError(422, "validation_failed", "request seq must be an integer")
    return Request(request_id, requester_id, payer_id, amount, note, status,
                   payment_id, created_at, record_seq)


def _authorization_list(payload):
    value = payload.get("authorizations", [])
    if not isinstance(value, list):
        raise ApiError(422, "validation_failed", "authorizations must be an array")
    return value


def _authorization_from_json(state, entry, format_version):
    authorization_id = _fixture_string(entry, "id")
    from_user_id = _fixture_string(entry, "from_user_id")
    to_user_id = _fixture_string(entry, "to_user_id")
    if from_user_id not in state.users or to_user_id not in state.users:
        raise ApiError(422, "validation_failed", "authorization references an unknown user")
    if authorization_id in state.authorizations:
        raise ApiError(422, "validation_failed", "duplicate authorization id")
    amount = _fixture_amount(entry.get("amount"), 0, "authorization amount")
    note = entry.get("note", "")
    if not isinstance(note, str):
        raise ApiError(422, "validation_failed", "note must be a string")
    visibility = entry.get("visibility")
    if visibility not in ("public", "private"):
        raise ApiError(422, "validation_failed", 'visibility must be "public" or "private"')
    status = entry.get("status")
    if status not in AUTHORIZATION_STATUSES:
        raise ApiError(422, "validation_failed",
                       'authorization status must be open, captured, voided or expired')
    captured_amount = entry.get("captured_amount")
    if captured_amount is None:
        captured_amount = amount if status == "captured" else 0
    else:
        if isinstance(captured_amount, bool) or not isinstance(captured_amount, int):
            raise ApiError(422, "validation_failed",
                           "authorization captured_amount must be an integer")
        if captured_amount < 0 or captured_amount > amount:
            raise ApiError(422, "validation_failed",
                           "authorization captured_amount must be between 0 and amount")
    payment_ids = entry.get("payment_ids", [])
    if not isinstance(payment_ids, list) or not all(isinstance(p, str) for p in payment_ids):
        raise ApiError(422, "validation_failed",
                       "authorization payment_ids must be an array of strings")
    created_at = entry.get("created_at")
    if not isinstance(created_at, str):
        raise ApiError(422, "validation_failed", "created_at must be a string")
    expires_at = entry.get("expires_at")
    expires_dt = parse_rfc3339(expires_at, "authorization expires_at")
    closed_event_dt = None
    if format_version >= 3:
        raw_closed = entry.get("closed_event_at")
        if raw_closed is not None:
            if not isinstance(raw_closed, str):
                raise ApiError(422, "validation_failed",
                               "closed_event_at must be a string or null")
            closed_event_dt = parse_rfc3339(raw_closed, "closed_event_at")
    elif status in ("captured", "voided"):
        closed_event_dt = parse_rfc3339(created_at, "created_at")
    record_seq = entry.get("seq", 0)
    if isinstance(record_seq, bool) or not isinstance(record_seq, int) or record_seq < 0:
        raise ApiError(422, "validation_failed", "authorization seq must be a non-negative integer")
    return Authorization(authorization_id, from_user_id, to_user_id, amount, note,
                         visibility, status, captured_amount, list(payment_ids),
                         created_at, expires_at, expires_dt, seq=record_seq,
                         closed_event_dt=closed_event_dt)


def _revisions_from_json(entry):
    raw = entry.get("revisions")
    if not isinstance(raw, list) or not raw:
        raise ApiError(422, "validation_failed",
                       "payment revisions must be a non-empty array")
    revisions = []
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError(422, "validation_failed", "each revision must be an object")
        number = item.get("revision")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ApiError(422, "validation_failed", "revision must be a positive integer")
        amount = _fixture_amount(item.get("amount"), 0, "revision amount")
        effective_at = item.get("effective_at")
        recorded_at = item.get("recorded_at")
        if not isinstance(effective_at, str) or not isinstance(recorded_at, str):
            raise ApiError(422, "validation_failed", "revision timestamps must be strings")
        reason = item.get("reason", "")
        if not isinstance(reason, str):
            raise ApiError(422, "validation_failed", "revision reason must be a string")
        correction_batch_id = item.get("correction_batch_id")
        if correction_batch_id is not None and not isinstance(correction_batch_id, str):
            raise ApiError(422, "validation_failed",
                           "revision correction_batch_id must be a string or null")
        revisions.append(Revision(number, amount, effective_at, recorded_at, reason,
                                  correction_batch_id))
    numbers = [r.revision for r in revisions]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ApiError(422, "validation_failed",
                       "payment revisions must be numbered 1..N in order")
    return revisions


def _payment_from_json(state, entry, format_version, payment_ids_seen):
    payment_id = _fixture_string(entry, "id")
    from_user_id = _fixture_string(entry, "from_user_id")
    to_user_id = _fixture_string(entry, "to_user_id")
    if from_user_id not in state.users or to_user_id not in state.users:
        raise ApiError(422, "validation_failed", "payment references an unknown user")
    amount = _fixture_amount(entry.get("amount"), 0, "payment amount")
    note = entry.get("note", "")
    if not isinstance(note, str):
        raise ApiError(422, "validation_failed", "note must be a string")
    visibility = entry.get("visibility")
    if visibility not in ("public", "private"):
        raise ApiError(422, "validation_failed", 'visibility must be "public" or "private"')
    request_id = entry.get("request_id")
    if request_id is not None:
        if not isinstance(request_id, str) or request_id not in state.requests:
            raise ApiError(422, "validation_failed", "payment references an unknown request")
    settlement_id = entry.get("settlement_id")
    if settlement_id is not None and not isinstance(settlement_id, str):
        raise ApiError(422, "validation_failed", "settlement_id must be a string or null")
    authorization_id = entry.get("authorization_id")
    if authorization_id is not None:
        if not isinstance(authorization_id, str) or authorization_id not in state.authorizations:
            raise ApiError(422, "validation_failed", "payment references an unknown authorization")
    refund_of = entry.get("refund_of")
    if refund_of is not None:
        if (not isinstance(refund_of, str) or refund_of == payment_id
                or refund_of not in payment_ids_seen):
            raise ApiError(422, "validation_failed",
                           "payment references an unknown refund target")
    effective_at = entry.get("effective_at")
    recorded_at = entry.get("recorded_at")
    if not isinstance(effective_at, str) or not isinstance(recorded_at, str):
        raise ApiError(422, "validation_failed", "payment timestamps must be strings")
    record_seq = entry.get("seq")
    if isinstance(record_seq, bool) or not isinstance(record_seq, int):
        raise ApiError(422, "validation_failed", "payment seq must be an integer")
    revisions = _revisions_from_json(entry) if format_version >= 3 else None
    return Payment(payment_id, from_user_id, to_user_id, amount, note, visibility,
                   request_id, settlement_id, effective_at, recorded_at, record_seq,
                   authorization_id, revisions=revisions, refund_of=refund_of)


def _split_from_json(state, entry):
    split_id = _fixture_string(entry, "id")
    caller_id = _fixture_string(entry, "caller_id")
    if caller_id not in state.users:
        raise ApiError(422, "validation_failed", "split references an unknown user")
    amount = _fixture_amount(entry.get("amount"), 0, "split amount")
    note = entry.get("note", "")
    if not isinstance(note, str):
        raise ApiError(422, "validation_failed", "note must be a string")
    handles = entry.get("participant_handles")
    if not isinstance(handles, list) or not all(isinstance(h, str) for h in handles):
        raise ApiError(422, "validation_failed", "participant_handles must be an array of strings")
    shares = entry.get("shares")
    if not isinstance(shares, list) or not all(isinstance(s, int) and not isinstance(s, bool) for s in shares):
        raise ApiError(422, "validation_failed", "shares must be an array of integers")
    if len(shares) != len(handles):
        raise ApiError(422, "validation_failed", "shares must align with participant_handles")
    request_ids = entry.get("request_ids")
    if not isinstance(request_ids, list) or not all(r in state.requests for r in request_ids):
        raise ApiError(422, "validation_failed", "split references an unknown request")
    created_at = entry.get("created_at")
    if not isinstance(created_at, str):
        raise ApiError(422, "validation_failed", "created_at must be a string")
    record_seq = entry.get("seq")
    if isinstance(record_seq, bool) or not isinstance(record_seq, int):
        raise ApiError(422, "validation_failed", "split seq must be an integer")
    return Split(split_id, caller_id, amount, note, handles, shares, request_ids,
                 created_at, record_seq)


def _settlement_from_json(state, entry):
    settlement_id = _fixture_string(entry, "id")
    operator_id = _fixture_string(entry, "operator_id")
    if operator_id not in state.users:
        raise ApiError(422, "validation_failed", "settlement references an unknown operator")
    transfers = entry.get("transfers")
    if not isinstance(transfers, list):
        raise ApiError(422, "validation_failed", "transfers must be an array")
    payment_ids = entry.get("payment_ids")
    if not isinstance(payment_ids, list) or not all(p in {x.id for x in state.payments} for p in payment_ids):
        raise ApiError(422, "validation_failed", "settlement references an unknown payment")
    committed_at = entry.get("committed_at")
    if not isinstance(committed_at, str):
        raise ApiError(422, "validation_failed", "committed_at must be a string")
    record_seq = entry.get("seq")
    if isinstance(record_seq, bool) or not isinstance(record_seq, int):
        raise ApiError(422, "validation_failed", "settlement seq must be an integer")
    return Settlement(settlement_id, operator_id, transfers, payment_ids, committed_at, record_seq)


def _idempotency_from_json(state, entry):
    user_id = _fixture_string(entry, "user_id")
    if user_id not in state.users:
        raise ApiError(422, "validation_failed", "idempotency record references an unknown user")
    method = _fixture_string(entry, "method")
    path = _fixture_string(entry, "path")
    key = _fixture_string(entry, "key")
    request_body = entry.get("request_body")
    response_status = entry.get("response_status")
    if isinstance(response_status, bool) or not isinstance(response_status, int):
        raise ApiError(422, "validation_failed", "response_status must be an integer")
    response_body = entry.get("response_body")
    return IdempotencyRecord(user_id, method, path, key, request_body, "done",
                             response_status, response_body)


def handle_export(user, body, params, query):
    with STATE_LOCK:
        state = state_module.STATE
        return 200, {"track": "pocketful", "format_version": 4, "state": state_to_json(state)}


def handle_import(user, body, params, query):
    if body.get("track") != "pocketful":
        raise ApiError(422, "validation_failed", "track must be pocketful")
    version = body.get("format_version")
    if (isinstance(version, bool) or not isinstance(version, (int, float))
            or version not in (1, 2, 3, 4)):
        raise ApiError(422, "validation_failed", "format_version must be 1, 2, 3 or 4")
    payload_state = body.get("state")
    if not isinstance(payload_state, dict):
        raise ApiError(422, "validation_failed", "state is required")
    new_state = state_from_json(payload_state, version)
    with STATE_LOCK:
        state_module.STATE = new_state
    return 204, None