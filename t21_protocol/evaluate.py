"""Production evaluation phase for an already-sealed immutable workspace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .artifact_graph import command_write_paths, load_artifact_graph
from .context import EvaluationAuthorization, WorkspaceMode, require_evaluation_authorization
from .contract import load_contract
from .errors import ValidationError
from .evaluator import evaluate_rows
from .ledger import EvaluationLedger
from .preflight import validate_sealed_evaluation_bundle
from .providers import CandidateProvider, FileCandidateProvider, validate_candidate_provider
from .scorer import score
from .seal import verify_seal
from .state_machine import Phase, ProtocolStateMachine
from .taxonomy import load_taxonomy
from .util import iter_jsonl, read_json, write_json, write_jsonl
from .write_guard import WriteGuard

SUCCESS_VERDICT = "T21R15_ONE_SHOT_OFFICIAL_EVALUATION_COMPLETE"
FAIL_VERDICT = "T21R15_ONE_SHOT_OFFICIAL_EVALUATION_FAILED"


def _gold_rows(root: Path, contract: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    suite_root = root / "evaluations" / contract.experiment / "suites"
    for suite_name in contract.get("suites"):
        rows.extend(iter_jsonl(suite_root / suite_name / "holdout.jsonl"))
    return rows


def run_evaluation(
    experiment: str,
    sealed_workspace: Path,
    authorization: EvaluationAuthorization | str,
    *,
    workspace_mode: WorkspaceMode,
    candidate_provider: CandidateProvider,
) -> dict[str, Any]:
    """Continue SEALED to EVALUATION_COMPLETE without construction capability."""
    require_evaluation_authorization(authorization)
    root = sealed_workspace.resolve()
    out = root / "evaluations" / experiment
    contract = load_contract(out / "t21_master_contract.json")
    graph = load_artifact_graph(out / "artifact_graph.json")
    validate_candidate_provider(candidate_provider, workspace_mode)
    ledger_path = out / "construction_run_ledger.json"
    if not ledger_path.is_file() or read_json(ledger_path).get("state") != "COMPLETE":
        raise ValidationError("evaluation requires construction ledger COMPLETE")
    if (out / "evaluation_run_ledger.json").exists():
        raise ValidationError("evaluation ledger must be absent")
    marker = read_json(out / "HOLDOUT_FROZEN") if (out / "HOLDOUT_FROZEN").is_file() else {}
    if marker.get("workspace_mode") != workspace_mode.value:
        raise ValidationError("sealed workspace mode differs from evaluation mode")
    verify_seal(root, contract, graph)

    machine = ProtocolStateMachine.from_contract(contract)
    phase = Phase.SEALED
    transitions: list[str] = []
    evaluation_ledger: EvaluationLedger | None = None
    allowed = command_write_paths(graph, "evaluate")
    with WriteGuard(root, allowed):
        sealed_preflight = validate_sealed_evaluation_bundle(root, contract, graph)
        write_json(
            out / "sealed_preflight.json",
            {"status": sealed_preflight["status"], "same_gold_validator": True},
            exclusive=True,
        )
        evaluation_ledger = EvaluationLedger.create_exclusive(
            out / "evaluation_run_ledger.json",
            experiment,
            {"authorization_class": "EVALUATION", "workspace_mode": workspace_mode.value},
        )
        phase = machine.transition("start_evaluation", phase)
        transitions.append(phase.value)
        try:
            gold_rows = _gold_rows(root, contract)
            candidate_rows = candidate_provider.generate(gold_rows)
            write_jsonl(out / "candidate_outputs.jsonl", candidate_rows)
            taxonomy = load_taxonomy(root / contract.get("artifacts.domain_taxonomy"))
            evaluated = evaluate_rows(gold_rows, candidate_rows, taxonomy)
            write_json(
                out / "evaluator_results.json",
                {"status": "PASS", "rows": len(evaluated), "results": evaluated},
                exclusive=True,
            )
            scores = score(evaluated, contract.get("promotion_floors"))
            write_json(out / "score_results.json", scores, exclusive=True)
            provenance = {
                "schema_version": "t21-evaluation-provenance-v1",
                "artifact": "T21R15_EVALUATION_PROVENANCE",
                "status": "PASS",
                "workspace_mode": workspace_mode.value,
                "candidate_provider": candidate_provider.provider_id,
                "candidate_provider_kind": candidate_provider.provider_kind,
                "rows": len(evaluated),
                "seal_root": marker["freeze_root_sha256"],
                "floor_calculations": scores["floor_calculations"],
            }
            write_json(out / "evaluation_provenance.json", provenance, exclusive=True)
            evaluation_ledger.complete(
                {"rows": len(evaluated), "floor_calculations": scores["floor_calculations"]}
            )
            phase = machine.transition("complete_evaluation", phase)
            transitions.append(phase.value)
        except Exception as exc:
            if evaluation_ledger.state == "STARTED":
                evaluation_ledger.fail({"error_type": type(exc).__name__, "error": str(exc)})
            raise
    return {
        "status": "PASS",
        "verdict": SUCCESS_VERDICT,
        "terminal_state": phase.value,
        "state_transitions": transitions,
        "evaluation_ledger": evaluation_ledger.state,
        "candidate_rows_executed": len(candidate_rows),
        "official_evaluator_rows": len(evaluated),
        "scorer": scores["status"],
        "floor_calculations": scores["floor_calculations"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run official evaluation from an immutable T21 seal")
    parser.add_argument("--experiment", default="t21r15")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--candidate-outputs", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        rows = list(iter_jsonl(arguments.candidate_outputs))
        report = run_evaluation(
            arguments.experiment,
            arguments.workspace,
            arguments.authorization,
            workspace_mode=WorkspaceMode.REAL_EXPERIMENT,
            candidate_provider=FileCandidateProvider(rows),
        )
    except Exception as exc:
        report = {"status": "FAIL", "verdict": FAIL_VERDICT, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
