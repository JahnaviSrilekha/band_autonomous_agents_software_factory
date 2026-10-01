#!/usr/bin/env python3
"""One-command black-box acceptance runner for pocketful stage 3.

Usage:
    python3 specs/stage-3/acceptance/run.py [BASE_URL] [--skip-regression] [--filter SUB] [--list]

BASE_URL defaults to $BASE_URL or http://127.0.0.1:8080. Every test resets the
service state first (POST /_test/reset with a stage-2/3 fixture), so the suite
can run repeatedly and in any order against a freshly started container.

By default the suite also re-runs the stage-1 and stage-2 acceptance modules
(unmodified) against this service — stages 1-2 remain in force by reference
(stage-3.md intro). --skip-regression skips them. Stdlib only.

Stage 3 adds no routes, screens or data-testids (stage-3.md is API-only), so
there is no stage-3 UI module; the stage-2 UI module doubles as the UI
regression for the carried-forward deliverable.
"""
import glob
import importlib
import importlib.util
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE1_ACCEPTANCE = os.path.join(HERE, "..", "..", "stage-1", "acceptance")
STAGE2_ACCEPTANCE = os.path.join(HERE, "..", "..", "stage-2", "acceptance")

# Regression assertions superseded by a later stage's own requirements; the
# earlier stage folders are accepted history and stay unedited, so the runner
# skips them with the sanctioning later-stage requirement as the recorded
# reason. Equivalent later-stage assertions exist in this suite (README
# coverage).
SANCTIONED_STAGE3_DELTAS = {
    "stage1.test_payments.test_payment_happy_shape":
        "payment shape gains authorization_id on every payment-producing path "
        "(stage-2 R143); asserted in stage2 suite test_authorizations.test_r143_*",
    "stage1.test_export_import.test_export_is_atomic_read_only_snapshot":
        "the service exports format_version 3 per ADR-010; asserted in "
        "test_upgrade.test_export_v3_with_revisions",
    "stage1.test_export_import.test_export_unauthenticated_shape":
        "the service exports format_version 3 per ADR-010; asserted in "
        "test_upgrade.test_export_v3_with_revisions",
    "stage1.test_export_import.test_import_errors_leave_destination_unchanged":
        "import of this service's own export is v3-shaped per ADR-010; v1 "
        "import errors still 422 and leave state unchanged "
        "(test_upgrade.test_r235_import_v1_export)",
    "stage1.test_export_import.test_import_preserves_settlement_membership":
        "import of this service's own export is v3-shaped per ADR-010; "
        "membership preservation asserted on the v1 path in "
        "test_upgrade.test_r235_import_v1_export",
    "stage1.test_export_import.test_import_preserves_tokens_login_replays_and_failed_keys":
        "import of this service's own export is v3-shaped per ADR-010; "
        "token/replay preservation asserted on the v1 path in "
        "test_upgrade.test_r235_import_v1_export",
    "stage1.test_export_import.test_import_replacement_not_merge":
        "import of this service's own export is v3-shaped per ADR-010; "
        "replacement asserted on the v1 path in "
        "test_upgrade.test_r235_import_v1_export",
    "stage1.test_export_import.test_reset_clears_imported_state":
        "import of this service's own export is v3-shaped per ADR-010; "
        "reset-after-import asserted on the v1 path in "
        "test_upgrade.test_r235_import_v1_export",
    "stage1.test_export_import.test_round_trip_is_a_noop":
        "the service exports format_version 3 per ADR-010; round trip "
        "asserted in test_upgrade.test_export_v3_round_trip",
    "stage2.test_upgrade.test_r119_import_between_browser_requests":
        "the service now exports format_version 3 per ADR-010 (this test "
        "asserts the v2 export format mid-way); v3 export + round trip "
        "asserted in test_upgrade.test_export_v3_with_revisions and "
        "test_upgrade.test_export_v3_round_trip; import-between-browser-"
        "requests behaviour itself is unchanged and covered by "
        "test_r119's remaining stage-2 assertions via the v1 path in "
        "test_upgrade.test_r235_import_v1_export",
}


def _load_module(path, mod_name):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def discover(skip_regression):
    """Yield (label, fn) for every test_*.py test function, stage-1 then
    stage-2 first so a regression fails fast before stage-3 specifics."""
    items = []
    if not skip_regression:
        sys.path.insert(0, HERE)      # shared superset client.py resolves first
        sys.path.insert(1, STAGE2_ACCEPTANCE)  # dom.py for stage-2 UI modules
        for prefix, folder in (("stage1", STAGE1_ACCEPTANCE),
                               ("stage2", STAGE2_ACCEPTANCE)):
            for path in sorted(glob.glob(os.path.join(folder, "test_*.py"))):
                base = os.path.basename(path)[:-3]
                mod = _load_module(path, f"{prefix}_{base}")
                for name, fn in sorted(vars(mod).items()):
                    if name.startswith("test_") and inspect.isfunction(fn):
                        items.append((f"{prefix}.{base}.{name}", fn))
    for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
        mod_name = os.path.basename(path)[:-3]
        mod = importlib.import_module(mod_name)
        for name, fn in sorted(vars(mod).items()):
            if name.startswith("test_") and inspect.isfunction(fn):
                items.append((f"{mod_name}.{name}", fn))
    return items


def main(argv):
    skip_regression = "--skip-regression" in argv
    only_list = "--list" in argv
    flt = None
    if "--filter" in argv:
        flt = argv[argv.index("--filter") + 1]
        argv = [a for i, a in enumerate(argv) if not (a == "--filter" or i == argv.index("--filter") + 1)]
    base = next((a for a in argv if not a.startswith("--")),
                os.environ.get("BASE_URL", "http://127.0.0.1:8080"))
    sys.path.insert(0, HERE)
    from client import Client
    items = discover(skip_regression)
    if flt:
        items = [(label, fn) for label, fn in items if flt in label]
    if only_list:
        for label, _ in items:
            print(label)
        return 0
    passed, failed, skipped = 0, 0, 0
    failures = []
    for label, fn in items:
        if label in SANCTIONED_STAGE3_DELTAS:
            skipped += 1
            print(f"SKIP {label}: superseded — {SANCTIONED_STAGE3_DELTAS[label]}")
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