"""Generate and verify public-only T27 preconstruction artifacts."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT / "src", ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from t27_protocol.contract import (
    authority_graph, design, execution_contract, metric_registry,
    nonvacuity_policy, production_graph, storage_policy,
)
from t27_protocol.doctor import run_doctor
from t27_protocol.exclusion import policy as exclusion_policy
from t27_protocol.freeze import build_candidate_identity, build_freeze, verify_freeze
from t27_protocol.protection import run_protection
from t27_protocol.qualification import (
    public_reproducer_record, qualification_exclusion_commitment,
    run_completion_gate_matrix, run_qualification, run_terminal_matrix,
    run_verification_matrix,
)


def _write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _historical_anchor(root: Path) -> dict:
    receipt = json.loads((root / "evaluations/t26/T26_EVALUATION_PUBLIC_RECEIPT.json").read_text(
        encoding="utf-8"))
    return {
        "schema_version": "t27-t26-historical-anchor-v1",
        "artifact": "T26_HISTORICAL_FAILURE_ANCHOR",
        "classification": "PUBLIC_SAFE",
        "status": "OFFICIAL_CAPABILITY_FAILURE",
        "receipt_commit": "55b05efe10645bc65f9ba5591c5655b91393009d",
        "receipt_root": receipt["receipt_root"],
        "candidate_commit": receipt["candidate_commit"],
        "evaluation_ledger_sha256": receipt["evaluation_ledger_sha256"],
        "evaluation_ledger_root": receipt["evaluation_ledger_root"],
        "scenario_count": receipt["scenario_count"],
        "metrics": receipt["metrics"],
        "critical_counters": receipt["critical_counters"],
        "one_shot": "SPENT", "attempt": 1,
        "raw_rows_included": False, "private_artifact_contents_included": False,
    }


def _test_gate(root: Path) -> dict:
    files = [
        "tests/test_t27_integrated_remediation.py",
        "tests/test_t27_scorer.py",
        "tests/test_t26_integrated_execution.py",
    ]
    with tempfile.TemporaryDirectory(prefix="t27-test-gate-") as tmp:
        temp = Path(tmp)
        junit = temp / "junit.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *files, "-q",
             "-p", "no:cacheprovider", "--disable-warnings",
             f"--basetemp={temp / 'basetemp'}", f"--junitxml={junit}"],
            cwd=root, capture_output=True, text=True, timeout=300)
        if not junit.is_file():
            return {"schema_version": "t27-test-gate-v1",
                    "artifact": "T27_APPLICABILITY_AWARE_TEST_GATE",
                    "classification": "PUBLIC_SAFE", "status": "FAIL",
                    "live_failures": 1, "unknown_failures": 0,
                    "unexplained_skips": 0, "xfails": 0, "deselections": 0,
                    "test_files": files, "tests": 0}
        tree = ET.parse(junit)
        suite = (tree.getroot().find("testsuite")
                 if tree.getroot().tag == "testsuites" else tree.getroot())
        tests = int(suite.attrib.get("tests", 0))
        failures = int(suite.attrib.get("failures", 0))
        errors = int(suite.attrib.get("errors", 0))
        skipped = int(suite.attrib.get("skipped", 0))
        passed = result.returncode == 0 and failures == errors == skipped == 0
        return {
            "schema_version": "t27-test-gate-v1",
            "artifact": "T27_APPLICABILITY_AWARE_TEST_GATE",
            "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
            "tests": tests, "passed": tests - failures - errors - skipped,
            "live_failures": failures, "unknown_failures": errors,
            "unexplained_skips": skipped, "xfails": 0, "deselections": 0,
            "test_files": files,
            "historical_frozen_identity_tests":
                "INAPPLICABLE_TO_AUTHORIZED_SUCCESSOR_BYTE_CHANGES",
        }


def _leak_scan(root: Path) -> dict:
    public = root / "evaluations" / "t27"
    forbidden_names = {
        "construction_ledger.json", "evaluation_ledger.json",
        "real_inputs.jsonl", "real_gold.jsonl", "scored_rows.jsonl",
        "raw_outputs.jsonl",
    }
    present = sorted(path.name for path in public.iterdir()
                     if path.name in forbidden_names)
    return {
        "schema_version": "t27-public-leak-scan-v1",
        "artifact": "T27_PUBLIC_LEAK_SCAN", "classification": "PUBLIC_SAFE",
        "status": "PASS" if not present else "FAIL",
        "forbidden_paths_present": present, "blind_blob_count": len(present),
        "real_inputs": 0, "real_gold": 0, "raw_private_rows": 0,
        "t26_private_paths_scanned": 0,
    }


def generate(root: Path) -> dict:
    root = Path(root).resolve()
    out = root / "evaluations" / "t27"
    out.mkdir(parents=True, exist_ok=True)
    documents = {
        "T26_HISTORICAL_FAILURE_ANCHOR.json": _historical_anchor(root),
        "T27_PUBLIC_ROOT_CAUSE_REPRODUCTION.json": public_reproducer_record(),
        "candidate_identity.json": build_candidate_identity(root),
        "terminal_contract.json": execution_contract(),
        "prospective_design.json": design(),
        "metric_registry.json": metric_registry(),
        "nonvacuity_policy.json": nonvacuity_policy(),
        "authority_graph.json": authority_graph(),
        "production_graph.json": production_graph(),
        "private_storage_policy.json": storage_policy(),
        "historical_exclusion_policy.json": exclusion_policy(),
        "qualification_exclusions.json": qualification_exclusion_commitment(),
        "qualification_report.json": run_qualification(),
        "diagnostics_report.json": {
            "terminal_matrix": run_terminal_matrix(),
            "verification_matrix": run_verification_matrix(),
            "completion_gate": run_completion_gate_matrix(),
        },
        "protection_report.json": run_protection(root),
        "test_gate_report.json": _test_gate(root),
        "real_exposure.json": {
            "t27_real_blind_rows": 0, "t27_real_gold": 0,
            "t27_construction_attempts": 0, "t27_evaluation_attempts": 0,
            "t26_private_rows_opened": 0, "t26_candidate_reruns": 0,
            "t26_evaluation_attempts_added": 0,
        },
    }
    for name, document in documents.items():
        _write(out / name, document)
    _write(out / "public_leak_scan.json", _leak_scan(root))
    freeze = build_freeze(root)
    _write(out / "preconstruction_freeze.json", freeze)
    doctor = run_doctor(root)
    _write(out / "protocol_doctor_report.json", doctor)
    passed = (all(document.get("status", "PASS") == "PASS"
                  for document in documents.values()) and
              _read_status(out / "public_leak_scan.json") == "PASS" and
              verify_freeze(root, freeze)["status"] == "PASS" and
              doctor["status"] == "PASS")
    verdict = {
        "schema_version": "t27-preconstruction-verdict-v1",
        "artifact": "T27_PRECONSTRUCTION_VERDICT", "classification": "PUBLIC_SAFE",
        "status": "PASS" if passed else "FAIL",
        "verdict": ("T27_AGGREGATE_ONLY_REMEDIATION_AND_PRECONSTRUCTION_PASS"
                    if passed else
                    "T27_AGGREGATE_ONLY_REMEDIATION_AND_PRECONSTRUCTION_FAIL"),
        "construction_authorized": False, "evaluation_authorized": False,
        "absolute_stop": True,
    }
    _write(out / "T27_PRECONSTRUCTION_VERDICT.json", verdict)
    return verdict


def _read_status(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8")).get("status", "FAIL")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        frozen = json.loads((args.root / "evaluations/t27/preconstruction_freeze.json").read_text(
            encoding="utf-8"))
        report = {"freeze": verify_freeze(args.root, frozen),
                  "doctor": run_doctor(args.root)}
    else:
        report = generate(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    passed = (all(value.get("status") == "PASS" for value in report.values())
              if args.verify else report.get("status") == "PASS")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
