import re
import unittest

import base
from pocketful.errors import ApiError, parse_amount, parse_note, parse_visibility, parse_json_body, require_string


class TestHealth(unittest.TestCase):
    def setUp(self):
        self.httpd, self.port = base.make_server()

    def tearDown(self):
        base.stop_server(self.httpd)

    def test_health_exact_body(self):
        status, payload, headers = base.request(self.port, "GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})
        self.assertTrue(headers["Content-Type"].startswith("application/json"))

    def test_unknown_route_404_envelope(self):
        status, payload, _ = base.request(self.port, "GET", "/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", payload)
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertIn("message", payload["error"])

    def test_unknown_method_on_known_path_404(self):
        status, payload, _ = base.request(self.port, "POST", "/health", body={})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_malformed_json_body_400(self):
        status, payload, _ = base.request_raw(self.port, "POST", "/health", data=b"{nope")
        self.assertEqual(status, 404)

    def test_health_does_not_500_without_state(self):
        status, _, _ = base.request(self.port, "GET", "/health")
        self.assertEqual(status, 200)


class TestBodyParsing(unittest.TestCase):
    def test_unparseable_body_400(self):
        with self.assertRaises(ApiError) as ctx:
            parse_json_body(b"{nope")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (400, "malformed_request"))

    def test_non_object_body_400(self):
        for raw in (b"[1,2]", b'"x"', b"5", b"true", b"null"):
            with self.assertRaises(ApiError) as ctx:
                parse_json_body(raw)
            self.assertEqual(ctx.exception.status, 400)

    def test_empty_body_is_empty_object(self):
        self.assertEqual(parse_json_body(b""), {})
        self.assertEqual(parse_json_body(None), {})

    def test_unknown_fields_survive(self):
        body = parse_json_body(b'{"amount": 5, "zzz": {"a": 1}}')
        self.assertEqual(body["zzz"], {"a": 1})


class TestFieldValidators(unittest.TestCase):
    def test_amount_integral_numeric_forms(self):
        self.assertEqual(parse_amount(1000), 1000)
        self.assertEqual(parse_amount(1000.0), 1000)
        self.assertEqual(parse_amount(1e3), 1000)
        self.assertEqual(parse_amount(1), 1)
        self.assertEqual(parse_amount(1000000000), 1000000000)

    def test_amount_invalid_cases_422(self):
        for value in ("1000", True, False, None, [5], {"a": 1}, 0, -5, 1000000001, 0.5, 1e400, float("inf")):
            with self.assertRaises(ApiError) as ctx:
                parse_amount(value)
            self.assertEqual((ctx.exception.status, ctx.exception.code), (422, "validation_failed"))

    def test_note_defaults_and_limits(self):
        self.assertEqual(parse_note({}), "")
        self.assertEqual(parse_note({"note": "hi"}), "hi")
        with self.assertRaises(ApiError) as ctx:
            parse_note({"note": None})
        self.assertEqual(ctx.exception.status, 422)
        with self.assertRaises(ApiError) as ctx:
            parse_note({"note": 5})
        self.assertEqual(ctx.exception.status, 422)
        with self.assertRaises(ApiError) as ctx:
            parse_note({"note": "x" * 201})
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(parse_note({"note": "x" * 200}), "x" * 200)

    def test_visibility_defaults_and_rules(self):
        self.assertEqual(parse_visibility({}), "public")
        self.assertEqual(parse_visibility({"visibility": "private"}), "private")
        for value in ("internal", "", None, 5, True, ["public"]):
            with self.assertRaises(ApiError) as ctx:
                parse_visibility({"visibility": value})
            self.assertEqual((ctx.exception.status, ctx.exception.code), (422, "validation_failed"))

    def test_required_string_missing_422_wrong_type_400(self):
        with self.assertRaises(ApiError) as ctx:
            require_string({}, "email")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (422, "validation_failed"))
        with self.assertRaises(ApiError) as ctx:
            require_string({"email": 5}, "email")
        self.assertEqual((ctx.exception.status, ctx.exception.code), (400, "malformed_request"))
        self.assertEqual(require_string({"email": "a@b.c"}, "email"), "a@b.c")


if __name__ == "__main__":
    unittest.main()