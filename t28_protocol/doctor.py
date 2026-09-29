"""Fail-closed public T28 preconstruction doctor."""
from __future__ import annotations

import json
from pathlib import Path

from t21_protocol.util import sha256_json

from .contract import (CONSTRUCTION_TOKEN, CRITICAL_COUNTERS, EVALUATION_TOKEN,
                       FAMILIES, FLOORS, NONVACUITY_MINIMUMS, REPLAN_TRIGGERS,
                       T27_CONSTRUCTION_STATE, T27_OFFICIAL_EVALUATION_ATTEMPT,
                       T27_OFFICIAL_EVALUATION_ELIGIBILITY,
                       T27_OFFICIAL_EVALUATION_STATE,
                       T27_PREDECESSOR_VERDICT)
from .construction import (CONSTRUCTION_GATE_IDS, CONTRACT_LEAF_IDS,
                           NEGATIVE_CONTROL_IDS, construction_contract,
                           official_marker_contract_report,
                           real_fingerprint_semantics_probe,
                           t27_oracle_nine_dimension_probe)
from .evaluation import (EVALUATION_STATES, runner_identity)
from .exclusion import (DIMENSIONS, GENERATED_PUBLIC_POLICY_SCHEMA,
                        GENERATED_PUBLIC_SOURCES, PUBLIC_HISTORY_BUILDER,
                        REQUIRED_HISTORICAL_SOURCES, SUPERSEDED_INDEX_ROOT,
                        authenticated_construction_policy,
                        build_authenticated_public_historical_index,
                        generated_public_dimension_policy,
                        historical_exclusion_policy_v4, policy,
                        public_index_report, public_index_supersession,
                        t27_public_qualification_exclusion_precedent,
                        construction_ready_policy,
                        GENERATED_PUBLIC_DIMENSION_CLASSIFICATIONS,
                        GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS,
                        verify_historical_index)
from .freeze import (PINNED_CANDIDATE_COMMIT, PINNED_CANDIDATE_TREE,
                     PINNED_RUNTIME_ROOT, T27_ADJUDICATION_COMMIT,
                     verify_freeze)
from .scorer import ZERO_DENOMINATOR_POLICY
from .store import storage_policy_successor
from .contract import metric_registry, nonvacuity_policy, production_graph, \
    storage_policy

TERMINALS_EXPECTED = {
    "COMPLETE", "PARTIAL", "INSUFFICIENT_EVIDENCE", "BLOCKED",
    "BUDGET_EXHAUSTED", "UNAVAILABLE_CAPABILITY", "SECURITY_REFUSAL", "ERROR",
}


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "evaluations" / "t28" / name).read_text(
        encoding="utf-8"))


def _optional(root: Path, name: str) -> dict:
    path = root / "evaluations" / "t28" / name
    return (json.loads(path.read_text(encoding="utf-8"))
            if path.is_file() else {})


