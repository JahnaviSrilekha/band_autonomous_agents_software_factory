import hashlib
import hmac
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

STATE_LOCK = threading.RLock()

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def now_dt():
    return datetime.now(timezone.utc)


def parse_rfc3339(value, what="timestamp", require_offset=False):
    from .errors import ApiError

    if not isinstance(value, str) or not value:
        raise ApiError(422, "validation_failed", f"{what} must be an RFC 3339 timestamp string")
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(422, "validation_failed", f"{what} must be an RFC 3339 timestamp")
    if parsed.tzinfo is None:
        if require_offset:
            raise ApiError(422, "validation_failed", f"{what} must include a UTC offset")
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def as_dt(value):
    if isinstance(value, datetime):
        return value
    return parse_rfc3339(value)


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def new_token():
    import secrets

    return secrets.token_urlsafe(32)


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(stored, password):
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
            dklen=len(expected),
        )
        return hmac.compare_digest(candidate, expected)
    except (ValueError, TypeError):
        return False


class User:
    def __init__(self, id, email, password_hash, display_name, handle, balance,
                 opening_balance=None):
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.display_name = display_name
        self.handle = handle
        self.balance = balance
        self.opening_balance = balance if opening_balance is None else opening_balance


class Revision:
    def __init__(self, revision, amount, effective_at, recorded_at, reason):
        self.revision = revision
        self.amount = amount
        self.effective_at = effective_at
        self.recorded_at = recorded_at
        self.reason = reason

    def to_json(self):
        return {
            "revision": self.revision,
            "amount": self.amount,
            "effective_at": self.effective_at,
            "recorded_at": self.recorded_at,
            "reason": self.reason,
        }


def make_revision_1(amount, created_at):
    return Revision(1, amount, created_at, created_at, "")


class Payment:
    def __init__(self, id, from_user_id, to_user_id, amount, note, visibility,
                 request_id, settlement_id, effective_at, recorded_at, seq,
                 authorization_id=None, revisions=None):
        self.id = id
        self.from_user_id = from_user_id
        self.to_user_id = to_user_id
        self.note = note
        self.visibility = visibility
        self.request_id = request_id
        self.settlement_id = settlement_id
        self.effective_at = effective_at
        self.recorded_at = recorded_at
        self.seq = seq
        self.authorization_id = authorization_id
        self.revisions = (list(revisions) if revisions is not None
                          else [make_revision_1(amount, effective_at)])

    @property
    def amount(self):
        return self.revisions[-1].amount

    def append_revision(self, amount, effective_at, recorded_at, reason):
        last = self.revisions[-1]
        recorded_dt = as_dt(recorded_at)
        last_dt = as_dt(last.recorded_at)
        if recorded_dt <= last_dt:
            recorded_dt = last_dt + timedelta(microseconds=1)
            recorded_at = recorded_dt.isoformat()
        revision = Revision(last.revision + 1, amount, effective_at, recorded_at, reason)
        self.revisions.append(revision)
        return revision


class Request:
    def __init__(self, id, requester_id, payer_id, amount, note, status, payment_id,
                 created_at, seq):
        self.id = id
        self.requester_id = requester_id
        self.payer_id = payer_id
        self.amount = amount
        self.note = note
        self.status = status
        self.payment_id = payment_id
        self.created_at = created_at
        self.seq = seq


class Split:
    def __init__(self, id, caller_id, amount, note, participant_handles, shares,
                 request_ids, created_at, seq):
        self.id = id
        self.caller_id = caller_id
        self.amount = amount
        self.note = note
        self.participant_handles = participant_handles
        self.shares = shares
        self.request_ids = request_ids
        self.created_at = created_at
        self.seq = seq


class Settlement:
    def __init__(self, id, operator_id, transfers, payment_ids, committed_at, seq):
        self.id = id
        self.operator_id = operator_id
        self.transfers = transfers
        self.payment_ids = payment_ids
        self.committed_at = committed_at
        self.seq = seq


class IdempotencyRecord:
    def __init__(self, user_id, method, path, key, request_body, status,
                 response_status, response_body):
        self.user_id = user_id
        self.method = method
        self.path = path
        self.key = key
        self.request_body = request_body
        self.status = status
        self.response_status = response_status
        self.response_body = response_body


AUTHORIZATION_STATUSES = ("open", "captured", "voided", "expired")


class Authorization:
    def __init__(self, id, from_user_id, to_user_id, amount, note, visibility, status,
                 captured_amount, payment_ids, created_at, expires_at, expires_dt,
                 created_dt=None, seq=0, closed_event_dt=None):
        self.id = id
        self.from_user_id = from_user_id
        self.to_user_id = to_user_id
        self.amount = amount
        self.note = note
        self.visibility = visibility
        self.status = status
        self.captured_amount = captured_amount
        self.payment_ids = payment_ids
        self.created_at = created_at
        self.created_dt = created_dt if created_dt is not None else parse_rfc3339(created_at, "created_at")
        self.expires_at = expires_at
        self.expires_dt = expires_dt
        self.seq = seq
        self.closed_event_dt = closed_event_dt


def is_live_hold(auth, now):
    return auth.status == "open" and auth.expires_dt > now


def effective_status(auth, now):
    if auth.status == "open" and auth.expires_dt <= now:
        return "expired"
    return auth.status


