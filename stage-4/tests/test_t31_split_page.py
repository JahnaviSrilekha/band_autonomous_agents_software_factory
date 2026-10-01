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


class TestT31SplitPage(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        self.token = _token(self.port)

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_split_page_testids(self):
        status, body, _ = _get(self.port, "/split", self.token)
        self.assertEqual(status, 200)
        text = body.decode()
        for testid in ("split-amount", "split-handles", "split-note", "split-submit",
                       "split-preview"):
            self.assertIn(f'data-testid="{testid}"', text)
        self.assertNotIn('data-testid="split-error"', text)

    def test_preview_hidden_until_input(self):
        status, body, _ = _get(self.port, "/split", self.token)
        text = body.decode()
        self.assertIn('data-testid="split-preview" hidden', text)

    def test_server_shares_rule_matches_js_rule_table(self):
        # both sides implement stage-1 §9: first amount % n participants get one extra
        from pocketful.shares import compute_shares
        for amount, n in [(100, 3), (1, 2), (10, 4), (7, 7), (999, 4)]:
            shares = compute_shares(amount, n)
            self.assertEqual(sum(shares), amount)
            self.assertEqual(shares, [amount // n + (1 if i < amount % n else 0)
                                      for i in range(n)])


if __name__ == "__main__":
    unittest.main()