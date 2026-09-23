"""Explicit T23 router metrics; every registered ID has one implementation."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from sciencemath.executive.router_v2 import REASON_ROUTE_MAP, ROUTE_IDS

ROOT = Path(__file__).resolve().parents[1]
FLOORS = ROOT / "evaluations" / "t23" / "router_metric_registry.json"
REGISTRY = ROOT / "evaluations" / "t23" / "production_router_metric_registry.json"
Row = dict[str, Any]
Metric = Callable[[list[Row]], tuple[int, int | None, float | int]]
STATIC = frozenset({"static_local_factual", "multi_hop_local", "cross_domain_local", "citation_sensitive", "ambiguous_route"})
CURRENT = frozenset({"explicit_current", "recency_sensitive"})


def _rate(rows: list[Row], predicate: Callable[[Row], bool]) -> tuple[int, int, float]:
    if not rows:
        raise ValueError("design-mandated router metric denominator is zero")
    numerator = sum(bool(predicate(row)) for row in rows)
    return numerator, len(rows), numerator / len(rows)


def _family(rows: list[Row], family: str) -> list[Row]:
    return [row for row in rows if row["gold"]["family"] == family]


def overall_route_accuracy(rows: list[Row]) -> tuple[int, int, float]:
    return _rate(rows, lambda row: row["decision"]["route_id"] == row["gold"]["expected_route"])


def route_macro_accuracy(rows: list[Row]) -> tuple[int, int, float]:
    rates = []
    for route in ROUTE_IDS:
        population = [row for row in rows if row["gold"]["expected_route"] == route]
        rates.append(_rate(population, lambda row: row["decision"]["route_id"] == route)[2])
    return sum(round(rate * 1000000) for rate in rates), len(rates) * 1000000, sum(rates) / len(rates)


def current_route_accuracy(rows: list[Row]) -> tuple[int, int, float]:
    return _rate([r for r in rows if r["gold"]["family"] in CURRENT],
                 lambda r: r["decision"]["route_id"] == r["gold"]["expected_route"])


def historical_route_accuracy(rows: list[Row]) -> tuple[int, int, float]:
    return _rate(_family(rows, "historical_as_of"),
                 lambda r: r["decision"]["route_id"] == r["gold"]["expected_route"])


def static_local_accuracy(rows: list[Row]) -> tuple[int, int, float]:
    return _rate([r for r in rows if r["gold"]["family"] in STATIC],
                 lambda r: r["decision"]["route_id"] == r["gold"]["expected_route"])


def tool_route_accuracy(rows: list[Row]) -> tuple[int, int, float]:
    return _rate(_family(rows, "tool_required"),
                 lambda r: r["decision"]["route_id"] == "TOOL_OR_SPECIALIST_ROUTE")


def security_route_accuracy(rows: list[Row]) -> tuple[int, int, float]:
    return _rate(_family(rows, "security_adversarial"),
                 lambda r: r["decision"]["route_id"] == "SECURITY_REFUSAL")


def conflict_abstention_route_accuracy(rows: list[Row]) -> tuple[int, int, float]:
    return _rate(_family(rows, "conflicting_evidence"),
                 lambda r: r["decision"]["route_id"] == "CONFLICT_HANDLING")


def unnecessary_web_rate(rows: list[Row]) -> tuple[int, int, float]:
    population = [r for r in rows if r["gold"]["family"] in STATIC]
    return _rate(population, lambda r: r["decision"]["route_id"] == "ROUTE_WEB_RESEARCH")


def unavailable_tool_route_events(rows: list[Row]) -> tuple[int, None, int]:
    count = sum(r["decision"]["route_id"] == "TOOL_OR_SPECIALIST_ROUTE"
                for r in _family(rows, "unsupported_tool_request"))
    return count, None, count


def unsafe_fallback_events(rows: list[Row]) -> tuple[int, None, int]:
    count = sum(r["decision"]["route_id"] != "SECURITY_REFUSAL"
                for r in _family(rows, "security_adversarial"))
    return count, None, count


def ambiguous_decision_events(rows: list[Row]) -> tuple[int, None, int]:
    count = sum(len(r["decision"].get("eligible_terminal_routes", [])) != 1 for r in rows)
    return count, None, count


def gold_signal_leakage_events(rows: list[Row]) -> tuple[int, None, int]:
    from .author import GOLD_ONLY

    count = sum(bool(set(r["candidate_input"]) & GOLD_ONLY) for r in rows)
    return count, None, count


def reason_route_contradictions(rows: list[Row]) -> tuple[int, None, int]:
    count = sum(r["decision"]["route_id"] not in REASON_ROUTE_MAP.get(r["decision"]["reason_code"], ())
                for r in rows)
    return count, None, count


def determinism_mismatches(rows: list[Row]) -> tuple[int, None, int]:
    fields = ("route_id", "reason_code", "selected_capability", "priority_resolution", "fallback")
    count = sum(any(r["decision"][field] != r["repeat_decision"][field] for field in fields)
                for r in rows)
    return count, None, count


IMPLEMENTATIONS: dict[str, Metric] = {
    function.__name__: function for function in (
        overall_route_accuracy, route_macro_accuracy, current_route_accuracy,
        historical_route_accuracy, static_local_accuracy, tool_route_accuracy,
        security_route_accuracy, conflict_abstention_route_accuracy,
        unnecessary_web_rate, unavailable_tool_route_events,
        unsafe_fallback_events, ambiguous_decision_events,
        gold_signal_leakage_events, reason_route_contradictions,
        determinism_mismatches,
    )
}


def implementation_hashes() -> dict[str, str]:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    segments = {node.name: ast.get_source_segment(source, node)
                for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    return {name: hashlib.sha256(segments[name].encode("utf-8")).hexdigest()
            for name in IMPLEMENTATIONS}


def production_registry() -> dict[str, Any]:
    floors = json.loads(FLOORS.read_text(encoding="utf-8"))["metrics"]
    hashes = implementation_hashes()
    if set(floors) != set(IMPLEMENTATIONS):
        raise ValueError("router floor/implementation sets differ")
    rate_ids = {"overall_route_accuracy", "route_macro_accuracy", "current_route_accuracy",
                "historical_route_accuracy", "static_local_accuracy", "tool_route_accuracy",
                "security_route_accuracy", "conflict_abstention_route_accuracy", "unnecessary_web_rate"}
    return {"schema_version": "t23-production-router-metric-registry-v1",
            "artifact": "T23_PRODUCTION_ROUTER_METRIC_REGISTRY",
            "experiment": "t23", "generic_fallback_consumers": 0,
            "metrics": {name: {
                "semantic": "mean per route" if name == "route_macro_accuracy" else
                            "eligible-population rate" if name in rate_ids else "event count",
                "implementation": f"t23_protocol.scorer:{name}",
                "implementation_sha256": hashes[name],
                "numerator": "correct-or-event count",
                "denominator": "eligible rows" if name in rate_ids else None,
                "aggregation": "macro_mean" if name == "route_macro_accuracy" else
                               "rate" if name in rate_ids else "sum",
                "operator": floors[name]["op"], "threshold": floors[name]["value"],
                "evidence_source": "evaluations/t23/raw_results.jsonl",
            } for name in sorted(IMPLEMENTATIONS)}}


def validate_registry(registry: dict[str, Any]) -> None:
    if registry != production_registry():
        raise ValueError("T23 production router metric registry drift")


def score_router(rows: list[Row], registry: dict[str, Any]) -> dict[str, Any]:
    validate_registry(registry)
    metrics = {}
    floors = {}
    for name, implementation in IMPLEMENTATIONS.items():
        numerator, denominator, observed = implementation(rows)
        spec = registry["metrics"][name]
        passed = (observed >= spec["threshold"] if spec["operator"] == ">=" else
                  observed <= spec["threshold"] if spec["operator"] == "<=" else
                  observed == spec["threshold"])
        metrics[name] = {"numerator": numerator, "denominator": denominator,
                         "observed": observed, "implementation_sha256": spec["implementation_sha256"]}
        floors[name] = {"observed": observed, "operator": spec["operator"],
                        "threshold": spec["threshold"], "pass": passed}
    return {"metrics": metrics, "floors": floors,
            "status": "PASS" if all(item["pass"] for item in floors.values()) else "FAIL"}
