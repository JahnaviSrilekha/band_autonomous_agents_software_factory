#!/usr/bin/env python3
"""One-command black-box acceptance runner for pocketful stage 2.

Usage:
    python3 specs/stage-2/acceptance/run.py [BASE_URL] [--skip-stage1] [--filter SUB] [--list]

BASE_URL defaults to $BASE_URL or http://127.0.0.1:8080. Every test resets the
service state first (POST /_test/reset with a stage-2 fixture), so the suite
can run repeatedly and in any order against a freshly started container.

By default the suite also re-runs the stage-1 acceptance modules
(specs/stage-1/acceptance/test_*.py, unmodified) against this service — stage-1
requirements remain in force by reference (stage-2 R94-R157 intro). --skip-stage1
skips them. Stdlib only.
"""
import glob
import importlib
import importlib.util
import inspect
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE1_ACCEPTANCE = os.path.join(HERE, "..", "..", "stage-1", "acceptance")


def discover(local_only=True):
    """Yield (label, fn) for every test_*.py test function, stage-1 first so a
    basic-behaviour regression fails fast before stage-2 specifics."""
    items = []
    if not local_only:
        sys.path.insert(0, HERE)  # shared superset client.py resolves for both
        for path in sorted(glob.glob(os.path.join(STAGE1_ACCEPTANCE, "test_*.py"))):
            mod_name = "s1_" + os.path.basename(path)[:-3]
            spec = importlib.util.spec_from_file_location(mod_name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            for name, fn in sorted(vars(mod).items()):
                if name.startswith("test_") and inspect.isfunction(fn):
                    items.append((f"stage1.{os.path.basename(path)[:-3]}.{name}", fn))
    for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
        mod_name = os.path.basename(path)[:-3]
        mod = importlib.import_module(mod_name)
        for name, fn in sorted(vars(mod).items()):
            if name.startswith("test_") and inspect.isfunction(fn):
                items.append((f"{mod_name}.{name}", fn))
    return items


def main(argv):
    skip_stage1 = "--skip-stage1" in argv
    only_list = "--list" in argv
    flt = None
    if "--filter" in argv:
        flt = argv[argv.index("--filter") + 1]
        argv = [a for i, a in enumerate(argv) if not (a == "--filter" or i == argv.index("--filter") + 1)]
    base = next((a for a in argv if not a.startswith("--")),
                os.environ.get("BASE_URL", "http://127.0.0.1:8080"))
    sys.path.insert(0, HERE)
    from client import Client
    items = discover(local_only=skip_stage1)
    if flt:
        items = [(label, fn) for label, fn in items if flt in label]
    if only_list:
        for label, _ in items:
            print(label)
        return 0
    passed, failed, skipped = 0, 0, 0
    failures = []
    for label, fn in items:
        c = Client(base)
        try:
            fn(c)
            passed += 1
            print(f"PASS {label}")
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001 - report and continue
            if "SKIP" in str(e):
                skipped += 1
                print(f"SKIP {label}: {e}")
                continue
            failed += 1
            failures.append((label, str(e)))
            print(f"FAIL {label}: {e}")
    total = passed + failed
    print(f"\n{passed}/{total} passed, {failed} failed"
          + (f", {skipped} skipped" if skipped else ""))
    if failures:
        print("\nFailures:")
        for label, msg in failures:
            print(f"  - {label}: {msg}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))