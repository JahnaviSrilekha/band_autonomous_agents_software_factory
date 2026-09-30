import hashlib
import hmac
import os
import threading
import uuid
from datetime import datetime, timezone

STATE_LOCK = threading.RLock()

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1


def now_iso():
    return datetime.now(timezone.utc).isoformat()


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
    def __init__(self, id, email, password_hash, display_name, handle, balance):
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.display_name = display_name
        self.handle = handle
        self.balance = balance


class Payment:
    def __init__(self, id, from_user_id, to_user_id, amount, note, visibility,
                 request_id, settlement_id, effective_at, recorded_at, seq):
        self.id = id
        self.from_user_id = from_user_id
        self.to_user_id = to_user_id
        self.amount = amount
        self.note = note
        self.visibility = visibility
        self.request_id = request_id
        self.settlement_id = settlement_id
        self.effective_at = effective_at
        self.recorded_at = recorded_at
        self.seq = seq


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


class State:
    def __init__(self):
        self.currency = "EUR"
        self.minor_units = 2
        self.settlement_operator_ids = set()
        self.users = {}
        self.handles = {}
        self.emails = {}
        self.tokens = {}
        self.payments = []
        self.requests = {}
        self.splits = {}
        self.settlements = {}
        self.idempotency = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


STATE = State()