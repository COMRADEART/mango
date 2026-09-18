"""Machine enforcement for the preregistered T21R8 construction contract.

This module is data-only: it does not import or execute the Knowledge RAG
runtime.  The future static gold audit records construction metrics, calls
``build_audit_section``, and embeds the returned section in
``evaluations/t21r8/static_gold_audit.json``.  The holdout freeze calls
``assert_static_audit_passes`` against that exact artifact.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "evaluations" / "t21r8" / "holdout_construction_contract.json"
)
STATIC_AUDIT_PATH = ROOT / "evaluations" / "t21r8" / "static_gold_audit.json"


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


def _maximum(check_id: str, observed: int | float, required: int | float) \
        -> dict:
    return _check(check_id, observed, "<=", required, observed <= required)


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

    checks.append(_check(
        "total_rows", total_rows, "=", int(contract["total_rows"]["exact"]),
        total_rows == int(contract["total_rows"]["exact"])))

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
    checks.append(_minimum(
        "stress.multihop_rows", int(stresses["multihop_rows"]),
        int(stress_rules["multihop_rows"]["minimum"])))
    checks.append(_minimum(
        "stress.multihop_chain_families",
        int(stresses["multihop_chain_families"]),
        int(stress_rules["multihop_chain_families"]["minimum"])))
    checks.append(_maximum(
        "stress.multihop_largest_chain_family_share",
        float(stresses["multihop_largest_chain_family_share"]),
        float(stress_rules["multihop_largest_chain_family_share"][
            "maximum"])))
    multihop_rows = int(stresses["multihop_rows"])
    multihop_fraction = (
        int(stresses["multihop_surface_mismatch_rows"]) / multihop_rows
        if multihop_rows else 0.0)
    checks.append(_minimum(
        "stress.multihop_relation_surface_mismatch_fraction",
        multihop_fraction,
        float(stress_rules["multihop_relation_surface_mismatch_fraction"][
            "minimum"])))

    checks.append(_minimum(
        "stress.crossdomain_rows", int(stresses["crossdomain_rows"]),
        int(stress_rules["crossdomain_rows"]["minimum"])))
    checks.append(_minimum(
        "stress.crossdomain_two_sources_two_domains",
        int(stresses["crossdomain_two_source_two_domain_rows"]),
        int(stress_rules["crossdomain_two_sources_two_domains"]["minimum"])))
    checks.append(_minimum(
        "stress.domain_pair_families", int(stresses["domain_pair_families"]),
        int(stress_rules["domain_pair_families"]["minimum"])))
    checks.append(_maximum(
        "stress.largest_domain_pair_share",
        float(stresses["largest_domain_pair_share"]),
        float(stress_rules["largest_domain_pair_share"]["maximum"])))
    checks.append(_minimum(
        "stress.multisource_path_required_rows",
        int(stresses["multisource_path_rows"]),
        int(stress_rules["multisource_path_required_rows"]["minimum"])))

    checks.append(_minimum(
        "stress.partial_path_ie_stress_rows",
        int(stresses["partial_path_ie_rows"]),
        int(stress_rules["partial_path_ie_stress_rows"]["minimum"])))
    for configuration in stress_rules[
            "partial_path_ie_stress_rows"]["required_configurations"]:
        observed = int(stresses["ie_configurations"].get(configuration, 0))
        checks.append(_minimum(
            f"stress.ie_configuration.{configuration}", observed,
            int(stress_rules["partial_path_ie_stress_rows"].get(
                "configuration_minimum", 1))))

    checks.append(_minimum(
        "stress.relation_surface_sensitive_rows",
        int(stresses["relation_surface_sensitive_rows"]),
        int(stress_rules["relation_surface_sensitive_rows"]["minimum"])))
    checks.append(_minimum(
        "stress.relation_surface_canonical_relations",
        len(stresses["canonical_relations"]),
        int(stress_rules["relation_surface_canonical_relations"]["minimum"])))
    surface_rows = int(stresses["relation_surface_sensitive_rows"])
    surface_fraction = (
        int(stresses["relation_surface_mismatch_rows"]) / surface_rows
        if surface_rows else 0.0)
    checks.append(_minimum(
        "stress.relation_surface_mismatch_fraction", surface_fraction,
        float(stress_rules["relation_surface_mismatch_fraction"]["minimum"])))

    checks.append(_minimum(
        "stress.source_injection_rows",
        int(stresses["source_injection_safe_fact_rows"]),
        int(stress_rules["source_injection_rows"]["minimum"])))
    checks.append(_minimum(
        "stress.query_injection_or_spoof_rows",
        int(stresses["query_injection_or_spoof_rows"]),
        int(stress_rules["query_injection_or_spoof_rows"]["minimum"])))
    checks.append(_minimum(
        "stress.safe_fact_with_directive_rows",
        int(stresses["safe_fact_with_directive_rows"]),
        int(stress_rules["safe_fact_with_directive_rows"]["minimum"])))

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