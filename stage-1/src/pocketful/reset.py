import math
import re

from .errors import ApiError
from . import state as state_module
from .state import (
    STATE_LOCK, Payment, Request, State, User, hash_password,
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


def build_state_from_fixture(fixture):
    state = _build_users(fixture)
    _seed_payments(state, fixture)
    _seed_requests(state, fixture)
    _seed_operators(state, fixture)
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


def _seed_payments(state, fixture):
    payments = fixture.get("payments", [])
    if not isinstance(payments, list):
        raise ApiError(422, "validation_failed", "payments must be an array")
    stamp = state_module.now_iso()
    for entry in payments:
        if not isinstance(entry, dict):
            raise ApiError(422, "validation_failed", "each seeded payment must be an object")
        payment_id = _fixture_string(entry, "id")
        from_user_id = _fixture_string(entry, "from_user_id")
        to_user_id = _fixture_string(entry, "to_user_id")
        if from_user_id not in state.users or to_user_id not in state.users:
            raise ApiError(422, "validation_failed", "seeded payment references an unknown user")
        amount = _fixture_amount(entry.get("amount"), 0, "seeded payment amount")
        payment = Payment(
            id=payment_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            amount=amount,
            note=_fixture_note(entry),
            visibility=_fixture_visibility(entry),
            request_id=None,
            settlement_id=None,
            effective_at=stamp,
            recorded_at=stamp,
            seq=state.next_seq(),
        )
        state.payments.append(payment)


def _seed_requests(state, fixture):
    requests = fixture.get("requests", [])
    if not isinstance(requests, list):
        raise ApiError(422, "validation_failed", "requests must be an array")
    stamp = state_module.now_iso()
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