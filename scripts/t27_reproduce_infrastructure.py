#!/usr/bin/env python3
"""Fresh-checkout reproduction for T27 public-safe infrastructure."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for value in (ROOT, ROOT / "src"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from t27_protocol.construction import (run_construction_failure_rehearsal,
    run_construction_rehearsals, run_negative_controls, run_publication_leak_gate)
from t27_protocol.contract import authority_graph, production_graph
from t27_protocol.doctor import run_doctor
from t27_protocol.evaluation import (run_evaluation_failure_rehearsal,
    run_evaluation_rehearsals, runner_identity)
from t27_protocol.freeze import runtime_identity, verify_freeze_v2
from t27_protocol.protection import run_protection
from t27_protocol.qualification import (public_reproducer_record,
    run_completion_gate_matrix, run_qualification, run_terminal_matrix,
    run_verification_matrix)


def read(out: Path, name: str) -> dict:
    return json.loads((out / name).read_text(encoding="utf-8"))


def reproduce(root: Path) -> dict:
    root = root.resolve(); out = root / "evaluations" / "t27"
    historical = read(out, "preconstruction_freeze.json")
    mapping, runtime_root = runtime_identity(root)
    candidate = read(out, "candidate_identity.json")
    construction = run_construction_rehearsals(root, historical)
    evaluation = run_evaluation_rehearsals(root)
    failures = {
        "construction": run_construction_failure_rehearsal(root, historical),
        "evaluation": run_evaluation_failure_rehearsal(root),
    }
    diagnostics = {
        "terminal_matrix": run_terminal_matrix(),
        "verification_matrix": run_verification_matrix(),
        "completion_gate": run_completion_gate_matrix(),
    }
    checks = {
        "candidate_identity": candidate["runtime_component_sha256"] == mapping
                              and candidate["runtime_root"] == runtime_root,
        "qualification": run_qualification() == read(out, "qualification_report.json"),
        "diagnostics": diagnostics == read(out, "diagnostics_report.json"),
        "public_reproducer": public_reproducer_record() == read(
            out, "T27_PUBLIC_ROOT_CAUSE_REPRODUCTION.json"),
        "protections": run_protection(root) == read(out, "protection_report.json"),
        "construction_rehearsals": construction == read(
            out, "construction_rehearsal_report.json"),
        "evaluation_rehearsals": evaluation == read(
            out, "evaluation_rehearsal_report.json"),
        "construction_failure_rehearsal": failures["construction"] == read(
            out, "failure_rehearsal_report.json")["construction"],
        "evaluation_failure_rehearsal": failures["evaluation"] == read(
            out, "failure_rehearsal_report.json")["evaluation"],
        "negative_controls": run_negative_controls(root, historical) == read(
            out, "construction_negative_controls.json"),
        "doctor": run_doctor(root)["status"] == "PASS",
        "production_graph": production_graph() == read(out, "production_graph.json"),
        "authority_graph": authority_graph() == read(out, "authority_graph.json"),
        "official_runner": runner_identity(root) == read(
            out, "official_runner_identity.json"),
        "freeze": verify_freeze_v2(
            root, read(out, "preconstruction_freeze_v2.json"))["status"] == "PASS",
        "public_leak_scan": run_publication_leak_gate(root)["status"] == "PASS",
    }
    return {
        "schema_version": "t27-fresh-remote-reproduction-v2",
        "artifact": "T27_FRESH_REMOTE_REPRODUCTION_V2",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "semantic_drift": sum(not value for value in checks.values()),
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0, "real_evaluation_attempts": 0,
        "t26_private_rows_opened": 0, "t26_reruns": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = reproduce(args.root)
    if args.write:
        path = args.root.resolve() / "evaluations/t27/fresh_remote_reproduction_v2.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
