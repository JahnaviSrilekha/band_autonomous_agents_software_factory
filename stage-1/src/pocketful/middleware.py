from .errors import ApiError
from . import state as state_module


def authenticate(headers):
    header = headers.get("Authorization")
    if not header:
        raise ApiError(401, "unauthenticated", "bearer token required")
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ApiError(401, "unauthenticated", "malformed authorization header")
    token = parts[1].strip()
    if not token:
        raise ApiError(401, "unauthenticated", "missing bearer token")
    with state_module.STATE_LOCK:
        state = state_module.STATE
        user_id = state.tokens.get(token)
        user = state.users.get(user_id) if user_id is not None else None
    if user is None:
        raise ApiError(401, "unauthenticated", "unknown bearer token")
    return user