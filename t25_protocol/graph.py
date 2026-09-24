"""Fail-closed validation of the T25 production evaluation graph (section 31).

Every producer is an importable, callable implementation; blind nodes live at
private locators; public nodes stay in the public-safe namespace; the graph
carries the SEALED/EVALUATED state gates.
"""
from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

from .classification import CLASSES, classify

GRAPH = Path(__file__).resolve().parents[1] / "evaluations" / "t25" / "production_evaluation_graph.json"
GRAPH_SCHEMA = "t25-evaluation-graph-v1"
REQUIRED = frozenset({
    "construction_inputs", "construction_gold", "construction_family_suites",
    "holdout_corpus", "construction_ledger", "construction_audits",
    "construction_gate_node", "construction_manifest", "holdout_seal",
    "public_construction_commitment", "public_manifest_commitment",
    "public_construction_receipt", "gold_firewall_verification",
    "router_decisions", "selected_capability_execution", "candidate_outputs",
    "router_evaluator", "capability_evaluator", "raw_results",
    "protected_t22_metric_evidence", "protected_t22_floor_evidence",
    "router_metric_evidence", "router_floor_evidence",
    "combined_holdout_results", "evaluation_provenance", "evaluation_ledger",
    "public_evaluation_receipt",
})
FORBIDDEN_NODE_PATHS = ("evaluations/t25/suites/", "rag/gk_holdout_t25/",
                        "documents/t25_private")


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes")
    if (graph.get("schema_version") != GRAPH_SCHEMA or graph.get("experiment") != "t25"
            or not isinstance(nodes, dict)
            or graph.get("gates", {}).get("evaluation_cannot_start_before") != "SEALED"
            or graph.get("gates", {}).get("promotion_cannot_start_before") != "EVALUATED"):
        raise ValueError("invalid T25 evaluation graph")
    missing_nodes = sorted(REQUIRED - set(nodes))
    missing_producers = []
    dangling_inputs = []
    stub_nodes = []
    classification_errors = []
    paths = set()
    duplicate_paths = []
    for name, node in nodes.items():
        if not isinstance(node, dict) or set(node) != {"producer", "inputs", "path",
                                                       "privacy", "classification"}:
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
        if ("stub" in producer.lower() or "mock" in producer.lower()
                or "test" in producer.lower()):
            stub_nodes.append(name)
        for dependency in node["inputs"]:
            if dependency not in nodes:
                dangling_inputs.append((name, dependency))
        path = node["path"]
        if not isinstance(path, str) or not (path.startswith("evaluations/t25/")
                                             or path.startswith("t25-private://")):
            raise ValueError(f"T25 graph path outside allowed namespaces: {name}")
        if any(pattern in path for pattern in FORBIDDEN_NODE_PATHS):
            raise ValueError(f"T25 graph node claims a forbidden pre-evaluation path: {name}")
        if path in paths:
            duplicate_paths.append(path)
        paths.add(path)
        if node["privacy"] != "PRIVATE":
            raise ValueError(f"blind graph node not private: {name}")
        if node["classification"] not in CLASSES:
            classification_errors.append(name)
        else:
            if (path.startswith("t25-private://")
                    and node["classification"] not in {"PRIVATE_BLIND", "PRIVATE_EVALUATION"}):
                classification_errors.append(name)
            if path.startswith("evaluations/t25/") and node["classification"] == "PRIVATE_BLIND":
                classification_errors.append(name)
    if duplicate_paths:
        raise ValueError(f"duplicate graph paths: {duplicate_paths}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError("T25 evaluation graph cycle")
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
    return {"status": "PASS" if not (missing_nodes or missing_producers or dangling_inputs
                                     or stub_nodes or classification_errors) else "FAIL",
            "producer_count": len(nodes) - len(missing_producers),
            "missing_nodes": missing_nodes,
            "missing_producers": missing_producers,
            "dangling_inputs": dangling_inputs,
            "stub_production_nodes": stub_nodes,
            "classification_errors": classification_errors,
            "gates": graph["gates"]}


def load_graph(path: Path = GRAPH) -> dict[str, Any]:
    graph = json.loads(Path(path).read_text(encoding="utf-8"))
    report = validate_graph(graph)
    if report["status"] != "PASS":
        raise ValueError(f"T25 production graph incomplete: {report}")
    return graph


def node_role(node_name: str) -> str:
    """Map a graph node to its classification-registry role."""
    try:
        return NODE_ROLES[node_name]
    except KeyError as exc:
        raise ValueError(f"graph node has no classification role: {node_name}") from exc


NODE_ROLES: dict[str, str] = {
    "construction_inputs": "suite_inputs", "construction_gold": "suite_gold",
    "construction_family_suites": "suite_family", "holdout_corpus": "holdout_corpus_sources",
    "construction_ledger": "construction_run_ledger", "construction_audits": "construction_audits_index",
    "construction_gate_node": "construction_gate",
    "construction_manifest": "private_holdout_manifest", "holdout_seal": "holdout_seal",
    "public_construction_commitment": "construction_public_commitment",
    "public_manifest_commitment": "manifest_public_commitment",
    "public_construction_receipt": "construction_public_receipt",
    "gold_firewall_verification": "gold_firewall_verification",
    "router_decisions": "router_decisions",
    "selected_capability_execution": "selected_capability_execution",
    "candidate_outputs": "candidate_outputs", "router_evaluator": "router_evaluator",
    "capability_evaluator": "capability_evaluator", "raw_results": "raw_results",
    "protected_t22_metric_evidence": "protected_t22_metric_evidence",
    "protected_t22_floor_evidence": "protected_t22_floor_evidence",
    "router_metric_evidence": "router_metric_evidence",
    "router_floor_evidence": "router_floor_evidence",
    "combined_holdout_results": "holdout_results",
    "evaluation_provenance": "evaluation_provenance",
    "evaluation_ledger": "evaluation_run_ledger",
    "public_evaluation_receipt": "evaluation_public_receipt",
}