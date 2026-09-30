from .errors import ApiError
from . import state as state_module
from .state import STATE_LOCK, IdempotencyRecord

MAX_KEY_LENGTH = 255


def json_equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(json_equal(a[key], b[key]) for key in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return a == b


def canonicalize(value):
    if isinstance(value, dict):
        return {key: canonicalize(value[key]) for key in sorted(value.keys())}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    return value


def read_key(headers):
    key = headers.get("Idempotency-Key")
    if key is None or key == "":
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    if len(key) > MAX_KEY_LENGTH:
        raise ApiError(422, "validation_failed", "Idempotency-Key must be at most 255 characters")
    return key


def run_idempotent(route, user, method, path, headers, body, params, query):
    key = read_key(headers)
    record_key = (user.id, method, path, key)
    with STATE_LOCK:
        state = state_module.STATE
        existing = state.idempotency.get(record_key)
        if existing is not None:
            if json_equal(existing.request_body, body):
                return 200, existing.response_body
            raise ApiError(409, "idempotency_key_reuse", "key already used with a different request body")
        record = IdempotencyRecord(
            user_id=user.id,
            method=method,
            path=path,
            key=key,
            request_body=canonicalize(body),
            status="in_flight",
            response_status=None,
            response_body=None,
        )
        state.idempotency[record_key] = record
        try:
            status, payload = route.handler(user, body, params, query)
        except ApiError:
            del state.idempotency[record_key]
            raise
        record.status = "done"
        record.response_status = status
        record.response_body = payload
        return status, payload