import unittest

import base
from pocketful import state as state_module
from pocketful.auth import derive_handle
from pocketful.state import verify_password

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
    ],
    "payments": [],
    "requests": [],
}


def signup(port, body, expect=201):
    return base.request(port, "POST", "/auth/signup", body=body)


class TestSignup(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.reset_state()

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_signup_happy_path_201_shape(self):
        status, payload, _ = signup(self.port, {
            "email": "a@example.com", "password": "correct horse", "display_name": "Ada",
        })
        self.assertEqual(status, 201)
        self.assertEqual(set(payload.keys()), {"user_id", "display_name", "token"})
        self.assertEqual(payload["display_name"], "Ada")
        state = state_module.STATE
        user = state.users[payload["user_id"]]
        self.assertEqual(user.balance, 0)
        self.assertEqual(user.handle, "a")
        self.assertEqual(state.handles["a"], payload["user_id"])
        self.assertNotEqual(user.password_hash, "correct horse")
        self.assertTrue(verify_password(user.password_hash, "correct horse"))

    def test_email_taken_409(self):
        signup(self.port, {"email": "a@example.com", "password": "password1", "display_name": "A"})
        status, payload, _ = signup(self.port, {
            "email": "a@example.com", "password": "password2", "display_name": "B",
        })
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "email_taken")

    def test_email_matching_is_case_sensitive(self):
        first = signup(self.port, {"email": "a@example.com", "password": "password1", "display_name": "A"})
        self.assertEqual(first[0], 201)
        second = signup(self.port, {"email": "A@example.com", "password": "password2", "display_name": "B"})
        self.assertEqual(second[0], 409)
        self.assertEqual(second[1]["error"]["code"], "handle_taken")

    def test_short_password_422(self):
        status, payload, _ = signup(self.port, {
            "email": "a@example.com", "password": "short", "display_name": "A",
        })
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "validation_failed")

    def test_bad_email_format_422(self):
        for email in ("nodomain", "@example.com", "a@", "a@b@c", "a b@example.com", "a@ example.com"):
            status, payload, _ = signup(self.port, {
                "email": email, "password": "password1", "display_name": "A",
            })
            self.assertEqual(status, 422, email)
            self.assertEqual(payload["error"]["code"], "validation_failed", email)

    def test_missing_fields_422_wrong_type_400(self):
        base_cases = {"email": "a@example.com", "password": "password1", "display_name": "A"}
        for field in ("email", "password", "display_name"):
            body = dict(base_cases)
            del body[field]
            status, payload, _ = signup(self.port, body)
            self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"), field)
        for field in ("email", "password", "display_name"):
            body = dict(base_cases)
            body[field] = 5
            status, payload, _ = signup(self.port, body)
            self.assertEqual((status, payload["error"]["code"]), (400, "malformed_request"), field)

    def test_derived_handle_collision_409_no_user_created(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        before = set(state_module.STATE.users)
        status, payload, _ = signup(self.port, {
            "email": "Ada@example.com", "password": "password1", "display_name": "Imposter",
        })
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "handle_taken")
        self.assertEqual(set(state_module.STATE.users), before)

    def test_derived_handle_rule(self):
        self.assertEqual(derive_handle("Ada.Boost+news@Example.com"), "ada_boost_news")
        self.assertEqual(derive_handle("ABCDEFGHIJKLMNOPQRSTU@example.com"), "abcdefghijklmnopqrst")
        self.assertEqual(derive_handle("üñî@x.com"), "___")
        self.assertEqual(derive_handle("a@x.com"), "a")

    def test_new_user_can_receive_money_immediately(self):
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        status, payload, _ = signup(self.port, {
            "email": "cy@example.com", "password": "password1", "display_name": "Cy",
        })
        self.assertEqual(status, 201)
        user = state_module.STATE.users[payload["user_id"]]
        self.assertEqual(user.balance, 0)
        self.assertEqual(state_module.STATE.handles["cy"], payload["user_id"])
        ada = base.request(self.port, "POST", "/auth/login", body={
            "email": "ada@example.com", "password": "correct horse",
        })[1]
        status, payment, _ = base.request(self.port, "POST", "/payments", body={
            "to_handle": "cy", "amount": 250,
        }, headers={**{"Authorization": f"Bearer {ada['token']}"}, "Idempotency-Key": "first-pay"})
        self.assertEqual(status, 201)
        status, me, _ = base.request(self.port, "GET", "/me", headers={
            "Authorization": f"Bearer {payload['token']}",
        })
        self.assertEqual(me["balance"], 250)
        status, req, _ = base.request(self.port, "POST", "/requests", body={
            "payer_handle": "cy", "amount": 10,
        }, headers={"Authorization": f"Bearer {ada['token']}", "Idempotency-Key": "first-req"})
        self.assertEqual(status, 201, "new user can also be asked for money immediately")

    def test_signup_tokens_work(self):
        status, payload, _ = signup(self.port, {
            "email": "a@example.com", "password": "password1", "display_name": "A",
        })
        auth = {"Authorization": f"Bearer {payload['token']}"}
        status, me, _ = base.request(self.port, "GET", "/me", headers=auth)
        self.assertEqual(status, 200)
        self.assertEqual(me["user_id"], payload["user_id"])
        self.assertEqual(me["handle"], "a")
        self.assertEqual(me["balance"], 0)


