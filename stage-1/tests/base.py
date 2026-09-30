import json
import os
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pocketful import server as server_module


def reset_state():
    from pocketful import state as state_module
    from pocketful.state import State

    state_module.STATE = State()


def make_server():
    httpd = server_module.make_server(0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def stop_server(httpd):
    httpd.shutdown()
    httpd.server_close()


def request(port, method, path, body=None, headers=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    return _send(port, method, path, data, headers)


def request_raw(port, method, path, data=None, headers=None):
    return _send(port, method, path, data, headers)


def _send(port, method, path, data, headers):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            payload = json.loads(raw) if raw else None
            return resp.status, payload, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        payload = json.loads(raw) if raw else None
        return exc.code, payload, dict(exc.headers)