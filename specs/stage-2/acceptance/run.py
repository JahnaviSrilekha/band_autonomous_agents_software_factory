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

# Stage-1 regression assertions superseded by stage-2's own requirements; the
# stage-1 folder is accepted history and stays unedited, so the runner skips
# them with the sanctioning stage-2 requirement as the recorded reason.
# Equivalent stage-2 assertions exist in this suite (see README coverage).
SANCTIONED_STAGE2_DELTAS = {
    "stage1.test_payments.test_payment_happy_shape":
        "payment shape gains authorization_id on every payment-producing path "
        "(stage-2 R143); asserted in test_authorizations.test_r143_*",
    "stage1.test_export_import.test_export_is_atomic_read_only_snapshot":
        "stage-2 exports format_version 2 per ADR-006; asserted in "
        "test_upgrade.test_r119_import_between_browser_requests",
    "stage1.test_export_import.test_export_unauthenticated_shape":
        "stage-2 exports format_version 2 per ADR-006",
    "stage1.test_export_import.test_import_errors_leave_destination_unchanged":
        "stage-2 exports format_version 2 per ADR-006; v1 import errors still "
        "422 and leave state unchanged (test_upgrade.test_r115_*)",
    "stage1.test_export_import.test_import_preserves_settlement_membership":
        "stage-2 exports format_version 2 per ADR-006",
    "stage1.test_export_import.test_import_preserves_tokens_login_replays_and_failed_keys":
        "stage-2 exports format_version 2 per ADR-006; v1-import preservation "
        "is asserted in test_upgrade (R82/R116/R118)",
    "stage1.test_export_import.test_import_replacement_not_merge":
        "stage-2 exports format_version 2 per ADR-006",
    "stage1.test_export_import.test_reset_clears_imported_state":
        "stage-2 exports format_version 2 per ADR-006",
    "stage1.test_export_import.test_round_trip_is_a_noop":
        "stage-2 exports format_version 2 per ADR-006; v2 round trip asserted "
        "in test_upgrade.test_r119_import_between_browser_requests",
}


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
        if label in SANCTIONED_STAGE2_DELTAS:
            skipped += 1
            print(f"SKIP {label}: superseded — {SANCTIONED_STAGE2_DELTAS[label]}")
            continue
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