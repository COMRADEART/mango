"""Structural historical-exclusion dimension policy regression gate."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from t27_protocol.construction import (
    CONSTRUCTION_GATE_IDS, CONTRACT_LEAF_IDS, NEGATIVE_CONTROL_IDS,
    construction_contract, real_fingerprint_semantics_probe,
    t26_oracle_nine_dimension_probe,
)
from t27_protocol.exclusion import (
    DIMENSIONS, GENERATED_PUBLIC_POLICY_SCHEMA, GENERATED_PUBLIC_SOURCES,
    GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS, SUPERSEDED_INDEX_ROOT,
    authenticated_construction_policy, build_authenticated_public_historical_index,
    generated_public_dimension_policy, historical_exclusion_policy_v4,
    public_index_report, public_index_supersession,
    t26_public_qualification_exclusion_precedent,
    validate_generated_public_dimension_policy, verify_historical_index,
)
from t27_protocol.freeze import PRESERVED_V4_FREEZE_SHA256
from t27_protocol.oracle import verify_oracle_result

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "evaluations" / "t27"


def read(name: str) -> dict:
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def test_generated_public_dimension_policy_is_frozen_and_exactly_bound():
    policy = generated_public_dimension_policy()
    assert read("generated_public_exclusion_dimension_policy.json") == policy
    assert policy["schema_version"] == GENERATED_PUBLIC_POLICY_SCHEMA
    assert policy["applies_to_sources"] == list(GENERATED_PUBLIC_SOURCES)
    classifications = policy["dimension_classifications"]
    assert set(classifications) == set(DIMENSIONS)
    structural = set(GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS)
    assert {name for name, value in classifications.items()
            if value == "STRUCTURAL_SHARED_FROZEN_EMPTY"} == structural
    assert {"case_ids", "chunk_ids"} <= {name for name, value
                                         in classifications.items()
                                         if value == "IDENTITY_BEARING"}
    assert {"exact_queries", "exact_answers", "exact_source_text"} <= {
        name for name, value in classifications.items()
        if value == "CONTENT_BEARING"}
    assert set(classifications.values()) == {
        "IDENTITY_BEARING", "CONTENT_BEARING", "STRUCTURAL_SHARED_FROZEN_EMPTY"}
    validate_generated_public_dimension_policy(policy)
    with pytest.raises(ValueError):
        validate_generated_public_dimension_policy(
            {**policy, "schema_version": "t27-generated-public-exclusion-"
                                        "dimension-policy-v0"})
    with pytest.raises(ValueError):
        tampered = copy.deepcopy(policy)
        tampered["dimension_classifications"]["entity_identities"] = (
            "IDENTITY_BEARING")
        validate_generated_public_dimension_policy(tampered)


def test_remediated_index_carries_empty_structural_and_retained_identity():
    index = build_authenticated_public_historical_index(ROOT)
    verified = public_index_report(index)
    assert read("public_historical_index_report.json") == verified
    assert index["schema_version"] == (
        "t27-authenticated-public-historical-index-v2")
    assert verified["schema_version"] == (
        "t27-public-historical-index-report-v1")
    assert verified["public_historical_index_root"] == (
        index["public_historical_index_root"])
    assert verified["public_historical_index_root"] != SUPERSEDED_INDEX_ROOT
    sources = {source["source_class"]: source for source in verified["sources"]}
    for source_class in GENERATED_PUBLIC_SOURCES:
        source = sources[source_class]
        assert source["dimension_policy_schema"] == GENERATED_PUBLIC_POLICY_SCHEMA
        assert source["dimension_policy_root"] == (
            generated_public_dimension_policy()["dimension_policy_root"])
        for name in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS:
            assert source["dimension_populations"][name] == 0, (
                source_class, name)
        for name, value in source["dimension_populations"].items():
            if name not in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS:
                assert value > 0, (source_class, name)
    for source_class, source in sources.items():
        if source_class not in GENERATED_PUBLIC_SOURCES:
            assert "dimension_policy_schema" not in source
            assert "dimension_policy_root" not in source
    aggregate = verified["aggregate_dimension_populations"]
    assert all(aggregate[name] > 0
               for name in DIMENSIONS if name != "relations")
    assert verified["aggregate_dimension_populations"]["relations"] == 0
    # The mode-independent policy projection (what historical_exclusion_audit
    # consumes) records each structural dimension as exempt with the empty
    # contract, and each retained dimension as applicable.
    audit_view = verify_historical_index(index, mode="REAL", root=ROOT)
    assert audit_view["status"] == "PASS"
    audit_sources = {source["source_class"]: source
                     for source in audit_view["sources"]}
    for source_class in GENERATED_PUBLIC_SOURCES:
        records = audit_sources[source_class]["dimensions"]
        for name in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS:
            record = records[name]
            assert record["applicable"] is False
            assert record["historical_population"] == 0
            assert record["empty_contract"] == (
                f"{source_class}:{name}:STRUCTURAL_SHARED_FROZEN_EMPTY")
        for name in DIMENSIONS:
            if name not in GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS:
                assert records[name]["applicable"] is True
                assert records[name]["historical_population"] == (
                    sources[source_class]["dimension_populations"][name])
                assert records[name]["empty_contract"] is None


def test_supersession_policy_v4_and_precedent_are_exact():
    index = build_authenticated_public_historical_index(ROOT)
    assert read("public_index_supersession.json") == public_index_supersession(
        index)
    supersession = read("public_index_supersession.json")
    assert supersession["superseded_root"] == SUPERSEDED_INDEX_ROOT
    assert supersession["superseded_classification"] == "SUPERSEDED_PRE_EXPOSURE"
    assert supersession["superseded_reason"] == (
        "STRUCTURALLY_SHARED_GENERATED_PUBLIC_DIMENSIONS_MADE_REAL_"
        "ZERO_OVERLAP_UNSATISFIABLE")
    assert read("historical_exclusion_policy_v4.json") == (
        historical_exclusion_policy_v4())
    policy_v4 = read("historical_exclusion_policy_v4.json")
    assert policy_v4["real_prospective_fingerprints"] == "ALL_NINE_DIMENSIONS"
    assert policy_v4["overall_prohibited_overlap_required"] == 0
    assert read("t26_public_qualification_exclusion_precedent.json") == (
        t26_public_qualification_exclusion_precedent())


def test_reproducer_proves_old_structural_unsatisfiability():
    reproducer = read("structural_unsatisfiability_reproducer.json")
    assert reproducer["status"] == "REPRODUCED"
    assert reproducer["old_semantics_minimum_overlap"] == 33
    assert reproducer["old_semantics_capability_overlap_all_exercised"] == 12
    assert reproducer["old_semantics_minimum_overlap_all_exercised"] == 44
    assert reproducer["contract_forced_structural_overlap"] is True
    assert reproducer["contract_forcing"]["entity_identities"][
        "overlap_measured"] == 16
    assert reproducer["contract_forcing"]["verbatim_attack_wording"][
        "overlap_measured"] == 16
    assert reproducer["overall_prohibited_overlap_required"] == 0
    assert reproducer["remediated_semantics"] is True
    assert reproducer["remediated_structural_overlap"] == 0
    assert reproducer["real_blind_rows_authored"] == 0
    assert reproducer["construction_one_shot_spent"] is False


def test_witness_proves_remediated_zero_overlap_is_satisfiable():
    witness = read("structural_satisfiability_witness.json")
    assert witness["status"] == "PASS"
    assert witness["scenario_count"] == 512
    assert witness["family_count"] == 16
    assert witness["capabilities_exercised"] == 12
    assert witness["overall_prohibited_overlap"] == 0
    assert all(value == 0
               for value in witness["aggregate_overlap_by_dimension"].values())
    assert witness["per_source_overlap_zero"] is True
    assert witness["deterministic"] is True
    assert all(witness["value_level_disjointness"].values())
    assert all(witness["static_checks"].values())
    for name, minimum in witness["nonvacuity_minimums"].items():
        assert witness["designated_counts"][name] >= minimum
    assert witness["witness_material_is_not_real_blind_material"] is True
    assert witness["reused_public_blind_material"] is False
    assert witness["t26_private_rows_opened"] == 0


def test_probes_pin_real_semantics_and_sealed_t26_oracle():
    probe = real_fingerprint_semantics_probe()
    assert probe["status"] == "PASS"
    assert all(probe["checks"].values())
    oracle_probe = t26_oracle_nine_dimension_probe()
    assert oracle_probe["status"] == "PASS"
    assert oracle_probe["nine_dimension_result_pass"] is True
    assert oracle_probe["eight_dimension_refused"] is True
    assert oracle_probe["t26_private_rows_opened"] == 0


def test_expanded_enumerators_include_remediation_items():
    contract = construction_contract()
    assert contract["leaf_count"] == len(CONTRACT_LEAF_IDS) == 60
    assert {"exclusion.dimension_policy_exact",
            "exclusion.generated_structural_dimensions_frozen_empty",
            "exclusion.identity_dimensions_nonvacuous",
            "exclusion.structural_satisfiability_proven"} <= set(
        CONTRACT_LEAF_IDS)
    assert len(CONSTRUCTION_GATE_IDS) == 52
    assert {"G47_GENERATED_PUBLIC_DIMENSION_POLICY_EXACT",
            "G48_GENERATED_STRUCTURAL_DIMENSIONS_FROZEN_EMPTY",
            "G49_GENERATED_IDENTITY_DIMENSIONS_NONVACUOUS",
            "G50_OLD_STRUCTURAL_UNSATISFIABILITY_REPRODUCED",
            "G51_STRUCTURAL_SATISFIABILITY_WITNESS_PASS",
            "G52_NEW_PUBLIC_HISTORY_ROOT_EXACT"} <= set(CONSTRUCTION_GATE_IDS)
    assert len(NEGATIVE_CONTROL_IDS) >= 72
    assert {"structural_entity_identities_populated",
            "structural_source_ids_populated",
            "structural_verbatim_attack_wording_populated",
            "structural_relations_populated",
            "identity_case_ids_marked_structural",
            "identity_exact_queries_marked_structural",
            "identity_exact_answers_marked_structural",
            "identity_exact_source_text_marked_structural",
            "identity_chunk_ids_marked_structural",
            "unknown_structural_dimension", "dimension_policy_root_tampered",
            "source_policy_root_tampered", "reuse_case_ids_detected",
            "reuse_exact_queries_detected", "reuse_exact_answers_detected",
            "reuse_exact_source_text_detected",
            "reuse_chunk_ids_detected"} <= set(NEGATIVE_CONTROL_IDS)


def test_freeze_v4_is_preserved_by_sha_and_v5_supersedes_it():
    assert read("preconstruction_freeze_v4.json")["freeze_sha256"] == (
        PRESERVED_V4_FREEZE_SHA256)
    freeze_v5 = read("preconstruction_freeze_v5.json")
    assert freeze_v5["supersedes"]["freeze_sha256"] == (
        PRESERVED_V4_FREEZE_SHA256)
    assert freeze_v5["supersedes"]["reason"] == (
        "STRUCTURAL_HISTORICAL_EXCLUSION_SEMANTICS_DEFECT")
    assert freeze_v5["real_construction_authorized"] is False
    assert freeze_v5["real_evaluation_authorized"] is False