def run_doctor(root: Path) -> dict:
    """Verify every staged T28 preconstruction artifact; FAIL=0 required."""
    root = Path(root).resolve()
    adjudication = json.loads(
        (root / "evaluations/t27/"
         "T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json")
        .read_text(encoding="utf-8"))
    t26_receipt = json.loads(
        (root / "evaluations/t26/T26_EVALUATION_PUBLIC_RECEIPT.json")
        .read_text(encoding="utf-8"))
    candidate = _read(root, "candidate_identity.json")
    contract = _read(root, "terminal_contract.json")
    metrics = _read(root, "metric_registry.json")
    nonvacuity = _read(root, "nonvacuity_policy.json")
    qualification = _read(root, "qualification_report.json")
    diagnostics = _read(root, "diagnostics_report.json")
    protection = _read(root, "protection_report.json")
    storage = _read(root, "private_storage_policy.json")
    storage_v2 = _optional(root, "construction_ready_storage_policy.json")
    exclusion = _read(root, "historical_exclusion_policy.json")
    exclusion_v2 = _optional(root, "historical_exclusion_policy_v2.json")
    exclusion_v3 = _optional(root, "historical_exclusion_policy_v3.json")
    exclusion_v4 = _optional(root, "historical_exclusion_policy_v4.json")
    dimension_policy = _optional(
        root, "generated_public_exclusion_dimension_policy.json")
    public_history = _optional(root, "public_historical_index_report.json")
    supersession = _optional(root, "public_index_supersession.json")
    precedent = _optional(root, "t27_public_qualification_exclusion_precedent.json")
    anchor = _optional(root, "T27_HISTORICAL_FAILURE_ANCHOR.json")
    reproduction = _read(root, "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json")
    design = _read(root, "prospective_design.json")
    qualification_exclusions = _read(root, "qualification_exclusions.json")
    exposure = _optional(root, "real_exposure.json")
    leak_scan = _optional(root, "public_leak_scan.json")
    test_gate = _optional(root, "test_gate_report.json")
    marker_contract = _optional(root, "official_t27_marker_contract.json")
    store_preflight = _optional(root, "official_t27_store_preflight.json")
    environment_identity = _optional(
        root, "official_environment_identity.json")
    general_context = _optional(root, "official_general_context.json")
    production_stack = _optional(root, "production_stack_environment_preflight.json")
    construction_rehearsals = _optional(root, "construction_rehearsal_report.json")
    construction_failures = _optional(root, "construction_failure_rehearsal.json")
    real_oracle_rehearsal = _optional(root, "real_mode_oracle_rehearsal.json")
    negative_controls = _optional(root, "construction_negative_controls.json")
    policy_controls = _optional(root, "generated_public_policy_controls.json")
    marker_layout_controls = _optional(root, "t27_marker_layout_negative_controls.json")
    evaluation_rehearsals = _optional(root, "evaluation_rehearsal_report.json")
    evaluation_failures = _optional(root, "evaluation_failure_rehearsal.json")
    reproducer = _optional(root, "structural_unsatisfiability_reproducer.json")
    witness = _optional(root, "structural_satisfiability_witness.json")
    freeze = _optional(root, "preconstruction_freeze.json")
    freeze_verify = (verify_freeze(root, freeze) if bool(freeze)
                     else {"status": "UNSTAGED"})

    from .construction import run_publication_leak_gate
    live_leak = run_publication_leak_gate(root, fetch=True)

    checks = {
        # --- frozen predecessor state (§4/§5/§73) ---
        "t27_sealed_construction_state": (
            anchor.get("construction_state") == T27_CONSTRUCTION_STATE
            and anchor.get("attempt") == 1),
        "t27_unspent_permanently_ineligible": (
            anchor.get("official_evaluation_state") ==
            T27_OFFICIAL_EVALUATION_STATE
            and anchor.get("evaluation_attempt") ==
            T27_OFFICIAL_EVALUATION_ATTEMPT
            and anchor.get("eligibility") == T27_OFFICIAL_EVALUATION_ELIGIBILITY),
        "t27_verdict_exact": anchor.get("verdict") == T27_PREDECESSOR_VERDICT,
        "t27_adjudication_commit_bound": (
            adjudication_anchor_ok(root) and T27_ADJUDICATION_COMMIT ==
            "16314c515312e8da86f2b268d788f9aa6b0abd7f"),
        "t26_public_receipt_boundary": (
            t26_receipt.get("state") == "COMPLETE" and
            t26_receipt.get("attempt") == 1 and
            t26_receipt.get("raw_rows_included") is False and
            t26_receipt.get("scenario_bodies_included") is False),
        "t27_private_rows_never_opened": all(
            document.get(key, 0) == 0 for document, key in (
                (qualification, "t27_private_rows_opened"),
                (reproduction, "t27_private_rows_opened"),
                (exclusion, "t27_private_rows_opened"),
            )),
        "candidate_identity_pinned": (
            candidate.get("candidate_commit") == PINNED_CANDIDATE_COMMIT
            and candidate.get("candidate_tree") == PINNED_CANDIDATE_TREE
            and candidate.get("runtime_root") == PINNED_RUNTIME_ROOT
            and candidate.get("candidate_runtime_changes") == 0
            and candidate.get("candidate_changed") is False
            and candidate.get("runtime_root_matches_pinned_successor") is True),
        "terminal_contract": (
            set(contract.get("terminals", [])) == TERMINALS_EXPECTED
            and list(contract.get("replan_triggers", [])) == list(REPLAN_TRIGGERS)
            and contract.get("unknown_provider_status") == "REJECT"
            and contract.get("authority", {}).get("external_action_authority")
            is False
            and contract.get("frozen_before_real_construction") is True),
        # --- design / tokens / registry (§56) ---
        "design_frozen": (
            design.get("family_count") == 16
            and design.get("cases_per_family") == 32
            and design.get("total_real_blind_cases") == 512
            and design.get("families") == list(FAMILIES)
            and design.get("t27_evaluation_ever_run") is False
            and design.get("t27_official_evaluation_permitted_again") is False),
        "construction_token_exact": (
            design.get("construction_token") == CONSTRUCTION_TOKEN
            and design.get("construction_token") ==
            "T28_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"),
        "evaluation_token_exact": (
            design.get("evaluation_token") == EVALUATION_TOKEN
            and design.get("evaluation_token") ==
            "T28_ONE_SHOT_OFFICIAL_EVALUATION"
            and "T27_ONE_SHOT_OFFICIAL_EVALUATION" != EVALUATION_TOKEN),
        "metric_registry_frozen": (
            metrics == metric_registry()
            and set(metrics.get("metrics", {})) == set(FLOORS)
            and len(metrics.get("critical_counters", {})) == 9),
        "nonvacuity_policy_frozen": (
            nonvacuity == nonvacuity_policy()
            and nonvacuity.get("rate_policy") == "FAIL_NONVACUITY"
            and nonvacuity.get("requirements") == dict(NONVACUITY_MINIMUMS)),
        # --- qualification + diagnostics (§53–§58) ---
        "qualification": qualification.get("status") == "PASS",
        "qualification_material_new_and_excluded": (
            qualification.get("material") ==
            "NEW_PUBLIC_SYNTHETIC_PERMANENTLY_EXCLUDED"
            and qualification.get("raw_rows_included") is False
            and qualification_exclusions.get(
                "permanently_excluded_from_real_t28") is True
            and qualification_exclusions.get("scenario_count") == 64
            and len(qualification_exclusions.get("scenario_commitments", [])) == 64),
        "qualification_metric_denominators": all(
            item.get("denominator", 0) > 0
            and item.get("zero_denominator_policy") == "FAIL_NONVACUITY"
            for item in qualification.get("score", {}).get(
                "metrics", {}).values()),
        "fail_nonvacuity_scorer": ZERO_DENOMINATOR_POLICY == "FAIL_NONVACUITY",
        "terminal_contract_recovery": qualification.get("score", {}).get(
            "metrics", {}).get("recovery_success_rate", {}).get("pass") is True,
        "terminal_contract_replan": qualification.get("score", {}).get(
            "metrics", {}).get("replan_correctness_rate", {}).get("pass") is True,
        "terminal_contract_safe_abstention": qualification.get("score", {}).get(
            "metrics", {}).get("safe_abstention_accuracy", {}).get("pass") is True,
        "terminal_matrix": diagnostics.get("terminal_matrix", {}).get(
            "status") == "PASS",
        "verification_matrix": diagnostics.get("verification_matrix", {}).get(
            "status") == "PASS",
        "completion_gate": diagnostics.get("completion_gate", {}).get(
            "status") == "PASS",
        # --- protection / test gate / exposure / leak scan ---
        "t19_protection": (
            protection.get("t19", {}).get("tests", {}).get("status") == "PASS"
            and protection.get("t19", {}).get("authority") == "PROPOSE_ONLY"),
        "t20_protection": (
            protection.get("t20", {}).get("tests", {}).get("status") == "PASS"
            and protection.get("t20", {}).get("authority") ==
            "COORDINATE_INTERNAL_WORK_ONLY"),
        "t22_protection": (
            protection.get("t22", {}).get("passed") == 32
            and protection.get("t22", {}).get("total") == 32),
        "t25_router_protection": (
            protection.get("t25_router", {}).get("floor_count") == 15
            and protection.get("t25_router", {}).get("status") == "PASS"),
        "t25_dispatch_protection": protection.get(
            "t25_dispatch", {}).get("status") == "PASS",
        "t27_official_evaluator_never_invoked": (
            protection.get("t27_official_evaluator_invoked") is False),
        "focused_test_gate": (
            test_gate.get("status") == "PASS"
            and test_gate.get("live_failures", 1) == 0
            and test_gate.get("unknown_failures", 1) == 0
            and test_gate.get("unexplained_skips", 1) == 0
            and test_gate.get("xfails", 1) == 0
            and test_gate.get("deselections", 1) == 0),
        "real_exposure_zero": bool(exposure) and all(
            exposure.get(key, 1) == 0 for key in (
                "t28_real_blind_rows", "t28_real_gold",
                "t28_construction_attempts", "t28_evaluation_attempts",
                "t27_private_rows_opened", "t27_candidate_reruns")),
        "public_leak_scan_zero": (
            leak_scan.get("status") == "PASS"
            and leak_scan.get("blind_blob_count", 1) == 0),
        "live_public_leak_gate": (
            live_leak.get("status") == "PASS"
            and live_leak.get("blind_blob_count", 1) == 0
            and live_leak.get("forbidden_path_count", 1) == 0
            and live_leak.get("official_evaluation_eligible") is True),
        # --- storage (§59–§64) ---
        "private_store_policy": (
            storage == storage_policy()
            and storage.get("store_id") == "T28-STORE-01"
            and storage.get("namespace") == "t28"
            and storage.get("locator_scheme") == "t28-private://"
            and storage.get("construction_ledger_required_now") is False
            and storage.get("evaluation_ledger_required_now") is False),
        "construction_ready_storage_policy": (
            storage_v2 == storage_policy_successor()
            and storage_v2.get("construction_one_shot_required") is True
            and storage_v2.get("evaluation_ledger_required_for_official") is True
            and storage_v2.get("ledger_before_blind_material") is True),
        # --- authenticated historical exclusion (§6–§12) ---
        "nine_dimensional_exclusion": (
            exclusion == policy()
            and exclusion.get("dimensions") == list(DIMENSIONS)
            and exclusion.get("historical_source") ==
            "AUTHENTICATED_PUBLIC_INDEX_PLUS_SEALED_T27_PRIVATE_ORACLE"
            and exclusion.get("required_at_real_construction") is True),
        "construction_ready_exclusion_v2": exclusion_v2 == construction_ready_policy(),
        "authenticated_exclusion_v3": exclusion_v3 == authenticated_construction_policy(),
        "remediated_exclusion_v4": exclusion_v4 == historical_exclusion_policy_v4(),
        "generated_public_dimension_policy_frozen": (
            dimension_policy == generated_public_dimension_policy()
            and dimension_policy.get("schema_version") ==
            GENERATED_PUBLIC_POLICY_SCHEMA
            and set(dimension_policy.get("dimension_classifications", {})) ==
            set(DIMENSIONS)),
        "all_affected_sources_use_frozen_policy": (
            _policy_sources_exact(root)
            and _non_policy_sources_exact(root)),
        "structural_dimensions_empty_exactly_where_authorized":
            _structural_empty(root),
        "identity_content_dimensions_retained": _identity_retained(root),
        "public_historical_source_completeness": (
            public_history.get("required_source_count") ==
            len(REQUIRED_HISTORICAL_SOURCES)
            and {item.get("source_class")
                 for item in public_history.get("sources", [])} ==
            set(REQUIRED_HISTORICAL_SOURCES)),
        "public_history_builder_identity": (
            public_history.get("builder_implementation_identity") ==
            PUBLIC_HISTORY_BUILDER),
        "public_history_aggregate_root_exact": (
            public_history == public_index_report(
                build_authenticated_public_historical_index(root))),
        "old_public_history_root_superseded": (
            supersession == public_index_supersession(
                build_authenticated_public_historical_index(root))
            and supersession.get("superseded_root") == SUPERSEDED_INDEX_ROOT
            and supersession.get("superseded_classification") ==
            "SUPERSEDED_PRE_EXPOSURE"
            and build_authenticated_public_historical_index(root)[
                "public_historical_index_root"] != SUPERSEDED_INDEX_ROOT),
        "t27_public_qualification_exclusion_precedent_recorded": (
            precedent == t27_public_qualification_exclusion_precedent()),
        "t27_sealed_overlap_oracle_bound": (
            exclusion_v3.get("t27_boundary", {}).get("implementation") ==
            "t27_protocol.t28_private_oracle:run_sealed_t27_to_t28_overlap_oracle"
            and exclusion_v3.get("t27_boundary", {}).get(
                "result_artifact") == "T27_TO_T28_OVERLAP_ORACLE_RESULT"),
        "clean_room_author_provenance": (
            exclusion_v3.get("historical_private_row_exposure_to_author") == 0
            and exclusion_v3.get("candidate_execution_on_historical_rows")
            is False),
        "real_fingerprint_sets_unchanged": (
            real_fingerprint_semantics_probe().get("status") == "PASS"),
        "t27_sealed_oracle_still_all_nine_dimension": (
            t27_oracle_nine_dimension_probe().get("status") == "PASS"),
        # --- structural reproducer + witness (§62 remediation) ---
        "old_structural_contradiction_reproduced": (
            reproducer.get("status") == "REPRODUCED"
            and reproducer.get("t27_old_semantics_minimum_overlap") == 33
            and reproducer.get("contract_forced_structural_overlap") is True
            and reproducer.get("remediated_semantics_inherited_for_t28")
            is True
            and reproducer.get("t27_private_rows_opened") == 0
            and reproducer.get("real_blind_rows_authored") == 0),
        "public_satisfiability_witness_zero_overlap": (
            witness.get("status") == "PASS"
            and witness.get("overall_prohibited_overlap") == 0
            and witness.get("scenario_count") == 512
            and witness.get("family_count") == 16
            and witness.get("capabilities_exercised") == 12
            and witness.get("deterministic") is True
            and witness.get("reused_public_blind_material") is False
            and witness.get("t27_private_rows_opened") == 0
            and witness.get("real_blind_rows_authored") == 0),
        # --- official T27 marker compatibility (§35–§43) ---
        "t27_official_marker_contract": (
            marker_contract.get("status") == "PASS"
            and marker_contract.get("marker_path_exact") is True
            and marker_contract.get("marker_schema_exact") is True
            and marker_contract.get("legacy_marker_path_accepted") is False
            and marker_contract.get("disposable_layout_mirrors_official")
            is True),
        "t27_real_store_metadata_preflight": (
            store_preflight.get("status") == "PASS"
            and store_preflight.get("official_commitment_scope") == "OFFICIAL_T27"
            and store_preflight.get("t27_store_identity") == "T27-STORE-01"
            and store_preflight.get("t27_official_commitments_exact") is True
            and store_preflight.get("t27_construction_state") == "SEALED"
            and store_preflight.get("t27_construction_attempt") == 1
            and store_preflight.get("t27_official_evaluation_state") ==
            T27_OFFICIAL_EVALUATION_STATE
            and store_preflight.get("t27_official_evaluation_attempt") == 0
            and store_preflight.get("t27_official_evaluation_eligibility") ==
            T27_OFFICIAL_EVALUATION_ELIGIBILITY
            and store_preflight.get("t27_evaluation_event_count") == 0
            and store_preflight.get("t27_official_evaluation_artifacts_absent")
            is True),
        "t27_metadata_only_read_boundary": all(
            store_preflight.get(key, 1) == 0 for key in (
                "t27_private_rows_read", "t27_gold_rows_read",
                "t27_raw_output_rows_read", "t27_scored_rows_read",
                "t27_candidate_reruns", "outside_boundary_private_rows_exposed"))
            and store_preflight.get("t27_blind_rows_deserialized", 1) == 0
            and store_preflight.get("t28_fingerprint_derivation_invoked")
            is False,
        # --- environment staging (§20–§29) ---
        "official_environment_identity_staged": (
            _environment_identity_ok(environment_identity)),
        "official_general_context_bound": (
            general_context.get("schema_version") ==
            "t28-official-general-context-identity-v1"
            and general_context.get("artifact") ==
            "T28_OFFICIAL_GENERAL_CONTEXT_IDENTITY"
            and len(general_context.get("identity_root", "")) == 64
            and general_context.get("t26_predecessor_document", {}).get(
                "identity_root") is not None),
        "production_stack_environment_preflight": (
            production_stack.get("status") == "PASS"
            and production_stack.get("real_environment") is True
            and production_stack.get("candidate_executions") == 0
            and production_stack.get("checkpoints_written") == 0
            and production_stack.get("runner_count") == 0
            and production_stack.get("model_identity_verified") is True),
        # --- construction rehearsals (§44–§49) ---
        "construction_rehearsals_2": (
            construction_rehearsals.get("status") == "PASS"
            and len(construction_rehearsals.get("runs", [])) == 2
            and construction_rehearsals.get("semantic_equivalence") is True),
        "construction_ledger_hash_chain": all(
            run.get("state_sequence", []) == [
                "LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS",
                "MANIFESTED", "SEALED"]
            for run in construction_rehearsals.get("runs", [])),
        "construction_rehearsal_store_verify": all(
            run.get("store_status") == "PASS"
            and run.get("state") == "SEALED"
            and run.get("receipt_blind_content_included") is False
            and run.get("leak_gate_status") == "PASS"
            for run in construction_rehearsals.get("runs", [])),
        "construction_rehearsal_nonvacuity": all(
            run.get("designated_counts", {}).get(name, 0) >= minimum
            for run in construction_rehearsals.get("runs", [])
            for name, minimum in dict(NONVACUITY_MINIMUMS).items()),
        "combined_historical_exclusion_root": all(
            isinstance(run.get("combined_historical_exclusion_root"), str)
            and len(run["combined_historical_exclusion_root"]) == 64
            for run in construction_rehearsals.get("runs", [])),
        "construction_failure_semantics": (
            construction_failures.get("status") == "PASS"
            and construction_failures.get("post_ledger_failure_recorded")
            is True
            and construction_failures.get("retry_refused") is True
            and construction_failures.get("one_shot") == "SPENT"),
        "real_mode_oracle_rehearsal": (
            real_oracle_rehearsal.get("status") == "PASS"
            and real_oracle_rehearsal.get("store_authenticated") is True
            and real_oracle_rehearsal.get("commitments_exact") is True
            and real_oracle_rehearsal.get("real_mode_not_synthetic") is True
            and real_oracle_rehearsal.get("overall_prohibited_overlap") == 0
            and real_oracle_rehearsal.get("candidate_executions") == 0),
        "negative_controls": (
            negative_controls.get("status") == "PASS"
            and set(negative_controls.get("controls", {})) ==
            set(NEGATIVE_CONTROL_IDS)
            and negative_controls.get("control_count", 0) >= 72),
        "construction_implementation": (
            root / "t28_protocol/construction.py").is_file(),
        "exclusive_construction_ledger": negative_controls.get(
            "controls", {}).get("duplicate_ledger", {}).get("status") == "PASS",
        "construction_one_shot_marker": negative_controls.get(
            "controls", {}).get("attempt_2", {}).get("status") == "PASS",
        "exclusion_contract_gate_coverage": (
            len(CONTRACT_LEAF_IDS) > 45 and len(CONSTRUCTION_GATE_IDS) > 34),
        "construction_contract_leaf_enumerator":
            construction_contract().get("leaf_count") == len(CONTRACT_LEAF_IDS),
        # --- evaluation readiness (§19–§39, §44–§52) ---
        "evaluation_implementation": (root / "t28_protocol/evaluation.py").is_file(),
        "evaluation_ledger_state_machine": list(EVALUATION_STATES) == [
            "STARTED", "EXECUTED", "SCORED", "COMPLETE", "FAILED"],
        "evaluation_rehearsals_2": (
            evaluation_rehearsals.get("status") == "PASS"
            and len(evaluation_rehearsals.get("runs", [])) == 2
            and evaluation_rehearsals.get("semantic_equivalence") is True),
        "evaluation_rehearsal_ordering": all(
            run.get("state_sequence") == [
                "STARTED", "EXECUTED", "SCORED", "COMPLETE"]
            and run.get("ordering_binding_precedes_blind_reads") is True
            and run.get("ordering_blind_inputs_before_gold") is True
            and run.get("ordering_reads_before_workspace") is True
            for run in evaluation_rehearsals.get("runs", [])),
        "evaluation_rehearsal_gold_firewall": (
            (evaluation_rehearsals.get("runs") or [{}])[0].get(
                "gold_firewall_projected_rows") ==
            (evaluation_rehearsals.get("runs") or [{}])[0].get(
                "scenario_count")),
        "evaluation_rehearsal_fail_nonvacuity": all(
            run.get("denominators_nonzero") is True
            for run in evaluation_rehearsals.get("runs", [])),
        "evaluation_rehearsal_identity_shared": bool(
            evaluation_rehearsals.get("identities_shared_with_real_mode")),
        "public_leak_preflight_in_rehearsal": (
            evaluation_rehearsals.get("public_leak_preflight", {}).get(
                "status") == "PASS"
            and evaluation_rehearsals.get("public_leak_preflight", {}).get(
                "blind_blob_count", 1) == 0),
        "evaluation_failure_semantics": (
            evaluation_failures.get("status") == "PASS"
            and evaluation_failures.get("post_ledger_failure_recorded") is True
            and evaluation_failures.get("one_shot") == "SPENT"
            and all(item.get("injected") and
                    item.get("ledger_state") == "FAILED" and
                    item.get("retry_refused")
                    for item in
                    evaluation_failures.get("failure_phases", []))),
        # --- freeze + authorization flags (§68–§69) ---
        "preconstruction_freeze": (
            bool(freeze) and freeze_verify.get("status") == "PASS"
            and freeze.get("real_construction_authorized") is False
            and freeze.get("real_evaluation_authorized") is False
            and freeze.get("real_blind_rows") == 0
            and freeze.get("real_gold_rows") == 0),
        "preconstruction_authorization_flags": (
            freeze.get("real_construction_authorized") is False
            and freeze.get("real_evaluation_authorized") is False
            and freeze.get("candidate_runtime_changes") == 0),
        # --- production graph (§56) ---
        "production_graph_complete": _production_graph_complete(root),
        "authority_graph_complete": _authority_graph_complete(root),
        "construction_ledger_absent_project_side": not (
            root / "evaluations/t28/construction_ledger.json").exists(),
        "evaluation_ledger_absent_project_side": not (
            root / "evaluations/t28/evaluation_ledger.json").exists(),
    }
    return {
        "schema_version": "t28-doctor-v1", "artifact": "T28_PROTOCOL_DOCTOR",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "check_count": len(checks),
        "failed_checks": sorted(
            name for name, passed in checks.items() if not passed),
        "t27_private_paths_probed": 1, "t27_private_rows_read": 0,
        "t27_gold_rows_read": 0, "t27_candidate_reruns": 0,
        "t27_candidate_executions": 0,
    }


