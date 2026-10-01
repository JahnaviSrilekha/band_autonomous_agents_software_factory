import re
import unittest
from urllib.parse import unquote

import base
import helpers_t2 as h


ROUTES = ("/", "/requests", "/split", "/authorizations")


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


def _input_ids(html_text):
    return re.findall(r'<input[^>]*id="([^"]+)"', html_text)


def _label_fors(html_text):
    return set(re.findall(r'<label[^>]*for="([^"]+)"', html_text))


class TestT35AccessibilitySweep(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        status, payload, _ = base.request(self.port, "POST", "/auth/login",
                                          body={"email": "ada@example.com",
                                                "password": "correct horse"})
        self.token = payload["token"]

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_every_input_has_a_visible_label(self):
        pages = {path: _get(self.port, path, self.token)[1].decode()
                 for path in ROUTES + ("/login", "/signup")}
        for path, text in pages.items():
            for input_id in _input_ids(text):
                self.assertIn(input_id, _label_fors(text), f"{path}: input {input_id} unlabeled")

    def test_nav_identical_across_routes(self):
        navs = {}
        for path in ROUTES:
            _, body, _ = _get(self.port, path, self.token)
            match = re.search(r'<nav class="nav"[^>]*>(.*?)</nav>', body.decode(), re.S)
            self.assertIsNotNone(match, path)
            pairs = re.findall(r'href="([^"]+)">([^<]+)</a>', match.group(1))
            self.assertEqual(pairs, [('/', 'Home'), ('/requests', 'Requests'),
                                     ('/split', 'Split'),
                                     ('/authorizations', 'Authorizations')], path)
            navs[path] = pairs

    def test_empty_states_present_and_considered(self):
        for path, marker, phrase in (
                ("/", "empty-activity", "No payments"),
                ("/requests", "empty-requests", "No requests"),
                ("/authorizations", "empty-authorizations", "No authorizations")):
            _, body, _ = _get(self.port, path, self.token)
            text = body.decode()
            self.assertIn(f'data-testid="{marker}"', text, path)
            self.assertIn(phrase, text, path)

    def test_focus_visible_and_contrast_tokens_in_css(self):
        status, css, _ = _get(self.port, "/static/styles.css")
        text = css.decode()
        self.assertIn(":focus-visible", text)
        self.assertIn("outline: 2px solid", text)
        # AA contrast tokens: ink on light backgrounds
        self.assertIn("--ink: #16233b", text)
        self.assertIn("--bg: #f4f7fb", text)

    def test_viewport_meta_and_fluid_layout(self):
        _, body, _ = _get(self.port, "/", self.token)
        text = body.decode()
        self.assertIn('name="viewport"', text)
        self.assertIn("box-sizing", _get(self.port, "/static/styles.css")[1].decode())

    def test_error_states_styled(self):
        status, css, _ = _get(self.port, "/static/styles.css")
        text = css.decode()
        for marker in ("form-msg--error", "form-msg--uncertain", "form-msg--success",
                       "pill--pending", "pill--captured", "pill--voided", "pill--expired",
                       "amount--available", "amount--held", "amount--total"):
            self.assertIn(marker, text, f"missing state style {marker}")


if __name__ == "__main__":
    unittest.main()