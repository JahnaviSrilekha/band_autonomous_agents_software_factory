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


def _check_operator(user):
    from . import state as state_module

    with state_module.STATE_LOCK:
        if user.id not in state_module.STATE.settlement_operator_ids:
            raise ApiError(403, "forbidden", "operator permission required")


def _add_auth_routes():
    from .auth import login, signup
    from .handlers.me import get_me

    ROUTES.append(Route("POST", r"^/auth/signup$", signup))
    ROUTES.append(Route("POST", r"^/auth/login$", login))
    ROUTES.append(Route("GET", r"^/me$", get_me, auth=True))


_add_auth_routes()


def _add_wallet_routes():
    from .handlers.activity import list_activity
    from .handlers.payments import create_payment
    from .handlers.requests import (
        cancel_request, create_request, decline_request, list_requests, pay_request,
    )

    ROUTES.append(Route("POST", r"^/payments$", create_payment, auth=True, idem=True))
    ROUTES.append(Route("POST", r"^/requests$", create_request, auth=True, idem=True))
    ROUTES.append(Route("POST", r"^/requests/(?P<id>[^/]+)/pay$", pay_request, auth=True, idem=True))
    ROUTES.append(Route("POST", r"^/requests/(?P<id>[^/]+)/decline$", decline_request, auth=True))
    ROUTES.append(Route("POST", r"^/requests/(?P<id>[^/]+)/cancel$", cancel_request, auth=True))
    ROUTES.append(Route("GET", r"^/requests$", list_requests, auth=True))
    ROUTES.append(Route("GET", r"^/activity$", list_activity, auth=True))


_add_wallet_routes()


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
            from .middleware import authenticate

            user = authenticate(self.headers)
        if route.operator:
            _check_operator(user)
        if route.idem:
            from .idempotency import run_idempotent

            return run_idempotent(route, user, method, path, self.headers, body, match, query)
        return route.handler(user, body, match, query)


def make_server(port):
    return _Server(("0.0.0.0", port), Handler)