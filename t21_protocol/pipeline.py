"""Disposable qualification harness composed from production phase APIs."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from .construction import run_construction
from .context import CONSTRUCTION_TOKEN, EVALUATION_TOKEN, WorkspaceMode
from .evaluate import run_evaluation
from .providers import RealDryRunMaterialProvider, SyntheticCandidateProvider, SyntheticMaterialProvider
from .util import sha256_json


def _copy_preconstruction_inputs(source: Path, target: Path, graph: dict[str, Any]) -> None:
    for node in graph["nodes"].values():
        if node["phase_owner"] != "PRECONSTRUCTION":
            continue
        relative = Path(node["path"])
        origin = source / relative
        destination = target / relative
        if origin.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)
        elif origin.is_dir():
            shutil.copytree(origin, destination)


def _run_disposable(
    source_root: Path,
    contract: Any,
    graph: dict[str, Any],
    *,
    include_evaluation: bool,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="t21r15-phase-api-") as directory:
        root = Path(directory)
        _copy_preconstruction_inputs(source_root, root, graph)
        construction = run_construction(
            contract.experiment,
            root,
            CONSTRUCTION_TOKEN,
            workspace_mode=WorkspaceMode.SYNTHETIC_DISPOSABLE,
            provider=SyntheticMaterialProvider(),
            source_root=source_root,
        )
        report: dict[str, Any] = {
            "status": construction["status"],
            "construction": construction,
            "artifact_graph_root": sha256_json(graph),
            "schema_root": sha256_json(
                {"contract_schema": contract.document["schema_version"], "seal_schema": "t21-holdout-frozen-v1"}
            ),
        }
        if include_evaluation:
            evaluation = run_evaluation(
                contract.experiment,
                root,
                EVALUATION_TOKEN,
                workspace_mode=WorkspaceMode.SYNTHETIC_DISPOSABLE,
                candidate_provider=SyntheticCandidateProvider(),
            )
            report["evaluation"] = evaluation
            report["status"] = "PASS" if construction["status"] == evaluation["status"] == "PASS" else "FAIL"
        return report


def run_synthetic_construction_once(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    return _run_disposable(source_root, contract, graph, include_evaluation=False)


def run_synthetic_construction_twice(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    first = run_synthetic_construction_once(source_root, contract, graph)
    second = run_synthetic_construction_once(source_root, contract, graph)
    first_construction = first["construction"]
    second_construction = second["construction"]
    comparisons = {
        "state_transition_differences": 0
        if first_construction["state_transitions"] == second_construction["state_transitions"]
        else 1,
        "artifact_graph_differences": 0 if first["artifact_graph_root"] == second["artifact_graph_root"] else 1,
        "schema_differences": 0 if first["schema_root"] == second["schema_root"] else 1,
        "seal_binding_set_differences": 0
        if first_construction["seal_binding_set"] == second_construction["seal_binding_set"]
        else 1,
    }
    return {
        "status": "PASS"
        if first["status"] == second["status"] == "PASS" and not any(comparisons.values())
        else "FAIL",
        "run_1": first,
        "run_2": second,
        **comparisons,
        "disposable_workspaces_destroyed": True,
    }


def run_synthetic_once(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    return _run_disposable(source_root, contract, graph, include_evaluation=True)


def run_real_mode_dry_rehearsal(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    """Exercise REAL_EXPERIMENT guards with disposable, non-official material."""
    with tempfile.TemporaryDirectory(prefix="t21r15-real-mode-dry-") as directory:
        root = Path(directory)
        _copy_preconstruction_inputs(source_root, root, graph)
        report = run_construction(
            contract.experiment,
            root,
            CONSTRUCTION_TOKEN,
            workspace_mode=WorkspaceMode.REAL_EXPERIMENT,
            provider=RealDryRunMaterialProvider(),
            source_root=source_root,
            qualification_rehearsal=True,
        )
        return {
            "status": report["status"],
            "terminal_state": report["terminal_state"],
            "construction_ledger": report["construction_ledger"],
            "evaluation_ledger_absent": report["evaluation_ledger_absent"],
            "candidate_executions": report["candidate_executions"],
            "material_mode": report["material_mode"],
            "workspace_destroyed": True,
        }


def run_synthetic_twice(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    first = run_synthetic_once(source_root, contract, graph)
    second = run_synthetic_once(source_root, contract, graph)
    comparisons = {
        "construction_transition_differences": 0
        if first["construction"]["state_transitions"] == second["construction"]["state_transitions"]
        else 1,
        "evaluation_transition_differences": 0
        if first["evaluation"]["state_transitions"] == second["evaluation"]["state_transitions"]
        else 1,
        "artifact_graph_differences": 0 if first["artifact_graph_root"] == second["artifact_graph_root"] else 1,
        "schema_differences": 0 if first["schema_root"] == second["schema_root"] else 1,
        "seal_binding_set_differences": 0
        if first["construction"]["seal_binding_set"] == second["construction"]["seal_binding_set"]
        else 1,
    }
    return {
        "status": "PASS"
        if first["status"] == second["status"] == "PASS" and not any(comparisons.values())
        else "FAIL",
        "run_1": first,
        "run_2": second,
        **comparisons,
        "disposable_workspaces_destroyed": True,
    }
