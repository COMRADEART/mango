"""Artifact dependency graph and seal-input derivation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import GraphError
from .util import read_json

GRAPH_KEYS = frozenset({"schema_version", "artifact", "experiment", "known_producers", "nodes"})
NODE_KEYS = frozenset(
    {
        "path",
        "producer",
        "required_inputs",
        "consumers",
        "phase_created",
        "phase_frozen",
        "phase_owner",
        "include_in_seal",
        "include_in_evaluation_provenance",
        "required",
        "external",
    }
)
PHASE_OWNERS = frozenset({"PRECONSTRUCTION", "CONSTRUCTION", "SEAL", "EVALUATION"})


def load_artifact_graph(path: Path) -> dict[str, Any]:
    graph = read_json(path)
    if not isinstance(graph, dict):
        raise GraphError("artifact graph must be an object")
    validate_artifact_graph(graph)
    return graph


def validate_artifact_graph(graph: dict[str, Any], *, raise_on_error: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    unknown_root = set(graph) - GRAPH_KEYS
    missing_root = GRAPH_KEYS - set(graph)
    errors.extend(f"unknown graph field: {name}" for name in sorted(unknown_root))
    errors.extend(f"missing graph field: {name}" for name in sorted(missing_root))
    nodes = graph.get("nodes")
    if not isinstance(nodes, dict):
        errors.append("nodes must be an object")
        nodes = {}
    known_producers = graph.get("known_producers")
    if not isinstance(known_producers, list):
        errors.append("known_producers must be an array")
        known_producers = []

    missing_producers = 0
    dangling_requirements = 0
    no_consumers = 0
    seal_not_producible = 0
    omitted_seal = 0
    unknown_phase_owners = 0
    for name, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"node {name!r} is not an object")
            continue
        unknown = set(node) - NODE_KEYS
        missing = NODE_KEYS - set(node)
        if unknown:
            errors.append(f"node {name}: unknown keys {sorted(unknown)}")
        if missing:
            errors.append(f"node {name}: missing keys {sorted(missing)}")
            continue
        producer = node["producer"]
        if not producer or producer not in known_producers:
            missing_producers += 1
            errors.append(f"node {name}: no known producer")
        requirements = node["required_inputs"]
        if not isinstance(requirements, list):
            errors.append(f"node {name}: required_inputs must be an array")
            requirements = []
        for requirement in requirements:
            if requirement not in nodes:
                dangling_requirements += 1
                errors.append(f"node {name}: dangling requirement {requirement}")
        if not isinstance(node["consumers"], list) or not node["consumers"]:
            no_consumers += 1
            errors.append(f"node {name}: no declared consumer")
        if node["include_in_seal"] and not producer:
            seal_not_producible += 1
        if node["required"] and node["phase_frozen"] == "SEALED" and not node["include_in_seal"]:
            omitted_seal += 1
            errors.append(f"node {name}: required SEALED artifact omitted from seal")
        if node["phase_owner"] not in PHASE_OWNERS:
            unknown_phase_owners += 1
            errors.append(f"node {name}: unknown phase owner {node['phase_owner']!r}")

    cycles = _cycles(nodes)
    errors.extend(f"cyclic dependency: {' -> '.join(cycle)}" for cycle in cycles)
    report = {
        "status": "PASS" if not errors else "FAIL",
        "nodes": len(nodes),
        "required_artifacts_with_no_producer": missing_producers,
        "produced_artifacts_with_no_declared_consumer": no_consumers,
        "seal_required_artifacts_not_producible": seal_not_producible,
        "seal_bound_required_artifacts_omitted": omitted_seal,
        "dangling_requirements": dangling_requirements,
        "cyclic_dependencies": len(cycles),
        "unknown_phase_owners": unknown_phase_owners,
        "construct_writable_evaluation_nodes": 0,
        "evaluate_writable_sealed_input_nodes": 0,
        "errors": errors,
    }
    if errors and raise_on_error:
        raise GraphError("; ".join(errors))
    return report


def _cycles(nodes: dict[str, Any]) -> list[list[str]]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(name: str) -> None:
        if name in visiting:
            start = stack.index(name)
            cycles.append(stack[start:] + [name])
            return
        if name in visited or name not in nodes:
            return
        visiting.add(name)
        stack.append(name)
        for requirement in nodes[name].get("required_inputs", []):
            visit(requirement)
        stack.pop()
        visiting.remove(name)
        visited.add(name)

    for node in nodes:
        visit(node)
    return cycles


def topological_nodes(graph: dict[str, Any]) -> list[str]:
    validate_artifact_graph(graph)
    nodes = graph["nodes"]
    result: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name in seen:
            return
        for requirement in nodes[name]["required_inputs"]:
            add(requirement)
        seen.add(name)
        result.append(name)

    for name in nodes:
        add(name)
    return result


def seal_input_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_artifact_graph(graph)
    return {
        name: graph["nodes"][name]
        for name in topological_nodes(graph)
        if graph["nodes"][name]["include_in_seal"]
    }


def evaluation_provenance_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_artifact_graph(graph)
    return {
        name: graph["nodes"][name]
        for name in topological_nodes(graph)
        if graph["nodes"][name]["include_in_evaluation_provenance"]
    }


def phase_owned_nodes(graph: dict[str, Any], owners: set[str] | frozenset[str]) -> dict[str, dict[str, Any]]:
    """Return nodes writable by the declared artifact phase owners."""
    validate_artifact_graph(graph)
    unknown = set(owners) - PHASE_OWNERS
    if unknown:
        raise GraphError(f"unknown requested phase owners: {sorted(unknown)}")
    return {
        name: node
        for name, node in graph["nodes"].items()
        if node["phase_owner"] in owners and not node["external"]
    }


def command_write_paths(graph: dict[str, Any], command: str) -> tuple[str, ...]:
    """Derive command write sets only from graph phase ownership."""
    owner_sets = {
        "construct": frozenset({"CONSTRUCTION", "SEAL"}),
        "evaluate": frozenset({"EVALUATION"}),
    }
    if command not in owner_sets:
        raise GraphError(f"unknown graph-derived write command: {command}")
    return tuple(sorted({node["path"] for node in phase_owned_nodes(graph, owner_sets[command]).values()}))


def phase_ownership_report(graph: dict[str, Any]) -> dict[str, Any]:
    validation = validate_artifact_graph(graph, raise_on_error=False)
    construct = set(command_write_paths(graph, "construct")) if validation["status"] == "PASS" else set()
    evaluate = set(command_write_paths(graph, "evaluate")) if validation["status"] == "PASS" else set()
    sealed = {
        node["path"]
        for node in graph.get("nodes", {}).values()
        if isinstance(node, dict) and node.get("phase_owner") in {"PRECONSTRUCTION", "CONSTRUCTION", "SEAL"}
    }
    evaluation_paths = {
        node["path"]
        for node in graph.get("nodes", {}).values()
        if isinstance(node, dict) and node.get("phase_owner") == "EVALUATION"
    }
    return {
        "status": "PASS"
        if validation["status"] == "PASS" and not construct & evaluation_paths and not evaluate & sealed
        else "FAIL",
        "unknown_phase_owners": validation.get("unknown_phase_owners", 0),
        "construct_writable_evaluation_artifacts": len(construct & evaluation_paths),
        "evaluate_writable_sealed_construction_artifacts": len(evaluate & sealed),
        "construct_paths": len(construct),
        "evaluate_paths": len(evaluate),
    }
