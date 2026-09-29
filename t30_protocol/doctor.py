"""Fail-closed public T30 preconstruction doctor."""
from __future__ import annotations

import inspect
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
                           FREEZE_PATH_NEGATIVE_CONTROL_IDS,
                           NEGATIVE_CONTROL_IDS, construction_contract,
                           official_marker_contract_report,
                           real_fingerprint_semantics_probe,
                           t27_oracle_nine_dimension_probe)
from .evaluation import (EVALUATION_READINESS_ITEMS, EVALUATION_STATES,
                         runner_identity)
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
from .freeze import (FREEZE_LOADER_ID, PINNED_CANDIDATE_COMMIT,
                     PINNED_CANDIDATE_TREE, PINNED_RUNTIME_ROOT,
                     T29_PREDECESSOR_STATUS_PATH, EXCLUDED,
                     T27_ADJUDICATION_COMMIT, T30_PRECONSTRUCTION_FREEZE_PATH,
                     load_preconstruction_freeze, verify_freeze)
from .scorer import ZERO_DENOMINATOR_POLICY
from .store import storage_policy_successor
from .contract import metric_registry, nonvacuity_policy, production_graph, \
    storage_policy

TERMINALS_EXPECTED = {
    "COMPLETE", "PARTIAL", "INSUFFICIENT_EVIDENCE", "BLOCKED",
    "BUDGET_EXHAUSTED", "UNAVAILABLE_CAPABILITY", "SECURITY_REFUSAL", "ERROR",
}

# §45: frozen predecessor one-shot tokens (read-only frozen imports); the T30
# design tokens must never equal any of them.
from t27_protocol.contract import (CONSTRUCTION_TOKEN as _T27_CONSTRUCTION_TOKEN,
                                   EVALUATION_TOKEN as _T27_EVALUATION_TOKEN)
from t28_protocol.contract import (CONSTRUCTION_TOKEN as _T28_CONSTRUCTION_TOKEN,
                                   EVALUATION_TOKEN as _T28_EVALUATION_TOKEN)

# The eleven official evaluate_official wrapper refusal controls staged by the
# wrapper-refusal rehearsal (§21).
_WRAPPER_REFUSAL_CONTROL_IDS = frozenset({
    "wrong_predecessor_report_schema", "missing_predecessor_anchor",
    "wrong_store_commitment", "wrong_candidate", "wrong_freeze",
    "public_leak", "missing_production_adapter", "wrong_environment_identity",
    "existing_evaluation_marker", "real_refuses_tagged_disposable",
    "rehearsal_refuses_untagged_official",
})


def _preconstruction_leaf_count() -> int:
    from .evaluation import PRECONSTRUCTION_CONTRACT_LEAF_IDS
    return len(PRECONSTRUCTION_CONTRACT_LEAF_IDS)


_PRECONSTRUCTION_LEAVES = _preconstruction_leaf_count()


def _read(root: Path, name: str) -> dict:
    return json.loads((root / "evaluations" / "t30" / name).read_text(
        encoding="utf-8"))


def _optional(root: Path, name: str) -> dict:
    path = root / "evaluations" / "t30" / name
    return (json.loads(path.read_text(encoding="utf-8"))
            if path.is_file() else {})


