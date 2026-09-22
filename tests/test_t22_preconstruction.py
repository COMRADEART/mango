"""T22 temporal-routing preconstruction artifact pins.

Every test reads committed preconstruction artifacts and pins the frozen
T22 contract: the R17 semantics carry (implementation registry unchanged
in content; the semantics document carries only the preregistered
harmonized prose deltas — the measuring stick does not change), the
remediated candidate identity, the temporal signal
contract and holdout design with the mandatory candidate-visible
signal-carrier audit (gold-only-signal rows = 0), the harmonized
zero-denominator policy resolution, the R17 closure preserved verbatim,
historical exclusion hash-only, and zero real T22 exposure. The module
skips until the T22 master contract exists, so the adjudication-time
full-suite run (which precedes T22 construction) exercises only the
historically registered failure set.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t22"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

if not (OUT / "t21_master_contract.json").is_file():
    pytest.skip(
        "T22 master contract not yet present (preconstruction in progress)",
        allow_module_level=True,
    )

from t21_protocol.metric_semantics import load_metric_semantics, semantics_root  # noqa: E402
from t21_protocol.util import read_json, sha256_file, sha256_json  # noqa: E402

FLOOR_HASH = "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"
T22_CANDIDATE_COMMIT = "7d919a255c2df87adcb3dd42011b505b10509713"
T22_CANDIDATE_TREE = "0bbf81b234458a4ac204ff6b035bc59b59078544"
T22_PROVIDER_ID = "t21_protocol.providers_t22:RealCandidateProviderT22Evidence"
R17_EVAL_HEAD = "9fc953468921e527d5c340b6e69bb1c3ea48c7a9"
R17_HISTORICAL_MILESTONE = "T21R17_OFFICIAL_VALID_CAPABILITY_FAILURE"
R17_FAILED_METRICS = ["explicit_current_routing_accuracy", "stale_snapshot_false_current_answers"]
SEMANTICS_RELATIVE = "evaluations/t22/official_metric_semantics.json"
REGISTRY_RELATIVE = "evaluations/t22/metric_implementation_registry.json"
FIXTURES_RELATIVE = "evaluations/t22/metric_semantics_fixtures.json"
DESIGN_RELATIVE = "evaluations/t22/temporal_holdout_design.json"
SIGNAL_CONTRACT_RELATIVE = "evaluations/t22/temporal_signal_contract.json"
RESOLUTION_RELATIVE = "evaluations/t22/zero_denominator_policy_resolution.json"
IDENTITY_RELATIVE = "evaluations/t22/candidate_identity.json"


def _load(relative: str) -> dict:
    return read_json(ROOT / relative)


def _contract() -> dict:
    return _load("evaluations/t22/t21_master_contract.json")


def _r17_values() -> dict:
    return _load("evaluations/t21r17/t21_master_contract.json")["values"]


def _floors() -> dict:
    return _r17_values()["promotion_floors"]


def _floor_metrics() -> list[str]:
    return sorted(metric for group in _floors().values() for metric in group)


def _semantics() -> dict:
    return load_metric_semantics(ROOT, {}, relative=SEMANTICS_RELATIVE, floors=_floors(),
                                 artifact="T22_OFFICIAL_METRIC_SEMANTICS", experiment="t22")


def _later_artifact(relative: str, name: str):
    if not (ROOT / relative).is_file():
        pytest.skip(f"{name} not yet written (preconstruction stage pending)")
    return _load(relative)


# --------------------------------------------------------- frozen stick ----


def test_scorer_and_semantics_carry_byte_identical_from_r17() -> None:
    # The implementation registry carries with a header-only identity delta
    # (the implementations content is unchanged — the measuring stick does
    # not change); the semantics document carries with only the
    # preregistered harmonized prose deltas (frozen carry report).
    registry_delta = _load(REGISTRY_RELATIVE)
    r17_registry = _load("evaluations/t21r17/metric_implementation_registry.json")
    assert {key: value for key, value in registry_delta.items() if key not in ("artifact", "experiment")} == {
        key: value for key, value in r17_registry.items() if key not in ("artifact", "experiment")
    }
    assert registry_delta["artifact"] == "T22_METRIC_IMPLEMENTATION_REGISTRY"
    assert registry_delta["experiment"] == "t22"
    registry = registry_delta
    assert registry["scorer_module_sha256"] == sha256_file(ROOT / "t21_protocol" / "scorer_r17.py")
    assert registry["scorer_module_sha256"] == r17_registry["scorer_module_sha256"]
    carry = _load("evaluations/t22/semantics_carry_report.json")
    assert sorted(carry["harmonized_paths"]) == [
        "artifact",
        "experiment",
        "lineage.notes",
        "metrics.conflict_false_resolution.lineage.notes",
        "zero_denominator_conventions.PREREGISTERED_CONVENTION_0.0.capability_guard",
    ]
    assert carry["registry_byte_identical_except"] == []
    assert carry["implementation_sha256_recomputed"] == 32
    assert carry["implementation_sha256_mismatches"] == []
    assert carry["floor_hash_unchanged"] is True
    validation = _load("evaluations/t22/metric_semantics_validation.json")
    assert validation["r17_semantics_carry"]["semantics_delta_paths"] == sorted(carry["harmonized_paths"])
    assert validation["r17_semantics_carry"]["semantics_delta_matches_frozen_harmonized_paths"] is True


def test_floor_hash_unchanged_from_r17() -> None:
    floors = _floors()
    assert sha256_json(floors) == FLOOR_HASH
    contract = _contract()
    assert contract["values"]["roots"]["floor_hash"] == FLOOR_HASH
    assert contract["values"]["roots"]["floor_hash"] == _r17_values()["roots"]["floor_hash"]
    assert _load("evaluations/t22/metric_semantics_validation.json")["floor_hash"] == FLOOR_HASH
    assert _load(FIXTURES_RELATIVE)["floor_hash"] == FLOOR_HASH


def test_contract_metric_semantics_block() -> None:
    contract = _contract()
    values = contract["values"]
    block = values["metric_semantics"]
    assert set(block) == {
        "rule",
        "generic_fallback_consumers",
        "unknown_metric_behavior",
        "semantics_artifact",
        "implementation_registry_artifact",
        "metric_count",
    }
    assert block["generic_fallback_consumers"] == 0
    assert block["unknown_metric_behavior"] == "SCORER_CONFIGURATION_ERROR"
    assert block["metric_count"] == 32
    assert block["semantics_artifact"] == SEMANTICS_RELATIVE
    assert block["implementation_registry_artifact"] == REGISTRY_RELATIVE
    assert "no generic fallback" in block["rule"]
    roots = values["roots"]
    assert roots["scorer_semantic_root"] == semantics_root(_semantics())
    assert len(roots["evaluator_semantic_root"]) == 64 and len(roots["protocol_root"]) == 64
    phase_apis = values["phase_apis"]
    assert phase_apis["construct"]["authorization_token"] == "T22_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
    assert phase_apis["evaluate"]["authorization_token"] == "T22_ONE_SHOT_OFFICIAL_EVALUATION"


def test_contract_candidate_identity_is_the_remediated_candidate() -> None:
    roots = _contract()["values"]["roots"]
    assert roots["candidate_commit"] == T22_CANDIDATE_COMMIT
    assert roots["candidate_tree"] == T22_CANDIDATE_TREE
    assert roots["candidate_commit"] != _r17_values()["roots"]["candidate_commit"]
    assert roots["runtime_root"] != _r17_values()["roots"]["runtime_root"]
    assert roots["candidate_provider_id"] == T22_PROVIDER_ID
    assert roots["candidate_provider_sha256"] == sha256_file(ROOT / "t21_protocol" / "providers_t22.py")
    identity = _load(IDENTITY_RELATIVE)
    assert identity["status"] == "FROZEN_PRECONSTRUCTION" and identity["experiment"] == "t22"
    new_candidate = identity["new_candidate"]
    assert new_candidate["candidate_commit"] == T22_CANDIDATE_COMMIT
    assert new_candidate["scorer_unchanged"] is True
    file_hashes = {path: sha256_file(ROOT / path) for path in new_candidate["candidate_runtime_files_sha256"]}
    assert file_hashes == new_candidate["candidate_runtime_files_sha256"]
    assert sha256_json(file_hashes) == new_candidate["candidate_runtime_identity_root"]


# --------------------------------------------------- temporal signal pins ----


def test_temporal_signal_carrier_audit_zero_gold_only() -> None:
    shadow = _load("evaluations/t22/runtime_native_shadow_validation.json")
    audit = shadow["signal_carrier_audit"]
    assert audit["temporal_rows"] == 250
    assert audit["rows_with_signal"] == 250
    assert audit["gold_only_signal_rows"] == 0
    assert audit["gold_only_signal_rows_allowed"] == 0
    assert audit["per_signal_counts"] == {
        "query_text_signal": 175,
        "request_metadata_signal": 250,
        "source_metadata_signal": 70,
    }
    assert audit["request_date"] == "2026-06-30" and audit["snapshot_date"] == "2026-01-31"
    assert audit["request_date"] > audit["snapshot_date"]


def test_row_authoring_composition_matches_frozen_design() -> None:
    design = _load(DESIGN_RELATIVE)
    shadow = _load("evaluations/t22/runtime_native_shadow_validation.json")
    composition = shadow["frozen_authoring_composition"]
    assert composition["temporal_suite"] == design["suite"]
    assert composition["record_pinned_non_temporal_rows"] == 4550
    assert composition["request_date_carrier"] == design["request_date"]["value"]
    assert composition["value_prefix"] == design["row_authoring"]["value_prefix"] == "R22"
    families = design["families"]
    assert (
        families["explicit_current"]["count"],
        families["historical_as_of"]["count"],
        families["stale_snapshot"]["count"],
        families["static_unnecessary_web"]["count"],
    ) == (70, 50, 70, 60)
    assert design["suite_total"] == 250 and design["status"] == "PREREGISTERED_PRECONSTRUCTION"
    signal_contract = _load(SIGNAL_CONTRACT_RELATIVE)
    assert signal_contract["status"] == "FROZEN_PRECONSTRUCTION" and signal_contract["experiment"] == "t22"


def test_temporal_router_qualification_gates() -> None:
    from t21_protocol.util import sha256_file as _sha256_file

    results = _load("evaluations/t22/temporal_regressions/results.json")
    assert results["battery_pass"] is True
    assert results["spec_sha256"] == _sha256_file(
        ROOT / "evaluations" / "t22" / "temporal_regressions" / "battery_spec.json"
    )
    gates = results["gates"]
    expected = {
        "explicit_current_routing_accuracy": 1.0,
        "stale_snapshot_false_current_answers": 0,
        "static_query_unnecessary_web_routing": 0.0,
        "historical_as_of_handling": 1.0,
    }
    for gate, observed in expected.items():
        assert gates[gate]["observed"] == observed and gates[gate]["pass"] is True, gate
    blindness = results["blindness"]
    assert blindness["forbidden_gold_only_keys_present"] == []
    assert blindness["candidate_runtime_inputs"] == ["query", "now (request_date)"]


def test_candidate_provider_reads_only_candidate_visible_inputs() -> None:
    source = (ROOT / "t21_protocol" / "providers_t22.py").read_text(encoding="utf-8")
    forbidden = tuple(
        pattern
        for field in ("construction_tag", "signal_class", "expected_route", "expected_status")
        for pattern in (f'row["{field}"', f'row.get("{field}"')
    )
    assert not any(pattern in source for pattern in forbidden)
    assert 'row["gold"]' not in source
    assert 'row["query"]' in source
    assert 'row.get("request_date"' in source


# ------------------------------------------------ zero-denominator pins ----


def test_zero_denominator_harmonization_frozen() -> None:
    fixtures = _load(FIXTURES_RELATIVE)
    section = fixtures["zero_denominator_harmonization"]
    assert fixtures["status"] == "PASS" and section["status"] == "PASS" and section["ok"] is True
    assert section["prose_harmonized"] is True
    assert section["policy_classes_byte_identical_to_r17"] is True
    assert section["no_retroactive_effect_on_r17"] is True
    cases = section["cases"]
    emergent = [case for case in cases if case["case"].startswith("emergent_empty")]
    refused = [case for case in cases if case["case"].startswith("design_mandated_empty")]
    assert len(emergent) == 2 and all(case["floor_pass"] and case["ok"] for case in emergent)
    assert len(refused) == 3 and all(case["refused"] and case["ok"] for case in refused)
    resolution = _load(RESOLUTION_RELATIVE)
    assert resolution["status"] == "FROZEN_PRECONSTRUCTION"
    assert resolution["frozen_policy"]["name"] == (
        "DESIGN_MANDATED_POSITIVE_POPULATIONS_WITH_RESIDUAL_EMERGENT_CONVENTION"
    )


# ------------------------------------------------------ R17 disposition ----


def test_r17_disposition_records_valid_capability_failure() -> None:
    disposition = _load("evaluations/t22/r17_final_disposition.json")
    assert disposition["status"] == "CLOSED / VALID_CAPABILITY_FAILURE"
    assert disposition["reason"] == (
        "TWO_TEMPORAL_FLOOR_METRICS_MEASURED_A_CANDIDATE_FAILURE_WITHOUT_CANDIDATE_VISIBLE_SIGNALS"
    )
    assert disposition["capability_verdict"] == "FAIL" and disposition["capability_failure"] is True
    assert disposition["failed_metrics"] == R17_FAILED_METRICS
    assert disposition["failed_metric_designation"] == "VALID_MEASUREMENTS_OF_CANDIDATE_CAPABILITY_FAILURE"
    assert disposition["holdout_status"] == "PERMANENTLY_EXPOSED_CONSUMED"
    assert disposition["rows_scored"] == 4800 and disposition["one_shot_consumed"] is True
    assert disposition["frozen_observed_values"] == {
        "explicit_current_routing_accuracy": 0.0,
        "stale_snapshot_false_current_answers": 70,
    }
    refusal = _load("evaluations/t22/r17_evaluation_refusal.json")
    assert refusal["permanent"] is True and refusal["experiment"] == "t21r17"
    preserved = disposition["official_run_preserved"]
    assert preserved["official_evaluation_commit"] == R17_EVAL_HEAD
    assert preserved["branch"] == "t21r17-official-evaluation"
    assert preserved["rerun"] == "PROHIBITED"


def test_r17_disposition_contract_block() -> None:
    block = _contract()["values"]["r17_disposition"]
    assert block["status"] == "CLOSED / VALID_CAPABILITY_FAILURE"
    assert block["capability_verdict"] == "FAIL"
    assert block["failed_metrics"] == R17_FAILED_METRICS
    assert block["failed_metric_designation"] == "VALID_MEASUREMENTS_OF_CANDIDATE_CAPABILITY_FAILURE"
    assert block["retroactive_capability_declaration"] == "FORBIDDEN"
    assert block["rerun"] == "REFUSED"
    assert block["adjudication"] == "T21R17_FINAL_ADJUDICATION_VALID_CAPABILITY_FAILURE"
    assert block["evaluation_commit"] == R17_EVAL_HEAD
    assert _contract()["values"]["r16_disposition"] == _r17_values()["r16_disposition"]


def test_r17_artifacts_unmodified() -> None:
    disposition = _load("evaluations/t22/r17_final_disposition.json")
    for relative, digest in disposition["artifact_fingerprints_sha256"].items():
        assert sha256_file(ROOT / relative) == digest, relative


def test_r17_quarantine_forbidden() -> None:
    quarantine = _contract()["values"]["quarantine"]
    assert quarantine["status"] == "FORBIDDEN"
    assert quarantine["r17_official_evaluation_reads"] == 0
    assert quarantine["r17_raw_result_reads_by_t22_material"] == 0
    assert quarantine["registry_access_only"] is True


# --------------------------------------------------- historical exclusion ----


def test_prior_exclusion_registry_17_milestones_with_r17_hash_only() -> None:
    registry = _load("evaluations/t22/prior_exclusion.json")
    assert registry["version"] == "t22-v1"
    assert registry["historical_milestone_count"] == 17
    assert registry["raw_values_included"] is False
    assert len(registry["milestones"]) == 17
    assert registry["milestone_order"][-1] == R17_HISTORICAL_MILESTONE
    milestone = registry["milestones"][R17_HISTORICAL_MILESTONE]
    provenance = milestone["provenance"]
    assert provenance["raw_values_included"] is False
    assert provenance["rows_scored"] == 4800
    assert provenance["one_shot_consumed"] is True
    assert provenance["holdout_status"] == "PERMANENTLY_EXPOSED_CONSUMED"
    assert provenance["official_evaluation_head"] == R17_EVAL_HEAD
    assert "capability failure" in provenance["measurement_note"]
    assert provenance["measurement_note"].startswith("the milestone records")
    for dimension, spec in milestone["dimensions"].items():
        assert spec["set_sha256"] and len(spec["set_sha256"]) == 64
        assert all(len(fingerprint) == 64 for fingerprint in spec["fingerprints"])


def test_historical_exclusion_policy_hash_only() -> None:
    exclusion = _load("evaluations/t22/historical_exclusion.json")
    assert exclusion["historical_milestone_count"] == 17
    assert len(exclusion["milestones"]) == 17
    assert exclusion["milestones"][-1] == R17_HISTORICAL_MILESTONE
    assert exclusion["raw_values_included"] is False
    assert exclusion["r17_protocol_history"]["blind_fingerprints_invented"] is False
    assert exclusion["r17_protocol_history"]["capability_verdict"] == "FAIL"
    assert exclusion["r17_protocol_history"]["rerun_refused"] is True


# ------------------------------------------------------- contract pins ----


def test_real_t22_paths_absent() -> None:
    values = _contract()["values"]
    present = sorted(relative for relative in values["real_t22_paths"] if (ROOT / relative).exists())
    assert present == []
    assert len(values["real_t22_paths"]) == 28


def test_contract_temporal_design_bound() -> None:
    values = _contract()["values"]
    assert values["artifacts"]["temporal_signal_contract"] == SIGNAL_CONTRACT_RELATIVE
    assert values["artifacts"]["temporal_holdout_design"] == DESIGN_RELATIVE
    assert values["artifacts"]["zero_denominator_policy_resolution"] == RESOLUTION_RELATIVE
    assert values["artifacts"]["candidate_identity"] == IDENTITY_RELATIVE
    design = _load(DESIGN_RELATIVE)
    assert set(design["blindness"]["never_candidate_visible"]) == {
        "construction_tag",
        "signal_class",
        "expected_route",
        "expected_status",
        "gold expected_answer",
    }
    temporal = values["exact_design"]["temporal"]
    assert temporal == {"explicit_current": 70, "historical_as_of": 50, "stale_snapshot": 70, "static_unnecessary_web": 60}
    assert values["suites"]["mango-t22-temporal-holdout-v1"] == {"count": 250, "family": "temporal"}


def test_metric_semantics_validation_closed_schema() -> None:
    validation = _load("evaluations/t22/metric_semantics_validation.json")
    assert validation["status"] == "PASS"
    assert validation["floor_hash_matches_frozen"] is True
    assert validation["registry_shape_ok"] is True
    assert validation["r17_semantics_carry_verified"] is True
    carry = validation["r17_semantics_carry"]
    assert carry["registry_header_only_delta"] is True
    assert carry["registry_delta_paths"] == ["artifact", "experiment"]
    assert carry["implementation_sha256_recomputed"] == 32
    assert carry["implementation_sha256_mismatches"] == []
    assert carry["prospective_only"] is True
    assert len(validation["metrics"]) == 32
    for name, problems in validation["problems"].items():
        assert not problems, (name, problems)


# ---------------------------------------------------- rehearsal evidence ----


def test_shadow_validation_zero_overlap() -> None:
    shadow = _load("evaluations/t22/runtime_native_shadow_validation.json")
    assert shadow["status"] == "PASS" and shadow["audit_mode"] == "EXECUTED"
    assert shadow["rows"] == 4800 and shadow["row_count_matches_design"] is True
    assert shadow["adapter_used"] is False and shadow["candidate_execution_rows"] == 0
    assert all(value == 0 for value in shadow["checks"].values())
    overlap = shadow["protected_dimension_overlap"]
    assert overlap["milestones_checked"] == 17
    assert overlap["total_overlaps"] == 0
    assert overlap["r17_milestone_overlap"] == 0


def test_provider_parity_t22_committed() -> None:
    parity = _load("evaluations/t22/provider_parity_report.json")
    assert parity["status"] == "PASS" and parity["audit_mode"] == "EXECUTED"
    assert parity["provider_id"] == T22_PROVIDER_ID
    assert parity["provider_init_rows"] == 0
    assert parity["provider_rows_after_execution"] == parity["rows"]
    assert parity["rows"] == 4800
    assert parity["semantic_differences"] == []
    assert parity["request_date_carrier_threaded"] is True


def test_lifecycle_rehearsal_twice_deterministic() -> None:
    lifecycle = _later_artifact("evaluations/t22/lifecycle_rehearsal.json", "lifecycle rehearsal")
    assert lifecycle["status"] == "PASS" and lifecycle["runs"] == 2
    assert lifecycle["deterministic"] is True
    assert lifecycle["real_t22_cases_exercised"] is False
    assert lifecycle["material_mode"] == "REAL_DRY_RUN"
    assert lifecycle["disposable_workspaces_destroyed"] is True
    assert lifecycle["candidate_rows_executed"] > 0
    assert lifecycle["official_evaluator_rows"] == lifecycle["candidate_rows_executed"]
    for name, differences in lifecycle["differences"].items():
        assert isinstance(differences, int) and not isinstance(differences, bool), name
        assert differences == 0, name


# ------------------------------------------------------- late-stage pins ----


def test_test_cleanliness_committed() -> None:
    cleanliness = _later_artifact("evaluations/t22/test_cleanliness.json", "test cleanliness document")
    assert cleanliness["status"] == "PASS"
    assert cleanliness["raw_full_suite"]["exit_code"] == 1
    assert cleanliness["raw_full_suite"]["unexpected_failures"] == 0
    assert cleanliness["raw_full_suite"]["missing_registered_failures"] == 0
    assert cleanliness["raw_full_suite"]["adjudication_exact_match"] is True
    assert cleanliness["applicable_suite"]["exit_code"] == 0
    assert cleanliness["focused_protocol_kernel"]["exit_code"] == 0
    assert cleanliness["test_time_unexpected_repository_writes"] == 0


def test_protocol_doctor_report_pass() -> None:
    doctor = _later_artifact("evaluations/t22/protocol_doctor_report.json", "protocol doctor report")
    assert doctor["verdict"] == "T21_PROTOCOL_DOCTOR_PASS"
    assert doctor["checks"]["r16_disposition"]["status"] == "PASS"
    assert doctor["checks"]["r17_disposition"]["status"] == "PASS"
    assert doctor["checks"]["metric_semantics_validation"]["status"] == "PASS"
    assert doctor["checks"]["temporal_signal_visibility"]["status"] == "PASS"
    assert doctor["checks"]["temporal_router_qualification"]["status"] == "PASS"
    assert doctor["checks"]["zero_denominator_harmonization"]["status"] == "PASS"
    assert doctor["checks"]["metric_semantics_lifecycle_rehearsal"]["status"] == "PASS"


def test_preconstruction_audit_verdict() -> None:
    audit = _later_artifact("evaluations/t22/T22_PRECONSTRUCTION_AUDIT.json", "preconstruction audit")
    assert audit["verdict"] == "T22_PRECONSTRUCTION_AUDIT_PASS"
    assert audit["status"] == "PASS" and audit["construction_authorized"] is False
    disposition = audit["r17_final_disposition"]
    assert disposition["status"] == "CLOSED / VALID_CAPABILITY_FAILURE"
    assert disposition["capability_verdict"] == "FAIL"
    assert disposition["failed_metrics"] == R17_FAILED_METRICS
    assert disposition["frozen_observed_values"] == {
        "explicit_current_routing_accuracy": 0.0,
        "stale_snapshot_false_current_answers": 70,
    }
    assert disposition["holdout_status"] == "PERMANENTLY_EXPOSED_CONSUMED"
    assert audit["metric_semantics"]["metric_count"] == 32
    assert audit["metric_semantics"]["no_generic_fallback"] is True
    assert audit["metric_semantics"]["unknown_metric_policy"] == "SCORER_CONFIGURATION_ERROR"
    assert audit["metric_semantics"]["zero_denominator_policy_preregistered"] is True
    harmonization = audit["zero_denominator_harmonization"]
    assert harmonization["status"] == "PASS" and harmonization["ok"] is True
    assert harmonization["prose_harmonized"] is True
    assert harmonization["no_retroactive_effect_on_r17"] is True
    assert harmonization["emergent_empty_cases_ok"] == 2
    assert harmonization["design_mandated_empty_cases_refused"] == 3
    qualification = audit["temporal_router_qualification"]
    assert qualification["battery_pass"] is True
    for gate in (
        "explicit_current_routing_accuracy",
        "stale_snapshot_false_current_answers",
        "static_query_unnecessary_web_routing",
        "historical_as_of_handling",
    ):
        assert qualification["gates"][gate]["pass"] is True, gate
    audit_signal = audit["temporal_signal_carrier_audit"]
    assert audit_signal["gold_only_signal_rows"] == 0 and audit_signal["rows_with_signal"] == 250
    assert audit["temporal_design"]["temporal_suite_total"] == 250
    assert audit["r16_regression"]["status"] == "PASS"
    assert audit["r16_regression"]["floors_passed"] == 32
    assert audit["r16_regression"]["frozen_generic_scorer_reproduces_r16_failure"] is True
    assert all(value == 0 for value in audit["scorer_closure"].values() if isinstance(value, int))
    assert audit["roots"]["floor_hash_unchanged_from_r17"] is True
    assert audit["real_t22_paths_absent"] is True
    assert audit["shadow_validation"]["total_overlap"] == 0
    assert audit["shadow_validation"]["record_pinned_non_temporal_rows"] == 4550
    assert audit["provider_parity"]["semantic_differences"] == []
    assert audit["lifecycle_rehearsal"]["real_t22_cases_exercised"] is False
    assert audit["tests"]["live_failures"] == 0 and audit["tests"]["unknown_failures"] == 0
    assert audit["tests"]["tracked_tree_drift"] == 0
    preservation = audit["r17_preservation"]
    assert preservation["sealed_holdout_unmodified"] is True
    assert preservation["r16_sealed_holdout_unmodified"] is True
    assert preservation["evaluation_permanently_refused"] is True
    assert preservation["raw_access"]["t22_artifacts_containing_raw_r17_values"] == 0
    assert preservation["frozen_observed_values"] == {
        "explicit_current_routing_accuracy": 0.0,
        "stale_snapshot_false_current_answers": 70,
    }
    assert audit["exposure_zeros"] == {
        "candidate_rows_executed": 0,
        "official_evaluator_rows": 0,
        "real_t22_rows": 0,
        "rows_scored": 0,
        "capability_verdict": "NONE",
    }
    assert audit["candidate_identity"]["repair_chain_complete"] is True


def test_preconstruction_freeze_committed() -> None:
    freeze = _later_artifact("evaluations/t22/preconstruction_freeze.json", "preconstruction freeze")
    assert freeze["status"] == "PASS"
    assert freeze["branch"] == "t22-preconstruction"
    assert freeze["construction_authorized"] is False