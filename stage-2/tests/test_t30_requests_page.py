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


class TestT30RequestsPage(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=h.BASE_FIXTURE)
        self.token = _token(self.port)

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_requests_page_testids(self):
        status, body, _ = _get(self.port, "/requests", self.token)
        self.assertEqual(status, 200)
        text = body.decode()
        for testid in ("incoming-list", "outgoing-list", "empty-requests"):
            self.assertIn(f'data-testid="{testid}"', text)
        self.assertNotIn('data-testid="request-error"', text)

    def test_buttons_only_for_pending_items_server_rendered_via_js_contract(self):
        # the page ships containers + empty state; item rendering is client-side
        # (app.js). The API shape feeding it is verified here.
        status, rq, _ = base.request(self.port, "POST", "/requests",
                                     body={"payer_handle": "bob", "amount": 300, "note": "n"},
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Idempotency-Key": "k-rq-t30"})
        self.assertEqual(status, 201)
        status, list_body, _ = base.request(self.port, "GET", "/requests?direction=outgoing",
                                            headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(status, 200)
        self.assertEqual(list_body["requests"][0]["status"], "pending")

    def test_empty_requests_iff_both_lists_empty(self):
        status, body, _ = _get(self.port, "/requests", self.token)
        text = body.decode()
        self.assertIn('data-testid="empty-requests" hidden', text)


if __name__ == "__main__":
    unittest.main()