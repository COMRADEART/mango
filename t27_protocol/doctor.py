"""Fail-closed public T27 preconstruction doctor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract import CONSTRUCTION_TOKEN, EVALUATION_TOKEN, REPLAN_TRIGGERS
from .exclusion import DIMENSIONS
from .freeze import runtime_identity, verify_freeze_v2


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "evaluations" / "t27" / name).read_text(
        encoding="utf-8"))


def run_doctor(root: Path) -> dict:
    root = Path(root).resolve()
    receipt = json.loads((root / "evaluations/t26/T26_EVALUATION_PUBLIC_RECEIPT.json").read_text(
        encoding="utf-8"))
    candidate = _read(root, "candidate_identity.json")
    contract = _read(root, "terminal_contract.json")
    metrics = _read(root, "metric_registry.json")
    nonvacuity = _read(root, "nonvacuity_policy.json")
    qualification = _read(root, "qualification_report.json")
    diagnostics = _read(root, "diagnostics_report.json")
    protection = _read(root, "protection_report.json")
    storage = _read(root, "private_storage_policy.json")
    exclusions = _read(root, "historical_exclusion_policy.json")
    freeze = _read(root, "preconstruction_freeze.json")
    mapping, runtime_root = runtime_identity(root)
    checks = {
        "t26_closed_no_rerun": receipt.get("state") == "COMPLETE" and
            receipt.get("attempt") == 1 and receipt.get("capability_status") == "FAIL",
        "t26_aggregate_only_boundary": receipt.get("raw_rows_included") is False and
            receipt.get("scenario_bodies_included") is False,
        "t26_private_artifacts_sealed": qualification.get("t26_private_rows_opened") == 0 and
            qualification.get("t26_candidate_reruns") == 0,
        "candidate_identity": candidate.get("runtime_component_sha256") == mapping and
            candidate.get("runtime_root") == runtime_root,
        "terminal_contract": set(contract.get("terminals", [])) == {
            "COMPLETE", "PARTIAL", "INSUFFICIENT_EVIDENCE", "BLOCKED",
            "BUDGET_EXHAUSTED", "UNAVAILABLE_CAPABILITY", "SECURITY_REFUSAL", "ERROR"},
        "completion_gate": diagnostics.get("completion_gate", {}).get("status") == "PASS",
        "recovery_contract": qualification["score"]["metrics"]["recovery_success_rate"]["pass"],
        "replan_contract": list(contract.get("replan_triggers", [])) == list(REPLAN_TRIGGERS) and
            qualification["score"]["metrics"]["replan_correctness_rate"]["pass"],
        "safe_abstention_contract": qualification["score"]["metrics"]["safe_abstention_accuracy"]["pass"],
        "metric_denominators": all(item.get("denominator", 0) > 0 and
                                   item.get("zero_denominator_policy") == "FAIL_NONVACUITY"
                                   for item in qualification["score"]["metrics"].values()),
        "nonvacuity_rules": nonvacuity.get("rate_policy") == "FAIL_NONVACUITY" and
            all(value > 0 for value in nonvacuity.get("requirements", {}).values()),
        "t19_protection": protection.get("t19", {}).get("tests", {}).get("status") == "PASS" and
            protection.get("t19", {}).get("authority") == "PROPOSE_ONLY",
        "t20_protection": protection.get("t20", {}).get("tests", {}).get("status") == "PASS" and
            protection.get("t20", {}).get("authority") == "COORDINATE_INTERNAL_WORK_ONLY",
        "t22_protection": protection.get("t22", {}).get("passed") == 32 and
            protection.get("t22", {}).get("total") == 32,
        "t25_router_protection": protection.get("t25_router", {}).get("floor_count") == 15 and
            protection.get("t25_router", {}).get("status") == "PASS",
        "t25_dispatch_protection": protection.get("t25_dispatch", {}).get("status") == "PASS",
        "private_store_policy": storage.get("store_id") == "T27-STORE-01" and
            storage.get("namespace") == "t27" and
            storage.get("locator_scheme") == "t27-private://",
        "nine_dimensional_exclusion": exclusions.get("dimensions") == list(DIMENSIONS) and
            exclusions.get("historical_source") == "T26_SEALED_HASH_OVERLAP_ORACLE_ONLY",
        "construction_token": _read(root, "prospective_design.json").get("construction_token") == CONSTRUCTION_TOKEN,
        "evaluation_token": _read(root, "prospective_design.json").get("evaluation_token") == EVALUATION_TOKEN,
        "qualification": qualification.get("status") == "PASS",
        "terminal_matrix": diagnostics.get("terminal_matrix", {}).get("status") == "PASS",
        "verification_matrix": diagnostics.get("verification_matrix", {}).get("status") == "PASS",
        "freeze_v1_preserved_historically":
            freeze.get("freeze_sha256") == "ac11569f973ca819795eef370d5befe384b9cb2dcc23c850a0ef84ea1bb536b8",
        "construction_ledger_absent": not (root / "evaluations/t27/construction_ledger.json").exists(),
        "evaluation_ledger_absent": not (root / "evaluations/t27/evaluation_ledger.json").exists(),
        "tokens_exact_no_aliases": CONSTRUCTION_TOKEN != EVALUATION_TOKEN,
    }
    from .construction import (CONSTRUCTION_GATE_IDS, CONTRACT_LEAF_IDS,
                               construction_contract)
    from .evaluation import EVALUATION_STATES, runner_identity
    from .store import storage_policy_successor

    def optional(name: str) -> dict:
        path = root / "evaluations" / "t27" / name
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    storage_v2 = optional("construction_ready_storage_policy.json")
    exclusion_v2 = optional("historical_exclusion_policy_v2.json")
    construction_rehearsals = optional("construction_rehearsal_report.json")
    evaluation_rehearsals = optional("evaluation_rehearsal_report.json")
    failure_rehearsals = optional("failure_rehearsal_report.json")
    negative_controls = optional("construction_negative_controls.json")
    runner = optional("official_runner_identity.json")
    freeze_v2 = optional("preconstruction_freeze_v2.json")
    exposure = optional("real_exposure_v2.json")
    unrestricted = optional("unrestricted_test_report.json")
    focused_test_gate = optional("test_gate_report_v2.json")
    production_graph = _read(root, "production_graph.json")
    authority_graph = _read(root, "authority_graph.json")
    required_graph_nodes = {
        "private_author", "historical_exclusion_oracle", "T26_overlap_oracle",
        "construction_ledger", "private_materialization", "construction_audit",
        "construction_gate", "private_manifest", "holdout_seal",
        "publication_gate", "public_construction_receipt", "planner",
        "orchestrator", "router", "provider_normalizer",
        "registered_capabilities", "handoff_validator", "verification_layer",
        "retry_controller", "replan_controller", "completion_gate",
        "evaluation_ledger", "official_runner", "gold_firewall", "scorer",
        "public_evaluation_receipt",
    }
    negative_required = {
        "wrong_token", "wrong_candidate", "wrong_runtime_root", "wrong_freeze",
        "wrong_metric_registry", "wrong_nonvacuity_policy", "wrong_authority_graph",
        "duplicate_ledger", "attempt_2", "scenario_count_511", "scenario_count_513",
        "missing_family", "wrong_family_count", "successful_completion_below_minimum",
        "recoverable_below_minimum", "replan_below_minimum",
        "safe_abstention_below_minimum", "duplicate_scenario_id",
        "historical_overlap", "t26_oracle_overlap", "gold_field_exposure",
        "candidate_gold_edge", "authority_escalation", "fixture_hash_mismatch",
        "contract_leaf_failure", "premature_evaluation_artifact",
    }
    checks.update({
        "construction_ready_storage_policy": storage_v2 == storage_policy_successor(),
        "construction_implementation": (root / "t27_protocol/construction.py").is_file(),
        "exclusive_construction_ledger": negative_controls.get("controls", {}).get(
            "duplicate_ledger", {}).get("status") == "PASS",
        "construction_one_shot_marker": negative_controls.get("controls", {}).get(
            "attempt_2", {}).get("status") == "PASS",
        "construction_ledger_hash_chain": all(
            run.get("state_sequence", []) == [
                "LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS",
                "MANIFESTED", "SEALED"]
            for run in construction_rehearsals.get("runs", []))
            and len(construction_rehearsals.get("runs", [])) == 2,
        "t26_overlap_oracle_interface": exclusion_v2.get("t26_boundary", {}).get(
            "result_artifact") == "T26_TO_T27_OVERLAP_ORACLE_RESULT",
        "clean_room_author_provenance": exclusion_v2.get(
            "historical_private_row_exposure_to_author") == 0,
        "nonvacuity_design_gate": all(
            run.get("designated_counts", {}).get(name, 0) >= minimum
            for run in construction_rehearsals.get("runs", [])
            for name, minimum in nonvacuity.get("requirements", {}).items()),
        "construction_contract_leaf_enumerator":
            construction_contract().get("leaf_count") == len(CONTRACT_LEAF_IDS),
        "construction_audit": all(run.get("status") == "PASS"
                                  for run in construction_rehearsals.get("runs", []))
                              and len(construction_rehearsals.get("runs", [])) == 2,
        "construction_gate": all(run.get("gate_check_count") == len(CONSTRUCTION_GATE_IDS)
                                 for run in construction_rehearsals.get("runs", [])),
        "construction_negative_controls": negative_controls.get("status") == "PASS"
            and set(negative_controls.get("controls", {})) == negative_required,
        "private_manifest_and_seal": all(run.get("state") == "SEALED"
                                         for run in construction_rehearsals.get("runs", [])),
        "private_store_verify": all(run.get("store_status") == "PASS"
                                    for run in construction_rehearsals.get("runs", [])),
        "construction_receipt_safe": all(
            run.get("receipt_blind_content_included") is False
            for run in construction_rehearsals.get("runs", [])),
        "publication_leak_gate": all(run.get("leak_gate_status") == "PASS"
                                    for run in construction_rehearsals.get("runs", [])),
        "evaluation_implementation": (root / "t27_protocol/evaluation.py").is_file(),
        "evaluation_ledger_state_machine": list(EVALUATION_STATES) == [
            "STARTED", "EXECUTED", "SCORED", "COMPLETE", "FAILED"],
        "official_runner_identity": runner == runner_identity(root),
        "gold_firewall": all(run.get("gold_firewall") == "PASS"
                             for run in evaluation_rehearsals.get("runs", [])),
        "fail_nonvacuity_scorer": all(
            run.get("denominators_nonzero") is True
            for run in evaluation_rehearsals.get("runs", [])),
        "construction_failure_semantics": failure_rehearsals.get(
            "construction", {}).get("status") == "PASS",
        "evaluation_failure_semantics": failure_rehearsals.get(
            "evaluation", {}).get("status") == "PASS",
        "disposable_construction_rehearsals":
            construction_rehearsals.get("status") == "PASS"
            and construction_rehearsals.get("semantic_equivalence") is True,
        "disposable_evaluation_rehearsals":
            evaluation_rehearsals.get("status") == "PASS"
            and evaluation_rehearsals.get("semantic_equivalence") is True,
        "production_graph_complete": set(production_graph.get("nodes", {})) == required_graph_nodes
            and production_graph.get("missing_producers") == 0
            and production_graph.get("dangling_edges") == 0
            and production_graph.get("production_stubs") == 0,
        "authority_graph_complete": authority_graph.get("candidate_gold_access") is False
            and authority_graph.get("construction_candidate_execution_authority") is False
            and authority_graph.get("private_evaluator_authority") == "SCORE_PRIVATE_ONCE",
        "freeze_v2": bool(freeze_v2) and verify_freeze_v2(root, freeze_v2).get("status") == "PASS"
            and freeze_v2.get("real_construction_authorized") is False
            and freeze_v2.get("real_evaluation_authorized") is False,
        "real_exposure_zero_v2": bool(exposure) and all(exposure.get(key) == 0 for key in (
            "t27_real_blind_rows", "t27_real_gold", "construction_attempts",
            "evaluation_attempts", "candidate_real_executions",
            "official_real_evaluator_invocations", "t26_private_rows_opened",
            "t26_reruns")),
        "applicability_aware_test_gate": bool(unrestricted)
            and unrestricted.get("new_live_failures") == 0
            and unrestricted.get("new_unknown_failures") == 0
            and unrestricted.get("unexplained_skips") == 0
            and unrestricted.get("xfails") == 0
            and unrestricted.get("deselections") == 0
            and unrestricted.get("t27_focused", {}).get("status") == "PASS",
        "focused_test_gate_v2": focused_test_gate.get("status") == "PASS"
            and focused_test_gate.get("passed") == 19
            and focused_test_gate.get("live_failures") == 0
            and focused_test_gate.get("errors") == 0
            and focused_test_gate.get("unexplained_skips") == 0
            and focused_test_gate.get("xfails") == 0
            and focused_test_gate.get("deselections") == 0,
    })
    return {
        "schema_version": "t27-doctor-v1", "artifact": "T27_PROTOCOL_DOCTOR",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "check_count": len(checks),
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
        "t26_private_paths_probed": 0, "t26_private_rows_opened": 0,
        "t26_candidate_reruns": 0,
    }
