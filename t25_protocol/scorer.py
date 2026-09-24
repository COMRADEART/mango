"""T25 scoring: frozen T23 router metric implementations, T25 registry and evidence.

Metric semantics, thresholds, and implementations are byte-identical to T23's
frozen scorer; only the artifact namespace and evidence locator are T25's.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from t23_protocol.scorer import IMPLEMENTATIONS, implementation_hashes  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
FLOORS = ROOT / "evaluations" / "t25" / "router_metric_registry.json"
REGISTRY = ROOT / "evaluations" / "t25" / "production_router_metric_registry.json"
EVIDENCE_LOCATOR = "t25-private://T25-STORE-01/t25/evaluation/raw_results.jsonl"


def production_registry() -> dict[str, Any]:
    floors = json.loads(FLOORS.read_text(encoding="utf-8"))["metrics"]
    hashes = implementation_hashes()
    if set(floors) != set(IMPLEMENTATIONS):
        raise ValueError("router floor/implementation sets differ")
    rate_ids = {"overall_route_accuracy", "route_macro_accuracy", "current_route_accuracy",
                "historical_route_accuracy", "static_local_accuracy", "tool_route_accuracy",
                "security_route_accuracy", "conflict_abstention_route_accuracy",
                "unnecessary_web_rate"}
    return {"schema_version": "t25-production-router-metric-registry-v1",
            "artifact": "T25_PRODUCTION_ROUTER_METRIC_REGISTRY",
            "experiment": "t25", "generic_fallback_consumers": 0,
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
                "evidence_source": EVIDENCE_LOCATOR,
            } for name in sorted(IMPLEMENTATIONS)}}


def validate_registry(registry: dict[str, Any]) -> None:
    if registry != production_registry():
        raise ValueError("T25 production router metric registry drift")


def score_router(rows: list[dict[str, Any]], registry: dict[str, Any]) -> dict[str, Any]:
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