def adjudication_anchor_ok(root: Path) -> bool:
    document = json.loads(
        (root / "evaluations/t27/"
         "T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json")
        .read_text(encoding="utf-8"))
    return (document.get("schema_version", "").startswith(
        "t27-official-evaluation-eligibility-adjudication"))


def _policy_sources_exact(root: Path) -> bool:
    index = build_authenticated_public_historical_index(root)
    sources = {source["source_class"]: source for source in index["sources"]}
    expected_policy = generated_public_dimension_policy()
    return all(
        sources[source_class].get("dimension_policy_schema") ==
        GENERATED_PUBLIC_POLICY_SCHEMA
        and sources[source_class].get("dimension_policy_root") ==
        expected_policy["dimension_policy_root"]
        for source_class in GENERATED_PUBLIC_SOURCES)


def _non_policy_sources_exact(root: Path) -> bool:
    index = build_authenticated_public_historical_index(root)
    sources = {source["source_class"]: source for source in index["sources"]}
    return all(
        "dimension_policy_schema" not in source
        and "dimension_policy_root" not in source
        for source_class, source in sources.items()
        if source_class not in GENERATED_PUBLIC_SOURCES)


def _structural_empty(root: Path) -> bool:
    index = build_authenticated_public_historical_index(root)
    sources = {source["source_class"]: source for source in index["sources"]}
    structural = frozenset(GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS)
    return all(
        not sources[source_class]["dimensions"][name]["historical_population"]
        and sources[source_class]["dimensions"][name]["applicable"] is False
        and sources[source_class]["dimensions"][name]["empty_contract"] ==
        f"{source_class}:{name}:STRUCTURAL_SHARED_FROZEN_EMPTY"
        for source_class in GENERATED_PUBLIC_SOURCES
        for name in (name for name, classification in
                     GENERATED_PUBLIC_DIMENSION_CLASSIFICATIONS.items()
                     if classification == "STRUCTURAL_SHARED_FROZEN_EMPTY")
        if name in structural)