class TestLogin(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)

    def tearDown(self):
        base.stop_server(self.httpd)

    def login(self, email="ada@example.com", password="correct horse"):
        return base.request(self.port, "POST", "/auth/login", body={"email": email, "password": password})

    def test_login_happy_path_200_same_shape_as_signup(self):
        status, payload, _ = self.login()
        self.assertEqual(status, 200)
        self.assertEqual(set(payload.keys()), {"user_id", "display_name", "token"})
        self.assertEqual(payload["user_id"], "u_ada")
        self.assertEqual(payload["display_name"], "Ada")

    def test_seeded_users_log_in_immediately(self):
        for email in ("ada@example.com", "bob@example.com"):
            status, payload, _ = self.login(email=email)
            self.assertEqual(status, 200, email)

    def test_wrong_password_401_unknown_email_401(self):
        for kwargs in ({"password": "wrong password"}, {"email": "ghost@example.com"}):
            status, payload, _ = self.login(**kwargs)
            self.assertEqual(status, 401)
            self.assertEqual(payload["error"]["code"], "unauthenticated")

    def test_two_logins_two_independent_tokens(self):
        first = self.login()
        second = self.login()
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertNotEqual(first[1]["token"], second[1]["token"])
        for token in (first[1]["token"], second[1]["token"]):
            status, _, _ = base.request(self.port, "GET", "/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(status, 200)

    def test_login_missing_fields(self):
        status, payload, _ = base.request(self.port, "POST", "/auth/login", body={"email": "ada@example.com"})
        self.assertEqual((status, payload["error"]["code"]), (422, "validation_failed"))
        status, payload, _ = base.request_raw(self.port, "POST", "/auth/login", data=b"[]")
        self.assertEqual((status, payload["error"]["code"]), (400, "malformed_request"))


class TestBearerMiddleware(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()
        base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        status, payload, _ = base.request(self.port, "POST", "/auth/login", body={
            "email": "ada@example.com", "password": "correct horse",
        })
        self.token = payload["token"]

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_me_exact_shape(self):
        status, me, _ = base.request(self.port, "GET", "/me", headers={
            "Authorization": f"Bearer {self.token}",
        })
        self.assertEqual(status, 200)
        self.assertEqual(me, {
            "user_id": "u_ada", "display_name": "Ada", "handle": "ada",
            "balance": 10000, "currency": "EUR", "minor_units": 2,
        })

    def test_missing_garbage_unknown_token_401(self):
        cases = [
            {},
            {"Authorization": "Basic abc"},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer "},
            {"Authorization": f"Bearer {self.token}x"},
        ]
        for headers in cases:
            status, payload, _ = base.request(self.port, "GET", "/me", headers=headers)
            self.assertEqual(status, 401, headers)
            self.assertEqual(payload["error"]["code"], "unauthenticated", headers)

    def test_health_and_reset_and_auth_require_no_auth(self):
        status, _, _ = base.request(self.port, "GET", "/health")
        self.assertEqual(status, 200)
        status, _, _ = base.request(self.port, "POST", "/_test/reset", body=FIXTURE)
        self.assertEqual(status, 204)
        status, _, _ = base.request(self.port, "POST", "/auth/login", body={
            "email": "ada@example.com", "password": "correct horse",
        })
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()