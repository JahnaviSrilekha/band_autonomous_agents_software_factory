import unittest
from datetime import datetime, timedelta, timezone

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


class TestT32AuthorizationsPage(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        self.token = _token(self.port)
        self.bob_token = _token(self.port, "bob@example.com")

    def tearDown(self):
        base.stop_server(self.httpd)

    def _seed(self, authorizations):
        base.request(self.port, "POST", "/_test/reset",
                     body=h.seeded_fixture(authorizations))
        self.token = _token(self.port)
        self.bob_token = _token(self.port, "bob@example.com")

    def test_authorize_form_testids(self):
        self._seed([])
        status, body, _ = _get(self.port, "/authorizations", self.token)
        self.assertEqual(status, 200)
        text = body.decode()
        for testid in ("authorize-handle", "authorize-amount", "authorize-note",
                       "authorize-visibility", "authorize-submit", "authorization-list",
                       "empty-authorizations"):
            self.assertIn(f'data-testid="{testid}"', text)
        self.assertNotIn('data-testid="authorize-error"', text)
        self.assertNotIn('data-testid="authorization-error"', text)

    def test_visibility_options_and_wallet_numbers(self):
        self._seed([
            {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 2000, "status": "open", "expires_at": h.future()},
        ])
        status, body, _ = _get(self.port, "/authorizations", self.token)
        text = body.decode()
        self.assertIn('<option value="public">Public</option>', text)
        self.assertIn('<option value="private">Private</option>', text)
        self.assertIn('data-testid="wallet-available" data-amount="8000"', text)
        self.assertIn("80.00 EUR", text)
        self.assertIn('data-testid="wallet-held" data-amount="2000"', text)
        self.assertIn("20.00 EUR", text)
        self.assertIn('data-testid="wallet-balance" data-amount="10000"', text)

    def test_wallet_held_absent_when_zero(self):
        self._seed([])
        status, body, _ = _get(self.port, "/authorizations", self.token)
        self.assertNotIn('data-testid="wallet-held"', body.decode())

    def test_seeded_holds_reflected_immediately(self):
        self._seed([
            {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 500, "status": "open", "expires_at": h.future()},
        ])
        status, body, _ = _get(self.port, "/", self.token)
        text = body.decode()
        self.assertIn('data-testid="wallet-held" data-amount="500"', text)
        self.assertIn('data-testid="wallet-available" data-amount="9500"', text)
        self.assertIn("95.00 EUR", text)

    def test_minor_units_zero_format(self):
        fixture = {**h.BASE_FIXTURE, "minor_units": 0, "currency": "JPY"}
        base.request(self.port, "POST", "/_test/reset", body=fixture)
        self.token = _token(self.port)
        status, body, _ = _get(self.port, "/", self.token)
        self.assertIn("10000 JPY", body.decode())


if __name__ == "__main__":
    unittest.main()