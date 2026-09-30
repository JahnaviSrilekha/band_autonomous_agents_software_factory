#!/usr/bin/env python3
"""One-command black-box acceptance runner for pocketful stage 1.

Usage:
    python3 specs/stage-1/acceptance/run.py [BASE_URL]

BASE_URL defaults to $BASE_URL or http://127.0.0.1:8080. Every test resets the
service state first (POST /_test/reset), so the suite can run repeatedly and in
any order against a freshly started container. Stdlib only.
"""
import glob
import importlib
import inspect
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv):
    if "--list" in argv:
        list_tests()
        return 0
    argv = [a for a in argv if not a.startswith("--")]
    base = argv[0] if argv else os.environ.get("BASE_URL", "http://127.0.0.1:8080")
    sys.path.insert(0, HERE)
    from client import Client
    passed, failed = 0, 0
    failures = []
    for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
        mod_name = os.path.basename(path)[:-3]
        mod = importlib.import_module(mod_name)
        for name, fn in sorted(vars(mod).items()):
            if not (name.startswith("test_") and inspect.isfunction(fn)):
                continue
            label = f"{mod_name}.{name}"
            c = Client(base)
            try:
                fn(c)
                passed += 1
                print(f"PASS {label}")
            except Exception as e:  # noqa: BLE001 - report and continue
                failed += 1
                failures.append((label, str(e)))
                print(f"FAIL {label}: {e}")
                traceback.print_exc()
    total = passed + failed
    print(f"\n{passed}/{total} passed, {failed} failed")
    if failures:
        print("\nFailures:")
        for label, msg in failures:
            print(f"  - {label}: {msg}")
    return 1 if failed else 0


def list_tests():
    sys.path.insert(0, HERE)
    for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
        mod_name = os.path.basename(path)[:-3]
        mod = importlib.import_module(mod_name)
        for name, fn in sorted(vars(mod).items()):
            if name.startswith("test_") and inspect.isfunction(fn):
                print(f"{mod_name}.{name}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))