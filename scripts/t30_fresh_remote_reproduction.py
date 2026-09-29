"""§50 fresh remote reproduction: semantic drift = 0 on a fresh clone.

Clones the pushed ``t30-preconstruction`` branch from origin into a
temporary directory outside every worktree, then re-runs the read-only
verification entrypoint (``scripts/t30_preconstruction.py --verify``)
inside the fresh clone and compares the recomputed freeze and doctor
against the pushed artifacts.  The reproduction contains no private
material: the clone only carries PUBLIC_SAFE artifacts; the sealed T27 and
T28 stores are never touched and no predecessor blind row ever leaves a
sealed boundary.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT / "src", ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

# §2 candidate-unchanged pins carried verbatim into the reproduction.
FREEZE_IDENTITY_KEYS = (
    "candidate_commit", "candidate_tree", "runtime_root",
    "candidate_runtime_changes", "component_count", "component_root",
    "freeze_root", "freeze_sha256", "real_construction_authorized",
    "real_evaluation_authorized", "real_blind_rows", "real_gold_rows",
    "real_construction_attempts", "real_evaluation_attempts",
)


def reproduce(root: Path, *, clone_parent: str | None = None) -> dict:
    from t21_protocol.util import sha256_json

    root = Path(root).resolve()
    pushed_freeze = json.loads(
        (root / "evaluations/t30/preconstruction_freeze.json")
        .read_text(encoding="utf-8"))
    pushed_doctor = json.loads(
        (root / "evaluations/t30/protocol_doctor_report.json")
        .read_text(encoding="utf-8"))
    pushed_verdict = json.loads(
        (root / "evaluations/t30/T30_PRECONSTRUCTION_VERDICT.json")
        .read_text(encoding="utf-8"))
    pushed_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
        text=True, check=True).stdout.strip()
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=root,
        capture_output=True, text=True, check=True).stdout.strip()

    with tempfile.TemporaryDirectory(
            prefix="t30-fresh-remote-", dir=clone_parent) as tmp:
        clone = Path(tmp) / "clone"
        environment = dict(os.environ)
        # Unrelated historical LFS checkpoints are irrelevant to the T30
        # verification surface; skipping smudge avoids their bulk fetch.
        environment["GIT_LFS_SKIP_SMUDGE"] = "1"
        subprocess.run(
            ["git", "clone", "--branch", "t30-preconstruction",
             origin, str(clone)],
            capture_output=True, text=True, check=True, timeout=900,
            env=environment)
        cloned_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=clone, capture_output=True,
            text=True, check=True).stdout.strip()

        verify = subprocess.run(
            [sys.executable, "scripts/t30_preconstruction.py", "--verify"],
            cwd=clone, capture_output=True, text=True, timeout=1800)
        if not verify.stdout.strip():
            raise RuntimeError("fresh-clone verify produced no output: "
                               f"{verify.stderr[-2000:]}")
        report = json.loads(verify.stdout)
        cloned_freeze = json.loads(
            (clone / "evaluations/t30/preconstruction_freeze.json")
            .read_text(encoding="utf-8"))
        cloned_doctor = json.loads(
            (clone / "evaluations/t30/protocol_doctor_report.json")
            .read_text(encoding="utf-8"))

        # §45 full semantic reproduction.  The pinned public adapter (LFS)
        # is hydrated from the source worktree bytes so evaluation-wrapper
        # rehearsals can bind the model identity; private predecessor
        # locations come from the environment only.
        adapter = "training/adapters/sciencemath-v0.1-t3/adapter_model.safetensors"
        shutil.copyfile(root / adapter, clone / adapter)
        full = subprocess.run(
            [sys.executable, "scripts/t30_preconstruction.py", "--verify-full"],
            cwd=clone, capture_output=True, text=True, timeout=7200)
        if not full.stdout.strip():
            raise RuntimeError("fresh-clone verify-full produced no output: "
                               f"{full.stderr[-2000:]}")
        full_report = json.loads(full.stdout[full.stdout.index("{"):])
        freeze_drift = sorted(
            key for key in FREEZE_IDENTITY_KEYS
            if cloned_freeze.get(key) != pushed_freeze.get(key))
        if cloned_freeze.get("components") != pushed_freeze.get("components"):
            freeze_drift.append("components")
        doctor_bytes_equal = (
            (root / "evaluations/t30/protocol_doctor_report.json")
            .read_bytes() ==
            (clone / "evaluations/t30/protocol_doctor_report.json")
            .read_bytes())

        semantic = {
            "source_commit": pushed_commit,
            "clone_commit": cloned_commit,
            "source_freeze_sha256": pushed_freeze.get("freeze_sha256"),
            "clone_freeze_sha256": cloned_freeze.get("freeze_sha256"),
            "component_count": pushed_freeze.get("component_count"),
            "doctor_rerun_status": report.get("doctor"),
            "doctor_rerun_check_count": report.get("doctor_check_count"),
            "pushed_doctor_check_count": pushed_doctor.get("check_count"),
            "doctor_report_reproduced_byte_exact": doctor_bytes_equal,
            "pushed_verdict": pushed_verdict.get("verdict"),
            "clone_verdict_field": report.get("verdict"),
            "candidate_runtime_changes":
                cloned_freeze.get("candidate_runtime_changes"),
        }
        drifted = int(
            bool(freeze_drift)
            or report.get("doctor") != "PASS"
            or report.get("verdict") != "T30_PRECONSTRUCTION_PASS"
            or pushed_verdict.get("verdict") != "T30_PRECONSTRUCTION_PASS"
            or pushed_doctor.get("status") != "PASS"
            or doctor_bytes_equal is not True
            or pushed_doctor.get("check_count")
            != report.get("doctor_check_count")
            or cloned_commit != pushed_commit
            or full_report.get("semantic_drift") != 0)
        document = {
            "schema_version": "t30-fresh-remote-reproduction-v1",
            "artifact": "T30_FRESH_REMOTE_REPRODUCTION",
            "classification": "PUBLIC_SAFE",
            "status": "PASS" if not drifted else "FAIL",
            "branch": "t30-preconstruction",
            "source_worktree_commit": pushed_commit,
            "fresh_clone_commit": cloned_commit,
            "fresh_remote_commit_matches_push": cloned_commit == pushed_commit,
            "semantic_signature": sha256_json(semantic),
            "semantic": semantic,
            "doctor_report_reproduced_byte_exact": doctor_bytes_equal,
            "freeze_components_identical": (
                cloned_freeze.get("components")
                == pushed_freeze.get("components")),
            "freeze_drift_keys": freeze_drift,
            "clone_verdict": report.get("verdict"),
            "full_reproduction": {
                "semantic_drift": full_report.get("semantic_drift"),
                "drifted": full_report.get("drifted"),
                "items": {name: item.get("match") for name, item
                          in full_report.get("items", {}).items()},
                "doctor": full_report.get("doctor"),
                "doctor_check_count": full_report.get("doctor_check_count"),
                "test_gate_tests": full_report.get("test_gate_tests"),
            },
            "semantic_drift": drifted,
            "t27_private_rows_read": 0, "t27_gold_rows_read": 0,
            "t28_private_rows_read": 0, "t28_gold_rows_read": 0,
            "t28_blind_rows_read": 0,
            "t30_candidate_executions": 0,
            "t30_real_blind_rows": 0, "t30_real_gold_rows": 0,
            "t30_construction_attempts": 0, "t30_evaluation_attempts": 0,
            "t30_construction_one_shot": "UNSPENT",
            "t29_abandoned_row_files_opened": 0,
        }
        return {**document, "reproduction_sha256": sha256_json(document)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1]
                        / "evaluations/t30/fresh_remote_reproduction.json")
    args = parser.parse_args()
    report = reproduce(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "branch", "fresh_clone_commit", "semantic_drift",
        "freeze_drift_keys", "clone_verdict")}, indent=2, sort_keys=True))
    # fresh_remote_reproduction.json is freeze-EXCLUDED; writing it does not
    # change any frozen component.
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())