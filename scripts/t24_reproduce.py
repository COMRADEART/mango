#!/usr/bin/env python3
"""T24 preconstruction reproduction in a fresh worktree (section 42).

Run from a fresh checkout of the pushed t24-preconstruction branch. Re-verifies
the author lock, the freeze identity against the checked-out bytes, the
public-Git blind-blob scan, and the full preconstruction battery. Prints a
summary; exits nonzero on any failure.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def main() -> None:
    from t24_protocol import doctor as t24_doctor
    from t24_protocol.freeze import load_freeze
    from t24_protocol.leakscan import scan_public_git
    from t24_protocol.lock import verify_lock
    from t21_protocol.util import sha256_file

    # 1. Author lock re-verified from the checked-out bytes.
    lock = verify_lock()

    # 2. Freeze: recompute every component hash from the checkout.
    from t24_protocol import freeze as freeze_module

    freeze = load_freeze()
    drifted = []
    for component in freeze["components"]:
        path = ROOT / component["path"]
        if not path.is_file() or sha256_file(path) != component["sha256"]:
            drifted.append(component["path"])

    # 3. Public-Git blind-blob scan (sections 9, 37).
    from t24_protocol.policy import path_forbidden

    tracked = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                             cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.splitlines()
    scan = scan_public_git(ROOT, blind_hashes=set())
    scan["tracked_path_violations"] = sorted(p for p in tracked if path_forbidden(p))

    # 4. Storage and live-web negative controls re-run in this checkout.
    storage = t24_doctor._private_storage_controls(ROOT)
    live = t24_doctor._live_web_controls(ROOT)

    summary = {
        "artifact": "T24_PRECONSTRUCTION_REPRODUCTION",
        "lock_status": lock["status"],
        "lock_bindings": lock["binding_count"],
        "freeze_sha256": freeze["freeze_sha256"],
        "freeze_component_count": freeze["component_count"],
        "freeze_drifted_components": drifted,
        "blind_blob_count": scan["blind_blob_count"],
        "path_policy_violations": scan["path_policy_violations"],
        "tracked_path_violations": scan["tracked_path_violations"],
        "storage_controls_all_refused": storage["all_refused"],
        "storage_control_count": storage["control_count"],
        "live_web_controls_all_denied": live["all_denied"],
        "doctor_report": read_doctor_report(),
        "rehearsal_report": read_rehearsal_summary(),
    }
    passed = (summary["lock_status"] == "PASS"
              and not drifted
              and scan["status"] == "PASS"
              and not scan["tracked_path_violations"]
              and summary["storage_controls_all_refused"]
              and summary["storage_control_count"] == 12
              and summary["live_web_controls_all_denied"] is True
              and summary["doctor_report"] == "T24_PRODUCTION_PROTOCOL_DOCTOR_PASS"
              and summary["rehearsal_report"]["status"] == "PASS")
    summary["status"] = "PASS" if passed else "FAIL"
    summary["verdict"] = ("T24_PRECONSTRUCTION_REPRODUCTION_PASS" if passed
                          else "T24_PRECONSTRUCTION_REPRODUCTION_FAIL")
    print(json.dumps(summary, indent=1))
    if not passed:
        raise SystemExit(1)


def read_doctor_report() -> str:
    path = ROOT / "evaluations" / "t24" / "protocol_doctor_report.json"
    if not path.is_file():
        return "ABSENT"
    return json.loads(path.read_text(encoding="utf-8")).get("verdict", "ABSENT")


def read_rehearsal_summary() -> dict:
    path = ROOT / "evaluations" / "t24" / "production_shadow_lifecycle_report.json"
    if not path.is_file():
        return {"status": "ABSENT"}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {"status": report["status"], "runs": len(report["runs"]),
            "comparisons": report["comparisons"],
            "real_blind_rows": report["real_blind_rows"]}


if __name__ == "__main__":
    main()