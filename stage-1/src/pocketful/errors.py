import json
import math


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_body(code, message):
    return {"error": {"code": code, "message": message}}


def parse_json_body(raw):
    if raw is None or len(raw) == 0:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ApiError(400, "malformed_request", "request body is not valid JSON")
    if not isinstance(value, dict):
        raise ApiError(400, "malformed_request", "request body must be a JSON object")
    return value


def require_string(body, name):
    if name not in body:
        raise ApiError(422, "validation_failed", f"{name} is required")
    value = body[name]
    if not isinstance(value, str):
        raise ApiError(400, "malformed_request", f"{name} must be a string")
    return value


def parse_amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(422, "validation_failed", "amount must be a number")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ApiError(422, "validation_failed", "amount must be an integer")
    if value < 1 or value > 1000000000:
        raise ApiError(422, "validation_failed", "amount must be between 1 and 1000000000")
    return int(value)


def parse_note(body):
    if "note" not in body:
        return ""
    value = body["note"]
    if not isinstance(value, str):
        raise ApiError(422, "validation_failed", "note must be a string")
    if len(value) > 200:
        raise ApiError(422, "validation_failed", "note must be at most 200 characters")
    return value


def parse_visibility(body):
    if "visibility" not in body:
        return "public"
    value = body["visibility"]
    if value not in ("public", "private"):
        raise ApiError(422, "validation_failed", 'visibility must be "public" or "private"')
    return value


def parse_limit_offset(query):
    limit = 50
    offset = 0
    raw_limit = _query_single(query, "limit")
    if raw_limit is not None:
        if not _is_decimal_digits(raw_limit):
            raise ApiError(422, "validation_failed", "limit must be a plain decimal integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 200:
            raise ApiError(422, "validation_failed", "limit must be between 1 and 200")
    raw_offset = _query_single(query, "offset")
    if raw_offset is not None:
        if not _is_decimal_digits(raw_offset):
            raise ApiError(422, "validation_failed", "offset must be a plain decimal integer")
        offset = int(raw_offset)
    return limit, offset


def _query_single(query, name):
    values = query.get(name)
    if not values:
        return None
    return values[0]


def _is_decimal_digits(value):
    return len(value) > 0 and all(c in "0123456789" for c in value)