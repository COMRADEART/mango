"""T21R17 metric-semantics preconstruction artifact pins.

Every test reads committed preconstruction artifacts and pins the frozen
metric-semantics contract: 32 explicit per-metric semantics with no generic
fallback, unknown metrics fail closed, one-to-one implementation registry,
R16 disposition preserved verbatim, historical exclusion hash-only, zero real
R17 exposure. The module skips until the T21R17 master contract exists, so
the adjudication-time full-suite run (which precedes R17 construction)
exercises only the historically registered failure set.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r17"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

if not (OUT / "t21_master_contract.json").is_file():
    pytest.skip(
        "T21R17 master contract not yet present (preconstruction in progress)",
        allow_module_level=True,
    )

from t21_protocol.errors import ScorerConfigurationError  # noqa: E402
from t21_protocol.metric_semantics import load_metric_semantics, semantics_root  # noqa: E402
from t21_protocol.scorer_r17 import (  # noqa: E402
    IMPLEMENTATIONS,
    IMPLEMENTATION_SOURCES,
    score_explicit,
)
from t21_protocol.util import read_json, sha256_file, sha256_json  # noqa: E402

FLOOR_HASH = "4656be728db91c8a3dee0873797c52f9050b4c22d266effb265a04909ae50baa"
R16_INVALID_METRICS = ["conflict_false_resolution", "static_query_unnecessary_web_routing"]
CANDIDATE_COMMIT = "d4b1902c9b93cae4931a348e460ce2da3e776c6f"
CANDIDATE_TREE = "dc3ca7f14375e3e71356b166a2e78a24ac3f668b"
R16_OFFICIAL_EVAL_HEAD = "8d9d1be6ffeff4f249a93de876b40ed95a4e4083"
R16_HISTORICAL_MILESTONE = "T21R16_OFFICIAL_EVALUATED_MEASUREMENT_INVALID"
SEMANTICS_RELATIVE = "evaluations/t21r17/official_metric_semantics.json"
REGISTRY_RELATIVE = "evaluations/t21r17/metric_implementation_registry.json"
FIXTURES_RELATIVE = "evaluations/t21r17/metric_semantics_fixtures.json"


def _load(relative: str) -> dict:
    return read_json(ROOT / relative)


def _contract() -> dict:
    return _load("evaluations/t21r17/t21_master_contract.json")


def _r16_values() -> dict:
    return _load("evaluations/t21r16/t21_master_contract.json")["values"]


def _floors() -> dict:
    return _r16_values()["promotion_floors"]


def _floor_metrics() -> list[str]:
    return sorted(metric for group in _floors().values() for metric in group)


def _semantics() -> dict:
    return load_metric_semantics(ROOT, {}, relative=SEMANTICS_RELATIVE, floors=_floors())


def _later_artifact(relative: str, name: str):
    if not (ROOT / relative).is_file():
        pytest.skip(f"{name} not yet written (preconstruction stage pending)")
    return _load(relative)


# ------------------------------------------------- negative-control pins ----


def test_metric_semantics_fixture_battery_passes() -> None:
    fixtures = _load(FIXTURES_RELATIVE)
    assert fixtures["status"] == "PASS"
    assert fixtures["floor_hash"] == FLOOR_HASH
    sections = (
        "truth_tables",
        "monotonicity",
        "complement_confusion",
        "operator_negative_controls",
        "all_good",
        "golden_vector",
        "targeted_bad",
        "metric_independence",
        "r16_regression",
        "legacy_evaluator_parity",
        "unknown_metric_fail_closed",
    )
    assert not fixtures["failed_sections"]
    for name in sections:
        assert fixtures[name]["status"] == "PASS", name
    assert fixtures["all_good"]["floors_passed"] == 32
    assert fixtures["golden_vector"]["floors_matched"] == 32
    assert fixtures["targeted_bad"]["cases"] == 32
    assert fixtures["targeted_bad"]["single_failure"] == 32
    assert fixtures["monotonicity"]["violations"] == 0


def test_unknown_floor_metric_fails_closed() -> None:
    import t21r17_fixtures as fixtures_module

    floors = _floors()
    semantics = _semantics()
    rows = fixtures_module._all_good()
    with pytest.raises(ScorerConfigurationError):
        score_explicit(
            rows,
            {**floors, "answers": {**floors["answers"], "unregistered_metric": {"op": ">=", "value": 0.9}}},
            semantics,
        )
    with pytest.raises(ScorerConfigurationError):
        score_explicit(
            rows,
            floors,
            {**semantics, "metrics": {k: v for k, v in semantics["metrics"].items() if k != "citation_coverage"}},
        )
    with pytest.raises(ScorerConfigurationError):
        score_explicit([], floors, semantics)
    with pytest.raises(ScorerConfigurationError):
        score_explicit([r for r in rows if r["suite_family"] != "adversarial"], floors, semantics)


def test_scorer_has_no_generic_fallback_path() -> None:
    source = (ROOT / "t21_protocol" / "scorer_r17.py").read_text(encoding="utf-8")
    floor_metrics = set(_floor_metrics())
    assert set(IMPLEMENTATIONS) == floor_metrics
    assert set(IMPLEMENTATION_SOURCES) == floor_metrics
    assert all(isinstance(source_name, str) and source_name for source_name in IMPLEMENTATION_SOURCES.values())
    assert "metrics[metric] = accuracy" not in source
    assert 'in {"=", "<="}' not in source
    assert 'elif metric == "domain_macro_grounded_accuracy"' not in source
    assert "raise ScorerConfigurationError" in source
    semantics = _semantics()
    assert "no generic fallback" in semantics["rule"]


def test_metric_registry_has_no_missing_or_multiple_implementations() -> None:
    registry = _load(REGISTRY_RELATIVE)
    assert registry["implementation_count"] == 32
    assert not registry["missing_implementations"]
    assert not registry["multiple_implementations"]
    assert sorted(registry["implementations"]) == _floor_metrics()
    assert registry["scorer_module_sha256"] == sha256_file(ROOT / "t21_protocol" / "scorer_r17.py")
    for entry in registry["implementations"].values():
        assert entry.get("implementation_sha256") and entry.get("function")


# --------------------------------------------------------- frozen roots ----


def test_floor_hash_unchanged_from_r16() -> None:
    floors = _floors()
    assert sha256_json(floors) == FLOOR_HASH
    contract = _contract()
    assert contract["values"]["roots"]["floor_hash"] == FLOOR_HASH
    assert contract["values"]["roots"]["floor_hash"] == _r16_values()["roots"]["floor_hash"]
    assert _load("evaluations/t21r17/metric_semantics_validation.json")["floor_hash"] == FLOOR_HASH
    assert _load(FIXTURES_RELATIVE)["floor_hash"] == FLOOR_HASH


def test_contract_candidate_identity_unchanged_from_r16() -> None:
    roots = _contract()["values"]["roots"]
    assert roots["candidate_commit"] == CANDIDATE_COMMIT
    assert roots["candidate_tree"] == CANDIDATE_TREE
    assert roots["candidate_commit"] == _r16_values()["roots"]["candidate_commit"]
    assert roots["candidate_tree"] == _r16_values()["roots"]["candidate_tree"]
    assert roots["runtime_root"] == _r16_values()["roots"]["runtime_root"]
    assert roots["candidate_provider_id"] == "t21_protocol.providers_r17:RealCandidateProviderEvidence"
    assert roots["candidate_provider_sha256"] == sha256_file(ROOT / "t21_protocol" / "providers_r17.py")


# ------------------------------------------------- R16 final disposition ----


def test_r16_closure_records_measurement_specification_failure() -> None:
    closure = _load("evaluations/t21r16/T21R16_CLOSURE.json")
    assert closure["status"] == "CLOSED / OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE"
    assert closure["reason"] == (
        "OFFICIAL_RUN_COMPLETED_BUT_TWO_FROZEN_FLOOR_METRICS_DID_NOT_SEMANTICALLY_"
        "MEASURE_THEIR_REGISTERED_QUANTITIES"
    )
    assert closure["capability_verdict"] == "NONE"
    assert closure["capability_failure"] is False
    assert closure["invalid_metrics"] == R16_INVALID_METRICS
    assert closure["invalid_metric_designation"] == "SEMANTICALLY_INVALID_FOR_CAPABILITY_ADJUDICATION"
    assert closure["holdout_status"] == "PERMANENTLY_EXPOSED_CONSUMED"
    assert closure["rows_scored"] == 4800
    assert closure["one_shot_consumed"] is True


def test_r16_official_run_preserved_no_rerun() -> None:
    closure = _load("evaluations/t21r16/T21R16_CLOSURE.json")
    preserved = closure["official_run_preserved"]
    assert preserved["construction_commit"] == "6d5b069"
    assert preserved["official_evaluation_commit"] == R16_OFFICIAL_EVAL_HEAD
    assert preserved["branch"] == "t21r16-official-evaluation"
    assert preserved["construction_attempt"] == 1 and preserved["evaluation_attempt"] == 1
    assert preserved["rows"] == 4800 and preserved["ledger_status"] == "COMPLETE"
    assert preserved["exposures"] == 1 and preserved["floors_passed"] == 30
    assert preserved["floors_failed"] == R16_INVALID_METRICS
    assert preserved["rerun"] == "PROHIBITED"
    assert closure["rerun_policy"]["rerun_r16_evaluation"] == "REFUSED"
    assert closure["rerun_policy"]["holdout_reuse"] == "FORBIDDEN"


def test_r16_evaluation_permanently_refused() -> None:
    refusal = _load("evaluations/t21r16/evaluation_refusal.json")
    assert refusal["permanent"] is True
    assert refusal["experiment"] == "t21r16"
    assert "further T21R16 official evaluation" in refusal["refused_action"]


def test_r16_frozen_observed_values_preserved() -> None:
    closure = _load("evaluations/t21r16/T21R16_CLOSURE.json")
    score = _load("evaluations/t21r16/score_results.json")
    assert closure["frozen_observed_values"] == {metric: 1.0 for metric in R16_INVALID_METRICS}
    for metric in R16_INVALID_METRICS:
        assert score["metrics"][metric] == closure["frozen_observed_values"][metric]
    assert score["rows"] == 4800 and score["candidate_capability_pass"] is False


def test_r16_final_disposition_records_quarantine() -> None:
    disposition = _load("evaluations/t21r17/r16_final_disposition.json")
    assert disposition["status"] == "CLOSED / OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE"
    assert disposition["invalid_metrics"] == R16_INVALID_METRICS
    assert disposition["invalid_metric_designation"] == "SEMANTICALLY_INVALID_FOR_CAPABILITY_ADJUDICATION"
    assert disposition["derivation_provenance"]["r16_rows_read_by_r17_material"] == 0
    assert "quarantine §17" in disposition["derivation_provenance"]["rule"]
    assert "t21r17 official_metric_semantics" in disposition["consumers"]


# --------------------------------------------------- historical exclusion ----


def test_prior_exclusion_registry_16_milestones_with_r16_hash_only() -> None:
    registry = _load("evaluations/t21r17/prior_exclusion.json")
    assert registry["version"] == "t21r17-v1"
    assert registry["historical_milestone_count"] == 16
    assert registry["raw_values_included"] is False
    assert len(registry["milestones"]) == 16
    assert registry["milestone_order"][-1] == R16_HISTORICAL_MILESTONE
    milestone = registry["milestones"][R16_HISTORICAL_MILESTONE]
    provenance = milestone["provenance"]
    assert provenance["raw_values_included"] is False
    assert provenance["rows_scored"] == 4800
    assert provenance["one_shot_consumed"] is True
    assert provenance["holdout_status"] == "PERMANENTLY_EXPOSED_CONSUMED"
    assert provenance["official_evaluation_head"] == R16_OFFICIAL_EVAL_HEAD
    for dimension, spec in milestone["dimensions"].items():
        assert spec["set_sha256"] and len(spec["set_sha256"]) == 64
        assert all(len(fingerprint) == 64 for fingerprint in spec["fingerprints"])


def test_historical_exclusion_policy_hash_only() -> None:
    exclusion = _load("evaluations/t21r17/historical_exclusion.json")
    assert exclusion["historical_milestone_count"] == 16
    assert len(exclusion["milestones"]) == 16
    assert exclusion["milestones"][-1] == R16_HISTORICAL_MILESTONE
    assert exclusion["raw_values_included"] is False
    assert exclusion["r16_protocol_history"]["blind_fingerprints_invented"] is False
    assert exclusion["r16_protocol_history"]["capability_verdict"] == "NONE"


# ------------------------------------------------------- contract pins ----


def test_real_r17_paths_absent() -> None:
    values = _contract()["values"]
    present = sorted(relative for relative in values["real_r17_paths"] if (ROOT / relative).exists())
    assert present == []
    assert len(values["real_r17_paths"]) == 28


def test_quarantine_forbidden() -> None:
    quarantine = _contract()["values"]["quarantine"]
    assert quarantine["status"] == "FORBIDDEN"
    assert quarantine["r16_official_evaluation_reads"] == 0
    assert quarantine["r16_raw_result_reads_by_r17_material"] == 0
    assert quarantine["registry_access_only"] is True


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
    assert values["artifacts"]["official_metric_semantics"] == SEMANTICS_RELATIVE
    assert values["artifacts"]["metric_implementation_registry"] == REGISTRY_RELATIVE
    roots = values["roots"]
    assert roots["scorer_semantic_root"] == semantics_root(_semantics())
    assert len(roots["evaluator_semantic_root"]) == 64 and len(roots["protocol_root"]) == 64
    phase_apis = values["phase_apis"]
    assert phase_apis["construct"]["authorization_token"] == "T21R17_REAL_BLIND_CONSTRUCTION_AUTHORIZED"
    assert phase_apis["evaluate"]["authorization_token"] == "T21R17_ONE_SHOT_OFFICIAL_EVALUATION"


def test_contract_r16_disposition_block() -> None:
    block = _contract()["values"]["r16_disposition"]
    assert block["status"] == "CLOSED / OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE"
    assert block["capability_verdict"] == "NONE"
    assert block["invalid_metrics"] == R16_INVALID_METRICS
    assert block["invalid_metric_count"] == 2
    assert block["invalid_metric_designation"] == "SEMANTICALLY_INVALID_FOR_CAPABILITY_ADJUDICATION"
    assert block["retroactive_capability_declaration"] == "FORBIDDEN"
    assert block["rerun"] == "REFUSED"
    assert block["evaluation_permanently_refused"] is True
    assert block["holdout_status"] == "PERMANENTLY_EXPOSED_CONSUMED"


def test_metric_semantics_validation_closed_schema() -> None:
    validation = _load("evaluations/t21r17/metric_semantics_validation.json")
    assert validation["status"] == "PASS"
    assert validation["floor_hash_matches_frozen"] is True
    assert validation["registry_shape_ok"] is True
    assert len(validation["metrics"]) == 32
    for name, values in validation["problems"].items():
        assert not values, (name, values)
    for metric, entry in validation["metrics"].items():
        assert entry["metric_id"] == metric
        assert entry["numerator"] and entry["denominator"]
        assert entry["zero_denominator_policy"]
        assert entry["direction"] == {"=": "EXACT", "<=": "LOWER_IS_BETTER", ">=": "HIGHER_IS_BETTER"}[entry["operator"]]


def test_metric_semantics_entries_match_frozen_floors() -> None:
    semantics = _semantics()
    entries = semantics["metrics"]
    for group, group_floors in _floors().items():
        for metric, spec in group_floors.items():
            entry = entries[metric]
            assert entry["operator"] == spec["op"] and entry["threshold"] == spec["value"], metric
            assert entry["family"] == group, metric
            assert entry["floor_consumers"], metric


# ---------------------------------------------------- rehearsal evidence ----


def test_shadow_validation_zero_overlap() -> None:
    shadow = _load("evaluations/t21r17/runtime_native_shadow_validation.json")
    assert shadow["status"] == "PASS" and shadow["audit_mode"] == "EXECUTED"
    assert shadow["rows"] == 4800 and shadow["row_count_matches_design"] is True
    assert shadow["adapter_used"] is False and shadow["candidate_execution_rows"] == 0
    assert all(value == 0 for value in shadow["checks"].values())
    overlap = shadow["protected_dimension_overlap"]
    assert overlap["milestones_checked"] == 16
    assert overlap["total_overlaps"] == 0
    assert overlap["r16_milestone_overlap"] == 0


def test_provider_parity_evidence_committed() -> None:
    parity = _load("evaluations/t21r17/provider_parity_report.json")
    assert parity["status"] == "PASS" and parity["audit_mode"] == "EXECUTED"
    assert parity["provider_id"] == "t21_protocol.providers_r17:RealCandidateProviderEvidence"
    assert parity["provider_init_rows"] == 0
    assert parity["provider_rows_after_execution"] == parity["rows"]
    assert parity["rows"] == 4800
    assert parity["semantic_differences"] == []
    assert parity["compared_fields"] == [
        "status", "answer", "counters", "citations", "citation_report", "claim_review", "evidence_pack", "eligibility",
    ]


def test_lifecycle_rehearsal_twice_deterministic() -> None:
    lifecycle = _later_artifact("evaluations/t21r17/lifecycle_rehearsal.json", "lifecycle rehearsal")
    assert lifecycle["status"] == "PASS" and lifecycle["runs"] == 2
    assert lifecycle["deterministic"] is True
    assert lifecycle["real_r17_cases_exercised"] is False
    assert lifecycle["material_mode"] == "REAL_DRY_RUN"
    assert lifecycle["disposable_workspaces_destroyed"] is True
    assert lifecycle["candidate_rows_executed"] > 0
    assert lifecycle["official_evaluator_rows"] == lifecycle["candidate_rows_executed"]
    for name, differences in lifecycle["differences"].items():
        # T21R17_REQUALIFICATION: the typed producer contract (t21_protocol/pipeline_r17.py)
        # emits integer difference counts; 0 means zero drift. A mapping value ({}) is a
        # schema drift regression against this typed contract and must fail closed.
        assert isinstance(differences, int) and not isinstance(differences, bool), name
        assert differences == 0, name


# ------------------------------------------------------- late-stage pins ----


def test_test_cleanliness_committed() -> None:
    cleanliness = _later_artifact("evaluations/t21r17/test_cleanliness.json", "test cleanliness document")
    assert cleanliness["status"] == "PASS"
    assert cleanliness["raw_full_suite"]["exit_code"] == 1
    assert cleanliness["raw_full_suite"]["unexpected_failures"] == 0
    assert cleanliness["raw_full_suite"]["missing_registered_failures"] == 0
    assert cleanliness["raw_full_suite"]["adjudication_exact_match"] is True
    assert cleanliness["applicable_suite"]["exit_code"] == 0
    assert cleanliness["focused_protocol_kernel"]["exit_code"] == 0
    assert cleanliness["test_time_unexpected_repository_writes"] == 0


def test_protocol_doctor_report_pass() -> None:
    doctor = _later_artifact("evaluations/t21r17/protocol_doctor_report.json", "protocol doctor report")
    assert doctor["verdict"] == "T21_PROTOCOL_DOCTOR_PASS"
    metric_check = doctor["checks"]["metric_semantics_validation"]
    assert metric_check["status"] == "PASS"
    assert doctor["checks"]["r16_disposition"]["status"] == "PASS"


def test_preconstruction_audit_verdict() -> None:
    audit = _later_artifact("evaluations/t21r17/T21R17_PRECONSTRUCTION_AUDIT.json", "preconstruction audit")
    assert audit["verdict"] == "T21R17_PRECONSTRUCTION_AUDIT_PASS"
    assert audit["status"] == "PASS" and audit["construction_authorized"] is False
    assert audit["r16_final_disposition"]["status"] == "CLOSED / OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE"
    assert audit["metric_semantics"]["metric_count"] == 32
    assert audit["metric_semantics"]["no_generic_fallback"] is True
    assert audit["metric_semantics"]["unknown_metric_policy"] == "SCORER_CONFIGURATION_ERROR"
    assert audit["metric_semantics"]["zero_denominator_policy_preregistered"] is True
    regression = audit["r16_regression"]
    assert regression["status"] == "PASS"
    assert regression["overall"] == 1.0
    assert regression["conflict_false_resolution"] == 0.0
    assert regression["static_query_unnecessary_web_routing"] == 0.0
    assert regression["floors_passed"] == 32
    assert regression["frozen_generic_scorer_reproduces_r16_failure"] is True
    assert all(value == 0 for value in audit["scorer_closure"].values() if isinstance(value, int))
    assert audit["roots"]["floor_hash_unchanged_from_r16"] is True
    assert audit["real_r17_paths_absent"] is True
    assert audit["shadow_validation"]["total_overlap"] == 0
    assert audit["provider_parity"]["semantic_differences"] == []
    assert audit["lifecycle_rehearsal"]["real_r17_cases_exercised"] is False
    assert audit["tests"]["live_failures"] == 0 and audit["tests"]["unknown_failures"] == 0
    assert audit["tests"]["tracked_tree_drift"] == 0
    preservation = audit["r16_preservation"]
    assert preservation["sealed_holdout_unmodified"] is True
    assert preservation["evaluation_permanently_refused"] is True
    assert preservation["raw_access"]["r17_artifacts_containing_raw_r16_values"] == 0
    assert audit["exposure_zeros"] == {
        "candidate_rows_executed": 0,
        "official_evaluator_rows": 0,
        "real_r17_rows": 0,
        "rows_scored": 0,
        "capability_verdict": "NONE",
    }


def test_preconstruction_freeze_committed() -> None:
    freeze = _later_artifact("evaluations/t21r17/preconstruction_freeze.json", "preconstruction freeze")
    assert freeze["status"] == "PASS"
    assert freeze["branch"] == "t21r17-preconstruction"
    assert freeze["construction_authorized"] is False