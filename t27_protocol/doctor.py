"""Fail-closed public T27 preconstruction doctor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract import CONSTRUCTION_TOKEN, EVALUATION_TOKEN, REPLAN_TRIGGERS
from .exclusion import DIMENSIONS
from .freeze import runtime_identity, verify_freeze


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "evaluations" / "t27" / name).read_text(
        encoding="utf-8"))


def run_doctor(root: Path) -> dict:
    root = Path(root).resolve()
    receipt = json.loads((root / "evaluations/t26/T26_EVALUATION_PUBLIC_RECEIPT.json").read_text(
        encoding="utf-8"))
    candidate = _read(root, "candidate_identity.json")
    contract = _read(root, "terminal_contract.json")
    metrics = _read(root, "metric_registry.json")
    nonvacuity = _read(root, "nonvacuity_policy.json")
    qualification = _read(root, "qualification_report.json")
    diagnostics = _read(root, "diagnostics_report.json")
    protection = _read(root, "protection_report.json")
    storage = _read(root, "private_storage_policy.json")
    exclusions = _read(root, "historical_exclusion_policy.json")
    freeze = _read(root, "preconstruction_freeze.json")
    mapping, runtime_root = runtime_identity(root)
    checks = {
        "t26_closed_no_rerun": receipt.get("state") == "COMPLETE" and
            receipt.get("attempt") == 1 and receipt.get("capability_status") == "FAIL",
        "t26_aggregate_only_boundary": receipt.get("raw_rows_included") is False and
            receipt.get("scenario_bodies_included") is False,
        "t26_private_artifacts_sealed": qualification.get("t26_private_rows_opened") == 0 and
            qualification.get("t26_candidate_reruns") == 0,
        "candidate_identity": candidate.get("runtime_component_sha256") == mapping and
            candidate.get("runtime_root") == runtime_root,
        "terminal_contract": set(contract.get("terminals", [])) == {
            "COMPLETE", "PARTIAL", "INSUFFICIENT_EVIDENCE", "BLOCKED",
            "BUDGET_EXHAUSTED", "UNAVAILABLE_CAPABILITY", "SECURITY_REFUSAL", "ERROR"},
        "completion_gate": diagnostics.get("completion_gate", {}).get("status") == "PASS",
        "recovery_contract": qualification["score"]["metrics"]["recovery_success_rate"]["pass"],
        "replan_contract": list(contract.get("replan_triggers", [])) == list(REPLAN_TRIGGERS) and
            qualification["score"]["metrics"]["replan_correctness_rate"]["pass"],
        "safe_abstention_contract": qualification["score"]["metrics"]["safe_abstention_accuracy"]["pass"],
        "metric_denominators": all(item.get("denominator", 0) > 0 and
                                   item.get("zero_denominator_policy") == "FAIL_NONVACUITY"
                                   for item in qualification["score"]["metrics"].values()),
        "nonvacuity_rules": nonvacuity.get("rate_policy") == "FAIL_NONVACUITY" and
            all(value > 0 for value in nonvacuity.get("requirements", {}).values()),
        "t19_protection": protection.get("t19", {}).get("tests", {}).get("status") == "PASS" and
            protection.get("t19", {}).get("authority") == "PROPOSE_ONLY",
        "t20_protection": protection.get("t20", {}).get("tests", {}).get("status") == "PASS" and
            protection.get("t20", {}).get("authority") == "COORDINATE_INTERNAL_WORK_ONLY",
        "t22_protection": protection.get("t22", {}).get("passed") == 32 and
            protection.get("t22", {}).get("total") == 32,
        "t25_router_protection": protection.get("t25_router", {}).get("floor_count") == 15 and
            protection.get("t25_router", {}).get("status") == "PASS",
        "t25_dispatch_protection": protection.get("t25_dispatch", {}).get("status") == "PASS",
        "private_store_policy": storage.get("store_id") == "T27-STORE-01" and
            storage.get("namespace") == "t27" and
            storage.get("locator_scheme") == "t27-private://",
        "nine_dimensional_exclusion": exclusions.get("dimensions") == list(DIMENSIONS) and
            exclusions.get("historical_source") == "T26_SEALED_HASH_OVERLAP_ORACLE_ONLY",
        "construction_token": _read(root, "prospective_design.json").get("construction_token") == CONSTRUCTION_TOKEN,
        "evaluation_token": _read(root, "prospective_design.json").get("evaluation_token") == EVALUATION_TOKEN,
        "qualification": qualification.get("status") == "PASS",
        "terminal_matrix": diagnostics.get("terminal_matrix", {}).get("status") == "PASS",
        "verification_matrix": diagnostics.get("verification_matrix", {}).get("status") == "PASS",
        "freeze": verify_freeze(root, freeze).get("status") == "PASS",
        "construction_ledger_absent": not (root / "evaluations/t27/construction_ledger.json").exists(),
        "evaluation_ledger_absent": not (root / "evaluations/t27/evaluation_ledger.json").exists(),
        "tokens_exact_no_aliases": CONSTRUCTION_TOKEN != EVALUATION_TOKEN,
    }
    return {
        "schema_version": "t27-doctor-v1", "artifact": "T27_PROTOCOL_DOCTOR",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "check_count": len(checks),
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
        "t26_private_paths_probed": 0, "t26_private_rows_opened": 0,
        "t26_candidate_reruns": 0,
    }
