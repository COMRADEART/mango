"""Official-like T23 evaluation over a sealed disposable workspace.

Candidate receives inputs only; the evaluator joins private gold after the
router and selected capability have executed. Protected T22 scoring is an
independent disposable T22 lifecycle, never a replay of T22 blind material.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciencemath.executive.router_v2 import route_request
from sciencemath.web.fixture_provider import FixtureCorpus, FixtureSearchProvider
from t21_protocol.artifact_graph import load_artifact_graph
from t21_protocol.contract import load_contract
from t21_protocol.ledger import EvaluationLedger
from t21_protocol.pipeline_t22 import run_real_mode_lifecycle_rehearsal_t22
from t21_protocol.util import iter_jsonl, read_json, sha256_file, write_json, write_jsonl

from .construction import verify_seal
from .context import require_evaluation_authorization
from .graph import load_graph, validate_graph
from .provider import ProductionRouterProvider, decision_parity
from .scorer import REGISTRY, score_router


def evaluate_router(gold: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(gold) != len(outputs):
        raise ValueError("router evaluator row counts differ")
    rows = []
    for expected, output in zip(gold, outputs):
        if expected["case_id"] != output["case_id"]:
            raise ValueError("router evaluator case order differs")
        decision = output["router_decision"]
        rows.append({"case_id": expected["case_id"],
                     "expected_route": expected["expected_route"],
                     "observed_route": decision["route_id"],
                     "route_match": decision["route_id"] == expected["expected_route"],
                     "expected_reason": expected["expected_reason"],
                     "observed_reason": decision["reason_code"]})
    return rows


def evaluate_capability(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for output in outputs:
        decision = output["router_decision"]
        execution = output["selected_capability_execution"]
        matched = execution["capability"] == decision["selected_capability"]
        status = execution.get("status")
        if not isinstance(status, str) or not status or status == "UNKNOWN":
            matched = False
        rows.append({"case_id": output["case_id"],
                     "selected_capability": decision["selected_capability"],
                     "executed_capability": execution["capability"],
                     "status": status, "dispatch_match": matched})
    return rows


def combine_raw(inputs: list[dict[str, Any]], gold: list[dict[str, Any]],
                outputs: list[dict[str, Any]], router_rows: list[dict[str, Any]],
                capability_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len({len(inputs), len(gold), len(outputs), len(router_rows), len(capability_rows)}) != 1:
        raise ValueError("raw result join counts differ")
    raw = []
    for inp, expected, output, router_row, capability_row in zip(inputs, gold, outputs, router_rows, capability_rows):
        if len({inp["case_id"], expected["case_id"], output["case_id"], router_row["case_id"], capability_row["case_id"]}) != 1:
            raise ValueError("raw result join identity mismatch")
        raw.append({"case_id": inp["case_id"], "candidate_input": inp["candidate_input"],
                    "gold": expected, "decision": output["router_decision"],
                    "repeat_decision": route_request(inp["candidate_input"]),
                    "router_evaluation": router_row,
                    "capability_evaluation": capability_row})
    return raw


def protected_t22_metric_evidence(source_root: Path) -> dict[str, Any]:
    contract = load_contract(source_root / "evaluations" / "t22" / "t21_master_contract.json")
    graph = load_artifact_graph(source_root / contract.get("artifacts.artifact_graph"))
    rehearsal = run_real_mode_lifecycle_rehearsal_t22(source_root, contract, graph)
    registry = read_json(source_root / "evaluations" / "t22" / "official_metric_registry.json")
    metrics = sorted(metric for family in registry["families"].values() for metric in family)
    if rehearsal["status"] != "PASS" or rehearsal["evaluation"]["floor_calculations"] != 32 or len(metrics) != 32:
        raise ValueError("protected T22 disposable scorer did not pass 32 floors")
    return {"status": "PASS", "metric_ids": metrics, "metric_count": 32,
            "scorer": "t21_protocol.scorer_r17:score_explicit",
            "scorer_invoked_on": "DISPOSABLE_NONBLIND_T22_SHADOW",
            "t22_raw_blind_access": 0,
            "t22_rehearsal": rehearsal}


def protected_t22_floor_evidence(metric_evidence: dict[str, Any]) -> dict[str, Any]:
    if metric_evidence.get("status") != "PASS" or metric_evidence.get("metric_count") != 32:
        raise ValueError("T22 metric evidence incomplete")
    return {"status": "PASS", "passed": 32, "failed": 0, "total": 32,
            "metric_ids": metric_evidence["metric_ids"]}


def combine_results(router_score: dict[str, Any], protection: dict[str, Any],
                    capability_rows: list[dict[str, Any]]) -> dict[str, Any]:
    cap_pass = all(row["dispatch_match"] for row in capability_rows)
    return {"schema_version": "t23-holdout-results-v1",
            "artifact": "T23_HOLDOUT_RESULTS", "experiment": "t23",
            "router_status": router_score["status"],
            "protected_t22_status": protection["status"],
            "protected_t22_floors_passed": protection["passed"],
            "capability_dispatch_status": "PASS" if cap_pass else "FAIL",
            "rows": len(capability_rows),
            "status": "PASS" if router_score["status"] == protection["status"] == "PASS" and cap_pass else "FAIL"}


def build_provenance(root: Path, provider: ProductionRouterProvider,
                     parity: dict[str, Any], graph_report: dict[str, Any]) -> dict[str, Any]:
    out = root / "evaluations" / "t23"
    return {"schema_version": "t23-evaluation-provenance-v1",
            "artifact": "T23_EVALUATION_PROVENANCE",
            "provider": provider.provider_id, "provider_sha256": sha256_file(Path(__file__).with_name("provider.py")),
            "provider_rows_executed": provider.rows_executed,
            "provider_initialization_rows": 0,
            "parity": parity, "graph": graph_report,
            "seal_sha256": sha256_file(out / "HOLDOUT_FROZEN"),
            "material_mode": "REAL_BLIND" if provider.workspace_mode == "REAL_EXPERIMENT" else "SYNTHETIC",
            "workspace_mode": provider.workspace_mode}


def _evaluate(source_root: Path, workspace: Path, *, general_context: Any,
              web_provider: Any, real: bool) -> dict[str, Any]:
    root = Path(workspace).resolve()
    verify_seal(root)
    marker = read_json(root / "evaluations" / "t23" / "HOLDOUT_FROZEN")
    expected_mode = "REAL_EXPERIMENT" if real else "SYNTHETIC_DISPOSABLE"
    if marker["workspace_mode"] != expected_mode:
        raise ValueError("T23 evaluation mode differs from sealed material")
    graph_report = validate_graph(load_graph(source_root / "evaluations" / "t23" / "production_evaluation_graph.json"))
    out = root / "evaluations" / "t23"
    if (out / "evaluation_run_ledger.json").exists():
        raise ValueError("T23 evaluation one-shot ledger already exists")
    inputs = list(iter_jsonl(out / "suites" / "inputs.jsonl"))
    gold = list(iter_jsonl(out / "suites" / "gold.jsonl"))
    provider = ProductionRouterProvider(root / "rag" / "gk_holdout_t23",
                                        web_provider=web_provider, general_context=general_context,
                                        document_roots=(root,),
                                        workspace_mode=expected_mode)
    if provider.rows_executed:
        raise ValueError("candidate executed rows during provider initialization")
    ledger = EvaluationLedger.create_exclusive(out / "evaluation_run_ledger.json", "t23",
                                               {"material_mode": "REAL_BLIND" if real else "SYNTHETIC", "provider": provider.provider_id})
    transitions = ["SEALED", "EVALUATION_STARTED"]
    try:
        outputs = provider.generate(inputs)
        parity = decision_parity(inputs, outputs)
        if parity["status"] != "PASS":
            raise ValueError("direct/runtime provider parity failed")
        write_jsonl(out / "router_decisions.jsonl", [{"case_id": row["case_id"], **row["router_decision"]} for row in outputs])
        write_jsonl(out / "selected_capability_execution.jsonl", [{"case_id": row["case_id"], **row["selected_capability_execution"]} for row in outputs])
        write_jsonl(out / "candidate_outputs.jsonl", outputs)
        router_rows = evaluate_router(gold, outputs)
        capability_rows = evaluate_capability(outputs)
        write_jsonl(out / "router_evaluator.jsonl", router_rows)
        write_jsonl(out / "capability_evaluator.jsonl", capability_rows)
        raw = combine_raw(inputs, gold, outputs, router_rows, capability_rows)
        write_jsonl(out / "raw_results.jsonl", raw)
        registry = read_json(source_root / "evaluations" / "t23" / "production_router_metric_registry.json")
        router_score = score_router(raw, registry)
        write_json(out / "router_metric_evidence.json", router_score["metrics"], exclusive=True)
        write_json(out / "router_floor_evidence.json", router_score["floors"], exclusive=True)
        t22 = protected_t22_metric_evidence(source_root)
        write_json(out / "t22_disposable_scorer_rehearsal.json", t22["t22_rehearsal"], exclusive=True)
        write_json(out / "protected_t22_metric_evidence.json", {k: v for k, v in t22.items() if k != "t22_rehearsal"}, exclusive=True)
        protection = protected_t22_floor_evidence(t22)
        write_json(out / "protected_t22_floor_evidence.json", protection, exclusive=True)
        combined = combine_results(router_score, protection, capability_rows)
        write_json(out / "holdout_results.json", combined, exclusive=True)
        provenance = build_provenance(root, provider, parity, graph_report)
        write_json(out / "evaluation_provenance.json", provenance, exclusive=True)
        ledger.complete({"rows": len(outputs), "router_metrics": len(router_score["metrics"]), "protected_t22_metrics": 32})
        transitions.append("EVALUATION_COMPLETE")
        return {"status": combined["status"], "terminal_state": transitions[-1],
                "transitions": transitions, "rows": len(outputs),
                "router_metrics": router_score, "protected_t22_floors": 32,
                "provider_parity": parity, "provider_initialization_rows": 0,
                "evaluation_graph": graph_report}
    except Exception as exc:
        if ledger.state == "STARTED":
            ledger.fail({"error_type": type(exc).__name__, "error": str(exc)})
        raise


def run_shadow_evaluation(source_root: Path, workspace: Path, *, general_context: Any) -> dict[str, Any]:
    """Official-like evaluation of a sealed disposable T23 shadow."""
    web = FixtureSearchProvider(FixtureCorpus([], query_time="2026-09-22"))
    return _evaluate(source_root, workspace, general_context=general_context,
                     web_provider=web, real=False)


def run_real_evaluation(source_root: Path, authorization: str, *,
                        general_context: Any, live_web_provider: Any) -> dict[str, Any]:
    """Future authorized one-shot evaluation; never called in preconstruction."""
    require_evaluation_authorization(authorization, experiment="t23")
    root = Path(source_root).resolve()
    return _evaluate(root, root, general_context=general_context,
                     web_provider=live_web_provider, real=True)
