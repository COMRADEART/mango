"""Official T22 evaluation phase: explicit measurement semantics, fail closed.

The measuring stick does not change: this driver binds the byte-identical
explicit scorer (t21_protocol.scorer_r17:score_explicit) and the T22
frozen metric-semantics contract (numeric fields byte-identical to the
R17 frozen semantics; the contradictory zero-denominator prose harmonized
per the frozen T22 resolution). The candidate is the remediated runtime
with the request-date carrier (providers_t22). Mirrors the frozen
production evaluation protocol (seal verification, one-shot
EvaluationLedger, write-guarded artifact production, phase transitions).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .artifact_graph import command_write_paths, load_artifact_graph
from .context import EvaluationAuthorization, WorkspaceMode, require_evaluation_authorization
from .contract import load_contract
from .errors import ScorerConfigurationError, ValidationError
from .evaluator_r17 import evaluate_evidence_rows
from .metric_semantics import load_metric_semantics, semantics_root
from .providers_r17 import SERIALIZATION_V2
from .providers_t22 import PROVIDER_ID_T22_EVIDENCE
from .scorer_r17 import IMPLEMENTATION_SOURCES, IMPLEMENTATIONS, SCORER_ID, score_explicit
from .seal import verify_seal
from .state_machine import Phase, ProtocolStateMachine
from .taxonomy import load_taxonomy
from .util import iter_jsonl, read_json, sha256_file, sha256_json, write_json, write_jsonl
from .write_guard import WriteGuard

SUCCESS_VERDICT = "T22_ONE_SHOT_OFFICIAL_EVALUATION_COMPLETE"
FAIL_VERDICT = "T22_ONE_SHOT_OFFICIAL_EVALUATION_FAILED"


def _verify_implementation_registry(root: Path, contract: Any) -> dict[str, Any]:
    """The T22 implementation registry must bind every registered metric to
    its frozen implementation source hash; drift in scorer_r17.py bytes
    fails closed. The T22 registry is a carry of the R17 registry with the
    same implementation_sha256 values because the measuring stick does not
    change."""
    registry = read_json(root / contract.get("artifacts.metric_implementation_registry"))
    entries = registry.get("implementations") or {}
    import ast

    scorer_path = Path(sys.modules[f"{__package__}.scorer_r17"].__file__)
    source = scorer_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    segments = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    mismatches: list[str] = []
    for metric_id, entry in sorted(entries.items()):
        expected_function = IMPLEMENTATION_SOURCES.get(metric_id)
        if expected_function is None or entry.get("function") != expected_function:
            mismatches.append(metric_id)
            continue
        segment = segments.get(expected_function)
        if segment is None or sha256_json({"source": segment}) != entry.get("implementation_sha256"):
            mismatches.append(metric_id)
    if set(entries) != set(IMPLEMENTATIONS):
        mismatches.append("registry coverage mismatch")
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "implementation_count": len(entries),
        "mismatches": mismatches,
        "scorer_module_sha256": sha256_file(scorer_path),
    }


def _gold_rows(root: Path, contract: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    suite_root = root / "evaluations" / contract.experiment / "suites"
    for suite_name in contract.get("suites"):
        rows.extend(iter_jsonl(suite_root / suite_name / "holdout.jsonl"))
    return rows


def run_evaluation_t22(
    experiment: str,
    sealed_workspace: Path,
    authorization: EvaluationAuthorization | str,
    *,
    workspace_mode: WorkspaceMode,
    candidate_provider: Any,
) -> dict[str, Any]:
    """Continue SEALED to EVALUATION_COMPLETE with explicit measurement semantics."""
    if experiment != "t22":
        raise ValidationError("this evaluation driver is bound to t22")
    root = sealed_workspace.resolve()
    out = root / "evaluations" / experiment
    require_evaluation_authorization(authorization, experiment=experiment)
    contract = load_contract(out / "t21_master_contract.json")
    if contract.experiment != experiment:
        raise ValidationError("evaluation experiment identity mismatch")
    graph = load_artifact_graph(root / contract.get("artifacts.artifact_graph"))
    from .providers import validate_candidate_provider

    validate_candidate_provider(candidate_provider, workspace_mode)
    if getattr(candidate_provider, "provider_id", None) != PROVIDER_ID_T22_EVIDENCE:
        raise ValidationError("official T22 evaluation requires the T22 request-date candidate provider")
    ledger_path = out / "construction_run_ledger.json"
    if not ledger_path.is_file() or read_json(ledger_path).get("state") != "COMPLETE":
        raise ValidationError("evaluation requires construction ledger COMPLETE")
    if (out / "evaluation_run_ledger.json").exists():
        raise ValidationError("evaluation ledger must be absent")
    marker = read_json(out / "HOLDOUT_FROZEN") if (out / "HOLDOUT_FROZEN").is_file() else {}
    if marker.get("workspace_mode") != workspace_mode.value:
        raise ValidationError("sealed workspace mode differs from evaluation mode")
    verify_seal(root, contract, graph)

    semantics = load_metric_semantics(root, contract,
                                      artifact="T22_OFFICIAL_METRIC_SEMANTICS",
                                      experiment="t22")
    if semantics_root(semantics) != contract.get("roots.scorer_semantic_root"):
        raise ScorerConfigurationError("frozen metric semantics root does not match the contract")
    floors = contract.get("promotion_floors")
    if semantics["floor_hash"] != sha256_json(floors):
        raise ScorerConfigurationError("frozen semantics floor hash does not match the contract")
    registry_check = _verify_implementation_registry(root, contract)
    if registry_check["status"] != "PASS":
        raise ScorerConfigurationError(f"metric implementation registry mismatch: {registry_check['mismatches']}")

    machine = ProtocolStateMachine.from_contract(contract)
    phase = Phase.SEALED
    transitions: list[str] = []
    from .ledger import EvaluationLedger

    evaluation_ledger: EvaluationLedger | None = None
    allowed = command_write_paths(graph, "evaluate")
    with WriteGuard(root, allowed):
        from .preflight import validate_sealed_evaluation_bundle

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
            evidence_rows = evaluate_evidence_rows(gold_rows, candidate_rows, taxonomy)
            write_json(
                out / "evaluator_results.json",
                {
                    "status": "PASS",
                    "rows": len(evidence_rows),
                    "evaluator": "t21_protocol.evaluator_r17:evaluate_evidence_rows",
                    "results": evidence_rows,
                },
                exclusive=True,
            )
            scores = score_explicit(evidence_rows, floors, semantics)
            write_json(
                out / "score_results.json",
                {key: value for key, value in scores.items() if key != "floor_comparisons"},
                exclusive=True,
            )
            if "raw_results" in graph["nodes"]:
                write_jsonl(out / "raw_results.jsonl", evidence_rows)
            if "metric_evidence" in graph["nodes"]:
                metric_evidence = {
                    "schema_version": "t21-metric-evidence-v2",
                    "artifact": "T22_METRIC_EVIDENCE",
                    "status": "PASS",
                    "rows": len(evidence_rows),
                    "evidence_source": "evaluator_results.json:results",
                    "evaluator": "t21_protocol.evaluator_r17:evaluate_evidence_rows",
                    "metric_count": len(scores["metrics"]),
                    "per_metric": {
                        item["metric"]: {
                            "numerator": item["numerator"],
                            "denominator": item["denominator"],
                            "observed": item["observed"],
                            "zero_denominator_policy_applied": item["zero_denominator_policy_applied"],
                        }
                        for item in scores["floor_comparisons"]
                    },
                    "row_fields": list(evidence_rows[0].keys()) if evidence_rows else [],
                    "semantics_sha256": semantics_root(semantics),
                }
                write_json(out / "metric_evidence.json", metric_evidence, exclusive=True)
            if "floor_evidence" in graph["nodes"]:
                floor_evidence = {
                    "schema_version": "t21-floor-evidence-v2",
                    "artifact": "T22_FLOOR_EVIDENCE",
                    "status": "PASS",
                    "floors_expected": 32,
                    "floors_evaluated": len(scores["floor_comparisons"]),
                    "floor_comparisons": scores["floor_comparisons"],
                    "aggregation": {
                        "definition": "t21_protocol.scorer_r17:score_explicit over explicit per-metric semantics",
                        "generic_fallback_consumers": 0,
                        "scorer_configuration_errors": 0,
                        "semantics_contract": contract.get("artifacts.official_metric_semantics"),
                        "implementation_registry": contract.get("artifacts.metric_implementation_registry"),
                    },
                    "evidence_source": "score_results.json:floor_comparisons",
                    "scorer": SCORER_ID,
                }
                write_json(out / "floor_evidence.json", floor_evidence, exclusive=True)
            if "holdout_results" in graph["nodes"]:
                holdout_results = {
                    "schema_version": "t21-holdout-results-v2",
                    "artifact": "T22_HOLDOUT_RESULTS",
                    "status": "PASS",
                    "experiment": experiment,
                    "rows": len(evidence_rows),
                    "metrics": scores["metrics"],
                    "domain_macro": scores["domain_macro"],
                    "floor_calculations": scores["floor_calculations"],
                    "candidate_capability_pass": scores["candidate_capability_pass"],
                    "scorer": SCORER_ID,
                    "semantics_root": semantics_root(semantics),
                    "seal_root": marker.get("freeze_root_sha256"),
                }
                write_json(out / "holdout_results.json", holdout_results, exclusive=True)
            provenance = {
                "schema_version": "t21-evaluation-provenance-v2",
                "artifact": "T22_EVALUATION_PROVENANCE",
                "status": "PASS",
                "workspace_mode": workspace_mode.value,
                "candidate_provider": candidate_provider.provider_id,
                "candidate_provider_kind": candidate_provider.provider_kind,
                "candidate_serialization": SERIALIZATION_V2,
                "rows": len(evidence_rows),
                "seal_root": marker["freeze_root_sha256"],
                "scorer": SCORER_ID,
                "semantics_root": semantics_root(semantics),
                "implementation_registry_check": registry_check,
                "floor_calculations": scores["floor_calculations"],
            }
            for binding in (
                "runtime_data_contract_root",
                "runtime_corpus_contract_sha256",
                "runtime_field_provenance_sha256",
                "runtime_loader_validation_sha256",
                "candidate_provider_sha256",
            ):
                if binding in marker:
                    provenance.setdefault("runtime_bindings", {})[binding] = marker[binding]
            if "candidate_provider_id" in marker:
                provenance["candidate_provider_id"] = marker["candidate_provider_id"]
            write_json(out / "evaluation_provenance.json", provenance, exclusive=True)
            evaluation_ledger.complete(
                {"rows": len(evidence_rows), "floor_calculations": scores["floor_calculations"]}
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
        "official_evaluator_rows": len(evidence_rows),
        "scorer": scores["status"],
        "candidate_capability_pass": scores["candidate_capability_pass"],
        "floor_calculations": scores["floor_calculations"],
    }


__all__ = [
    "SUCCESS_VERDICT",
    "FAIL_VERDICT",
    "run_evaluation_t22",
    "score_explicit",
]