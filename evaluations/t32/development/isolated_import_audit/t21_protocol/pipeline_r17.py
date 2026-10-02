"""T21R17 disposable qualification harnesses with the corrected scorer.

Mirrors the production rehearsal harness with the two R17 phase APIs: the
v2 evidence candidate provider (RealCandidateProviderEvidence) and the
explicit-metric official evaluation driver (run_evaluation_r17). All R17
lifecycle rehearsals run the real frozen candidate runtime on disposable,
non-blind material; no real R17 case exists in preconstruction.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .construction import run_construction
from .context import CONSTRUCTION_TOKENS, EVALUATION_TOKENS, WorkspaceMode
from .errors import ValidationError
from .evaluate_r17 import run_evaluation_r17
from .pipeline import _copy_preconstruction_inputs, run_real_mode_dry_rehearsal
from .providers import RealDryRunMaterialProvider
from .providers_r17 import PROVIDER_ID_EVIDENCE, RealCandidateProviderEvidence


def run_real_mode_lifecycle_rehearsal_r17(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    """Full production lifecycle on disposable, non-blind material.

    Exercises every production step end to end — qualification, construction
    ledger, runtime-native corpus, frozen loader validation, suites, audits,
    seal, HOLDOUT_FROZEN, sealed preflight, the R17 evaluation protocol,
    one-shot EvaluationLedger, the v2 REAL candidate provider on disposable
    non-blind material, evidence rows, explicit per-metric scoring, metric
    evidence, all 32 floors, and holdout results. The real candidate runtime
    is exercised; no real R17 case exists."""
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
        provider = RealCandidateProviderEvidence(root, corpus_dir)
        if provider.rows_executed != 0:
            raise ValidationError("candidate provider executed rows during lifecycle initialization")
        try:
            evaluation = run_evaluation_r17(
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
                "candidate_capability_pass": evaluation.get("candidate_capability_pass"),
            },
            "real_candidate_provider": PROVIDER_ID_EVIDENCE,
            "candidate_runtime_exercised": True,
            "candidate_rows_executed": evaluation["candidate_rows_executed"],
            "provider_rows_executed_total": rows_after,
            "official_evaluator_rows": evaluation["official_evaluator_rows"],
            "real_r17_cases_exercised": False,
            "material_mode": "REAL_DRY_RUN",
            "workspace_destroyed": True,
        }


def run_real_mode_lifecycle_rehearsal_r17_twice(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    first = run_real_mode_lifecycle_rehearsal_r17(source_root, contract, graph)
    second = run_real_mode_lifecycle_rehearsal_r17(source_root, contract, graph)
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


__all__ = [
    "run_real_mode_dry_rehearsal",
    "run_real_mode_lifecycle_rehearsal_r17",
    "run_real_mode_lifecycle_rehearsal_r17_twice",
]