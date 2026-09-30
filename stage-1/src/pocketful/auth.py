import re

from .errors import ApiError, require_string
from . import state as state_module
from .state import STATE_LOCK, User, hash_password, new_id, new_token, verify_password

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")


def derive_handle(email):
    local = email.split("@", 1)[0].lower()
    cleaned = re.sub(r"[^a-z0-9_]", "_", local)
    return cleaned[:20]


def signup(user, body, params, query):
    email = require_string(body, "email")
    password = require_string(body, "password")
    display_name = require_string(body, "display_name")
    if not EMAIL_RE.match(email):
        raise ApiError(422, "validation_failed", "email must be of the form local@domain")
    if len(password) < 8:
        raise ApiError(422, "validation_failed", "password must be at least 8 characters")
    password_hash = hash_password(password)
    handle = derive_handle(email)
    with STATE_LOCK:
        state = state_module.STATE
        if email in state.emails:
            raise ApiError(409, "email_taken", "email already registered")
        if handle in state.handles:
            raise ApiError(409, "handle_taken", "derived handle already taken")
        user_id = new_id("u")
        token = new_token()
        state.users[user_id] = User(user_id, email, password_hash, display_name, handle, 0)
        state.handles[handle] = user_id
        state.emails[email] = user_id
        state.tokens[token] = user_id
    return 201, {"user_id": user_id, "display_name": display_name, "token": token}


def login(user, body, params, query):
    email = require_string(body, "email")
    password = require_string(body, "password")
    with STATE_LOCK:
        state = state_module.STATE
        user_id = state.emails.get(email)
        stored_hash = state.users[user_id].password_hash if user_id is not None else None
        display_name = state.users[user_id].display_name if user_id is not None else None
    if stored_hash is None or not verify_password(stored_hash, password):
        raise ApiError(401, "unauthenticated", "unknown email or wrong password")
    token = new_token()
    with STATE_LOCK:
        state_module.STATE.tokens[token] = user_id
    return 200, {"user_id": user_id, "display_name": display_name, "token": token}