def run_doctor(root: Path) -> dict:
    """Verify every staged T30 preconstruction artifact; FAIL=0 required."""
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
    anchor_t27 = _optional(root, "historical_anchor_t27.json")
    anchor_t28 = _optional(root, "historical_anchor_t28.json")
    reproduction = _read(root, "T28_PUBLIC_ROOT_CAUSE_REPRODUCTION.json")
    design = _read(root, "prospective_design.json")
    qualification_exclusions = _read(root, "qualification_exclusions.json")
    exposure = _optional(root, "real_exposure.json")
    leak_scan = _optional(root, "public_leak_scan.json")
    test_gate = _optional(root, "test_gate_report.json")
    marker_contract = _optional(root, "official_t27_marker_contract.json")
    environment_identity = _optional(
        root, "official_environment_identity.json")
    general_context = _optional(root, "official_general_context.json")
    production_stack = _optional(
        root, "production_stack_environment_preflight.json")
    construction_rehearsals = _optional(root, "construction_rehearsal_report.json")
    construction_failures = _optional(root, "construction_failure_rehearsal.json")
    real_oracle_rehearsal = _optional(root, "real_mode_oracle_evidence.json")
    negative_controls = _optional(root, "construction_negative_controls.json")
    policy_controls = _optional(root, "generated_public_policy_controls.json")
    marker_layout_controls = _optional(root, "t27_marker_layout_negative_controls.json")
    wrapper_refusals = _optional(root, "wrapper_refusal_controls_evidence.json")
    preledger_refusals = _optional(
        root, "evaluation_preledger_refusals_evidence.json")
    evaluation_rehearsals = _optional(
        root, "evaluation_wrapper_rehearsal_evidence.json")
    evaluation_failures = _optional(
        root, "evaluation_failure_rehearsal_evidence.json")
    anchor_controls = _optional(
        root, "historical_anchor_controls_evidence.json")
    contract_audit = _optional(root, "preconstruction_contract.json")
    readiness_gate = _optional(root, "evaluation_readiness_gate.json")
    reproducer = _optional(root, "structural_unsatisfiability_reproducer.json")
    witness = _optional(root, "structural_satisfiability_witness.json")
    freeze = _optional(root, "preconstruction_freeze.json")
    freeze_verify = (verify_freeze(root, freeze) if bool(freeze)
                     else {"status": "UNSTAGED"})
    wrapper_rehearsal = _optional(root, "real_entrypoint_rehearsal.json")
    freeze_path_controls = _optional(
        root, "freeze_path_negative_controls.json")
    t29_status = _optional(root, "t29_predecessor_status.json")

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
        "t27_t28_private_rows_never_opened": all(
            document.get(key, 1) == 0 for document, key in (
                (qualification, "t27_private_rows_opened"),
                (reproduction, "t27_private_rows_opened"),
                (reproduction, "t27_candidate_reruns"),
                (exclusion, "t27_private_rows_opened"),
            )) and reproduction.get("t28_private_material_parsed") is False,
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
            "T30_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"),
        "evaluation_token_exact": (
            design.get("evaluation_token") == EVALUATION_TOKEN
            and design.get("evaluation_token") ==
            "T30_ONE_SHOT_OFFICIAL_EVALUATION"
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
                "permanently_excluded_from_real_t30") is True
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
                "t30_real_blind_rows", "t30_real_gold",
                "t30_construction_attempts", "t30_evaluation_attempts",
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
            and storage.get("store_id") == "T30-STORE-01"
            and storage.get("namespace") == "t30"
            and storage.get("locator_scheme") == "t30-private://"
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
        "t27_t28_historical_boundary_retained": (
            exclusion_v3.get("t27_boundary", {}).get("implementation") ==
            "t27_protocol.t28_private_oracle:run_sealed_t27_to_t28_overlap_oracle"
            and exclusion_v3.get("t27_boundary", {}).get(
                "result_artifact") == "T27_TO_T28_OVERLAP_ORACLE_RESULT"),
        # --- §8/§9 sealed DUAL overlap oracle T27→T30 AND T28→T30 ---
        "t27_sealed_overlap_oracle_bound": (
            real_oracle_rehearsal.get("t27_store_authenticated") is True
            and real_oracle_rehearsal.get("t27_commitments_exact") is True),
        "t28_sealed_overlap_oracle_bound": (
            real_oracle_rehearsal.get("t28_store_authenticated") is True
            and real_oracle_rehearsal.get("t28_commitments_exact") is True),
        "t30_dual_overlap_oracle_implementation_bound":
            _dual_oracle_implementation_bound(root, real_oracle_rehearsal),
        "clean_room_author_provenance": (
            exclusion_v3.get("historical_private_row_exposure_to_author") == 0
            and exclusion_v3.get("candidate_execution_on_historical_rows")
            is False),
        "real_fingerprint_sets_unchanged": (
            real_fingerprint_semantics_probe().get("status") == "PASS"),
        "t27_sealed_oracle_still_all_nine_dimension": (
            t27_oracle_nine_dimension_probe().get("status") == "PASS"),
        # --- T28 root-cause reproducer (§11; replaces the T27-era structural
        # reproducer/witness pair whose real bindings arrive on the authorized
        # real-construction pass as explicitly tagged disposable stand-ins) ---
        "t28_public_root_cause_reproduction_bound": (
            reproduction.get("status") ==
            "T28_FROZEN_PREFLIGHT_KEY_SHAPE_DEFECT_REPRODUCED"
            and reproduction.get("reproduced") is True
            and reproduction.get("defect_class") ==
            "FROZEN_PREFLIGHT_KEY_SHAPE_DEFECT"
            and reproduction.get("classification") == "PUBLIC_SAFE"
            and reproduction.get("real_one_shot_states_touched") is False
            and reproduction.get("t27_private_rows_opened") == 0
            and reproduction.get("t28_private_material_parsed") is False),
        "structural_reproducer_placeholder_tagged": (
            reproducer.get("schema_version") ==
            "t30-standin-public-placeholder-v1"
            and reproducer.get("classification") == "PUBLIC_SAFE"
            and reproducer.get("experiment") == "t30"
            and reproducer.get("explicitly_tagged_disposable_substitute")
            is True
            and bool(reproducer.get("real_binding"))),
        "structural_witness_placeholder_tagged": (
            witness.get("schema_version") ==
            "t30-standin-public-placeholder-v1"
            and witness.get("classification") == "PUBLIC_SAFE"
            and witness.get("experiment") == "t30"
            and witness.get("explicitly_tagged_disposable_substitute") is True
            and bool(witness.get("real_binding"))),
        # --- official T27 marker compatibility (§35–§43) ---
        "t27_official_marker_contract": (
            marker_contract.get("status") == "PASS"
            and marker_contract.get("marker_path_exact") is True
            and marker_contract.get("marker_schema_exact") is True
            and marker_contract.get("legacy_marker_path_accepted") is False
            and marker_contract.get("disposable_layout_mirrors_official")
            is True),
        # --- official T27 marker compatibility (§35–§43) ---
        "t27_official_marker_contract": (
            marker_contract.get("status") == "PASS"
            and marker_contract.get("marker_path_exact") is True
            and marker_contract.get("marker_schema_exact") is True
            and marker_contract.get("legacy_marker_path_accepted") is False
            and marker_contract.get("disposable_layout_mirrors_official")
            is True),
        # §35: the REAL official T27 store is preflighted machine-only
        # (metadata only) inside the sealed dual oracle rehearsal — the
        # staged REAL-mode evidence binds the store identity and terminal
        # commitments; the disposable-standin authentication path is proven
        # by the real-entrypoint rehearsal.
        "t27_real_store_metadata_preflight": (
            real_oracle_rehearsal.get("status") == "PASS"
            and real_oracle_rehearsal.get("t27_store_authenticated") is True
            and real_oracle_rehearsal.get("t27_commitments_exact") is True
            and anchor_t27.get("construction_state") == "SEALED"
            and anchor_t27.get("construction_attempt") == 1
            and anchor_t27.get("evaluation_state") ==
            T27_OFFICIAL_EVALUATION_STATE
            and anchor_t27.get("evaluation_attempt") == 0
            and anchor_t27.get("evaluation_eligibility") ==
            T27_OFFICIAL_EVALUATION_ELIGIBILITY
            and anchor_t27.get("store_authenticated") is True
            and anchor_t27.get("private_rows_read", 1) == 0
            and wrapper_rehearsal.get(
                "t27_metadata_authentication_reached") is True),
        "t27_metadata_only_read_boundary": (
            anchor_t27.get("private_rows_read", 1) == 0
            and real_oracle_rehearsal.get(
                "outside_boundary_private_rows_exposed", 1) == 0
            and real_oracle_rehearsal.get("candidate_executions", 1) == 0
            and reproduction.get("t27_candidate_reruns", 1) == 0
            and wrapper_rehearsal.get("t27_private_rows_read", 1) == 0
            and wrapper_rehearsal.get("t27_candidate_reruns", 1) == 0
            and wrapper_rehearsal.get("real_construction_attempts", 1) == 0
            and wrapper_rehearsal.get("real_evaluation_attempts", 1) == 0
            and wrapper_rehearsal.get("disposable_sealed") is True),
        # --- environment staging (§20–§29) ---
        "official_environment_identity_staged": (
            _environment_identity_ok(environment_identity)),
        "official_general_context_bound": (
            general_context.get("schema_version") ==
            "t30-official-general-context-identity-v1"
            and general_context.get("artifact") ==
            "T30_OFFICIAL_GENERAL_CONTEXT_IDENTITY"
            and len(general_context.get("identity_root", "")) == 64
            and general_context.get("t26_predecessor_document", {}).get(
                "identity_root") is not None),
        # §25/§26/§27: the REAL production environment root plus the model
        # hydration preflight are preconstruction artifacts — staged with
        # real identities on a production-capable host (candidate executions
        # = 0, no real blind data, no placeholders).
        "production_stack_hydration_preflight": (
            production_stack.get("status") == "PASS"
            and production_stack.get("real_environment") is True
            and production_stack.get("candidate_executions", 1) == 0
            and production_stack.get("checkpoints_written", 1) == 0
            and production_stack.get("runner_count", 1) == 0
            and production_stack.get("model_identity_verified") is True
            and production_stack.get("model_stack_loadable", 1) is True
            and production_stack.get("t27_private_rows_read", 1) == 0
            and production_stack.get("t28_private_material_parsed", True)
            is False
            and production_stack.get("real_blind_rows", 1) == 0),
        # §45: production/model-stack hydration before the separate real
        # construction authorization must fail closed.  At preconstruction
        # the model stack is NOT authorized to run the candidate; hydration
        # is proven only by the §27 loadable preflight (zero executions) and
        # the wrapper rehearsals on disposable stand-ins via the gate.
        "production_environment_and_hydration_gate": (
            bool(readiness_gate)
            and readiness_gate.get("status") == "GATE_GREEN"
            and set(readiness_gate.get("items", {})) ==
            set(EVALUATION_READINESS_ITEMS)
            and readiness_gate.get("items", {}).get(
                "production_environment_pass") is True
            and readiness_gate.get("items", {}).get(
                "model_hydration_pass") is True),
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
            and real_oracle_rehearsal.get("predecessors") == ["t27", "t28"]
            and real_oracle_rehearsal.get("real_mode_not_synthetic") is True
            and real_oracle_rehearsal.get("overall_prohibited_overlap") == 0
            and real_oracle_rehearsal.get("candidate_executions") == 0
            and real_oracle_rehearsal.get(
                "outside_boundary_private_rows_exposed", 1) == 0
            and real_oracle_rehearsal.get("prospective_root_exact") is True
            and isinstance(real_oracle_rehearsal.get("dual_oracle_root"), str)
            and len(real_oracle_rehearsal.get("dual_oracle_root", "")) == 64),
        "negative_controls": (
            negative_controls.get("status") == "PASS"
            and set(negative_controls.get("controls", {})) ==
            set(NEGATIVE_CONTROL_IDS)
            and negative_controls.get("control_count", 0) >= 72),
        "construction_implementation": (
            root / "t30_protocol/construction.py").is_file(),
        "exclusive_construction_ledger": negative_controls.get(
            "controls", {}).get("duplicate_ledger", {}).get("status") == "PASS",
        "construction_one_shot_marker": negative_controls.get(
            "controls", {}).get("attempt_2", {}).get("status") == "PASS",
        "exclusion_contract_gate_coverage": (
            len(CONTRACT_LEAF_IDS) > 45 and len(CONSTRUCTION_GATE_IDS) > 34),
        "construction_contract_leaf_enumerator":
            construction_contract().get("leaf_count") == len(CONTRACT_LEAF_IDS),
        # --- evaluation readiness (§19–§39, §44–§52) ---
        "evaluation_implementation": (root / "t30_protocol/evaluation.py").is_file(),
        "evaluation_ledger_state_machine": list(EVALUATION_STATES) == [
            "STARTED", "EXECUTED", "SCORED", "COMPLETE", "FAILED"],
        "evaluation_rehearsals_2": (
            evaluation_rehearsals.get("status") == "PASS"
            and len(evaluation_rehearsals.get("runs", [])) == 2
            and evaluation_rehearsals.get("semantic_equivalence") is True
            and evaluation_rehearsals.get(
                "wrapper_invocations_on_disposable_standins") == 2
            # §45: a rehearsal that touched the official real evaluator (or a
            # single invocation anywhere) is a protocol violation.
            and evaluation_rehearsals.get(
                "official_real_evaluator_invocations", 1) == 0
            and evaluation_rehearsals.get("real_blind_rows", 1) == 0
            and evaluation_rehearsals.get("real_gold_rows", 1) == 0
            and evaluation_rehearsals.get("real_evaluation_attempts", 1) == 0),
        "evaluation_rehearsal_ordering": all(
            run.get("state_sequence") == [
                "STARTED", "EXECUTED", "SCORED", "COMPLETE"]
            and run.get("ordering_binding_precedes_blind_reads") is True
            and run.get("ordering_strictly_increasing") is True
            and run.get("ordering_blind_inputs_before_gold") is True
            and run.get("ordering_reads_before_workspace") is True
            and run.get("ordering_workspace_precedes_candidate_execution")
            is True
            for run in evaluation_rehearsals.get("runs", [])),
        "evaluation_rehearsal_gold_firewall": all(
            run.get("gold_firewall_projected_rows") == run.get(
                "scenario_count") and run.get("scenario_count") == 512
            for run in evaluation_rehearsals.get("runs", [])),
        "evaluation_rehearsal_fail_nonvacuity": all(
            run.get("denominators_nonzero") is True
            and run.get("fail_nonvacuity_policy") is True
            for run in evaluation_rehearsals.get("runs", [])),
        # §45: the rehearsal must execute the actual evaluate_official wrapper
        # (not only _evaluate_once, not only score_suite, not only preflight
        # helpers) — bound by staged qualified identity AND live introspection.
        "evaluation_wrapper_only_rehearsal": (
            all(run.get("wrapper_qualified_id") ==
                "t30_protocol.evaluation:evaluate_official"
                and run.get("mode") == "REAL_REHEARSAL"
                for run in evaluation_rehearsals.get("runs", []))
            and _wrapper_rehearsal_sources_bound(root)
            and wrapper_refusals.get("wrapper_entrypoint") ==
            "t30_protocol.evaluation:evaluate_official"),
        "construct_real_wrapper_only_rehearsal": (
            wrapper_rehearsal.get("status") == "PASS"
            and wrapper_rehearsal.get("oracle_mode") == "REAL_REHEARSAL"
            and wrapper_rehearsal.get("oracle_commitments_exact") is True
            and wrapper_rehearsal.get("construct_once_reached") is True
            and _construct_real_wrapper_source_bound(root)),
        "public_leak_preflight_in_rehearsal": (
            evaluation_rehearsals.get("public_leak_preflight", {}).get(
                "status") == "PASS"
            and evaluation_rehearsals.get("public_leak_preflight", {}).get(
                "blind_blob_count", 1) == 0),
        # §45: pre-ledger blind deserialization and pre-ledger workspace
        # creation must fail closed → the ledger-absence rehearsal refuses in
        # every scenario with zero blind rows parsed and UNSPENT one-shot.
        "evaluation_preledger_refusals_green": (
            preledger_refusals.get("status") == "PASS"
            and {item.get("scenario")
                 for item in preledger_refusals.get("scenarios", [])} ==
            {"historical_anchor_schema_invalid", "store_verification_failure",
             "public_leak", "model_hydration_failure", "environment_mismatch"}
            and len(preledger_refusals.get("scenarios", [])) == 5
            and all(item.get("refused") is True and item.get("passed") is True
                    and item.get("blind_rows_parsed", 1) == 0
                    and item.get("evaluation_ledger_absent") is True
                    and item.get("evaluation_marker_absent") is True
                    and item.get("evaluation_one_shot") == "UNSPENT"
                    for item in preledger_refusals.get("scenarios", []))
            and preledger_refusals.get("blind_rows_parsed", 1) == 0
            and preledger_refusals.get(
                "evaluation_ledger_absent_in_every_scenario") is True
            and preledger_refusals.get("one_shot") == "UNSPENT"
            and not (root / "evaluations/t30/evaluation_ledger.json").exists()),
        "wrapper_refusal_controls_green": (
            wrapper_refusals.get("status") == "PASS"
            and {item.get("control")
                 for item in wrapper_refusals.get("controls", [])} ==
            set(_WRAPPER_REFUSAL_CONTROL_IDS)
            and len(wrapper_refusals.get("controls", [])) ==
            len(_WRAPPER_REFUSAL_CONTROL_IDS)
            and all(item.get("refused") is True and item.get("passed") is True
                    and item.get("blind_rows_parsed", 1) == 0
                    and item.get("evaluation_ledger_absent") is True
                    # The official T30 one-shot is UNSPENT in every control;
                    # the existing_evaluation_marker control intentionally
                    # pre-positions a DISPOSABLE stand-in marker, so its
                    # scenario reports that stand-in state ("SPENT") — the
                    # official token remains untracked below.
                    and (item.get("evaluation_one_shot") == "UNSPENT"
                         or item.get("control") == "existing_evaluation_marker")
                    for item in wrapper_refusals.get("controls", []))
            and wrapper_refusals.get("real_evaluation_attempts", 1) == 0),
        # §45: historical-anchor schema drift / raw report indexing without a
        # validator must fail closed → live anchor validation plus the control
        # rehearsal evidence.
        "historical_anchor_drift_controls": (
            anchor_controls.get("status") == "PASS"
            and (anchor_controls.get("schema_exact") is True
                 or (isinstance(anchor_controls.get("schema_exact"), dict)
                     and all(value is True for value in
                             anchor_controls["schema_exact"].values())))
            and anchor_controls.get("roundtrip_exact") is True
            and anchor_controls.get("consumer_validated") is True
            and anchor_controls.get("mutation_refusals_failed", 1) == 0
            and anchor_controls.get("mutation_control_status") == "PASS"
            and anchor_controls.get("raw_indexing_consumers", 1) == 0
            and anchor_controls.get("t27_private_rows_read", 1) == 0
            and anchor_controls.get("t28_private_rows_read", 1) == 0
            and all(isinstance(item_anch_root, str) and
                    len(item_anch_root) == 64 for item_anch_root in
                    (anchor_controls.get(
                        "official_anchor_commitment_roots", {})
                     or {}).values())),
        "evaluation_failure_semantics": (
            evaluation_failures.get("status") == "PASS"
            and evaluation_failures.get("post_ledger_failure_recorded") is True
            and evaluation_failures.get("one_shot") ==
            "SPENT_ON_DISPOSABLE_STANDINS"
            and evaluation_failures.get("real_evaluation_attempts", 1) == 0
            and {item.get("phase") for item in
                 evaluation_failures.get("failure_phases", [])} ==
            {"STARTED", "BLIND_READ", "EXECUTED", "SCORED"}
            and len(evaluation_failures.get("failure_phases", [])) == 4
            and all(item.get("injected") and
                    item.get("ledger_state") == "FAILED" and
                    item.get("retry_refused") and
                    item.get("marker_spent") is True
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
        # §48: zero attempts and zero real rows bound in the freeze itself.
        "freeze_real_attempt_counters_zero": (
            freeze.get("real_construction_attempts", 1) == 0
            and freeze.get("real_evaluation_attempts", 1) == 0),
        # §45: T27/T28 one-shot tokens must never be reused by T30.
        "predecessor_tokens_not_reused": (
            design.get("construction_token") == CONSTRUCTION_TOKEN
            and design.get("evaluation_token") == EVALUATION_TOKEN
            and CONSTRUCTION_TOKEN != _T27_CONSTRUCTION_TOKEN
            and CONSTRUCTION_TOKEN != _T28_CONSTRUCTION_TOKEN
            and EVALUATION_TOKEN != _T27_EVALUATION_TOKEN
            and EVALUATION_TOKEN != _T28_EVALUATION_TOKEN),
        # §42/§43/§44 layers consumed as staged artifacts.
        "preconstruction_contract_pass": (
            contract_audit.get("status") == "PASS"
            and contract_audit.get("leaf_count") == _PRECONSTRUCTION_LEAVES
            and len(contract_audit.get("leaf_ids", [])) == _PRECONSTRUCTION_LEAVES
            and contract_audit.get("PASS") == _PRECONSTRUCTION_LEAVES
            and contract_audit.get("FAIL", 1) == 0
            and contract_audit.get("UNVERIFIABLE", 1) == 0
            and contract_audit.get("required_fail_count") == 0
            and contract_audit.get("required_unverifiable_count") == 0
            and contract_audit.get("classification") == "PUBLIC_SAFE"
            and isinstance(contract_audit.get("leaf_root"), str)
            and len(contract_audit.get("leaf_root", "")) == 64
            and all(item == 0 for item in (
                contract_audit.get("real_blind_rows", 1),
                contract_audit.get("real_gold_rows", 1),
                contract_audit.get("real_construction_attempts", 1),
                contract_audit.get("real_evaluation_attempts", 1)))
            and all(isinstance(item, str) and len(item) == 64 for item in
                    contract_audit.get("evidence_sha256", {}).values())),
        "evaluation_readiness_gate_green": (
            bool(readiness_gate)
            and readiness_gate.get("status") == "GATE_GREEN"
            and readiness_gate.get("item_count") == 12
            and readiness_gate.get("items_failed", [1]) == []
            and readiness_gate.get("refusal") in (None, "")
            and readiness_gate.get("classification") == "PUBLIC_SAFE"
            and readiness_gate.get("construction_contract_leaf_count")
            == _PRECONSTRUCTION_LEAVES
            and all(item is True for item in
                    readiness_gate.get("items", {}).values())),
        # §45: T28 terminal record unchanged and T27/T28 historical anchors
        # schema-exact — verified LIVE against the frozen official receipts.
        "t27_official_anchor_live": _official_anchor_live(
            root, "t27", anchor_t27),
        "t28_official_anchor_live": _official_anchor_live(
            root, "t28", anchor_t28),
        # --- production graph (§56) ---
        "production_graph_complete": _production_graph_complete(root),
        "authority_graph_complete": _authority_graph_complete(root),
        "construction_ledger_absent_project_side": not (
            root / "evaluations/t30/construction_ledger.json").exists(),
        "evaluation_ledger_absent_project_side": not (
            root / "evaluations/t30/evaluation_ledger.json").exists(),
        # --- real-entrypoint freeze-path remediation (§9/§11/§14–§18/§23) ---
        "canonical_freeze_path_canonical": _canonical_loader_roundtrip(
            root, freeze),
        "construct_real_uses_canonical_loader":
            _construct_real_loader_bound(root),
        "obsolete_freeze_path_not_active": (
            _freeze_path_sources_clean(root)
            and t29_predecessor_status_present(root, t29_status)
            and not any(("preconstruction_freeze_" + "v1") in entry
                        for entry in EXCLUDED)),
        "real_entrypoint_rehearsal_staged": (
            wrapper_rehearsal.get("status") == "PASS"
            and all(wrapper_rehearsal.get(name) is True for name in (
                "canonical_freeze_loaded", "freeze_path_exact",
                "freeze_component_root_verified", "freeze_root_verified",
                "freeze_sha256_verified", "t27_metadata_authentication_reached",
                "historical_index_verification_reached",
                "construct_once_reached", "disposable_sealed"))
            and wrapper_rehearsal.get("state_sequence") == [
                "LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS",
                "MANIFESTED", "SEALED"]
            and wrapper_rehearsal.get("contract_leaf_count") ==
            len(CONTRACT_LEAF_IDS)
            and wrapper_rehearsal.get("gate_check_count") ==
            len(CONSTRUCTION_GATE_IDS)
            and wrapper_rehearsal.get("store_status") == "PASS"
            and wrapper_rehearsal.get("leak_gate_status") == "PASS"
            and wrapper_rehearsal.get("one_shot") == "UNSPENT"
            and wrapper_rehearsal.get("real_blind_rows", 1) == 0
            and wrapper_rehearsal.get("real_gold_rows", 1) == 0
            and wrapper_rehearsal.get("real_construction_attempts", 1) == 0
            and wrapper_rehearsal.get("real_evaluation_attempts", 1) == 0
            and wrapper_rehearsal.get("t27_private_rows_read", 1) == 0),
        "freeze_path_tamper_controls": (
            freeze_path_controls.get("status") == "PASS"
            and freeze_path_controls.get("control_count") ==
            len(FREEZE_PATH_NEGATIVE_CONTROL_IDS)
            and set(freeze_path_controls.get("controls", {}))
            == set(FREEZE_PATH_NEGATIVE_CONTROL_IDS)
            and all(item.get("status") == "PASS"
                    and item.get("refused_pre_ledger") is True
                    and item.get("no_private_store_artifacts") is True
                    and item.get("construction_ledger_absent") is True
                    and item.get("construction_marker_absent") is True
                    and item.get("one_shot") == "UNSPENT"
                    for item in
                    freeze_path_controls.get("controls", {}).values())
            and freeze_path_controls.get("forbidden_alias_paths_active", 1)
            == 0),
        "t29_predecessor_status_record_staged":
            t29_predecessor_status_present(root, t29_status),
        # --- T30 §40 successor checks (journal schema, stand-in, T29 package)
        **_t30_successor_checks(root),
        "evaluation_readiness_after_remediation": (
            wrapper_rehearsal.get("status") == "PASS"
            and freeze_path_controls.get("status") == "PASS"
            and wrapper_rehearsal.get("one_shot") == "UNSPENT"
            and freeze_path_controls.get("one_shot") == "UNSPENT"
            and live_leak.get("status") == "PASS"
            and bool(test_gate) and test_gate.get("status") == "PASS"
            and bool(freeze) and freeze_verify.get("status") == "PASS"
            and contract_audit.get("status") == "PASS"
            and readiness_gate.get("status") == "GATE_GREEN"),
    }
    return {
        "schema_version": "t30-doctor-v1", "artifact": "T30_PROTOCOL_DOCTOR",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "check_count": len(checks),
        "failed_checks": sorted(
            name for name, passed in checks.items() if not passed),
        "t27_private_paths_probed": 1, "t27_private_rows_read": 0,
        "t27_gold_rows_read": 0, "t27_candidate_reruns": 0,
        "t27_candidate_executions": 0,
    }


def _forbidden_alias_freeze_filename() -> str:
    """Assembled from fragments: no production source contains the `_v1`
    freeze filename as a contiguous literal, this file included (§9/§14)."""
    return ("evaluations/t30/preconstruction_freeze_"
            + "v1" + ".json")


def _source_text(path: Path) -> str:
    data = path.read_bytes()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return data.decode("utf-8")


def _canonical_loader_roundtrip(root: Path, staged: dict) -> bool:
    if not bool(staged):
        return False
    try:
        loaded = load_preconstruction_freeze(root)
    except Exception:
        return False
    return (loaded.get("freeze_path") == T30_PRECONSTRUCTION_FREEZE_PATH
            and loaded.get("freeze_path_verified") is True
            and loaded.get("canonical_freeze_loader") == FREEZE_LOADER_ID
            and loaded.get("freeze_sha256") == staged.get("freeze_sha256")
            and loaded.get("candidate_commit") == PINNED_CANDIDATE_COMMIT
            and loaded.get("real_construction_authorized") is False
            and loaded.get("real_evaluation_authorized") is False)


def _construct_real_loader_bound(root: Path) -> bool:
    try:
        source = _source_text(root / "t30_protocol" / "construction.py")
    except OSError:
        return False
    return ("freeze = load_preconstruction_freeze(root)" in source
            and "load_preconstruction_freeze" in source
            and FREEZE_LOADER_ID in _source_text(
                root / "t30_protocol" / "freeze.py"))


def _freeze_path_sources_clean(root: Path) -> bool:
    forbidden = _forbidden_alias_freeze_filename()
    scanned = list((root / "t30_protocol").glob("*.py"))
    scanned.extend((root / "scripts").glob("t30*.py"))
    scanned.extend((root / "tests").glob("test_t30*.py"))
    return all(
        forbidden not in _source_text(path) for path in scanned)


def t29_predecessor_status_present(root: Path, record: dict) -> bool:
    """§11/§12: T29 closed as authored-but-permanently-ineligible, bound to
    the published PUBLIC_SAFE adjudication; never a capability failure."""
    try:
        adjudication = json.loads(
            (root / "evaluations/t29/"
             "T29_REAL_CONSTRUCTION_ELIGIBILITY_ADJUDICATION.json")
            .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (record.get("schema_version") == "t30-t29-predecessor-status-v1"
            and record.get("t29_terminal") == adjudication.get("terminal")
            == ("T29_REAL_PACKAGE_AUTHORED_BUT_CONSTRUCTION_PERMANENTLY_"
                "INELIGIBLE_DUE_TO_FROZEN_T28_ACCESS_JOURNAL_SCHEMA_DEFECT")
            and record.get("t29_adjudication_root")
            == adjudication.get("adjudication_root")
            and record.get("construction_one_shot")
            == "UNSPENT_BUT_PERMANENTLY_INELIGIBLE"
            and record.get("capability_verdict") == "NOT_MEASURED"
            and record.get("sealed_holdout") is False
            and record.get("t29_real_oracle_invocations") == {"t27": 0, "t28": 0}
            and record.get("t29_construct_real_invocations") == 0
            and record.get("t29_protocol_repair_forbidden") is True
            and record.get("t29_package_reuse_forbidden") is True
            and record.get("historical_rewrite_of_predecessor") is False)


def _t30_successor_checks(root: Path) -> dict[str, bool]:
    """§40 fail-closed successor checks."""
    from .abandonment import (FORBIDDEN_ROW_FILES, t29_abandonment_commitment)
    from .oracle import (T28_JOURNAL_BASE_FIELDS, T28_JOURNAL_NEGATIVE_CONTROL_IDS,
                         T28_JOURNAL_OPERATION_SCHEMAS,
                         T28_REPLACE_LEDGER_STATE_SEQUENCE)
    compatibility = _optional(root, "t28_journal_compatibility.json")
    equivalence = _optional(root, "t28_journal_schema_equivalence.json")
    negatives = _optional(root, "t28_journal_negative_controls.json")
    reproducer = _optional(root, "T29_PUBLIC_ROOT_CAUSE_REPRODUCTION.json")
    t27_auth = _optional(root, "t27_metadata_authentication.json")
    commitment = _optional(root, "t29_abandonment_commitment.json")
    requirement = _optional(root, "t29_abandonment_oracle_requirement.json")
    readiness = _optional(root, "t29_abandonment_readiness.json")
    wrapper = _optional(root, "real_entrypoint_rehearsal.json")
    real_mode = _optional(root, "real_mode_oracle_evidence.json")
    sequence = list(T28_REPLACE_LEDGER_STATE_SEQUENCE)
    controls = negatives.get("controls", {})
    oracle_source = _source_text(root / "t30_protocol" / "oracle.py")
    construction_source = _source_text(root / "t30_protocol" / "construction.py")
    abandonment_source = _source_text(root / "t30_protocol" / "abandonment.py")
    standin_start = oracle_source.find("def disposable_t28_sealed_store(")
    standin_source = oracle_source[standin_start:oracle_source.find(
        "def disposable_real_mode_oracle_result(")]
    try:
        commitment_ok = commitment == t29_abandonment_commitment(root)
    except Exception:
        commitment_ok = False
    # No T30 source may open an abandoned row file (existence probes only).
    reads_rows = any(
        f'/ "{name}").read' in text or f'"{name}", "r' in text
        for name in FORBIDDEN_ROW_FILES
        for text in (abandonment_source, construction_source, oracle_source))
    return {
        "actual_t28_journal_positive_control": (
            compatibility.get("status") == "PASS"
            and compatibility.get("store_identity") == "T28-STORE-01"
            and compatibility.get("journal_record_count", 0) > 0
            and compatibility.get("replace_ledger_count") == 5
            and compatibility.get("replace_ledger_state_sequence") == sequence
            and compatibility.get("evaluation_surface_operations") == 0
            and compatibility.get("journal_unchanged_by_check") is True
            and compatibility.get("blind_bytes_read") == 0
            and compatibility.get("private_rows_exposed") == 0),
        "replace_ledger_state_not_ignored": (
            T28_JOURNAL_OPERATION_SCHEMAS.get("replace_ledger")
            == T28_JOURNAL_BASE_FIELDS | {"state"}
            and "T28_REPLACE_LEDGER_STATE_SEQUENCE" in oracle_source
            and all(controls.get(name, {}).get("refused") is True for name in (
                "replace_ledger_missing_state", "replace_ledger_unknown_state",
                "replace_ledger_wrong_ordering",
                "replace_ledger_duplicate_transition",
                "replace_ledger_skipped_transition"))),
        "state_not_globally_allowed": (
            all("state" not in schema
                for op, schema in T28_JOURNAL_OPERATION_SCHEMAS.items()
                if op != "replace_ledger")
            and all(controls.get(name, {}).get("refused") is True for name in (
                "state_attached_to_has", "state_attached_to_write_once",
                "state_attached_to_machine_only_blind_hash"))),
        "t28_journal_negative_controls_complete": (
            negatives.get("status") == "PASS"
            and set(controls) == set(T28_JOURNAL_NEGATIVE_CONTROL_IDS)
            and all(item.get("refused") is True for item in controls.values())),
        "standin_has_replace_ledger": (
            equivalence.get("standin_profile", {}).get("replace_ledger_count")
            == 5
            and "t28c.construct_once(" in standin_source
            and "T28PrivateStore(" in standin_source),
        "standin_transition_sequence_matches_official": (
            equivalence.get("SCHEMA_EQUIVALENT") is True
            and equivalence.get("standin_profile", {}).get(
                "replace_ledger_state_sequence")
            == equivalence.get("official_profile", {}).get(
                "replace_ledger_state_sequence") == sequence),
        "t29_journal_defect_reproduced_and_remediated": (
            reproducer.get("status") == "REPRODUCED_AND_REMEDIATED"
            and reproducer.get("frozen_consumer_refused_lifecycle_journal")
            is True
            and reproducer.get("frozen_t29_standin_has_replace_ledger") is False
            and reproducer.get("t30_replace_ledger_state_sequence") == sequence),
        "t27_metadata_positive_control": (
            t27_auth.get("status") == "PASS"
            and t27_auth.get("t27_private_rows_read") == 0
            and t27_auth.get("t27_oracle_executed") is False),
        "t29_abandoned_package_not_reused": (
            commitment_ok and commitment.get("reuse_permitted") is False
            and requirement.get("t29_package_reuse_forbidden") is True
            and requirement.get("sealed_machine_only_abandonment_oracle_required")
            is True
            and "t29_package_reuse_absent" in construction_source
            and not reads_rows
            and list(FORBIDDEN_ROW_FILES) == requirement.get("forbidden_files")),
        "t29_abandoned_package_preserved": (
            readiness.get("status") == "PASS"
            and readiness.get("package_retained_immutable") is True
            and readiness.get("t29_row_files_opened") == 0),
        "real_wrapper_rehearsal_three_boundaries": (
            wrapper.get("status") == "PASS"
            and wrapper.get("t28_store_authenticated") is True
            and wrapper.get("t28_standin_source") == "FROZEN_T28_LIFECYCLE"
            and wrapper.get("t29_abandoned_package_excluded") is True
            and wrapper.get("oracle_provenance_bound") is True),
        "predecessor_oracle_rehearsal_three_boundaries": (
            real_mode.get("status") == "PASS"
            and real_mode.get("t29_abandoned_package_authenticated") is True
            and real_mode.get("t29_abandoned_commitment_exact") is True
            and len(str(real_mode.get("predecessor_oracle_root"))) == 64),
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
            "T27_PUBLIC_QUALIFICATION", "T30_PUBLIC_QUALIFICATION")
        for name in retained if name in sources[source_class]["dimensions"])
    # T26_SEALED_EVALUATED is intentionally NOT in the required population set:
    # its public receipt contains no raw rows and no scenario bodies
    # (raw_rows_included False / scenario_bodies_included False), so its
    # content dimensions are truthfully empty in the public index.  The sealed
    # T26 store is authenticated machine-only and is covered by the
    # structural/T27-overlap oracles, not by publishable historical content.


def _environment_identity_ok(document: dict) -> bool:
    """§26: the REAL environment root and the rehearsal root must both be
    real, distinct 64-hex identities — never a placeholder (the REAL
    environment is staged on a production-capable host at preconstruction
    per §27; a null or sentinel identity fails closed)."""
    import re
    hex64 = re.compile(r"[0-9a-f]{64}")
    placeholders = {"", "0" * 64, "PENDING", "PLACEHOLDER", "TODO", "TBD",
                    "PLACEHOLDER_IDENTITY", "STUB", "ENV"}
    required = {
        "schema_version", "artifact", "classification", "environment_root",
        "rehearsal_environment_root", "experiment",
        "live_provider_identity_root",
    }
    if not isinstance(document, dict) or not required <= set(document):
        return False
    rehearsal_root = document["rehearsal_environment_root"]
    provider_root = document["live_provider_identity_root"]
    env_root = document["environment_root"]
    if (not isinstance(rehearsal_root, str)
            or rehearsal_root in placeholders
            or not hex64.fullmatch(rehearsal_root)
            or not isinstance(provider_root, str)
            or provider_root in placeholders
            or not hex64.fullmatch(provider_root)
            or rehearsal_root == provider_root):
        return False
    return (isinstance(env_root, str)
            and env_root not in placeholders
            and hex64.fullmatch(env_root) is not None
            and env_root != rehearsal_root
            and document["experiment"] == "t30"
            and document["schema_version"] ==
            "t30-official-environment-identity-v1"
            and document["artifact"] == "T30_OFFICIAL_ENVIRONMENT_IDENTITY")


def _wrapper_rehearsal_sources_bound(root: Path) -> bool:
    """§17/§45: the evaluation rehearsal drives the actual evaluate_official
    wrapper — never a bare ``_evaluate_once``/``score_suite``/preflight path
    (live introspection, not a staged claim)."""
    from .evaluation import run_evaluation_rehearsals
    try:
        source = inspect.getsource(run_evaluation_rehearsals)
    except (OSError, TypeError):
        return False
    return ("evaluate_official(" in source
            and "_evaluate_once(" not in source
            and "score_suite(" not in source)


def _construct_real_wrapper_source_bound(root: Path) -> bool:
    """§43/§45: the construction real-entrypoint rehearsal must execute the
    actual ``construct_real`` wrapper (not ``construct_once`` directly)."""
    from .construction import run_real_entrypoint_rehearsal
    try:
        source = inspect.getsource(run_real_entrypoint_rehearsal)
    except (OSError, TypeError):
        return False
    return ("construct_real(" in source
            and "construct_once(" not in source)


def _dual_oracle_implementation_bound(root: Path,
                                      evidence: dict) -> bool:
    """§8/§9: the sealed machine-only DUAL overlap oracle (T27→T30 AND
    T28→T30) is bound live to its t30_protocol.oracle implementations and to
    the staged REAL-mode evidence (never the retired single-predecessor
    T27→T28 oracle as the production T30 path)."""
    try:
        from .construction import run_real_mode_oracle_validation_rehearsal
        oracle_source = _source_text(root / "t30_protocol" / "oracle.py")
        rehearsal_source = inspect.getsource(
            run_real_mode_oracle_validation_rehearsal)
    except (OSError, TypeError):
        return False
    return ("run_sealed_t27_to_t30_overlap_oracle" in oracle_source
            and "run_sealed_t28_to_t30_overlap_oracle" in oracle_source
            and "disposable_real_mode_oracle_result" in rehearsal_source
            and evidence.get("predecessors") == ["t27", "t28"]
            and evidence.get("real_mode_not_synthetic") is True
            and evidence.get("overall_prohibited_overlap") == 0
            and evidence.get("outside_boundary_private_rows_exposed", 1) == 0
            and isinstance(evidence.get("dual_oracle_root"), str)
            and len(evidence.get("dual_oracle_root", "")) == 64)


def _official_anchor_live(root: Path, predecessor: str, staged: dict) -> bool:
    """§45: historical-anchor schema drift and T27/T28 terminal-record changes
    must fail closed — validate the official anchor LIVE (against the frozen
    authoritative receipts) and require the staged public anchor to match it
    exactly (producer→consumer roundtrip)."""
    if not staged:
        return False
    try:
        if predecessor == "t27":
            from .historical_anchor import t27_official_anchor
            live = t27_official_anchor(root)
        else:
            from .historical_anchor import t28_official_anchor
            live = t28_official_anchor(root)
    except Exception:
        return False
    return (live == staged
            and live.get("store_authenticated") is True
            and live.get("private_rows_read", 1) == 0)


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