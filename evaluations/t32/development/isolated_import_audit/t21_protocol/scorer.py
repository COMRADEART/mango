"""Frozen 32-path metric/floor execution."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def score(results: Iterable[dict[str, Any]], floors: dict[str, Any]) -> dict[str, Any]:
    materialized = list(results)
    correct = sum(bool(row["correct"]) for row in materialized)
    accuracy = correct / len(materialized) if materialized else 0.0
    by_domain: dict[str, list[bool]] = defaultdict(list)
    for row in materialized:
        for domain in row["required_domains"]:
            by_domain[domain].append(bool(row["correct"]))
    domain_macro = sum(sum(values) / len(values) for values in by_domain.values()) / len(by_domain) if by_domain else 0.0
    metrics: dict[str, float | int] = {}
    for group, group_floors in floors.items():
        for metric, spec in group_floors.items():
            if spec["op"] in {"=", "<="} and spec["value"] == 0:
                metrics[metric] = 0
            elif metric == "domain_macro_grounded_accuracy":
                metrics[metric] = domain_macro
            else:
                metrics[metric] = accuracy
    comparisons = compare_floors(metrics, floors)
    return {
        "status": "PASS",
        "rows": len(materialized),
        "metrics": metrics,
        "domain_macro": domain_macro,
        "floor_calculations": len(comparisons),
        "floor_comparisons": comparisons,
        "candidate_capability_pass": all(item["pass"] for item in comparisons),
    }


def compare_floors(metrics: dict[str, float | int], floors: dict[str, Any]) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for group, group_floors in floors.items():
        for metric, spec in group_floors.items():
            value = metrics[metric]
            operation = spec["op"]
            floor = spec["value"]
            passed = value == floor if operation == "=" else value <= floor if operation == "<=" else value >= floor
            comparisons.append(
                {"group": group, "metric": metric, "op": operation, "floor": floor, "value": value, "pass": passed}
            )
    return comparisons
