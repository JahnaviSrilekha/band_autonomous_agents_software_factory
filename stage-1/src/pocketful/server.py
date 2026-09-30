import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import ApiError, error_body, parse_json_body

MAX_BODY_BYTES = 16 * 1024 * 1024


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256


class Route:
    def __init__(self, method, pattern, handler, auth=False, idem=False, operator=False):
        self.method = method
        self.pattern = re.compile(pattern)
        self.handler = handler
        self.auth = auth
        self.idem = idem
        self.operator = operator


ROUTES = []


def _health(user, body, params, query):
    return 200, {"status": "ok"}


ROUTES.append(Route("GET", r"^/health$", _health))


def _add_reset_route():
    from .reset import handle_reset

    ROUTES.append(Route("POST", r"^/_test/reset$", handle_reset))


_add_reset_route()


def _authenticate(headers):
    from . import state as state_module

    header = headers.get("Authorization")
    if not header:
        raise ApiError(401, "unauthenticated", "bearer token required")
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ApiError(401, "unauthenticated", "malformed authorization header")
    token = parts[1].strip()
    if not token:
        raise ApiError(401, "unauthenticated", "missing bearer token")
    state = state_module.STATE
    with state_module.STATE_LOCK:
        user_id = state.tokens.get(token)
        user = state.users.get(user_id) if user_id is not None else None
    if user is None:
        raise ApiError(401, "unauthenticated", "unknown bearer token")
    return user


def _check_operator(user):
    from . import state as state_module

    with state_module.STATE_LOCK:
        if user.id not in state_module.STATE.settlement_operator_ids:
            raise ApiError(403, "forbidden", "operator permission required")


class Handler(BaseHTTPRequestHandler):
    server_version = "Pocketful/1"
    protocol_version = "HTTP/1.1"
    timeout = 60

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _send(self, status, payload):
        body = b""
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            if payload is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_body(self):
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            return b""
        try:
            length = int(length_header)
        except ValueError:
            raise ApiError(400, "malformed_request", "invalid Content-Length header")
        if length < 0 or length > MAX_BODY_BYTES:
            raise ApiError(400, "malformed_request", "unsupported request body size")
        data = self.rfile.read(length)
        if data is None or len(data) < length:
            raise ApiError(400, "malformed_request", "truncated request body")
        return data

    def _dispatch(self, method):
        try:
            status, payload = self._handle(method)
        except ApiError as exc:
            status, payload = exc.status, error_body(exc.code, exc.message)
        except Exception:
            status, payload = 500, error_body("internal_error", "unexpected server error")
        self._send(status, payload)

    def _handle(self, method):
        split = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(split.path)
        query = urllib.parse.parse_qs(split.query, keep_blank_values=True)
        route = None
        match = None
        for candidate in ROUTES:
            if candidate.method != method:
                continue
            found = candidate.pattern.match(path)
            if found:
                route = candidate
                match = found
                break
        if route is None:
            raise ApiError(404, "not_found", "no such resource")
        body = None
        if method == "POST":
            body = parse_json_body(self._read_body())
        user = None
        if route.auth:
            user = _authenticate(self.headers)
        if route.operator:
            _check_operator(user)
        if route.idem:
            from .idempotency import run_idempotent

            return run_idempotent(route, user, method, path, self.headers, body, match, query)
        return route.handler(user, body, match, query)


def make_server(port):
    return _Server(("0.0.0.0", port), Handler)