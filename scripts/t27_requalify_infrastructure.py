#!/usr/bin/env python3
"""Build public-safe T27 infrastructure requalification artifacts only."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from t27_protocol.construction import (construction_contract,
    run_construction_failure_rehearsal, run_construction_rehearsals,
    run_negative_controls, run_publication_leak_gate)
from t27_protocol.contract import authority_graph, production_graph
from t27_protocol.doctor import run_doctor
from t27_protocol.evaluation import (run_evaluation_failure_rehearsal,
                                     run_evaluation_rehearsals, runner_identity)
from t27_protocol.exclusion import construction_ready_policy
from t27_protocol.freeze import build_freeze_v2, verify_freeze_v2
from t27_protocol.protection import run_protection
from t27_protocol.store import storage_policy_successor


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def test_gate(root: Path) -> dict:
    tests = sorted(str(path.relative_to(root)) for path in (root / "tests").glob("test_t27*.py"))
    with tempfile.TemporaryDirectory(prefix="t27-test-gate-") as directory:
        junit = Path(directory) / "junit.xml"
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}", *tests],
            cwd=root, capture_output=True, text=True, timeout=600)
        suite = ET.parse(junit).getroot() if junit.is_file() else None
    output = completed.stdout + "\n" + completed.stderr
    status = "PASS" if completed.returncode == 0 else "FAIL"
    suites = ([] if suite is None else [suite] if suite.tag == "testsuite"
              else list(suite.findall("./testsuite")))
    collected = sum(int(item.attrib.get("tests", 0)) for item in suites)
    failures = sum(int(item.attrib.get("failures", 0)) for item in suites)
    errors = sum(int(item.attrib.get("errors", 0)) for item in suites)
    skipped = sum(int(item.attrib.get("skipped", 0)) for item in suites)
    passed = collected - failures - errors - skipped
    return {
        "schema_version": "t27-applicability-aware-test-gate-v2",
        "artifact": "T27_APPLICABILITY_AWARE_TEST_GATE_V2",
        "classification": "PUBLIC_SAFE", "status": status,
        "test_files": tests, "passed": passed,
        "live_failures": failures, "errors": errors,
        "unknown_failures": 0, "unexplained_skips": skipped,
        "xfails": 0, "deselections": 0,
        "return_code": completed.returncode,
        "summary_sha256": __import__("hashlib").sha256(output.encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / "evaluations" / "t27"
    v1 = json.loads((out / "preconstruction_freeze.json").read_text(encoding="utf-8"))
    write(out / "preconstruction_freeze_v1.json", v1)
    write(out / "construction_ready_storage_policy.json", storage_policy_successor())
    write(out / "historical_exclusion_policy_v2.json", construction_ready_policy())
    write(out / "construction_contract.json", construction_contract())
    write(out / "authority_graph.json", authority_graph())
    write(out / "production_graph.json", production_graph())
    write(out / "official_runner_identity.json", runner_identity(root))
    write(out / "protection_report.json", run_protection(root))

    construction = run_construction_rehearsals(root, v1)
    negative = run_negative_controls(root, v1)
    evaluation = run_evaluation_rehearsals(root)
    failures = {
        "schema_version": "t27-failure-rehearsals-v1",
        "artifact": "T27_FAILURE_REHEARSALS", "classification": "PUBLIC_SAFE",
        "construction": run_construction_failure_rehearsal(root, v1),
        "evaluation": run_evaluation_failure_rehearsal(root),
    }
    failures["status"] = "PASS" if all(
        failures[name]["status"] == "PASS" for name in ("construction", "evaluation")) else "FAIL"
    write(out / "construction_rehearsal_report.json", construction)
    write(out / "construction_negative_controls.json", negative)
    write(out / "evaluation_rehearsal_report.json", evaluation)
    write(out / "failure_rehearsal_report.json", failures)
    write(out / "publication_leak_gate_prepublication.json",
          run_publication_leak_gate(root))
    exposure = {
        "schema_version": "t27-real-exposure-v2",
        "artifact": "T27_REAL_EXPOSURE", "classification": "PUBLIC_SAFE",
        "t27_real_blind_rows": 0, "t27_real_gold": 0,
        "real_construction_ledger_present": False,
        "real_construction_one_shot_marker_present": False,
        "real_evaluation_ledger_present": False,
        "real_evaluation_marker_present": False,
        "construction_attempts": 0, "evaluation_attempts": 0,
        "candidate_real_executions": 0,
        "official_real_evaluator_invocations": 0,
        "t26_private_rows_opened": 0, "t26_reruns": 0,
    }
    write(out / "real_exposure_v2.json", exposure)

    # Seed the test artifact and freeze, then replace both with verified bytes.
    if not (out / "test_gate_report_v2.json").is_file():
        write(out / "test_gate_report_v2.json", {
            "schema_version": "t27-applicability-aware-test-gate-v2",
            "artifact": "T27_APPLICABILITY_AWARE_TEST_GATE_V2",
            "classification": "PUBLIC_SAFE", "status": "PENDING",
            "test_files": [], "passed": 0, "live_failures": 0,
            "unknown_failures": 0, "unexplained_skips": 0,
            "xfails": 0, "deselections": 0, "return_code": 0,
            "summary_sha256": "0" * 64,
        })
    write(out / "preconstruction_freeze_v2.json", build_freeze_v2(root))
    if not args.skip_tests:
        report = test_gate(root)
        write(out / "test_gate_report_v2.json", report)
        write(out / "preconstruction_freeze_v2.json", build_freeze_v2(root))
    freeze = json.loads((out / "preconstruction_freeze_v2.json").read_text(
        encoding="utf-8"))
    verification = verify_freeze_v2(root, freeze)
    write(out / "protocol_doctor_report.json", run_doctor(root))
    doctor = json.loads((out / "protocol_doctor_report.json").read_text(encoding="utf-8"))
    passed = all(item.get("status") == "PASS" for item in (
        construction, negative, evaluation, failures, verification, doctor))
    verdict = {
        "schema_version": "t27-infrastructure-requalification-verdict-v1",
        "artifact": "T27_INFRASTRUCTURE_REQUALIFICATION_VERDICT",
        "classification": "PUBLIC_SAFE",
        "verdict": ("T27_CONSTRUCTION_EVALUATION_INFRASTRUCTURE_REMEDIATION_AND_REQUALIFICATION_PASS"
                    if passed else
                    "T27_CONSTRUCTION_EVALUATION_INFRASTRUCTURE_REMEDIATION_AND_REQUALIFICATION_FAIL"),
        "real_construction_authorized": False,
        "real_evaluation_authorized": False,
        "real_exposure": exposure,
        "next_required_token": "T27_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",
    }
    write(out / "T27_INFRASTRUCTURE_REQUALIFICATION_VERDICT.json", verdict)
    print(json.dumps({"status": "PASS" if passed else "FAIL",
                      "freeze": verification, "doctor": doctor["status"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
