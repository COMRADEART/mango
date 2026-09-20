"""Contract-derived exact-design validation."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .errors import ValidationError


def expected_design(contract: Any) -> dict[str, Any]:
    design = contract.get("exact_design")
    flattened: dict[str, int] = {}
    for family, requirements in design.items():
        if not isinstance(requirements, dict):
            raise ValidationError(f"exact-design family is not an object: {family}")
        for tag, count in requirements.items():
            if not isinstance(count, (int, bool)) or (isinstance(count, int) and not isinstance(count, bool) and count <= 0):
                raise ValidationError(f"invalid exact-design requirement: {family}.{tag}")
            flattened[f"{family}.{tag}"] = count
    return flattened


def audit_rows(rows: Iterable[dict[str, Any]], contract: Any) -> dict[str, Any]:
    rows_materialized = list(rows)
    expected = expected_design(contract)
    observed: Counter[str] = Counter()
    missing_context = 0
    for row in rows_materialized:
        tag = row.get("construction_tag")
        if tag is None:
            if row.get("suite_family") in contract.get("exact_design"):
                missing_context += 1
            continue
        if not isinstance(tag, str):
            raise ValidationError("construction_tag must be a string")
        observed[f"{row.get('suite_family')}.{tag}"] += 1
    row_expected = {name: count for name, count in expected.items() if not name.startswith("crossdomain.")}
    mismatches = {
        name: {"expected": count, "observed": observed.get(name, 0)}
        for name, count in row_expected.items()
        if observed.get(name, 0) != count
    }
    cross_rows = {name.split(".", 1)[1]: count for name, count in observed.items() if name.startswith("crossdomain.")}
    cross_expected = {
        "novel_pair_families": expected.get("crossdomain.novel_pair_families"),
        "rows_per_pair": expected.get("crossdomain.rows_per_pair"),
        "prior_exact_pair_templates_forbidden": expected.get("crossdomain.prior_exact_pair_templates_forbidden"),
    }
    if len(cross_rows) != cross_expected["novel_pair_families"]:
        mismatches["crossdomain.novel_pair_families"] = {"expected": cross_expected["novel_pair_families"], "observed": len(cross_rows)}
    if cross_rows and set(cross_rows.values()) != {cross_expected["rows_per_pair"]}:
        mismatches["crossdomain.rows_per_pair"] = {"expected": cross_expected["rows_per_pair"], "observed": sorted(set(cross_rows.values()))}
    prior_overlap = any(bool(row.get("prior_pair_template_overlap")) for row in rows_materialized)
    if cross_expected["prior_exact_pair_templates_forbidden"] is True and prior_overlap:
        mismatches["crossdomain.prior_exact_pair_templates_forbidden"] = {"expected": True, "observed": False}
    known_row_tags = set(row_expected) | {f"crossdomain.{pair_id}" for pair_id in cross_rows}
    unknown = sorted(set(observed) - known_row_tags)
    return {
        "status": "PASS" if not mismatches and not unknown and not missing_context else "FAIL",
        "requirements": len(expected),
        "passed": len(expected) - len(mismatches),
        "failed": len(mismatches),
        "missing_context": missing_context,
        "unknown_tags": unknown,
        "mismatches": mismatches,
    }


def require_exact_design(rows: Iterable[dict[str, Any]], contract: Any) -> dict[str, Any]:
    report = audit_rows(rows, contract)
    if report["status"] != "PASS":
        raise ValidationError(f"exact-design audit failed: {report}")
    return report
