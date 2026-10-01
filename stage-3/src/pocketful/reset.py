import math
import re

from .errors import ApiError
from . import state as state_module
from .state import (
    AUTHORIZATION_STATUSES, STATE_LOCK, Authorization, Payment, Request, State, User,
    as_dt, hash_password, parse_rfc3339,
)

HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
VISIBILITIES = ("public", "private")


def _fixture_string(entry, field):
    value = entry.get(field)
    if not isinstance(value, str):
        raise ApiError(422, "validation_failed", f"{field} must be a string")
    return value


def _fixture_amount(value, minimum, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(422, "validation_failed", f"{what} must be a number")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ApiError(422, "validation_failed", f"{what} must be an integer")
    amount = int(value)
    if amount < minimum:
        raise ApiError(422, "validation_failed", f"{what} must be at least {minimum}")
    return amount


def _fixture_note(entry):
    note = entry.get("note", "")
    if not isinstance(note, str):
        raise ApiError(422, "validation_failed", "note must be a string")
    return note


def _fixture_visibility(entry):
    visibility = entry.get("visibility", "public")
    if visibility not in VISIBILITIES:
        raise ApiError(422, "validation_failed", 'visibility must be "public" or "private"')
    return visibility


def _fixture_ttl(fixture):
    value = fixture.get("authorization_ttl_seconds", 600)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(422, "validation_failed",
                       "authorization_ttl_seconds must be a positive integer number of seconds")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ApiError(422, "validation_failed",
                       "authorization_ttl_seconds must be a positive integer number of seconds")
    ttl = int(value)
    if ttl < 1:
        raise ApiError(422, "validation_failed",
                       "authorization_ttl_seconds must be a positive integer number of seconds")
    return ttl


def _seed_authorizations(state, fixture, reset_now):
    authorizations = fixture.get("authorizations", [])
    if not isinstance(authorizations, list):
        raise ApiError(422, "validation_failed", "authorizations must be an array")
    stamp = reset_now.isoformat()
    for entry in authorizations:
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each seeded authorization must be an object")
        authorization_id = _fixture_string(entry, "id")
        from_user_id = _fixture_string(entry, "from_user_id")
        to_user_id = _fixture_string(entry, "to_user_id")
        if from_user_id not in state.users or to_user_id not in state.users:
            raise ApiError(422, "validation_failed", "seeded authorization references an unknown user")
        if from_user_id == to_user_id:
            raise ApiError(422, "validation_failed",
                           "seeded authorization cannot be from and to the same user")
        if authorization_id in state.authorizations:
            raise ApiError(422, "validation_failed", "duplicate authorization id")
        amount = _fixture_amount(entry.get("amount"), 0, "seeded authorization amount")
        status = entry.get("status", "open")
        if status not in AUTHORIZATION_STATUSES:
            raise ApiError(422, "validation_failed",
                           'seeded authorization status must be open, captured, voided or expired')
        expires_at = entry.get("expires_at")
        expires_dt = parse_rfc3339(expires_at, "seeded authorization expires_at")
        if status == "expired":
            if expires_dt > reset_now:
                raise ApiError(422, "validation_failed",
                               'seeded "expired" authorization must have expires_at at or before now')
            status = "open"
        captured_amount = entry.get("captured_amount")
        if captured_amount is None:
            captured_amount = 0
        else:
            if isinstance(captured_amount, bool) or not isinstance(captured_amount, int):
                raise ApiError(422, "validation_failed",
                               "seeded authorization captured_amount must be an integer")
            if captured_amount < 0 or captured_amount > amount:
                raise ApiError(422, "validation_failed",
                               "seeded authorization captured_amount must be between 0 and amount")
        payment_ids = entry.get("payment_ids", [])
        if not isinstance(payment_ids, list) or not all(isinstance(p, str) for p in payment_ids):
            raise ApiError(422, "validation_failed",
                           "seeded authorization payment_ids must be an array of strings")
        created_at = entry.get("created_at", stamp)
        if not isinstance(created_at, str):
            raise ApiError(422, "validation_failed", "created_at must be a string")
        created_dt = parse_rfc3339(created_at, "seeded authorization created_at",
                                   require_offset=True)
        if created_dt > reset_now:
            raise ApiError(422, "validation_failed",
                           "seeded authorization created_at must not be in the future")
        authorization = Authorization(
            id=authorization_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            amount=amount,
            note=_fixture_note(entry),
            visibility=_fixture_visibility(entry),
            status=status,
            captured_amount=captured_amount,
            payment_ids=list(payment_ids),
            created_at=created_at,
            expires_at=expires_at,
            expires_dt=expires_dt,
            created_dt=created_dt,
            closed_event_dt=(created_dt if status in ("captured", "voided") else None),
        )
        state.authorizations[authorization_id] = authorization


def _check_hold_sum(state):
    now = state_module.now_dt()
    for user_id in state.users:
        holds = 0
        for auth in state.authorizations.values():
            if (auth.from_user_id == user_id and auth.status == "open"
                    and auth.expires_dt > now):
                holds += auth.amount - auth.captured_amount
        if state.users[user_id].balance - holds < 0:
            raise ApiError(422, "validation_failed",
                           "seeded open holds exceed the user's balance")


def build_state_from_fixture(fixture):
    state = _build_users(fixture)
    state.authorization_ttl_seconds = _fixture_ttl(fixture)
    reset_now = state_module.now_dt()
    _seed_payments(state, fixture, reset_now)
    _apply_seeded_opening_balances(state)
    _check_seeded_history(state)
    _seed_requests(state, fixture, reset_now)
    _seed_operators(state, fixture)
    _seed_authorizations(state, fixture, reset_now)
    _check_hold_sum(state)
    state.reset_epoch += 1
    return state


def _build_users(fixture):
    state = State()
    currency = fixture.get("currency")
    if not isinstance(currency, str) or not currency:
        raise ApiError(422, "validation_failed", "currency must be a non-empty string")
    state.currency = currency
    minor_units = fixture.get("minor_units")
    if isinstance(minor_units, bool) or not isinstance(minor_units, (int, float)):
        raise ApiError(422, "validation_failed", "minor_units must be a number")
    if isinstance(minor_units, float) and (not math.isfinite(minor_units) or not minor_units.is_integer()):
        raise ApiError(422, "validation_failed", "minor_units must be an integer")
    if int(minor_units) not in (0, 2, 3):
        raise ApiError(422, "validation_failed", "minor_units must be 0, 2 or 3")
    state.minor_units = int(minor_units)
    users = fixture.get("users")
    if not isinstance(users, list):
        raise ApiError(422, "validation_failed", "users must be an array")
    for entry in users:
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each user must be an object")
        user_id = _fixture_string(entry, "id")
        email = _fixture_string(entry, "email")
        password = _fixture_string(entry, "password")
        display_name = _fixture_string(entry, "display_name")
        handle = _fixture_string(entry, "handle")
        if not HANDLE_RE.match(handle):
            raise ApiError(422, "validation_failed", "handle must match ^[a-z0-9_]{1,20}$")
        if user_id in state.users or handle in state.handles or email in state.emails:
            raise ApiError(422, "validation_failed", "duplicate user id, handle or email")
        balance = _fixture_amount(entry.get("balance"), 0, "balance")
        user = User(user_id, email, hash_password(password), display_name, handle, balance)
        state.users[user_id] = user
        state.handles[handle] = user_id
        state.emails[email] = user_id
    return state


def _seed_payments(state, fixture, reset_now):
    payments = fixture.get("payments", [])
    if not isinstance(payments, list):
        raise ApiError(422, "validation_failed", "payments must be an array")
    stamp = reset_now.isoformat()
    for entry in payments:
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each seeded payment must be an object")
        payment_id = _fixture_string(entry, "id")
        from_user_id = _fixture_string(entry, "from_user_id")
        to_user_id = _fixture_string(entry, "to_user_id")
        if from_user_id not in state.users or to_user_id not in state.users:
            raise ApiError(422, "validation_failed", "seeded payment references an unknown user")
        amount = _fixture_amount(entry.get("amount"), 0, "seeded payment amount")
        created_at = entry.get("created_at")
        if created_at is None:
            created_at = stamp
        else:
            created_dt = parse_rfc3339(created_at, "seeded payment created_at", require_offset=True)
            if created_dt > reset_now:
                raise ApiError(422, "validation_failed",
                               "seeded payment created_at must not be in the future")
        payment = Payment(
            id=payment_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            amount=amount,
            note=_fixture_note(entry),
            visibility=_fixture_visibility(entry),
            request_id=None,
            settlement_id=None,
            effective_at=created_at,
            recorded_at=created_at,
            seq=state.next_seq(),
        )
        state.payments.append(payment)


def _apply_seeded_opening_balances(state):
    net = {user_id: 0 for user_id in state.users}
    for payment in state.payments:
        net[payment.from_user_id] -= payment.amount
        net[payment.to_user_id] += payment.amount
    for user_id, user in state.users.items():
        user.opening_balance = user.balance - net[user_id]


def _check_seeded_history(state):
    running = {user_id: user.opening_balance for user_id, user in state.users.items()}
    if any(value < 0 for value in running.values()):
        raise ApiError(422, "validation_failed",
                       "seeded payment history would overdraw an account")
    by_instant = {}
    for payment in state.payments:
        by_instant.setdefault(as_dt(payment.effective_at), []).append(payment)
    for instant in sorted(by_instant):
        for payment in by_instant[instant]:
            running[payment.from_user_id] -= payment.amount
            running[payment.to_user_id] += payment.amount
        if any(value < 0 for value in running.values()):
            raise ApiError(422, "validation_failed",
                           "seeded payment history would overdraw an account")


def _seed_requests(state, fixture, reset_now):
    requests = fixture.get("requests", [])
    if not isinstance(requests, list):
        raise ApiError(422, "validation_failed", "requests must be an array")
    stamp = reset_now.isoformat()
    for entry in requests:
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each seeded request must be an object")
        request_id = _fixture_string(entry, "id")
        requester_id = _fixture_string(entry, "requester_id")
        payer_id = _fixture_string(entry, "payer_id")
        if requester_id not in state.users or payer_id not in state.users:
            raise ApiError(422, "validation_failed", "seeded request references an unknown user")
        amount = _fixture_amount(entry.get("amount"), 0, "seeded request amount")
        status = entry.get("status", "pending")
        if not isinstance(status, str):
            raise ApiError(422, "validation_failed", "status must be a string")
        request = Request(
            id=request_id,
            requester_id=requester_id,
            payer_id=payer_id,
            amount=amount,
            note=_fixture_note(entry),
            status=status,
            payment_id=None,
            created_at=stamp,
            seq=state.next_seq(),
        )
        state.requests[request_id] = request


def _seed_operators(state, fixture):
    operators = fixture.get("settlement_operator_ids", [])
    if not isinstance(operators, list):
        raise ApiError(422, "validation_failed", "settlement_operator_ids must be an array")
    for operator_id in operators:
        if not isinstance(operator_id, str):
            raise ApiError(422, "validation_failed", "settlement_operator_ids entries must be strings")
        state.settlement_operator_ids.add(operator_id)


def handle_reset(user, body, params, query):
    new_state = build_state_from_fixture(body)
    with STATE_LOCK:
        state_module.STATE = new_state
    return 204, None