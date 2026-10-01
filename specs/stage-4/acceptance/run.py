#!/usr/bin/env python3
"""One-command black-box acceptance runner for pocketful stage 4.

Usage:
    python3 specs/stage-4/acceptance/run.py [BASE_URL] [--skip-regression] [--filter SUB] [--list]

BASE_URL defaults to $BASE_URL or http://127.0.0.1:8080. Every test resets the
service state first (POST /_test/reset with a stage-3/4 fixture), so the suite
can run repeatedly and in any order against a freshly started container.

By default the suite also re-runs the stage-1, stage-2 and stage-3 acceptance
modules (unmodified) against this service — stages 1-3 remain in force by
reference (stage-4.md intro; R1-R251 regression, including the stage-1 §9
rounding table). --skip-regression runs only the stage-4 modules. Stdlib only.

Stage 4 adds no routes, screens or data-testids beyond the JSON API (A48: no
new UI surface), so there is no stage-4 UI module; the carried-forward stage-2
UI module runs as the UI regression.
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
STAGE3_ACCEPTANCE = os.path.join(HERE, "..", "..", "stage-3", "acceptance")

# Regression assertions superseded by a later stage's own requirements; the
# earlier stage folders are accepted history and stay unedited, so the runner
# skips them with the sanctioning later-stage requirement as the recorded
# reason. Equivalent later-stage assertions exist in this suite (README
# coverage).
SANCTIONED_STAGE4_DELTAS = {
    "stage1.test_payments.test_payment_happy_shape":
        "payment shape gains authorization_id (stage-2 R143) and refund_of "
        "(stage-4 R264) on every payment-producing path; the carried-forward "
        "stage-2 exact-shape test (which imports the shared client's updated "
        "PAYMENT_KEYS) covers the current shape",
    "stage1.test_export_import.test_export_is_atomic_read_only_snapshot":
        "the service exports format_version 4 per R290; atomicity asserted in "
        "stage-1 R81 family and v4 contents in "
        "test_interactions.test_r290_export_v4",
    "stage1.test_export_import.test_export_unauthenticated_shape":
        "the service exports format_version 4 per R290; v4 contents asserted "
        "in test_interactions.test_r290_export_v4",
    "stage1.test_export_import.test_import_errors_leave_destination_unchanged":
        "import of this service's own export is v4-shaped per R290; v1 "
        "import errors still 422 and leave state unchanged "
        "(test_interactions.test_r289_import_earlier_stage_exports)",
    "stage1.test_export_import.test_import_preserves_settlement_membership":
        "import of this service's own export is v4-shaped per R290; "
        "membership preservation asserted on the v1 path in "
        "test_interactions.test_r289_import_earlier_stage_exports",
    "stage1.test_export_import.test_import_preserves_tokens_login_replays_and_failed_keys":
        "import of this service's own export is v4-shaped per R290; "
        "token/replay preservation asserted on the v1 path in "
        "test_interactions.test_r289_import_earlier_stage_exports",
    "stage1.test_export_import.test_import_replacement_not_merge":
        "import of this service's own export is v4-shaped per R290; "
        "replacement asserted on the v1 path in "
        "test_interactions.test_r289_import_earlier_stage_exports",
    "stage1.test_export_import.test_reset_clears_imported_state":
        "import of this service's own export is v4-shaped per R290; "
        "reset-after-import asserted on the v1 path in "
        "test_interactions.test_r289_import_earlier_stage_exports",
    "stage1.test_export_import.test_round_trip_is_a_noop":
        "the service exports format_version 4 per R290; round trip asserted "
        "in test_interactions.test_r290_export_v4 and "
        "test_interactions.test_r289_v4_round_trip_preserves_refunds",
    "stage2.test_authorizations.test_r139_create_shape_and_defaults":
        "stage-3 R244 adds closed_at to every authorization representation, so "
        "the exact-shape assertion (set == AUTHZ_KEYS) no longer holds; "
        "closed_at presence/semantics asserted in test_holds.test_r244_closed_at "
        "and the remaining R139 behavior is covered by stage2 "
        "test_r139_note_visibility_explicit plus the stage-3 holds tests",
    "stage2.test_authorizations.test_r148_r149_void":
        "stage-3 R244 adds closed_at to every authorization representation, so "
        "the exact-shape assertion (set == AUTHZ_KEYS) no longer holds; void "
        "release semantics and closed_at are asserted in test_holds."
        "test_r239_final_capture_and_void_release_at_event_time and test_holds."
        "test_r244_closed_at, and void permissions remain covered by stage2 "
        "test_r149_a15_void_permissions_and_ignored_key",
    "stage2.test_upgrade.test_r119_import_between_browser_requests":
        "the service now exports format_version 4 per R290 (this test "
        "asserts the v2 export format mid-way); v4 export + round trip "
        "asserted in test_interactions.test_r290_export_v4; import-between-"
        "browser-requests behaviour itself is unchanged and covered by "
        "test_r119's remaining stage-2 assertions via the v1 path in "
        "test_interactions.test_r289_import_earlier_stage_exports",
    "stage3.test_upgrade_settlements.test_export_v3_with_revisions":
        "the service now exports format_version 4 per R290 (this test pins "
        "format_version 3); v4 contents (refund_of per payment, "
        "correction_batch_id per revision, revision history) asserted in "
        "test_interactions.test_r290_export_v4",
}


def _load_module(path, mod_name):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def discover(skip_regression):
    """Yield (label, fn) for every test_*.py test function, regression stages
    first so an earlier-stage regression fails fast before stage-4 specifics."""
    items = []
    if not skip_regression:
        sys.path.insert(0, HERE)      # shared superset client.py resolves first
        sys.path.insert(1, STAGE2_ACCEPTANCE)  # dom.py for stage-2 UI modules
        for prefix, folder in (("stage1", STAGE1_ACCEPTANCE),
                               ("stage2", STAGE2_ACCEPTANCE),
                               ("stage3", STAGE3_ACCEPTANCE)):
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
        if label in SANCTIONED_STAGE4_DELTAS:
            skipped += 1
            print(f"SKIP {label}: superseded — {SANCTIONED_STAGE4_DELTAS[label]}")
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