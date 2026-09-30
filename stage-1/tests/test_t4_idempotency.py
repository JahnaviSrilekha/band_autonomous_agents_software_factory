import threading
import unittest

import base
from pocketful import idempotency as idem
from pocketful.errors import ApiError


class FakeRoute:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def handler(self, user, body, params, query):
        self.calls.append(copy_body(body))
        if isinstance(self.outcome, ApiError):
            raise self.outcome
        return 201, {"ok": True, "calls": len(self.calls)}


def copy_body(body):
    return idem.canonicalize(body)


class FakeUser:
    id = "u_test"


class FakeHeaders(dict):
    def get(self, name, default=None):
        return super().get(name, default)


class TestJsonEqual(unittest.TestCase):
    def test_key_order_and_whitespace_irrelevant(self):
        self.assertTrue(idem.json_equal({"a": 1, "b": 2}, {"b": 2, "a": 1}))
        self.assertTrue(idem.json_equal({"x": [1, {"y": "z"}]}, {"x": [1, {"y": "z"}]}))

    def test_numeric_forms_equal(self):
        self.assertTrue(idem.json_equal({"amount": 1000}, {"amount": 1000.0}))
        self.assertTrue(idem.json_equal({"amount": 1000}, {"amount": 1e3}))

    def test_bool_never_equals_number(self):
        self.assertFalse(idem.json_equal({"v": True}, {"v": 1}))
        self.assertFalse(idem.json_equal({"v": False}, {"v": 0}))
        self.assertFalse(idem.json_equal({"v": 1}, {"v": True}))
        self.assertFalse(idem.json_equal({"v": 0}, {"v": False}))

    def test_type_mismatches_unequal(self):
        self.assertFalse(idem.json_equal({"v": "1"}, {"v": 1}))
        self.assertFalse(idem.json_equal({"v": None}, {"v": 0}))
        self.assertFalse(idem.json_equal({"v": [1]}, {"v": 1}))
        self.assertFalse(idem.json_equal({"v": {"a": 1}}, {"v": {"a": "1"}}))

    def test_missing_vs_extra_keys_unequal(self):
        self.assertFalse(idem.json_equal({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(idem.json_equal({}, {"visibility": "public"}))


class TestIdempotencyChokepoint(unittest.TestCase):
    def setUp(self):
        base.reset_state()
        self.user = FakeUser()
        self.headers = FakeHeaders({"Idempotency-Key": "k1"})

    def run_route(self, route, body, path="/payments", key="k1"):
        headers = FakeHeaders({"Idempotency-Key": key})
        return idem.run_idempotent(route, self.user, "POST", path, headers, body, {}, {})

    def test_missing_key_400(self):
        for headers in ({}, {"Idempotency-Key": ""}):
            with self.assertRaises(ApiError) as ctx:
                idem.run_idempotent(FakeRoute(None), self.user, "POST", "/payments",
                                    FakeHeaders(headers), {}, {}, {})
            self.assertEqual((ctx.exception.status, ctx.exception.code), (400, "missing_idempotency_key"))

    def test_too_long_key_422(self):
        with self.assertRaises(ApiError) as ctx:
            self.run_route(FakeRoute(None), {}, key="k" * 256)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (422, "validation_failed"))

    def test_first_use_claims_and_executes_201(self):
        route = FakeRoute(None)
        status, payload = self.run_route(route, {"amount": 5})
        self.assertEqual(status, 201)
        self.assertEqual(len(route.calls), 1)

    def test_replay_same_body_returns_stored_response_without_reexecution(self):
        route = FakeRoute(None)
        first = self.run_route(route, {"amount": 5, "note": "x"})
        second = self.run_route(route, {"note": "x", "amount": 5.0})
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(len(route.calls), 1)

    def test_same_key_different_body_409(self):
        route = FakeRoute(None)
        self.run_route(route, {"amount": 5})
        with self.assertRaises(ApiError) as ctx:
            self.run_route(route, {"amount": 6})
        self.assertEqual((ctx.exception.status, ctx.exception.code), (409, "idempotency_key_reuse"))

    def test_failed_4xx_frees_key(self):
        route = FakeRoute(ApiError(409, "insufficient_funds", "short"))
        with self.assertRaises(ApiError):
            self.run_route(route, {"amount": 5})
        self.assertEqual(len(route.calls), 1)
        route2 = FakeRoute(None)
        status, _ = self.run_route(route2, {"amount": 5})
        self.assertEqual(status, 201)
        self.assertEqual(len(route2.calls), 1)

    def test_different_path_same_key_is_independent(self):
        first = FakeRoute(None)
        second = FakeRoute(None)
        a = self.run_route(first, {"amount": 5}, path="/payments")
        b = self.run_route(second, {"amount": 5}, path="/requests")
        self.assertEqual(a[0], 201)
        self.assertEqual(b[0], 201)
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(second.calls), 1)

    def test_key_scoped_to_user(self):
        other = FakeUser()
        other.id = "u_other"
        first = FakeRoute(None)
        second = FakeRoute(None)
        a = idem.run_idempotent(first, self.user, "POST", "/payments",
                                FakeHeaders({"Idempotency-Key": "shared"}), {"amount": 5}, {}, {})
        b = idem.run_idempotent(second, other, "POST", "/payments",
                                FakeHeaders({"Idempotency-Key": "k1"}), {"amount": 5}, {}, {})
        self.assertEqual(a[0], 201)
        self.assertEqual(b[0], 201)
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(second.calls), 1)

    def test_replay_after_resource_changed_still_original(self):
        import pocketful.state as state_mod

        route = FakeRoute(None)
        first = self.run_route(route, {"amount": 5})
        state_mod.STATE.requests["rq_1"] = object()
        second = self.run_route(route, {"amount": 5})
        self.assertEqual(second[0], 200)
        self.assertEqual(first[1], second[1])

    def test_concurrent_identical_requests_execute_once(self):
        route = FakeRoute(None)
        results = []
        errors = []
        barrier = threading.Barrier(20)

        def worker():
            barrier.wait()
            try:
                results.append(self.run_route(route, {"amount": 5}))
            except ApiError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)
        created = [r for r in results if r[0] == 201]
        replayed = [r for r in results if r[0] == 200]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(replayed), 19)
        self.assertTrue(all(r[1] == created[0][1] for r in replayed))
        self.assertEqual(len(route.calls), 1)


if __name__ == "__main__":
    unittest.main()