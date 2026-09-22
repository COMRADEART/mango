"""Seal-independent gold validation and sealed official preflight."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ValidationError
from .exact_design import require_exact_design
from .seal import verify_seal
from .taxonomy import load_taxonomy, validate_labels
from .util import iter_jsonl, sha256_json


def _validate_gold_bundle(root: Path, contract: Any) -> dict[str, Any]:
    suites = contract.get("suites")
    suite_root = root / "evaluations" / contract.experiment / "suites"
    taxonomy = load_taxonomy(root / contract.get("artifacts.domain_taxonomy"))
    rows: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    counts: dict[str, int] = {}
    for suite_name, spec in suites.items():
        path = suite_root / suite_name / "holdout.jsonl"
        if not path.is_file():
            raise ValidationError(f"missing suite: {suite_name}")
        suite_rows = list(iter_jsonl(path))
        if len(suite_rows) != spec["count"]:
            raise ValidationError(f"suite count mismatch: {suite_name}")
        counts[suite_name] = len(suite_rows)
        for index, row in enumerate(suite_rows):
            context = f"{suite_name}:{index + 1}"
            required = {"case_id", "suite_family", "query", "mode", "gold"}
            if not required <= set(row) or not isinstance(row["gold"], dict):
                raise ValidationError(f"{context}: gold row schema invalid")
            if row["case_id"] in seen_case_ids:
                raise ValidationError(f"{context}: duplicate case_id")
            seen_case_ids.add(row["case_id"])
            if not row["case_id"].startswith(contract.get("identity.case_id_prefix")):
                raise ValidationError(f"{context}: case_id namespace mismatch")
            validate_labels(row["gold"].get("required_domains", []), taxonomy, context=context)
            allowed_statuses = {"ANSWER", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"}
            if contract.experiment == "t22":
                # T22 temporal routing rows carry the frozen runtime route
                # status as their gold expectation (the t22 author contract's
                # ROUTE_STATUSES); prior experiments' gold semantics unchanged.
                allowed_statuses |= {"ROUTE_WEB_RESEARCH"}
            if row["gold"].get("expect_status") not in allowed_statuses:
                raise ValidationError(f"{context}: unknown expected status")
            rows.append(row)
    expected_total = contract.get("suite_total")
    if len(rows) != expected_total:
        raise ValidationError(f"gold total mismatch: {len(rows)} != {expected_total}")
    exact = require_exact_design(rows, contract)
    floors = contract.get("promotion_floors")
    floor_count = sum(len(group) for group in floors.values())
    if floor_count != 32 or sha256_json(floors) != contract.get("roots.floor_hash"):
        raise ValidationError("promotion floors are incompatible with the frozen floor contract")
    return {
        "status": "PASS",
        "rows": len(rows),
        "suites": counts,
        "taxonomy_labels": len(taxonomy["domains"]),
        "exact_design": exact,
        "floor_paths": floor_count,
        "rows_materialized": rows,
    }


def validate_gold_bundle(root: Path, contract: Any) -> dict[str, Any]:
    """Validate gold/scorer compatibility without requiring a seal."""
    return _validate_gold_bundle(root, contract)


def validate_sealed_evaluation_bundle(root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    """Run the same gold validator, plus complete seal verification."""
    gold = _validate_gold_bundle(root, contract)
    seal = verify_seal(root, contract, graph)
    return {"status": "PASS", "gold": gold, "seal": seal, "same_gold_validator": True}