def _identity_retained(root: Path) -> bool:
    index = build_authenticated_public_historical_index(root)
    sources = {source["source_class"]: source for source in index["sources"]}
    retained = frozenset(DIMENSIONS) - frozenset(
        GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS)
    return all(
        sources[source_class]["dimensions"][name]["applicable"] is True
        and sources[source_class]["dimensions"][name]["historical_population"] > 0
        for source_class in (
            "T21_T21R_HISTORICAL",
            "T27_PUBLIC_QUALIFICATION", "T28_PUBLIC_QUALIFICATION")
        for name in retained if name in sources[source_class]["dimensions"])
    # T26_SEALED_EVALUATED is intentionally NOT in the required population set:
    # its public receipt contains no raw rows and no scenario bodies
    # (raw_rows_included False / scenario_bodies_included False), so its
    # content dimensions are truthfully empty in the public index.  The sealed
    # T26 store is authenticated machine-only and is covered by the
    # structural/T27-overlap oracles, not by publishable historical content.


def _environment_identity_ok(document: dict) -> bool:
    import re
    hex64 = re.compile(r"[0-9a-f]{64}")
    required = {
        "schema_version", "artifact", "classification", "environment_root",
        "rehearsal_environment_root",
    }
    if not isinstance(document, dict) or not required <= set(document):
        return False
    return (all(hex64.fullmatch(document[key])
                for key in ("environment_root",
                            "rehearsal_environment_root"))
            and document["schema_version"] ==
            "t28-official-environment-identity-v1"
            and document["artifact"] ==
            "T28_OFFICIAL_ENVIRONMENT_IDENTITY"
            and document["environment_root"] !=
            document["rehearsal_environment_root"])


