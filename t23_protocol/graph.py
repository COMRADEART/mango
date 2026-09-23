"""Fail-closed validation of the T23 construction/evaluation artifact DAG."""
from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

GRAPH = Path(__file__).resolve().parents[1] / "evaluations" / "t23" / "production_evaluation_graph.json"
REQUIRED = frozenset({
    "router_decisions", "selected_capability_execution", "candidate_outputs",
    "router_evaluator", "capability_evaluator", "raw_results",
    "router_metric_evidence", "router_floor_evidence",
    "protected_t22_metric_evidence", "protected_t22_floor_evidence",
    "combined_holdout_results", "evaluation_provenance",
})


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes")
    if graph.get("schema_version") != "t23-evaluation-graph-v1" or graph.get("experiment") != "t23" or not isinstance(nodes, dict):
        raise ValueError("invalid T23 evaluation graph")
    missing_nodes = sorted(REQUIRED - set(nodes))
    missing_producers = []
    dangling_inputs = []
    stub_nodes = []
    paths = set()
    duplicate_paths = []
    for name, node in nodes.items():
        if not isinstance(node, dict) or set(node) != {"producer", "inputs", "path", "privacy"}:
            raise ValueError(f"invalid evaluation graph node {name}")
        producer = node["producer"]
        if not isinstance(producer, str) or ":" not in producer:
            missing_producers.append(name)
        else:
            module_name, member = producer.split(":", 1)
            try:
                implementation = getattr(import_module(module_name), member)
                if not callable(implementation):
                    missing_producers.append(name)
            except (ImportError, AttributeError):
                missing_producers.append(name)
        if "stub" in producer.lower() or "mock" in producer.lower() or "test" in producer.lower():
            stub_nodes.append(name)
        for dependency in node["inputs"]:
            if dependency not in nodes:
                dangling_inputs.append((name, dependency))
        path = node["path"]
        if not isinstance(path, str) or not path.startswith(("evaluations/t23/", "rag/gk_holdout_t23")) or ".." in Path(path).parts:
            raise ValueError(f"T23 graph path escapes/aliases namespace: {name}")
        if path in paths:
            duplicate_paths.append(path)
        paths.add(path)
        if node["privacy"] != "PRIVATE":
            raise ValueError(f"blind graph node not private: {name}")
    if duplicate_paths:
        raise ValueError(f"duplicate graph paths: {duplicate_paths}")
    # Cycle check, including dependencies produced by the same component.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError("T23 evaluation graph cycle")
        if name in visited:
            return
        visiting.add(name)
        for dependency in nodes[name]["inputs"]:
            if dependency in nodes:
                visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in nodes:
        visit(name)
    return {"status": "PASS" if not (missing_nodes or missing_producers or dangling_inputs or stub_nodes) else "FAIL",
            "producer_count": len(nodes) - len(missing_producers),
            "missing_nodes": missing_nodes,
            "missing_producers": missing_producers,
            "dangling_inputs": dangling_inputs,
            "stub_production_nodes": stub_nodes}


def load_graph(path: Path = GRAPH) -> dict[str, Any]:
    graph = json.loads(path.read_text(encoding="utf-8"))
    report = validate_graph(graph)
    if report["status"] != "PASS":
        raise ValueError(f"T23 production graph incomplete: {report}")
    return graph
