"""Disposable qualification harness composed from production phase APIs."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from .construction import run_construction
from .context import CONSTRUCTION_TOKENS, EVALUATION_TOKENS, WorkspaceMode
from .errors import ValidationError
from .evaluate import run_evaluation
from .providers import (
    RealCandidateProvider,
    RealDryRunMaterialProvider,
    SyntheticCandidateProvider,
    SyntheticMaterialProvider,
    contract_runtime_native,
)
from .util import sha256_json


def _seal_schema_version(contract: Any) -> str:
    runtime_native = contract_runtime_native(contract)
    if runtime_native is None:
        return "t21-holdout-frozen-v1"
    return runtime_native["holdout_frozen_schema_version"]


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
    experiment = contract.experiment
    with tempfile.TemporaryDirectory(prefix=f"{experiment}-phase-api-") as directory:
        root = Path(directory)
        _copy_preconstruction_inputs(source_root, root, graph)
        construction = run_construction(
            experiment,
            root,
            CONSTRUCTION_TOKENS[experiment],
            workspace_mode=WorkspaceMode.SYNTHETIC_DISPOSABLE,
            provider=SyntheticMaterialProvider(),
            source_root=source_root,
        )
        report: dict[str, Any] = {
            "status": construction["status"],
            "construction": construction,
            "artifact_graph_root": sha256_json(graph),
            "schema_root": sha256_json(
                {"contract_schema": contract.document["schema_version"], "seal_schema": _seal_schema_version(contract)}
            ),
        }
        if include_evaluation:
            evaluation = run_evaluation(
                experiment,
                root,
                EVALUATION_TOKENS[experiment],
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
    experiment = contract.experiment
    with tempfile.TemporaryDirectory(prefix=f"{experiment}-real-mode-dry-") as directory:
        root = Path(directory)
        _copy_preconstruction_inputs(source_root, root, graph)
        report = run_construction(
            experiment,
            root,
            CONSTRUCTION_TOKENS[experiment],
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


def run_real_mode_lifecycle_rehearsal(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    """Full production lifecycle on disposable, non-blind material.

    Exercises every production step end to end — qualification, construction
    ledger, runtime-native corpus, frozen loader validation, suites, audits,
    seal, HOLDOUT_FROZEN, sealed preflight, evaluation protocol, one-shot
    EvaluationLedger, the REAL candidate provider on disposable non-blind
    material, raw results, official evaluator, official scorer, metric
    evidence, all 32 floors, and holdout results. The real candidate runtime
    is exercised; no real R16 case is."""
    experiment = contract.experiment
    with tempfile.TemporaryDirectory(prefix=f"{experiment}-lifecycle-") as directory:
        root = Path(directory)
        _copy_preconstruction_inputs(source_root, root, graph)
        construction = run_construction(
            experiment,
            root,
            CONSTRUCTION_TOKENS[experiment],
            workspace_mode=WorkspaceMode.REAL_EXPERIMENT,
            provider=RealDryRunMaterialProvider(),
            source_root=source_root,
            qualification_rehearsal=True,
        )
        corpus_dir = root / "rag" / f"gk_holdout_{experiment}"
        provider = RealCandidateProvider(root, corpus_dir)
        if provider.rows_executed != 0:
            raise ValidationError("candidate provider executed rows during lifecycle initialization")
        try:
            evaluation = run_evaluation(
                experiment,
                root,
                EVALUATION_TOKENS[experiment],
                workspace_mode=WorkspaceMode.REAL_EXPERIMENT,
                candidate_provider=provider,
            )
        finally:
            rows_after = provider.rows_executed
            del provider
        return {
            "status": "PASS" if construction["status"] == evaluation["status"] == "PASS" else "FAIL",
            "construction": {
                "status": construction["status"],
                "terminal_state": construction["terminal_state"],
                "seal": construction["seal"],
                "corpus_format": construction["corpus"].get("corpus_version"),
                "runtime_loader_validated": bool(construction["corpus"].get("corpus_version")),
            },
            "evaluation": {
                "status": evaluation["status"],
                "terminal_state": evaluation["terminal_state"],
                "evaluation_ledger": evaluation["evaluation_ledger"],
                "scorer": evaluation["scorer"],
                "floor_calculations": evaluation["floor_calculations"],
            },
            "real_candidate_provider": RealCandidateProvider.provider_id,
            "candidate_runtime_exercised": True,
            "candidate_rows_executed": evaluation["candidate_rows_executed"],
            "provider_rows_executed_total": rows_after,
            "official_evaluator_rows": evaluation["official_evaluator_rows"],
            "real_r16_cases_exercised": False,
            "material_mode": "REAL_DRY_RUN",
            "workspace_destroyed": True,
        }


def run_real_mode_lifecycle_rehearsal_twice(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    first = run_real_mode_lifecycle_rehearsal(source_root, contract, graph)
    second = run_real_mode_lifecycle_rehearsal(source_root, contract, graph)
    comparisons = {
        "construction_transition_differences": 0
        if first["construction"]["terminal_state"] == second["construction"]["terminal_state"]
        else 1,
        "evaluation_transition_differences": 0
        if first["evaluation"]["terminal_state"] == second["evaluation"]["terminal_state"]
        else 1,
        "floor_calculations_differences": 0
        if first["evaluation"]["floor_calculations"] == second["evaluation"]["floor_calculations"]
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
