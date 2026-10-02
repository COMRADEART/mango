"""T22 disposable qualification harnesses with the unchanged measuring stick.

Mirrors the frozen R17 rehearsal harness with the two T22 phase APIs: the
request-date candidate provider (RealCandidateProviderT22Evidence) and the
official T22 evaluation driver (run_evaluation_t22). All T22 lifecycle
rehearsals run the real remediated candidate runtime on disposable,
non-blind material; no real T22 case exists in preconstruction (protocol
section 40: lifecycle rehearsal x2 with disposable data and the actual
remediated candidate, no stub candidate).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .construction import run_construction
from .context import CONSTRUCTION_TOKENS, EVALUATION_TOKENS, WorkspaceMode
from .errors import ValidationError
from .evaluate_t22 import run_evaluation_t22
from .pipeline import _copy_preconstruction_inputs, run_real_mode_dry_rehearsal
from .providers import RealDryRunMaterialProvider
from .providers_t22 import PROVIDER_ID_T22_EVIDENCE, RealCandidateProviderT22Evidence


def run_real_mode_lifecycle_rehearsal_t22(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    """Full production lifecycle on disposable, non-blind material.

    Exercises every production step end to end — qualification, construction
    ledger, runtime-native corpus, frozen loader validation, suites, audits,
    seal, HOLDOUT_FROZEN, sealed preflight, the T22 evaluation protocol
    (the byte-identical explicit scorer), one-shot EvaluationLedger, the
    REAL candidate provider with request-date threading on disposable
    non-blind material, evidence rows, explicit per-metric scoring, metric
    evidence, all 32 floors, and holdout results. The real remediated
    candidate runtime is exercised; no real T22 case exists."""
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
        provider = RealCandidateProviderT22Evidence(root, corpus_dir)
        if provider.rows_executed != 0:
            raise ValidationError("candidate provider executed rows during lifecycle initialization")
        try:
            evaluation = run_evaluation_t22(
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
            "real_candidate_provider": PROVIDER_ID_T22_EVIDENCE,
            "candidate_runtime_exercised": True,
            "candidate_rows_executed": evaluation["candidate_rows_executed"],
            "provider_rows_executed_total": rows_after,
            "official_evaluator_rows": evaluation["official_evaluator_rows"],
            "real_t22_cases_exercised": False,
            "material_mode": "REAL_DRY_RUN",
            "workspace_destroyed": True,
        }


def run_real_mode_lifecycle_rehearsal_t22_twice(source_root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    first = run_real_mode_lifecycle_rehearsal_t22(source_root, contract, graph)
    second = run_real_mode_lifecycle_rehearsal_t22(source_root, contract, graph)
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
    "run_real_mode_lifecycle_rehearsal_t22",
    "run_real_mode_lifecycle_rehearsal_t22_twice",
]