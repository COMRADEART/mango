"""Fail-closed public T27 preconstruction doctor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract import CONSTRUCTION_TOKEN, EVALUATION_TOKEN, REPLAN_TRIGGERS
from .exclusion import (DIMENSIONS, PUBLIC_HISTORY_BUILDER,
                        REQUIRED_HISTORICAL_SOURCES,
                        authenticated_construction_policy,
                        build_authenticated_public_historical_index,
                        public_index_report)
from .freeze import (PRESERVED_V2_FREEZE_SHA256, PRESERVED_V3_FREEZE_SHA256,
                     runtime_identity, verify_freeze_v4)


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
    exclusion_v3 = optional("historical_exclusion_policy_v3.json")
    public_history = optional("public_historical_index_report.json")
    real_oracle_rehearsal = optional("real_mode_oracle_rehearsal.json")
    construction_rehearsals = optional("construction_rehearsal_report.json")
    evaluation_rehearsals = optional("evaluation_rehearsal_report.json")
    failure_rehearsals = optional("failure_rehearsal_report.json")
    negative_controls = optional("construction_negative_controls.json")
    runner = optional("official_runner_identity.json")
    freeze_v2 = optional("preconstruction_freeze_v2.json")
    freeze_v3 = optional("preconstruction_freeze_v3.json")
    exposure = optional("real_exposure_v3.json")
    unrestricted = optional("unrestricted_test_report.json")
    focused_test_gate = optional("test_gate_report_v2.json")
    focused_test_gate_v3 = optional("test_gate_report_v3.json")
    focused_test_gate_v4 = optional("test_gate_report_v4.json")
    marker_contract = optional("official_t26_marker_contract.json")
    store_preflight = optional("official_t26_store_preflight.json")
    freeze_v4 = optional("preconstruction_freeze_v4.json")
    exposure_v4 = optional("real_exposure_v4.json")
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
        "public_history_none", "empty_nine_dimensional_history",
        "missing_required_historical_source", "missing_source_root",
        "fake_source_commitment", "fake_public_history_builder_identity",
        "synthetic_t26_oracle_real_mode", "wrong_t26_store",
        "wrong_t26_manifest_hash", "wrong_t26_seal_hash",
        "wrong_t26_evaluation_ledger_hash", "wrong_t26_holdout_root",
        "wrong_t27_prospective_root", "missing_oracle_dimension",
        "t26_overlap_gt_zero",
        "legacy_rehearsal_marker_path_only", "official_marker_absent",
        "official_marker_wrong_schema", "official_marker_wrong_artifact",
        "official_marker_wrong_experiment", "official_marker_wrong_attempt",
        "official_marker_wrong_genesis_hash", "marker_missing_from_commitment_index",
        "marker_commitment_hash_mismatch", "marker_byte_count_mismatch",
        "ledger_started_event_hash_mismatch", "ledger_chain_invalid",
        "ledger_state_not_complete", "disposable_standin_using_legacy_path",
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
        "t26_overlap_oracle_interface": exclusion_v3.get("t26_boundary", {}).get(
            "result_artifact") == "T26_TO_T27_OVERLAP_ORACLE_RESULT",
        "clean_room_author_provenance": exclusion_v3.get(
            "historical_private_row_exposure_to_author") == 0,
        "public_historical_source_completeness": public_history.get(
            "required_source_count") == len(REQUIRED_HISTORICAL_SOURCES)
            and {item.get("source_class") for item in public_history.get("sources", [])}
            == set(REQUIRED_HISTORICAL_SOURCES),
        "public_history_builder_identity": public_history.get(
            "builder_implementation_identity") == PUBLIC_HISTORY_BUILDER
            and exclusion_v3 == authenticated_construction_policy(),
        "public_history_aggregate_root": public_history == public_index_report(
            build_authenticated_public_historical_index(root)),
        "sealed_t26_oracle_entrypoint": exclusion_v3.get("t26_boundary", {}).get(
            "implementation") ==
            "t26_protocol.t27_private_oracle:run_sealed_t26_to_t27_overlap_oracle",
        "t26_store_authentication": real_oracle_rehearsal.get(
            "store_authenticated") is True,
        "exact_t26_commitment_binding": real_oracle_rehearsal.get(
            "commitments_exact") is True,
        "synthetic_real_oracle_separation": real_oracle_rehearsal.get(
            "real_mode_not_synthetic") is True,
        "combined_historical_exclusion_root": all(
            isinstance(run.get("combined_historical_exclusion_root"), str)
            and len(run["combined_historical_exclusion_root"]) == 64
            for run in construction_rehearsals.get("runs", []))
            and len(construction_rehearsals.get("runs", [])) == 2,
        "exclusion_contract_gate_coverage": (
            len(CONTRACT_LEAF_IDS) > 45 and len(CONSTRUCTION_GATE_IDS) > 34),
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
        "freeze_v2_preserved_historically": freeze_v2.get("freeze_sha256") ==
            PRESERVED_V2_FREEZE_SHA256,
        "freeze_v3_preserved_historically": freeze_v3.get("freeze_sha256") ==
            PRESERVED_V3_FREEZE_SHA256,
        "freeze_v4": bool(freeze_v4) and verify_freeze_v4(root, freeze_v4).get(
            "status") == "PASS"
            and freeze_v4.get("real_construction_authorized") is False
            and freeze_v4.get("real_evaluation_authorized") is False
            and freeze_v4.get("supersedes", {}).get("reason") ==
            "T26_OFFICIAL_EVALUATION_MARKER_PATH_COMPATIBILITY_DEFECT",
        "t26_official_marker_path_exact": (
            marker_contract.get("marker_path_exact") is True
            and marker_contract.get("official_marker_path") ==
            "evaluation/one_shot_spent.json"),
        "t26_official_marker_schema_exact": (
            marker_contract.get("marker_schema_exact") is True
            and marker_contract.get("official_marker_schema") ==
            "t26-evaluation-one-shot-marker-v2"),
        "t26_official_marker_contract_current": (
            marker_contract.get("status") == "PASS"
            and marker_contract.get("legacy_marker_path_accepted") is False
            and marker_contract.get("official_marker_artifact") ==
            "T26_EVALUATION_ONE_SHOT_SPENT"),
        "rehearsal_layout_equals_production_layout": (
            marker_contract.get("disposable_layout_mirrors_official") is True),
        "legacy_marker_path_rejected": (
            negative_controls.get("controls", {}).get(
                "legacy_rehearsal_marker_path_only", {}).get("status") == "PASS"
            and negative_controls.get("controls", {}).get(
                "disposable_standin_using_legacy_path", {}).get("status") == "PASS"),
        "t26_official_marker_negative_controls": all(
            negative_controls.get("controls", {}).get(name, {}).get("status")
            == "PASS" for name in (
                "official_marker_absent", "official_marker_wrong_schema",
                "official_marker_wrong_artifact", "official_marker_wrong_experiment",
                "official_marker_wrong_attempt", "official_marker_wrong_genesis_hash",
                "marker_missing_from_commitment_index",
                "marker_commitment_hash_mismatch", "marker_byte_count_mismatch",
                "ledger_started_event_hash_mismatch", "ledger_chain_invalid",
                "ledger_state_not_complete")),
        "real_store_metadata_preflight_pass": (
            store_preflight.get("status") == "PASS"
            and store_preflight.get("t26_store_authenticated") is True
            and store_preflight.get("official_commitment_scope") == "OFFICIAL_T26"
            and store_preflight.get("t26_store_identity") == "T26-STORE-01"
            and store_preflight.get("t26_official_marker_path") ==
            "evaluation/one_shot_spent.json"
            and store_preflight.get("t26_official_marker_schema") ==
            "t26-evaluation-one-shot-marker-v2"
            and store_preflight.get("t26_official_marker_committed") is True
            and store_preflight.get("t26_official_marker_genesis_matches_ledger")
            is True
            and store_preflight.get("t26_legacy_marker_path_present") is False
            and store_preflight.get("t26_official_evaluation_state") == "COMPLETE"
            and store_preflight.get("t26_official_evaluation_attempt") == 1
            and store_preflight.get("t26_evaluation_event_count") == 4
            and store_preflight.get("t26_official_commitments_exact") is True),
        "t26_private_rows_read_during_metadata_preflight_zero": all(
            store_preflight.get(key) == 0 for key in (
                "t26_private_rows_read", "t26_gold_rows_read",
                "t26_raw_output_rows_read", "t26_scored_rows_read",
                "t26_candidate_reruns", "outside_boundary_private_rows_exposed"))
            and store_preflight.get("t27_fingerprint_derivation_invoked") is False,
        "focused_test_gate_v4": focused_test_gate_v4.get("status") == "PASS"
            and focused_test_gate_v4.get("passed", 0) >= 19
            and focused_test_gate_v4.get("live_failures") == 0
            and focused_test_gate_v4.get("errors") == 0
            and focused_test_gate_v4.get("unexplained_skips") == 0
            and focused_test_gate_v4.get("xfails") == 0
            and focused_test_gate_v4.get("deselections") == 0,
        "real_exposure_zero_v4": bool(exposure_v4) and all(
            exposure_v4.get(key) == 0 for key in (
                "t27_real_blind_rows", "t27_real_gold", "construction_attempts",
                "evaluation_attempts", "candidate_real_executions",
                "official_real_evaluator_invocations",
                "t26_private_rows_exposed_outside_sealed_oracle",
                "t26_candidate_reruns")),
        "real_exposure_zero_v3": bool(exposure) and all(exposure.get(key) == 0 for key in (
            "t27_real_blind_rows", "t27_real_gold", "construction_attempts",
            "evaluation_attempts", "candidate_real_executions",
            "official_real_evaluator_invocations",
            "t26_private_rows_exposed_outside_sealed_oracle",
            "t26_candidate_reruns")),
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
        "focused_test_gate_v3": focused_test_gate_v3.get("status") == "PASS"
            and focused_test_gate_v3.get("passed", 0) >= 19
            and focused_test_gate_v3.get("live_failures") == 0
            and focused_test_gate_v3.get("errors") == 0
            and focused_test_gate_v3.get("unexplained_skips") == 0
            and focused_test_gate_v3.get("xfails") == 0
            and focused_test_gate_v3.get("deselections") == 0,
    })
    return {
        "schema_version": "t27-doctor-v2", "artifact": "T27_PROTOCOL_DOCTOR",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "check_count": len(checks),
        "failed_checks": sorted(name for name, passed in checks.items() if not passed),
        "t26_private_paths_probed": 0, "t26_private_rows_opened": 0,
        "t26_candidate_reruns": 0,
    }