def _production_graph_complete(root: Path) -> bool:
    graph = _read(root, "production_graph.json")
    expected = production_graph()
    return (graph == expected
            and graph.get("missing_producers") == 0
            and graph.get("dangling_edges") == 0
            and graph.get("production_stubs") == 0
            and graph.get("evaluation_ledger_precedes") ==
            ["blind_reader", "workspace_factory", "official_runner"])


def _authority_graph_complete(root: Path) -> bool:
    graph = _read(root, "authority_graph.json")
    evaluator_flags = {
        node["authority"]: (node["gold_access"],
                            node["candidate_execution_authority"])
        for node in graph.get("nodes", {}).values()
    }
    return (graph.get("candidate_gold_access") is False
            and graph.get("construction_candidate_execution_authority")
            is False
            and graph.get("external_action_authority") is False
            and graph.get("private_evaluator_authority") ==
            "SCORE_PRIVATE_ONCE"
            and graph["nodes"]["scorer"]["gold_access"] is True
            and graph["nodes"]["official_runner"][
                "candidate_execution_authority"] is True
            and graph["nodes"]["environment_builder"]["gold_access"] is False
            and graph["nodes"]["blind_reader"]["gold_access"] is False
            and graph["nodes"]["gold_firewall"]["authority"] ==
            "PROJECT_CANDIDATE_INPUT_ONLY")