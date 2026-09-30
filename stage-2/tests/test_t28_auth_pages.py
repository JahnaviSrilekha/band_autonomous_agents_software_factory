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


def _signup(port, email="ada@example.com", password="correct horse"):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": password})
    assert status == 200, payload
    return payload["token"]


def _get_html(port, path, token=None):
    return _get(port, path, token)


class TestT28AuthPages(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_signup_page_has_all_testids(self):
        status, body, headers = _get_html(self.port, "/signup")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        for testid in ("signup-email", "signup-password", "signup-display-name",
                       "signup-submit"):
            self.assertIn(f'data-testid="{testid}"', body.decode())

    def test_login_page_has_all_testids(self):
        status, body, _ = _get_html(self.port, "/login")
        self.assertEqual(status, 200)
        for testid in ("login-email", "login-password", "login-submit"):
            self.assertIn(f'data-testid="{testid}"', body.decode())

    def test_auth_error_absent_initially(self):
        status, body, _ = _get_html(self.port, "/login")
        self.assertEqual(status, 200)
        self.assertNotIn('data-testid="auth-error"', body.decode())

    def test_static_app_js_served(self):
        status, body, headers = _get_html(self.port, "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("Content-Type", ""))
        self.assertIn(b"pocketful", body)

    def test_no_cdn_links_in_pages(self):
        token = _signup(self.port)
        for path in ("/login", "/signup", "/"):
            status, body, _ = _get_html(self.port, path, token=token)
            text = body.decode()
            self.assertNotIn("https://cdn", text)
            self.assertNotIn("http://cdn", text)
            self.assertNotIn("unpkg.com", text)
            self.assertNotIn("jsdelivr", text)

    def test_signed_in_header_elements_on_every_screen(self):
        token = _signup(self.port)
        for path in ("/", "/requests", "/split", "/authorizations", "/login", "/signup"):
            status, body, _ = _get_html(self.port, path, token=token)
            self.assertEqual(status, 200, path)
            text = body.decode()
            self.assertIn('data-testid="current-user"', text, path)
            self.assertIn(">Ada</span>", text, path)
            self.assertIn('data-testid="current-handle">ada</span>', text, path)
            self.assertIn('data-testid="logout-button"', text, path)

    def test_requests_route_content_negotiation(self):
        token = _signup(self.port)
        status, body, headers = _get_html(self.port, "/requests", token=token)
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        status, body, _ = base.request(self.port, "GET", "/requests",
                                       headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"requests": [], "has_more": False})

    def test_unknown_static_file_404(self):
        status, body, _ = _get_html(self.port, "/static/nope.js")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()