"""Official metric measurement semantics: closed loader and validator.

T21R16 failed because its frozen scorer derived unregistered metrics from a
generic aggregate (overall accuracy). T21R17 closes that defect
structurally: every official floor metric must carry an explicit frozen
measurement semantic contract (numerator, denominator, aggregation scope,
direction, row evidence source, zero-denominator policy) before any
evaluation may run, and the scorer refuses to score anything the contract
does not register.

Derived only from metric names, preregistered evaluation lineage
(scripts/t21_run_eval.py, scripts/t21r6_run_eval.py), frozen floor
definitions, and the construction design vocabulary. No R16 blind case
informed any definition.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ContractError
from .util import sha256_file, sha256_json

SEMANTICS_SCHEMA_VERSION = "t21-official-metric-semantics-v1"
SEMANTICS_ARTIFACT = "T21R17_OFFICIAL_METRIC_SEMANTICS"

SEMANTIC_TYPES = frozenset(
    {
        "ACCURACY_HIGHER_IS_BETTER",
        "MACRO_ACCURACY_HIGHER_IS_BETTER",
        "RATE_HIGHER_IS_BETTER",
        "RATE_LOWER_IS_BETTER",
        "RATE_EXACT",
        "COUNT_LOWER_IS_BETTER",
    }
)
DIRECTIONS = frozenset({"HIGHER_IS_BETTER", "LOWER_IS_BETTER", "EXACT"})
POPULATION_GUARANTEES = frozenset({"DESIGN_MANDATED", "BEHAVIORAL"})
ZERO_DENOMINATOR_POLICIES = frozenset({"FAIL_CLOSED", "PREREGISTERED_CONVENTION", "NOT_APPLICABLE"})
AGGREGATIONS = frozenset(
    {"MICRO_OVER_POPULATION", "MACRO_OVER_DOMAINS", "SUM_COUNT", "CLAIM_SUM_RATIO"}
)
METRIC_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "artifact",
        "experiment",
        "rule",
        "floor_hash",
        "metric_count",
        "lineage",
        "status_vocabularies",
        "domain_universe",
        "population_predicates",
        "zero_denominator_conventions",
        "metrics",
    }
)
METRIC_ENTRY_KEYS = frozenset(
    {
        "metric_id",
        "family",
        "semantic_type",
        "direction",
        "numerator",
        "denominator",
        "aggregation",
        "aggregation_scope",
        "population",
        "row_evidence_inputs",
        "range",
        "operator",
        "threshold",
        "floor_consumers",
        "zero_denominator_policy",
        "lineage",
    }
)
POPULATION_KEYS = frozenset(
    {"predicate_id", "guarantee", "design_tags", "expected_status", "note"}
)
LINEAGE_KEYS = frozenset(
    {
        "source",
        "formula",
        "notes",
    }
)
PREDICATE_KEYS = frozenset(
    {
        "predicate_id",
        "field",
        "match",
        "values",
        "suite_families",
        "condition",
        "note",
    }
)
OPERATORS = frozenset({"=", "<=", ">="})


def _error(context: str, errors: list[str]) -> None:
    errors.append(context)


def validate_metric_semantics(document: dict[str, Any], floors: dict[str, Any]) -> dict[str, Any]:
    """Closed validation of an official metric semantics contract.

    The document must name exactly the registered floor metrics, each with a
    full semantic contract; the registered operators and thresholds must
    equal the frozen floors (no threshold repair), and direction must agree
    with the operator."""
    errors: list[str] = []
    if set(document) != METRIC_ROOT_KEYS:
        _error(f"semantics root fields differ: expected={sorted(METRIC_ROOT_KEYS)}, actual={sorted(document)}", errors)
        return {"status": "FAIL", "errors": errors}
    if document["schema_version"] != SEMANTICS_SCHEMA_VERSION:
        _error("unsupported semantics schema_version", errors)
    if document["artifact"] != SEMANTICS_ARTIFACT:
        _error("semantics artifact identity mismatch", errors)
    if document["experiment"] != "t21r17":
        _error("semantics experiment identity mismatch", errors)
    if not isinstance(document["rule"], str) or "generic fallback" not in document["rule"]:
        _error("semantics rule statement invalid", errors)
    floor_metrics = {
        metric: (spec["op"], spec["value"])
        for group, metrics in floors.items()
        for metric, spec in metrics.items()
    }
    if document["floor_hash"] != sha256_json(floors):
        _error("semantics floor hash does not match the frozen floors", errors)
    if document["metric_count"] != len(floor_metrics):
        _error("semantics metric_count does not match the frozen floor count", errors)
    metrics = document["metrics"]
    if not isinstance(metrics, dict):
        _error("semantics metrics must be an object", errors)
        metrics = {}
    missing = sorted(set(floor_metrics) - set(metrics))
    extra = sorted(set(metrics) - set(floor_metrics))
    if missing:
        _error(f"semantics missing registered metrics: {missing}", errors)
    if extra:
        _error(f"semantics carries unregistered metrics: {extra}", errors)
    for metric_id, entry in sorted(metrics.items()):
        context = f"semantics.{metric_id}"
        if metric_id not in floor_metrics:
            continue
        if set(entry) != METRIC_ENTRY_KEYS:
            _error(f"{context} fields differ: expected={sorted(METRIC_ENTRY_KEYS)}, actual={sorted(entry)}", errors)
            continue
        if entry["metric_id"] != metric_id:
            _error(f"{context} metric_id mismatch", errors)
        if entry["semantic_type"] not in SEMANTIC_TYPES:
            _error(f"{context} unknown semantic_type {entry['semantic_type']!r}", errors)
        if entry["direction"] not in DIRECTIONS:
            _error(f"{context} unknown direction {entry['direction']!r}", errors)
        op, threshold = floor_metrics[metric_id]
        if entry["operator"] != op or entry["threshold"] != threshold:
            _error(f"{context} operator/threshold differ from the frozen floor", errors)
        expected_direction = {"=": "EXACT", "<=": "LOWER_IS_BETTER", ">=": "HIGHER_IS_BETTER"}[op]
        if entry["direction"] != expected_direction:
            _error(f"{context} direction contradicts the registered operator", errors)
        if entry["aggregation"] not in AGGREGATIONS:
            _error(f"{context} unknown aggregation {entry['aggregation']!r}", errors)
        population = entry["population"]
        if not set(population) <= POPULATION_KEYS or "predicate_id" not in population:
            _error(f"{context} population violates the closed schema", errors)
        else:
            if population["predicate_id"] not in document["population_predicates"]:
                _error(f"{context} population references an unknown predicate", errors)
            if population.get("guarantee") not in POPULATION_GUARANTEES:
                _error(f"{context} unknown population guarantee", errors)
        policy = entry["zero_denominator_policy"]
        if not isinstance(policy, dict) or set(policy) - {"policy", "convention", "lineage"} or "policy" not in policy:
            _error(f"{context} zero_denominator_policy violates the closed schema", errors)
        elif policy["policy"] not in ZERO_DENOMINATOR_POLICIES:
            _error(f"{context} unknown zero_denominator_policy", errors)
        elif policy["policy"] == "PREREGISTERED_CONVENTION":
            if policy.get("convention") not in {"0.0", "1.0"}:
                _error(f"{context} preregistered convention must be 0.0 or 1.0", errors)
        elif "convention" in policy:
            _error(f"{context} {policy['policy']} policy must not carry a convention", errors)
        if not isinstance(entry["row_evidence_inputs"], list) or not entry["row_evidence_inputs"]:
            _error(f"{context} row_evidence_inputs must be a non-empty array", errors)
        if not isinstance(entry["floor_consumers"], list) or not entry["floor_consumers"]:
            _error(f"{context} floor_consumers must be a non-empty array", errors)
        family_metrics = [
            metric
            for group, group_metrics in floors.items()
            if group == entry["family"]
            for metric in group_metrics
        ]
        if metric_id not in family_metrics:
            _error(f"{context} family does not match the frozen floor group", errors)
        if set(entry["lineage"]) != LINEAGE_KEYS or not entry["lineage"]["source"]:
            _error(f"{context} lineage violates the closed schema", errors)
        if not isinstance(entry["numerator"], str) or not entry["numerator"]:
            _error(f"{context} numerator must be a non-empty definition", errors)
        if not isinstance(entry["denominator"], str):
            _error(f"{context} denominator must be a definition", errors)
        if not isinstance(entry["range"], list) or len(entry["range"]) != 2:
            _error(f"{context} range must be a two-element array", errors)
    predicates = document["population_predicates"]
    if not isinstance(predicates, dict) or not predicates:
        _error("population_predicates must be a non-empty object", errors)
    else:
        for predicate_id, predicate in predicates.items():
            if not set(predicate) <= PREDICATE_KEYS or "field" not in predicate:
                _error(f"population_predicates.{predicate_id} violates the closed schema", errors)
    conventions = document["zero_denominator_conventions"]
    if not isinstance(conventions, dict) or not conventions:
        _error("zero_denominator_conventions must be a non-empty object", errors)
    if not isinstance(document["domain_universe"], list) or not document["domain_universe"]:
        _error("domain_universe must be a non-empty array", errors)
    vocabularies = document["status_vocabularies"]
    if not isinstance(vocabularies, dict) or not vocabularies:
        _error("status_vocabularies must be a non-empty object", errors)
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def load_metric_semantics(
    root: Path,
    contract: Any,
    *,
    relative: str | None = None,
    floors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and validate the frozen semantics artifact from a workspace."""
    from .contract import value_at_path
    from .util import read_json

    relative = relative or contract.get("artifacts.official_metric_semantics")
    floors = floors if floors is not None else contract.get("promotion_floors")
    path = root / relative
    document = read_json(path)
    report = validate_metric_semantics(document, floors)
    if report["status"] != "PASS":
        raise ContractError("; ".join(report["errors"]))
    return document


def semantics_sha256(root: Path, relative: str) -> str:
    return sha256_file(root / relative)


def semantics_root(document: dict[str, Any]) -> str:
    """Canonical semantic root of a frozen semantics contract."""
    return sha256_json(document)