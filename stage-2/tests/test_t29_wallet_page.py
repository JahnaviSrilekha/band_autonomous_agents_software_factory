import json
import unittest

import base
import helpers_t2 as h


def _get(port, path, token=None):
    import urllib.request
    import urllib.error

    headers = {"Accept": "text/html"}
    if token:
        headers["Cookie"] = "pocketful_token=" + token
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _token(port, email="ada@example.com"):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": "correct horse"})
    assert status == 200, payload
    return payload["token"]


def _html(port, path, token=None):
    return _get(port, path, token)


class TestT29WalletPage(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        self.token = _token(self.port)

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_wallet_page_has_pay_and_request_form_testids(self):
        status, body, _ = _html(self.port, "/", self.token)
        self.assertEqual(status, 200)
        text = body.decode()
        for testid in ("wallet-balance", "pay-handle", "pay-amount", "pay-note",
                       "pay-visibility", "pay-submit", "request-handle", "request-amount",
                       "request-note", "request-submit", "activity-list", "wallet-refresh"):
            self.assertIn(f'data-testid="{testid}"', text)
        self.assertNotIn('data-testid="pay-error"', text)
        self.assertNotIn('data-testid="pay-uncertain"', text)
        self.assertNotIn('data-testid="request-error"', text)

    def test_pay_visibility_options_are_public_private(self):
        status, body, _ = _html(self.port, "/", self.token)
        text = body.decode()
        self.assertIn('<option value="public">Public</option>', text)
        self.assertIn('<option value="private">Private</option>', text)

    def test_activity_empty_state_present_in_markup(self):
        status, body, _ = _html(self.port, "/", self.token)
        text = body.decode()
        self.assertIn('data-testid="empty-activity"', text)

    def test_signed_out_wallet_shows_login(self):
        status, body, _ = _html(self.port, "/")
        self.assertEqual(status, 200)
        text = body.decode()
        self.assertIn('data-testid="login-submit"', text)
        self.assertNotIn("pay-submit", text)

    def test_authorized_page_negotiation_with_accept_header(self):
        status, body, headers = _html(self.port, "/authorizations", self.token)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        status, body, _ = base.request(self.port, "GET", "/authorizations",
                                       headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"authorizations": [], "has_more": False})

    def test_stylesheet_referenced_and_bundled(self):
        status, body, _ = _html(self.port, "/", self.token)
        self.assertIn('href="/static/styles.css"', body.decode())
        status, css, _ = _html(self.port, "/static/styles.css")
        self.assertIn("box-sizing: border-box", css.decode())

    def test_app_js_has_no_outbound_references(self):
        status, body, _ = _html(self.port, "/static/app.js")
        text = body.decode()
        self.assertNotIn("https://", text.replace("https://pocketful.invalid", ""))
        for marker in ("cdn.", "googleapis", "unpkg", "jsdelivr"):
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()