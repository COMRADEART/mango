"""§71 fresh remote reproduction: semantic drift = 0 on a fresh clone.

Clones the pushed ``t28-preconstruction`` branch from origin into a
temporary directory outside every worktree, then re-runs the public
verification entrypoint inside the fresh clone and compares the recomputed
freeze and doctor against the pushed artifacts.  The reproduction contains
no private material: the clone only carries PUBLIC_SAFE artifacts and the
sealed T27 store is never touched.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT / "src", ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))


def reproduce(root: Path, *, clone_parent: str | None = None) -> dict:
    from t21_protocol.util import sha256_json

    root = Path(root).resolve()
    pushed_freeze = json.loads(
        (root / "evaluations/t28/preconstruction_freeze.json")
        .read_text(encoding="utf-8"))
    pushed_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
        text=True, check=True).stdout.strip()
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=root, capture_output=True,
        text=True, check=True).stdout.strip()

    with tempfile.TemporaryDirectory(
            prefix="t28-fresh-remote-", dir=clone_parent) as tmp:
        clone = Path(tmp) / "clone"
        subprocess.run(
            ["git", "clone", "--branch", "t28-preconstruction",
             origin, str(clone)],
            capture_output=True, text=True, check=True, timeout=600)
        cloned_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True,
            text=True, check=True).stdout.strip()

        verify = subprocess.run(
            [sys.executable, "scripts/t28_preconstruction.py", "--verify"],
            cwd=clone, capture_output=True, text=True, timeout=1800)
        if not verify.stdout.strip():
            raise RuntimeError("fresh-clone verify produced no output: "
                               f"{verify.stderr[-2000:]}")
        report = json.loads(verify.stdout)
        cloned_freeze = json.loads(
            (clone / "evaluations/t28/preconstruction_freeze.json")
            .read_text(encoding="utf-8"))

        keys = ("candidate_commit", "candidate_tree", "runtime_root",
                "candidate_runtime_changes", "component_count",
                "component_root", "freeze_root", "freeze_sha256")
        freeze_drift = sorted(
            key for key in keys
            if cloned_freeze.get(key) != pushed_freeze.get(key))
        if cloned_freeze.get("components") != pushed_freeze.get("components"):
            freeze_drift.append("components")

        # remediation re-execution from exact pushed bytes (§30): the fresh
        # clone re-runs the real-entrypoint wrapper rehearsal and the six
        # freeze-path negative controls against the pushed canonical freeze
        # and reproduces the pushed PUBLIC_SAFE artifact bytes exactly.
        reexec = subprocess.run(
            [sys.executable, "scripts/t28_preconstruction.py",
             "--reexecute-remediation"],
            cwd=clone, capture_output=True, text=True, timeout=1800)
        try:
            reexec_report = json.loads(reexec.stdout) if reexec.stdout.strip() \
                else {}
        except ValueError:
            reexec_report = {}
        wrapper_bytes_equal = controls_bytes_equal = None
        errors: list[str] = []
        try:
            wrapper_bytes_equal = (
                (root / "evaluations/t28/real_entrypoint_rehearsal.json")
                .read_bytes() ==
                (clone / "evaluations/t28/real_entrypoint_rehearsal.json")
                .read_bytes())
            controls_bytes_equal = (
                (root / "evaluations/t28/freeze_path_negative_controls.json")
                .read_bytes() ==
                (clone / "evaluations/t28/freeze_path_negative_controls.json")
                .read_bytes())
        except FileNotFoundError as exc:
            errors.append(f"remediation artifact absent: {exc}")

        doctor = report.get("doctor", {})
        verdict = report.get("verdict", {})
        remediation = report.get("remediation", {})
        semantic = {
            "source_commit": pushed_commit,
            "clone_commit": cloned_commit,
            "source_freeze_sha256": pushed_freeze.get("freeze_sha256"),
            "clone_freeze_sha256": cloned_freeze.get("freeze_sha256"),
            "doctor_rerun_status": doctor.get("status"),
            "doctor_check_count": doctor.get("check_count"),
            "remediation_verdict": remediation.get("verdict"),
            "remediation_one_shot": remediation.get("construction_one_shot"),
            "wrapper_reexec_status": reexec_report.get("wrapper"),
            "controls_reexec_status": reexec_report.get("controls"),
            "wrapper_bytes_reproduced": wrapper_bytes_equal,
            "controls_bytes_reproduced": controls_bytes_equal,
        }
        drifted = int(bool(freeze_drift)
                      or doctor.get("status") != "PASS"
                      or verdict.get("status") != "PASS"
                      or remediation.get("status") != "PASS"
                      or remediation.get("construction_one_shot") != "UNSPENT"
                      or reexec_report.get("status") != "PASS"
                      or wrapper_bytes_equal is not True
                      or controls_bytes_equal is not True
                      or cloned_commit != pushed_commit)
        document = {
            "schema_version": "t28-fresh-remote-reproduction-v1",
            "artifact": "T28_FRESH_REMOTE_REPRODUCTION",
            "classification": "PUBLIC_SAFE",
            "status": "PASS" if not drifted else "FAIL",
            "branch": "t28-preconstruction",
            "source_worktree_commit": pushed_commit,
            "fresh_clone_commit": cloned_commit,
            "fresh_remote_commit_matches_push": cloned_commit == pushed_commit,
            "semantic_signature": sha256_json(semantic),
            "semantic": semantic,
            "remediation_artifact_errors": errors,
            "real_entrypoint_rehearsal_reproduced_byte_exact": (
                wrapper_bytes_equal),
            "freeze_path_negative_controls_reproduced_byte_exact": (
                controls_bytes_equal),
            "remediation_reexecution_status": reexec_report.get("status"),
            "construction_one_shot": "UNSPENT",
            "freeze_components_identical": (
                cloned_freeze.get("components")
                == pushed_freeze.get("components")),
            "freeze_drift_keys": freeze_drift,
            "clone_verdict": verdict.get("status"),
            "semantic_drift": drifted,
            "t27_private_rows_read": 0, "t27_gold_rows_read": 0,
            "t27_candidate_reruns": 0, "t28_candidate_executions": 0,
            "t28_real_blind_rows": 0, "t28_real_gold_rows": 0,
            "t28_construction_attempts": 0, "t28_evaluation_attempts": 0,
        }
        return {**document, "reproduction_sha256": sha256_json(document)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1]
                        / "evaluations/t28/fresh_remote_reproduction.json")
    args = parser.parse_args()
    report = reproduce(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "branch", "fresh_clone_commit", "semantic_drift",
        "freeze_drift_keys", "clone_verdict")}, indent=2, sort_keys=True))
    # fresh_remote_reproduction.json is freeze-excluded; staging it does not
    # change any frozen component.
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())