def remaining_amount(auth, now):
    if not is_live_hold(auth, now):
        return 0
    return auth.amount - auth.captured_amount


def held(state, user_id, now):
    return sum(a.amount - a.captured_amount
               for a in state.authorizations.values()
               if a.from_user_id == user_id and is_live_hold(a, now))


def _known_close_instant(auth, known):
    if auth.status in ("captured", "voided"):
        event = auth.closed_event_dt
        if event is None:
            return None
        if known is None or event <= known:
            return event
        return None
    return None


def is_live_hold_at(auth, at, known_at=None):
    at_dt = as_dt(at)
    known = as_dt(known_at) if known_at is not None else None
    created = as_dt(auth.created_dt)
    if known is not None and created > known:
        return False
    if created > at_dt:
        return False
    close = _known_close_instant(auth, known)
    if close is None:
        return at_dt < auth.expires_dt
    return at_dt < close


def historical_held(state, user_id, at, known_at=None):
    at_dt = as_dt(at)
    known = as_dt(known_at) if known_at is not None else None
    total = 0
    for auth in state.authorizations.values():
        if auth.from_user_id != user_id:
            continue
        if not is_live_hold_at(auth, at_dt, known):
            continue
        captured = 0
        for payment in state.payments:
            if payment.authorization_id != auth.id:
                continue
            if known is not None and as_dt(payment.recorded_at) > known:
                continue
            if as_dt(payment.effective_at) <= at_dt:
                captured += payment.amount
        total += auth.amount - captured
    return total


def available(state, user_id, now):
    return state.users[user_id].balance - held(state, user_id, now)


def selected_revision(payment, known_at):
    if known_at is None:
        return payment.revisions[-1]
    eligible = [r for r in payment.revisions if as_dt(r.recorded_at) <= known_at]
    return eligible[-1] if eligible else None


def historical_balance(state, user_id, as_of, known_at=None, inclusive=True):
    user = state.users.get(user_id)
    if user is None:
        return 0
    balance = user.opening_balance
    for payment in state.payments:
        if payment.from_user_id != user_id and payment.to_user_id != user_id:
            continue
        revision = selected_revision(payment, known_at)
        if revision is None:
            continue
        effective = as_dt(revision.effective_at)
        if effective > as_of or (not inclusive and effective >= as_of):
            continue
        balance += revision.amount if payment.to_user_id == user_id else -revision.amount
    return balance


def check_correction_funds(state, payment, new_amount, effective_dt, now):
    from .errors import ApiError

    old_amount = payment.revisions[-1].amount
    delta = new_amount - old_amount
    if delta != 0:
        debtor = payment.from_user_id if delta > 0 else payment.to_user_id
        if available(state, debtor, now) < abs(delta):
            raise ApiError(409, "insufficient_funds",
                           "correction debit exceeds the debtor's available funds")
    _check_historical_overdraft(state, payment, new_amount, effective_dt, now)


def _check_historical_overdraft(state, payment, new_amount, effective_dt, now):
    from .errors import ApiError

    parties = (payment.from_user_id, payment.to_user_id)
    movements = {user_id: {} for user_id in parties}
    for other in state.payments:
        if other.from_user_id not in parties and other.to_user_id not in parties:
            continue
        if other.id == payment.id:
            instant = effective_dt
            amount = new_amount
        else:
            revision = selected_revision(other, None)
            if revision is None:
                continue
            instant = as_dt(revision.effective_at)
            amount = revision.amount
        if instant > now:
            continue
        movements[other.from_user_id][instant] = (
            movements[other.from_user_id].get(instant, 0) - amount)
        movements[other.to_user_id][instant] = (
            movements[other.to_user_id].get(instant, 0) + amount)
    running = {user_id: state.users[user_id].opening_balance for user_id in parties}
    if any(value < 0 for value in running.values()):
        raise ApiError(409, "historical_overdraft",
                       "correction would overdraw a historical balance")
    instants = {instant for per_user in movements.values() for instant in per_user}
    for auth in state.authorizations.values():
        if auth.from_user_id not in parties:
            continue
        if as_dt(auth.created_dt) <= now:
            instants.add(as_dt(auth.created_dt))
        if auth.closed_event_dt is not None and auth.closed_event_dt <= now:
            instants.add(auth.closed_event_dt)
        if auth.status == "open" and auth.expires_dt <= now:
            instants.add(auth.expires_dt)
    for instant in sorted(instants):
        for user_id in parties:
            running[user_id] += movements[user_id].get(instant, 0)
        for user_id in parties:
            total = running[user_id]
            if total < 0:
                raise ApiError(409, "historical_overdraft",
                               "correction would overdraw a historical balance")
            if total - historical_held(state, user_id, instant) < 0:
                raise ApiError(409, "historical_overdraft",
                               "correction would overdraw a historical availability")


class State:
    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.authorization_ttl_seconds = 600
        self.settlement_operator_ids = set()
        self.users = {}
        self.handles = {}
        self.emails = {}
        self.tokens = {}
        self.payments = []
        self.requests = {}
        self.splits = {}
        self.settlements = {}
        self.authorizations = {}
        self.idempotency = {}
        self.statement_snapshots = {}
        self.reset_epoch = 0
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


STATE = State()