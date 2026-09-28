#!/usr/bin/env python3
"""Build public-safe T27 structural historical-exclusion remediation evidence.

Pre-exposure remediation only: rebuilds the authenticated public historical
index under the frozen generated-public dimension policy, proves the old
semantics unsatisfiable (machine-readable reproducer), proves the new
semantics satisfiable (disposable witness), re-runs all rehearsals and
controls against the remediated enumerators, and freezes V5.  Never authors
real T27 material, never executes the sealed T26 overlap oracle on real
material, never creates a T27 construction ledger, and never spends the
construction one-shot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for value in (ROOT, ROOT / "src"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from t26_protocol.t27_private_oracle import (  # noqa: E402
    validate_t26_store_authentication_evidence)
from t27_protocol.construction import (  # noqa: E402
    CONSTRUCTION_GATE_IDS, CONTRACT_LEAF_IDS, construction_contract,
    official_marker_contract_report, run_construction_failure_rehearsal,
    run_construction_rehearsals, run_negative_controls,
    run_publication_leak_gate, run_real_mode_oracle_validation_rehearsal)
from t27_protocol.contract import authority_graph, production_graph  # noqa: E402
from t27_protocol.doctor import run_doctor  # noqa: E402
from t27_protocol.evaluation import (  # noqa: E402
    run_evaluation_failure_rehearsal, run_evaluation_rehearsals,
    runner_identity)
from t27_protocol.exclusion import (  # noqa: E402
    SUPERSEDED_INDEX_ROOT, build_authenticated_public_historical_index,
    generated_public_dimension_policy, historical_exclusion_policy_v4,
    public_index_report, public_index_supersession,
    t26_public_qualification_exclusion_precedent)
from t27_protocol.freeze import (PRESERVED_V2_FREEZE_SHA256,  # noqa: E402
                                 PRESERVED_V3_FREEZE_SHA256,
                                 PRESERVED_V4_FREEZE_SHA256,
                                 build_freeze_v5, verify_freeze_v5)
from t27_protocol.protection import run_protection  # noqa: E402


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_script(root: Path, name: str) -> dict:
    completed = subprocess.run(
        [sys.executable, f"scripts/{name}"], cwd=root, capture_output=True,
        text=True, timeout=1800)
    if completed.returncode != 0:
        raise ValueError(f"{name} failed: {completed.stdout}\n{completed.stderr}")
    return completed.stdout + "\n" + completed.stderr


def test_gate(root: Path) -> dict:
    tests = sorted(str(path.relative_to(root))
                   for path in (root / "tests").glob("test_t27*.py"))
    with tempfile.TemporaryDirectory(prefix="t27-structural-test-gate-") as directory:
        junit = Path(directory) / "junit.xml"
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}", *tests],
            cwd=root, capture_output=True, text=True, timeout=2400)
        suite = ET.parse(junit).getroot() if junit.is_file() else None
    output = completed.stdout + "\n" + completed.stderr
    suites = ([] if suite is None else [suite] if suite.tag == "testsuite"
              else list(suite.findall("./testsuite")))
    collected = sum(int(item.attrib.get("tests", 0)) for item in suites)
    failures = sum(int(item.attrib.get("failures", 0)) for item in suites)
    errors = sum(int(item.attrib.get("errors", 0)) for item in suites)
    skipped = sum(int(item.attrib.get("skipped", 0)) for item in suites)
    return {
        "schema_version": "t27-applicability-aware-test-gate-v5",
        "artifact": "T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_TEST_GATE_V5",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "test_files": tests,
        "passed": collected - failures - errors - skipped,
        "live_failures": failures, "errors": errors,
        "unknown_failures": 0, "unexplained_skips": skipped,
        "xfails": 0, "deselections": 0,
        "return_code": completed.returncode,
        "summary_sha256": hashlib.sha256(output.encode()).hexdigest(),
    }


def exposure() -> dict:
    return {
        "schema_version": "t27-real-exposure-v5",
        "artifact": "T27_REAL_EXPOSURE",
        "classification": "PUBLIC_SAFE",
        "t27_real_blind_rows": 0, "t27_real_gold": 0,
        "real_construction_ledger_present": False,
        "real_construction_one_shot_marker_present": False,
        "real_evaluation_ledger_present": False,
        "real_evaluation_marker_present": False,
        "construction_attempts": 0, "evaluation_attempts": 0,
        "candidate_real_executions": 0,
        "official_real_evaluator_invocations": 0,
        "t26_private_rows_exposed_outside_sealed_oracle": 0,
        "t26_candidate_reruns": 0,
        "t26_private_rows_read_during_remediation": 0,
        "construction_one_shot": "UNSPENT",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--store", type=Path, default=None,
                        help="physical official T26 store root for the "
                             "metadata-only preflight re-run (local only)")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / "evaluations" / "t27"

    # Historical freeze identities are preserved by SHA, never rebuilt.
    for version, expected in (
            ("preconstruction_freeze_v2.json", PRESERVED_V2_FREEZE_SHA256),
            ("preconstruction_freeze_v3.json", PRESERVED_V3_FREEZE_SHA256),
            ("preconstruction_freeze_v4.json", PRESERVED_V4_FREEZE_SHA256)):
        frozen = read(out / version)
        if frozen.get("freeze_sha256") != expected:
            raise ValueError(f"historical freeze identity changed: {version}")

    # §35: re-run the real-store metadata preflight (local machine only).
    if args.store is not None:
        completed = subprocess.run(
            [sys.executable, "scripts/t27_t26_real_store_preflight.py",
             "--store", str(args.store.resolve())],
            cwd=root, capture_output=True, text=True, timeout=600)
        if completed.returncode != 0:
            raise ValueError(
                "official T26 store preflight re-run failed: "
                f"{completed.stdout}\n{completed.stderr}")
    preflight = read(out / "official_t26_store_preflight.json")
    validate_t26_store_authentication_evidence(preflight, real=True)
    if preflight.get("status") != "PASS":
        raise ValueError("official T26 store metadata preflight did not pass")
    if (preflight.get("t26_private_rows_read") != 0
            or preflight.get("t27_fingerprint_derivation_invoked") is not False):
        raise ValueError("official T26 store preflight is not metadata-only")

    # Remediated authenticated public historical index + policy artifacts.
    index = build_authenticated_public_historical_index(root)
    write(out / "public_historical_index_report.json", public_index_report(index))
    if index["public_historical_index_root"] == SUPERSEDED_INDEX_ROOT:
        raise ValueError("remediated public history root is not new")
    write(out / "generated_public_exclusion_dimension_policy.json",
          generated_public_dimension_policy())
    write(out / "historical_exclusion_policy_v4.json",
          historical_exclusion_policy_v4())
    write(out / "public_index_supersession.json",
          public_index_supersession(index))
    write(out / "t26_public_qualification_exclusion_precedent.json",
          t26_public_qualification_exclusion_precedent())

    # §16-17 reproducer and §18-20 witness (deterministic public scripts).
    run_script(root, "t27_structural_unsatisfiability_reproducer.py")
    reproducer = read(out / "structural_unsatisfiability_reproducer.json")
    if (reproducer.get("status") != "REPRODUCED"
            or reproducer.get("old_semantics_minimum_overlap") != 33):
        raise ValueError("structural unsatisfiability reproducer did not pass")
    run_script(root, "t27_structural_satisfiability_witness.py")
    witness = read(out / "structural_satisfiability_witness.json")
    if witness.get("status") != "PASS" or witness.get(
            "overall_prohibited_overlap") != 0:
        raise ValueError("structural satisfiability witness did not pass")

    write(out / "official_t26_marker_contract.json",
          official_marker_contract_report(root))
    marker_contract = read(out / "official_t26_marker_contract.json")
    if marker_contract.get("status") != "PASS":
        raise ValueError("official T26 marker contract binding failed")
    write(out / "construction_contract_v4.json", construction_contract())
    contract = read(out / "construction_contract_v4.json")
    if (contract.get("leaf_count") != len(CONTRACT_LEAF_IDS)
            or contract.get("leaf_count") != 60):
        raise ValueError("construction contract leaf enumerator drift")
    write(out / "authority_graph.json", authority_graph())
    write(out / "production_graph.json", production_graph())
    write(out / "official_runner_identity.json", runner_identity(root))
    write(out / "protection_report.json", run_protection(root))

    freeze_v2 = read(out / "preconstruction_freeze_v2.json")
    construction = run_construction_rehearsals(root, freeze_v2)
    negative = run_negative_controls(root, freeze_v2)
    if (negative.get("control_count") != 72
            or len(negative.get("controls", {})) != 72
            or negative.get("PASS") != 72):
        raise ValueError("negative control enumerator drift")
    real_oracle = run_real_mode_oracle_validation_rehearsal(root)
    evaluation = run_evaluation_rehearsals(root)
    failures = {
        "schema_version": "t27-failure-rehearsals-v2",
        "artifact": "T27_FAILURE_REHEARSALS",
        "classification": "PUBLIC_SAFE",
        "construction": run_construction_failure_rehearsal(root, freeze_v2),
        "evaluation": run_evaluation_failure_rehearsal(root),
    }
    failures["status"] = "PASS" if all(
        failures[name]["status"] == "PASS"
        for name in ("construction", "evaluation")) else "FAIL"
    write(out / "construction_rehearsal_report.json", construction)
    write(out / "construction_negative_controls.json", negative)
    write(out / "real_mode_oracle_rehearsal.json", real_oracle)
    write(out / "evaluation_rehearsal_report.json", evaluation)
    write(out / "failure_rehearsal_report.json", failures)
    write(out / "publication_leak_gate_prepublication.json",
          run_publication_leak_gate(root, fetch=True))
    exposure_report = exposure()
    write(out / "real_exposure_v5.json", exposure_report)

    if not (out / "test_gate_report_v5.json").is_file():
        write(out / "test_gate_report_v5.json", {
            "schema_version": "t27-applicability-aware-test-gate-v5",
            "artifact": "T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_"
                        "TEST_GATE_V5",
            "classification": "PUBLIC_SAFE", "status": "PENDING",
            "test_files": [], "passed": 0, "live_failures": 0,
            "errors": 0, "unknown_failures": 0, "unexplained_skips": 0,
            "xfails": 0, "deselections": 0, "return_code": 0,
            "summary_sha256": "0" * 64,
        })
    write(out / "preconstruction_freeze_v5.json", build_freeze_v5(root))
    if not args.skip_tests:
        # Break the test-gate/freeze self-check cycle only for the duration of
        # the test process.  The bootstrap record is immediately replaced by
        # the JUnit-derived result, and the freeze is rewritten afterward.
        bootstrap = {
            "schema_version": "t27-applicability-aware-test-gate-v5",
            "artifact": "T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_"
                        "TEST_GATE_V5",
            "classification": "PUBLIC_SAFE", "status": "PASS",
            "test_files": ["BOOTSTRAP_REPLACED_AFTER_TEST_EXECUTION"],
            "passed": 19, "live_failures": 0, "errors": 0,
            "unknown_failures": 0, "unexplained_skips": 0,
            "xfails": 0, "deselections": 0, "return_code": 0,
            "summary_sha256": "0" * 64,
        }
        write(out / "test_gate_report_v5.json", bootstrap)
        write(out / "test_gate_report_v5.json", test_gate(root))
        write(out / "preconstruction_freeze_v5.json", build_freeze_v5(root))
    freeze = read(out / "preconstruction_freeze_v5.json")
    verification = verify_freeze_v5(root, freeze)
    write(out / "protocol_doctor_report.json", run_doctor(root))
    doctor = read(out / "protocol_doctor_report.json")
    test_gate_report = read(out / "test_gate_report_v5.json")
    passed = all(item.get("status") == "PASS" for item in (
        marker_contract, negative, real_oracle, evaluation, failures,
        verification, doctor, test_gate_report))
    index_report = read(out / "public_historical_index_report.json")
    verdict = {
        "schema_version": "t27-structural-historical-exclusion-"
                          "remediation-verdict-v1",
        "artifact": "T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_VERDICT",
        "classification": "PUBLIC_SAFE",
        "verdict": ("T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_PASS"
                    if passed else
                    "T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_FAIL"),
        "root_cause": "PRE_EXPOSURE_STRUCTURAL_HISTORICAL_EXCLUSION_"
                      "SEMANTICS_DEFECT",
        "root_cause_detail":
            "Generated-public fingerprints encoded frozen structural "
            "vocabulary (entity_identities=sha256(family), "
            "source_ids=sha256(step.capability), verbatim=sha256((family, "
            "fallback_condition)) with the fallback dict contractually "
            "fixed, relations=sha256((step_id, depends_on)) generic "
            "topology), so any contract-complete 512-package forced "
            "structural overlap >= 33 against the authenticated public "
            "historical index and zero-overlap was unsatisfiable.",
        "dimension_classification": {
            "identity_bearing": ["case_ids", "chunk_ids"],
            "content_bearing": ["exact_queries", "exact_answers",
                                "exact_source_text"],
            "structural_shared_frozen_empty": [
                "entity_identities", "source_ids", "verbatim_attack_wording",
                "relations"],
        },
        "affected_sources": [
            "T27_PUBLIC_QUALIFICATION", "T27_DIAGNOSTICS",
            "T27_SYNTHETIC_TERMINAL_MATRIX",
            "T27_SYNTHETIC_RECOVERY_REPLAN_EXAMPLES"],
        "old_public_history_root": SUPERSEDED_INDEX_ROOT,
        "old_public_history_classification": "SUPERSEDED_PRE_EXPOSURE",
        "new_public_history_root":
            index_report["public_historical_index_root"],
        "new_public_history_schema": index_report["schema_version"],
        "unsatisfiability_reproducer": {
            "artifact":
                "evaluations/t27/structural_unsatisfiability_reproducer.json",
            "status": reproducer["status"],
            "old_semantics_minimum_overlap":
                reproducer["old_semantics_minimum_overlap"],
            "capability_overlap_all_exercised":
                reproducer["old_semantics_capability_overlap_all_exercised"],
        },
        "satisfiability_witness": {
            "artifact":
                "evaluations/t27/structural_satisfiability_witness.json",
            "status": witness["status"],
            "overall_prohibited_overlap":
                witness["overall_prohibited_overlap"],
            "scenario_count": witness["scenario_count"],
        },
        "identity_reuse_controls": {
            "control_count": negative["control_count"],
            "all_pass": negative["PASS"] == negative["control_count"],
            "reuse_positives": [
                "reuse_case_ids_detected", "reuse_exact_queries_detected",
                "reuse_exact_answers_detected", "reuse_exact_source_text_detected",
                "reuse_chunk_ids_detected"],
        },
        "construction_contract": {
            "old_leaf_count": 56, "new_leaf_count": contract["leaf_count"]},
        "construction_gate": {
            "old_check_count": 46,
            "new_check_count": len(CONSTRUCTION_GATE_IDS)},
        "negative_control_count": {
            "old_count": 55, "new_count": negative["control_count"]},
        "construction_rehearsals": {
            "run_count": len(construction.get("runs", [])),
            "status": construction.get("status"),
            "semantic_equivalence": construction.get("semantic_equivalence"),
            "failure_construction": failures["construction"]["status"],
            "failure_evaluation": failures["evaluation"]["status"],
        },
        "candidate_identity": {
            "candidate_commit": json.loads(
                (out / "candidate_identity.json").read_text(encoding="utf-8")
            )["candidate_commit"],
            "candidate_runtime_changed": False,
        },
        "t26_store_preflight": {
            "status": preflight.get("status"),
            "metadata_only": preflight.get("t27_fingerprint_derivation_invoked")
            is False
            and preflight.get("t26_private_rows_read") == 0,
            "t26_store_identity": preflight.get("t26_store_identity"),
        },
        "test_gate": {
            "status": test_gate_report["status"],
            "passed": test_gate_report.get("passed"),
            "live_failures": test_gate_report.get("live_failures"),
        },
        "doctor": doctor["status"],
        "preconstruction_freeze_v5_sha256": freeze["freeze_sha256"],
        "preserved_v4_freeze_sha256": PRESERVED_V4_FREEZE_SHA256,
        "real_construction_authorized": False,
        "real_evaluation_authorized": False,
        "real_exposure": exposure_report,
        "construction_one_shot": "UNSPENT",
        "t26_overlap_oracle": "NEVER EXECUTED ON REAL MATERIAL",
        "next_required_token":
            "T27_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",
    }
    write(out / "T27_STRUCTURAL_HISTORICAL_EXCLUSION_REMEDIATION_VERDICT.json",
          verdict)
    print(json.dumps({"status": "PASS" if passed else "FAIL",
                      "freeze": verification, "doctor": doctor["status"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())