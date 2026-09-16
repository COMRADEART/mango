"""Machine enforcement for the preregistered T21R7 construction contract.

This module is data-only: it does not import or execute the Knowledge RAG
runtime.  The future static gold audit records construction metrics, calls
``build_audit_section``, and embeds the returned section in
``evaluations/t21r7/static_gold_audit.json``.  The holdout freeze calls
``assert_static_audit_passes`` against that exact artifact.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "evaluations" / "t21r7" / "holdout_construction_contract.json"
)
STATIC_AUDIT_PATH = ROOT / "evaluations" / "t21r7" / "static_gold_audit.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check(
    check_id: str, observed: Any, op: str, required: Any, passed: bool,
) -> dict:
    return {
        "id": check_id,
        "observed": observed,
        "op": op,
        "required": required,
        "passed": bool(passed),
    }


def _minimum(check_id: str, observed: int | float, required: int | float) \
        -> dict:
    return _check(check_id, observed, ">=", required, observed >= required)


def _zero(check_id: str, observed: int) -> dict:
    return _check(check_id, observed, "=", 0, observed == 0)


def evaluate_metrics(contract: Mapping[str, Any],
                     metrics: Mapping[str, Any]) -> list[dict]:
    """Evaluate every construction requirement against measured metrics.

    ``metrics`` must be computed from the future frozen-candidate corpus and
    suites by the static audit.  Missing keys are an error, never a zero or a
    passing default.
    """
    checks: list[dict] = []
    total_rows = int(metrics["total_rows"])
    suite_rows = metrics["suite_rows"]
    stresses = metrics["stresses"]
    independence = metrics["independence"]

    checks.append(_zero(
        "audit.annotation_violations",
        int(metrics["annotation_violations"])))

    checks.append(_minimum(
        "total_rows", total_rows, int(contract["total_rows"]["minimum"])))

    suite_total = 0
    for suite_name, rule in contract["suite_target_minimums"].items():
        observed = int(suite_rows[suite_name])
        suite_total += observed
        checks.append(_minimum(
            f"suite_rows.{suite_name}", observed, int(rule["minimum"])))
    checks.append(_check(
        "suite_rows.sum_equals_total", suite_total, "=", total_rows,
        suite_total == total_rows))

    stress_rules = contract["stress_requirements"]
    direct_stresses = (
        "relation_paraphrase_sensitive_rows",
        "qualifier_sensitive_rows",
        "non_binding_qualifier",
        "identity_critical_qualifier",
        "routing_boundary_rows",
        "absent_entity_conflict_stress_rows",
        "source_injection_safe_fact_rows",
        "query_injection_or_spoof_rows",
    )
    for name in direct_stresses:
        observed = int(stresses[name])
        checks.append(_minimum(
            f"stress.{name}", observed,
            int(stress_rules[name]["minimum"])))

    relations = sorted(set(stresses["canonical_relations"]))
    checks.append(_minimum(
        "stress.canonical_relations_covered", len(relations),
        int(stress_rules["canonical_relations_covered"]["minimum"])))

    mismatch_rows = int(stresses["relation_surface_mismatch_rows"])
    relation_rows = int(stresses["relation_paraphrase_sensitive_rows"])
    mismatch_fraction = mismatch_rows / relation_rows if relation_rows else 0.0
    checks.append(_minimum(
        "stress.relation_surface_mismatch_fraction", mismatch_fraction,
        float(stress_rules["relation_surface_mismatch_fraction"]["minimum"])))
    checks.append(_check(
        "stress.relation_surface_mismatch_numerator_within_denominator",
        mismatch_rows, "<=", relation_rows, mismatch_rows <= relation_rows))

    milestones = contract["independence_requirements"][
        "comparison_milestones"]
    dimensions = contract["independence_requirements"][
        "zero_overlap_dimensions"]
    maximum = int(contract["independence_requirements"]["maximum_overlap"])
    attack_overlaps = []
    for milestone in milestones:
        milestone_counts = independence[milestone]
        for dimension in dimensions:
            observed = int(milestone_counts[dimension])
            checks.append(_check(
                f"independence.{milestone}.{dimension}", observed, "<=",
                maximum, observed <= maximum))
            if dimension == "verbatim_attacks":
                attack_overlaps.append(observed)
    checks.append(_check(
        "stress.fresh_attack_wording", sum(attack_overlaps), "=", 0,
        bool(stress_rules["fresh_attack_wording"]["required"])
        and all(value == 0 for value in attack_overlaps)))
    return checks


def build_audit_section(
    metrics: Mapping[str, Any], contract_path: Path = CONTRACT_PATH,
) -> dict:
    """Build the exact construction section embedded by the static audit."""
    contract = load_contract(contract_path)
    checks = evaluate_metrics(contract, metrics)
    return {
        "construction_contract_path": contract_path.relative_to(ROOT).as_posix(),
        "construction_contract_sha256": sha256_file(contract_path),
        "metrics": metrics,
        "checks": checks,
        "requirements_evaluated": len(checks),
        "requirements_passed": sum(check["passed"] for check in checks),
        "status": "PASS" if all(check["passed"] for check in checks) else "FAIL",
    }


def validate_static_audit(
    audit: Mapping[str, Any], contract_path: Path = CONTRACT_PATH,
) -> dict:
    """Reject a stale, incomplete, tampered, or failing static audit."""
    if audit.get("status") != "PASS":
        raise ValueError("static gold audit status is not PASS")
    section = audit.get("construction_contract")
    if not isinstance(section, Mapping):
        raise ValueError("static gold audit lacks construction_contract section")
    expected_hash = sha256_file(contract_path)
    if section.get("construction_contract_sha256") != expected_hash:
        raise ValueError("construction contract hash is missing or stale")
    expected_checks = evaluate_metrics(
        load_contract(contract_path), section["metrics"])
    if section.get("checks") != expected_checks:
        raise ValueError("construction checks are missing, stale, or tampered")
    if section.get("requirements_evaluated") != len(expected_checks):
        raise ValueError("not every construction requirement was evaluated")
    passed = sum(check["passed"] for check in expected_checks)
    if section.get("requirements_passed") != passed:
        raise ValueError("construction pass count is inconsistent")
    if not all(check["passed"] for check in expected_checks):
        raise ValueError("one or more construction requirements failed")
    if section.get("status") != "PASS":
        raise ValueError("construction audit status is not PASS")
    return dict(section)


def assert_static_audit_passes(
    audit_path: Path = STATIC_AUDIT_PATH,
    contract_path: Path = CONTRACT_PATH,
) -> dict:
    if not audit_path.exists():
        raise ValueError(f"static audit missing: {audit_path}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    return validate_static_audit(audit, contract_path)
