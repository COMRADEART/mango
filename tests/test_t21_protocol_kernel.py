"""Protocol-kernel qualification and R9-R14 failure-class regressions."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from t21_protocol.adjudication import generate_applicability, validate_adjudication
from t21_protocol.artifact_graph import seal_input_nodes, validate_artifact_graph
from t21_protocol.author import shadow_author
from t21_protocol.builder import build_rows
from t21_protocol.contract import KNOWN_COMPONENTS, load_contract, validate_master_contract
from t21_protocol.errors import (
    ContractError,
    GraphError,
    LedgerError,
    SealError,
    ValidationError,
    WriteGuardError,
)
from t21_protocol.exclusion import (
    DIMENSIONS,
    REMEDIATION_DIMENSIONS,
    audit_fingerprints,
    fingerprint,
    validate_historical_policy,
    validate_remediation_policy,
)
from t21_protocol.exact_design import audit_rows
from t21_protocol.import_audit import dynamic_import_write_audit, static_import_write_audit
from t21_protocol.ledger import ConstructionLedger, EvaluationLedger
from t21_protocol.pipeline import run_synthetic_twice
from t21_protocol.qualification import validate_qualification_lock
from t21_protocol.seal import (
    HOLDOUT_FROZEN_FIELDS,
    build_manifest,
    validate_holdout_frozen,
    validate_holdout_frozen_schema,
)
from t21_protocol.state_machine import Phase, ProtocolStateMachine
from t21_protocol.taxonomy import coverage_report, load_taxonomy, validate_labels
from t21_protocol.util import read_json, sha256_json
from t21_protocol.write_guard import WriteGuard, tracked_tree_hash

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r15"
CONTRACT = load_contract(OUT / "t21_master_contract.json")
GRAPH = read_json(OUT / "artifact_graph.json")
TAXONOMY = load_taxonomy(OUT / "domain_taxonomy_contract.json")


def test_master_contract_is_fully_typed_and_closed():
    report = validate_master_contract(CONTRACT.document, raise_on_error=False)
    assert report == {
        "status": "PASS",
        "untyped_fields": 0,
        "unknown_fields": 0,
        "unknown_consumers": 0,
        "type_disagreements": 0,
        "errors": [],
    }


def test_unknown_contract_field_fails_closed():
    bad = copy.deepcopy(CONTRACT.document)
    bad["unexpected"] = True
    with pytest.raises(ContractError, match="unknown top-level field"):
        validate_master_contract(bad)


def test_untyped_contract_field_fails_closed():
    bad = copy.deepcopy(CONTRACT.document)
    bad["values"]["surprise"] = 1
    with pytest.raises(ContractError, match="untyped field|values fields differ"):
        validate_master_contract(bad)


def test_contract_type_disagreement_rejected():
    bad = copy.deepcopy(CONTRACT.document)
    bad["values"]["suite_total"] = "4800"
    with pytest.raises(ContractError, match="declared type"):
        validate_master_contract(bad)


def test_unknown_contract_consumer_rejected():
    bad = copy.deepcopy(CONTRACT.document)
    bad["fields"][0]["consumers"].append("mystery_consumer")
    assert "mystery_consumer" not in KNOWN_COMPONENTS
    with pytest.raises(ContractError, match="unknown consumer"):
        validate_master_contract(bad)


def test_contract_exact_design_mismatch_rejected():
    bad = copy.deepcopy(CONTRACT.document)
    bad["values"]["exact_design"]["temporal"]["explicit_current"] -= 1
    with pytest.raises(ContractError, match="does not cover"):
        validate_master_contract(bad)


def test_artifact_graph_is_closed():
    report = validate_artifact_graph(GRAPH)
    assert report["status"] == "PASS"
    assert report["nodes"] == 38
    assert report["required_artifacts_with_no_producer"] == 0
    assert report["produced_artifacts_with_no_declared_consumer"] == 0
    assert report["seal_required_artifacts_not_producible"] == 0
    assert report["seal_bound_required_artifacts_omitted"] == 0
    assert report["dangling_requirements"] == 0
    assert report["cyclic_dependencies"] == 0


def test_missing_seal_input_fails_closed(tmp_path: Path):
    with pytest.raises(SealError, match="not producible/present"):
        build_manifest(tmp_path, CONTRACT, GRAPH)


def test_unbound_required_seal_artifact_fails_closed():
    bad = copy.deepcopy(GRAPH)
    bad["nodes"]["gold_compatibility"]["include_in_seal"] = False
    with pytest.raises(GraphError, match="omitted from seal"):
        validate_artifact_graph(bad)


def test_missing_producer_fails_closed():
    bad = copy.deepcopy(GRAPH)
    bad["nodes"]["gold_compatibility"]["producer"] = ""
    with pytest.raises(GraphError, match="no known producer"):
        validate_artifact_graph(bad)


def test_dangling_requirement_fails_closed():
    bad = copy.deepcopy(GRAPH)
    bad["nodes"]["gold_compatibility"]["required_inputs"].append("missing")
    with pytest.raises(GraphError, match="dangling requirement"):
        validate_artifact_graph(bad)


def test_cycle_fails_closed():
    bad = copy.deepcopy(GRAPH)
    bad["nodes"]["master_contract"]["required_inputs"] = ["artifact_graph"]
    with pytest.raises(GraphError, match="cyclic dependency"):
        validate_artifact_graph(bad)


def test_seal_inputs_are_derived_only_from_graph():
    inputs = seal_input_nodes(GRAPH)
    assert inputs
    assert all(GRAPH["nodes"][name]["include_in_seal"] for name in inputs)
    assert "holdout_manifest" not in inputs
    assert "remediation_exclusion" in inputs


def _valid_marker() -> dict:
    return {
        "schema_version": "t21-holdout-frozen-v1",
        "experiment": "t21r15",
        "construction_status": "COMPLETE",
        "holdout_manifest_sha256": "a" * 64,
        "freeze_root_sha256": "b" * 64,
        "candidate_commit": "c" * 40,
        "candidate_tree": "d" * 40,
        "runtime_root": "e" * 64,
        "evaluator_root": "f" * 64,
        "floor_hash": "0" * 64,
        "construction_attempts": 1,
        "corpus_materializations": 1,
        "suite_materializations": 1,
        "candidate_rows_executed": 0,
        "runtime_rows_executed": 0,
        "official_evaluator_invocations": 0,
    }


def test_holdout_frozen_schema_complete():
    marker = _valid_marker()
    assert set(marker) == set(HOLDOUT_FROZEN_FIELDS)
    assert validate_holdout_frozen(marker)["missing"] == 0
    schema = read_json(OUT / "holdout_frozen_schema.json")
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(HOLDOUT_FROZEN_FIELDS)
    assert set(schema["properties"]) == set(HOLDOUT_FROZEN_FIELDS)
    assert validate_holdout_frozen_schema(schema)["status"] == "PASS"


def test_incomplete_holdout_frozen_rejected():
    marker = _valid_marker()
    marker.pop("official_evaluator_invocations")
    with pytest.raises(SealError, match="missing"):
        validate_holdout_frozen(marker)


def test_ledger_services_are_callable():
    assert callable(ConstructionLedger.create_exclusive)
    assert callable(EvaluationLedger.create_exclusive)


@pytest.mark.parametrize("ledger_type", [ConstructionLedger, EvaluationLedger])
def test_second_ledger_creation_refused(tmp_path: Path, ledger_type):
    path = tmp_path / "ledger.json"
    ledger_type.create_exclusive(path, "t21r15")
    with pytest.raises(LedgerError, match="already exists"):
        ledger_type.create_exclusive(path, "t21r15")


def test_ledger_started_complete_and_no_restart(tmp_path: Path):
    path = tmp_path / "ledger.json"
    ledger = ConstructionLedger.create_exclusive(path, "t21r15")
    assert ledger.state == "STARTED"
    ledger.complete()
    assert ledger.state == "COMPLETE"
    with pytest.raises(LedgerError):
        ledger.complete()
    with pytest.raises(LedgerError):
        ConstructionLedger.create_exclusive(path, "t21r15")


def test_ledger_started_failed_and_no_restart(tmp_path: Path):
    path = tmp_path / "ledger.json"
    ledger = EvaluationLedger.create_exclusive(path, "t21r15")
    ledger.fail()
    assert ledger.state == "FAILED"
    with pytest.raises(LedgerError):
        ledger.complete()
    with pytest.raises(LedgerError):
        EvaluationLedger.create_exclusive(path, "t21r15")


def test_state_machine_lifecycle_and_illegal_transition():
    machine = ProtocolStateMachine.from_contract(CONTRACT)
    assert machine.validate()["status"] == "PASS"
    assert machine.transition("qualify", Phase.PRECONSTRUCTION) == Phase.QUALIFIED
    with pytest.raises(Exception):
        machine.transition("start_evaluation", Phase.PRECONSTRUCTION)


def test_single_canonical_taxonomy_coverage():
    canonical = set(CONTRACT.get("domain_taxonomy"))
    report = coverage_report(
        TAXONOMY,
        {"author": canonical, "evaluator": canonical, "scorer": canonical, "domain_macro_aggregator": canonical},
    )
    assert report["status"] == "PASS"
    assert report["canonical_count"] == 14
    assert report["unknown"] == 0


def test_unknown_taxonomy_label_rejected():
    with pytest.raises(ValidationError, match="outside the canonical taxonomy"):
        validate_labels(["__unknown__"], TAXONOMY)


def test_raw_remediation_exclusion_rejected():
    policy = read_json(OUT / "remediation_exclusion.json")
    bad = copy.deepcopy(policy)
    bad["dimensions"]["case_ids"] = ["raw-case-id"]
    with pytest.raises(ValidationError, match="raw value"):
        validate_remediation_policy(bad)


def test_missing_remediation_dimension_rejected():
    policy = read_json(OUT / "remediation_exclusion.json")
    bad = copy.deepcopy(policy)
    bad["dimensions"].pop("relations")
    with pytest.raises(ValidationError, match="missing a dimension"):
        validate_remediation_policy(bad)


def test_historical_policy_is_14_by_8_and_r14_is_provenance_only():
    report = validate_historical_policy(read_json(OUT / "historical_exclusion.json"), ROOT)
    assert report == {"status": "PASS", "historical_milestones": 14, "dimensions": 8, "r14_protocol_history_only": True}
    assert len(DIMENSIONS) == 8 and len(REMEDIATION_DIMENSIONS) == 9


def test_historical_collision_fails():
    value = "colliding-case"
    report = audit_fingerprints([{"case_id": value}], {"case_ids": {fingerprint(value)}})
    assert report["status"] == "FAIL"


def test_missing_exact_design_context_rejected():
    authored = shadow_author(CONTRACT, ROOT)
    rows = build_rows(CONTRACT, authored["spec"])
    all_rows = [row for suite in rows.values() for row in suite]
    target = next(row for row in all_rows if row["suite_family"] == "temporal")
    target.pop("construction_tag")
    report = audit_rows(all_rows, CONTRACT)
    assert report["status"] == "FAIL"
    assert report["missing_context"] == 1


def test_shadow_author_deterministic():
    first = shadow_author(CONTRACT, ROOT)
    second = shadow_author(CONTRACT, ROOT)
    assert first["fingerprint_root"] == second["fingerprint_root"]


def test_qualification_lock_rejects_author_root_mismatch():
    lock = read_json(OUT / "qualification_lock.json")
    bad = copy.deepcopy(lock)
    bad["shadow_fingerprint_root"] = "0" * 64
    with pytest.raises(ValidationError, match="qualification lock mismatch"):
        validate_qualification_lock(ROOT, CONTRACT, bad)


def test_write_guard_rejects_unexpected_write(tmp_path: Path):
    with pytest.raises(WriteGuardError, match="unexpected filesystem writes"):
        with WriteGuard(tmp_path, ["allowed"]):
            (tmp_path / "historical.json").write_text("mutated", encoding="utf-8")


def test_protocol_imports_are_side_effect_free():
    protocol_paths = sorted((ROOT / "t21_protocol").glob("*.py"))
    helper_names = ("t21r_fixtures", "t21r12_fixtures", "t21r13_fixtures", "t21r14_fixtures")
    paths = [
        *protocol_paths,
        *(ROOT / "scripts" / f"{name}.py" for name in helper_names),
        *sorted((ROOT / "tests").glob("test_t21*.py")),
    ]
    assert static_import_write_audit(paths)["status"] == "PASS"
    modules = [f"t21_protocol.{path.stem}" for path in protocol_paths if path.stem not in {"__init__", "doctor"}]
    modules += list(helper_names)
    assert dynamic_import_write_audit(ROOT, modules)["status"] == "PASS"


def test_gold_validator_is_seal_independent():
    from t21_protocol.preflight import validate_gold_bundle, validate_sealed_evaluation_bundle

    assert callable(validate_gold_bundle)
    assert callable(validate_sealed_evaluation_bundle)
    assert validate_gold_bundle is not validate_sealed_evaluation_bundle


def test_public_protocol_interfaces_exist():
    from t21_protocol import artifact_graph, author, builder, evaluator, preflight, scorer, seal

    for module, name in (
        (artifact_graph, "seal_input_nodes"),
        (author, "shadow_author"),
        (builder, "materialize_suites"),
        (evaluator, "evaluate_rows"),
        (preflight, "validate_gold_bundle"),
        (preflight, "validate_sealed_evaluation_bundle"),
        (scorer, "score"),
        (seal, "seal_holdout"),
    ):
        assert callable(getattr(module, name))


def test_adjudication_summary_and_applicability_are_generated():
    document = read_json(OUT / "test_failure_adjudication.json")
    report = validate_adjudication(document)
    generated = generate_applicability(document)
    committed = read_json(OUT / "current_test_applicability.json")
    assert report["classification_summary"]["LIVE"] == 0
    assert report["classification_summary"]["UNKNOWN"] == 0
    assert committed["deselect_nodeids"] == generated["deselect_nodeids"]


def test_adjudication_summary_contradiction_rejected():
    document = read_json(OUT / "test_failure_adjudication.json")
    document["classification_summary"]["OBSOLETE_HISTORICAL_ASSERTION"] = 6
    with pytest.raises(ValidationError, match="differs from computed"):
        validate_adjudication(document)


def test_floor_contract_is_32_and_frozen():
    floors = CONTRACT.get("promotion_floors")
    assert sum(len(group) for group in floors.values()) == 32
    assert sha256_json(floors) == "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"


def test_r14_closed_without_construction_and_evidence_preserved():
    closure = read_json(ROOT / "evaluations" / "t21r14" / "T21R14_CLOSURE.json")
    assert closure["status"] == "CLOSED / PRECONSTRUCTION_PROTOCOL_INTEGRATION_FAILURE"
    assert closure["construction_attempts"] == 0
    assert closure["one_shot_consumed"] is False
    assert (ROOT / "evaluations" / "t21r14" / "preconstruction_qualification.json").is_file()


def test_r13_raw_results_not_read_by_author_builder_or_pipeline():
    forbidden = "t21r13/raw_results.jsonl"
    for name in ("author.py", "builder.py", "pipeline.py"):
        assert forbidden not in (ROOT / "t21_protocol" / name).read_text(encoding="utf-8")


def test_real_r15_paths_are_absent():
    for relative in CONTRACT.get("real_r15_paths"):
        assert not (ROOT / relative).exists(), relative


def test_full_synthetic_protocol_twice():
    result = run_synthetic_twice(ROOT, CONTRACT, GRAPH)
    assert result["status"] == "PASS"
    assert result["run_1"]["floor_calculations"] == 32
    assert result["run_2"]["floor_calculations"] == 32
    assert result["run_1"]["candidate_rows_executed"] == 4800
    assert result["run_2"]["candidate_rows_executed"] == 4800
    assert result["state_transition_differences"] == 0
    assert result["artifact_graph_differences"] == 0
    assert result["schema_differences"] == 0
    assert result["disposable_workspaces_destroyed"] is True


def test_tracked_tree_hash_is_stable_for_read_only_call():
    before = tracked_tree_hash(ROOT)
    _ = shadow_author(CONTRACT, ROOT)
    assert tracked_tree_hash(ROOT) == before
