"""Official-like T24 evaluation over a sealed private holdout.

Candidate receives inputs only; the evaluator joins private gold after the
router and selected capability have executed. Live web passes the T24 source
firewall. The evaluation is one-shot over a private ledger, and publication
leakage refuses the run entirely.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sciencemath.executive.router_v2 import route_request
from t21_protocol.artifact_graph import load_artifact_graph
from t21_protocol.contract import load_contract
from t21_protocol.pipeline_t22 import run_real_mode_lifecycle_rehearsal_t22

from . import workspace as workspace_module
from .context import require_evaluation_authorization
from .firewall import FirewallSearchProvider, LiveWebSourceFirewall
from .gates import ensure_evaluation_permitted
from .graph import load_graph, validate_graph
from .ledgers import (T24EvaluationLedger, build_evaluation_receipt, load_evaluation_ledger,
                      verify_evaluation_ledger)
from .provider import T24ProductionRouterProvider, decision_parity
from .scorer import score_router
from .seal import verify_seal

RESULTS_SCHEMA = "t24-holdout-results-v1"


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
    for inp, expected, output, router_row, capability_row in zip(inputs, gold, outputs,
                                                                 router_rows, capability_rows):
        if len({inp["case_id"], expected["case_id"], output["case_id"],
                router_row["case_id"], capability_row["case_id"]}) != 1:
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
    registry = json.loads((source_root / "evaluations" / "t22" / "official_metric_registry.json")
                          .read_text(encoding="utf-8"))
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
    return {"schema_version": RESULTS_SCHEMA, "artifact": "T24_HOLDOUT_RESULTS",
            "experiment": "t24",
            "router_status": router_score["status"],
            "protected_t22_status": protection["status"],
            "protected_t22_floors_passed": protection["passed"],
            "capability_dispatch_status": "PASS" if cap_pass else "FAIL",
            "rows": len(capability_rows),
            "status": "PASS" if router_score["status"] == protection["status"] == "PASS"
                      and cap_pass else "FAIL"}


def build_provenance(store: Any, provider: T24ProductionRouterProvider,
                     parity: dict[str, Any], graph_report: dict[str, Any],
                     publication_gate: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "t24-evaluation-provenance-v1",
            "artifact": "T24_EVALUATION_PROVENANCE", "experiment": "t24",
            "provider": provider.provider_id, "provider_rows_executed": provider.rows_executed,
            "provider_initialization_rows": 0, "parity": parity, "graph": graph_report,
            "firewall_counters": provider.firewall_counters(),
            "publication_gate_status": publication_gate["status"],
            "seal_private_manifest_sha256": store.read("holdout_seal")["private_manifest_sha256"],
            "material_mode": ("REAL_BLIND" if provider.workspace_mode == "REAL_EXPERIMENT"
                              else "SYNTHETIC"),
            "workspace_mode": provider.workspace_mode}


def verify_gold_firewall(store: Any, workspace: Path,
                         provider: T24ProductionRouterProvider) -> dict[str, Any]:
    """Gold never reaches the candidate: field exposure raises; gold stays out of
    the candidate-visible corpus mount (the evaluator-side holdout keeps gold)."""
    gold_rows = store.read("suites/gold.jsonl")
    gold_fields = set(gold_rows[0]) if gold_rows else set()
    if not gold_fields:
        raise ValueError("gold firewall verification found no gold rows")
    probe = {"case_id": "t24-goldfirewall-probe-0000",
             "candidate_input": {"query": "gold firewall probe", "request_date": "2026-09-23"},
             **{field: "LEAK" for field in gold_fields if field != "case_id"}}
    try:
        provider.generate([probe])
    except Exception:
        refusal = {"status": "PASS", "refusal": "GOLD_FIELD_EXPOSURE_RAISED",
                   "gold_fields_protected": sorted(gold_fields)}
    else:
        refusal = {"status": "FAIL", "refusal": None,
                   "gold_fields_protected": sorted(gold_fields)}
    corpus = workspace_module.corpus_dir_in(workspace)
    provider_visible = [path.name for path in corpus.rglob("*") if path.is_file()]
    gold_in_corpus = [name for name in provider_visible if "gold" in name.lower()]
    if gold_in_corpus:
        raise ValueError("gold mounted into the candidate-visible corpus directory")
    return {"schema_version": "t24-gold-firewall-verification-v1",
            "artifact": "T24_GOLD_FIREWALL_VERIFICATION", "experiment": "t24",
            "field_refusal": refusal, "gold_in_corpus_mount": gold_in_corpus,
            "gold_not_in_provider_visible_inputs": True,
            "status": "PASS" if refusal["status"] == "PASS" and not gold_in_corpus else "FAIL"}


def _evaluate(source_root: Path, store: Any, ws: Path, *, general_context: Any,
              web_provider: Any, real: bool, publication_gate: dict[str, Any]) -> dict[str, Any]:
    if verify_seal(store)["status"] != "PASS":
        raise ValueError("T24 evaluation requires a verified seal")
    marker = store.read("holdout_seal")
    expected_mode = "REAL_EXPERIMENT" if real else "SYNTHETIC_DISPOSABLE"
    if marker["workspace_mode"] != expected_mode:
        raise ValueError("T24 evaluation mode differs from sealed material")
    graph_report = validate_graph(load_graph(source_root / "evaluations" / "t24"
                                             / "production_evaluation_graph.json"))
    if load_evaluation_ledger(store).state != "STARTED":
        raise ValueError("T24 evaluation ledger not in STARTED state")
    verify_evaluation_ledger(store)
    inputs = store.read("suites/inputs.jsonl")
    gold = store.read("suites/gold.jsonl")
    firewall = None
    if isinstance(web_provider, FirewallSearchProvider):
        firewall = web_provider.firewall
    provider = T24ProductionRouterProvider(
        workspace_module.corpus_dir_in(ws), web_provider=web_provider,
        general_context=general_context, document_roots=(workspace_module.holdout_dir_in(ws),),
        workspace_mode=expected_mode)
    if provider.rows_executed:
        raise ValueError("candidate executed rows during provider initialization")
    gold_firewall = verify_gold_firewall(store, ws, provider)
    if gold_firewall["status"] != "PASS":
        raise ValueError("T24 gold firewall verification failed")
    outputs = provider.generate(inputs)
    parity = decision_parity(inputs, outputs)
    if parity["status"] != "PASS":
        raise ValueError("direct/runtime provider parity failed")
    router_rows = evaluate_router(gold, outputs)
    capability_rows = evaluate_capability(outputs)
    raw = combine_raw(inputs, gold, outputs, router_rows, capability_rows)
    registry = json.loads((source_root / "evaluations" / "t24"
                           / "production_router_metric_registry.json").read_text(encoding="utf-8"))
    router_score = score_router(raw, registry)
    t22 = protected_t22_metric_evidence(source_root)
    protection = protected_t22_floor_evidence(t22)
    combined = combine_results(router_score, protection, capability_rows)
    provenance = build_provenance(store, provider, parity, graph_report, publication_gate)
    store.write("evaluation/router_decisions.jsonl",
                [{"case_id": row["case_id"], **row["router_decision"]} for row in outputs],
                role="router_decisions", schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/selected_capability_execution.jsonl",
                [{"case_id": row["case_id"], **row["selected_capability_execution"]} for row in outputs],
                role="selected_capability_execution", schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/candidate_outputs.jsonl", outputs, role="candidate_outputs",
                schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/router_evaluator.jsonl", router_rows, role="router_evaluator",
                schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/capability_evaluator.jsonl", capability_rows,
                role="capability_evaluator", schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/raw_results.jsonl", raw, role="raw_results",
                schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/router_metric_evidence.json", router_score["metrics"],
                role="router_metric_evidence", schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/router_floor_evidence.json", router_score["floors"],
                role="router_floor_evidence", schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/t22_disposable_scorer_rehearsal.json", t22["t22_rehearsal"],
                role="t22_disposable_scorer_rehearsal", schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/protected_t22_metric_evidence.json",
                {key: value for key, value in t22.items() if key != "t22_rehearsal"},
                role="protected_t22_metric_evidence", schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/protected_t22_floor_evidence.json", protection,
                role="protected_t22_floor_evidence", schema_version="t24-evaluation-artifacts-v1")
    store.write("evaluation/holdout_results.json", combined, role="holdout_results",
                schema_version=RESULTS_SCHEMA)
    store.write("evaluation/evaluation_provenance.json", provenance,
                role="evaluation_provenance", schema_version="t24-evaluation-artifacts-v1")
    store.write("gold_firewall_verification", gold_firewall, role="gold_firewall_verification",
                schema_version="t24-gold-firewall-verification-v1")
    ledger = load_evaluation_ledger(store)
    counters = provider.firewall_counters() or (dict(firewall.counters) if firewall else {})
    ledger.complete({"rows": len(outputs), "router_metrics": len(router_score["metrics"]),
                     "protected_t22_metrics": 32, "firewall_counters": counters,
                     "gold_firewall": gold_firewall["field_refusal"]["refusal"]})
    if combined["status"] == "PASS":
        receipt = build_evaluation_receipt(store.read("evaluation_run_ledger"))
    else:
        receipt = {"schema_version": "t24-public-evaluation-receipt-v1", "state": "COMPLETE",
                   "evaluation_status": "FAIL"}
    return {"status": combined["status"], "rows": len(outputs),
            "router_metrics": router_score, "protected_t22_floors": 32,
            "provider_parity": parity, "provider_initialization_rows": 0,
            "firewall_counters": counters, "gold_firewall": gold_firewall,
            "evaluation_graph": graph_report, "publication_gate": publication_gate["status"],
            "public_evaluation_receipt": receipt}


def run_shadow_evaluation(source_root: Path, store: PrivateArtifactStore,
                          ws: Path, *, general_context: Any = None) -> dict[str, Any]:
    """Official-like one-shot evaluation of a sealed disposable T24 shadow."""
    from sciencemath.web.fixture_provider import FixtureCorpus, FixtureSearchProvider

    registry = json.loads((source_root / "evaluations" / "t24"
                           / "live_web_source_firewall_registry.json").read_text(encoding="utf-8"))
    inner = FixtureSearchProvider(FixtureCorpus([], query_time="2026-09-23"))
    web = FirewallSearchProvider(inner, LiveWebSourceFirewall(registry, source_root))
    publication_gate = {"status": "PASS"}
    T24EvaluationLedger.create_exclusive(
        store=store, material_mode="SYNTHETIC",
        seal_commitment_sha256=store.commitment("holdout_seal")["canonical_sha256"],
        private_artifact_root=store.binding_free_component_root(),
        gold_firewall_verified=True)
    try:
        return _evaluate(source_root, store, ws, general_context=general_context,
                         web_provider=web, real=False, publication_gate=publication_gate)
    except Exception as exc:
        ledger = load_evaluation_ledger(store)
        if ledger.state == "STARTED":
            ledger.fail({"error_type": type(exc).__name__, "error": str(exc)})
        raise


def run_real_evaluation(source_root: Path, authorization: str, *,
                        general_context: Any, live_web_provider: Any,
                        store: Any) -> dict[str, Any]:
    """Future authorized one-shot evaluation; never callable during preconstruction."""
    require_evaluation_authorization(authorization)
    source_root = Path(source_root).resolve()
    store.verify()
    publication_gate = ensure_evaluation_permitted(source_root, blind_hashes=store.blind_hashes())
    if verify_seal(store)["status"] != "PASS":
        raise ValueError("T24 real evaluation requires a verified seal")
    T24EvaluationLedger.create_exclusive(
        store=store, material_mode="REAL_BLIND",
        seal_commitment_sha256=store.commitment("holdout_seal")["canonical_sha256"],
        private_artifact_root=store.binding_free_component_root(),
        gold_firewall_verified=True)
    ws, _mount_report = workspace_module.create_private_workspace(
        source_root, store, purpose="real-evaluation")
    try:
        return _evaluate(source_root, store, ws, general_context=general_context,
                         web_provider=live_web_provider, real=True,
                         publication_gate=publication_gate)
    finally:
        workspace_module.dispose_workspace(ws)