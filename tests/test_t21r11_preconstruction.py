"""Focused gates for T21R11 preregistration/preconstruction qualification."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r11"
sys.path.insert(0, str(ROOT / "scripts"))

import t21r11_blindness_audit as blindness  # noqa: E402
import t21r11_build_suites as suites  # noqa: E402
import t21r11_freeze_holdout as freeze  # noqa: E402
import t21r11_preconstruction as qualification  # noqa: E402
import t21r11_retrieval_mirror as retrieval  # noqa: E402
import t21r11_spec_author as author  # noqa: E402
import t21r11_uniqueness as uniqueness  # noqa: E402
import t21r11_world as world  # noqa: E402


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def test_required_preconstruction_artifacts_exist() -> None:
    required = {
        "preregistration.json", "validation_contract.json",
        "scoring_semantics.json", "holdout_construction_contract.json",
        "prior_exclusion.json", "remediation_exclusion.json",
        "runtime_freeze.json", "evaluator_freeze.json",
        "blindness_policy.json", "synthetic_protocol_report.json",
        "preconstruction_qualification.json", "remediation_provenance.json",
    }
    assert not sorted(name for name in required if not (OUT / name).is_file())


def test_project_states_are_open_experimental_and_blocked() -> None:
    prereg = _json(OUT / "preregistration.json")
    assert prereg["states"] == author.STATES
    assert prereg["promotion_authorized"] is False
    assert prereg["real_blind_construction_authorized"] is False
    assert prereg["official_blind_status"] == "NOT_BUILT"


def test_all_seven_hypotheses_are_preregistered() -> None:
    hypotheses = _json(OUT / "preregistration.json")["hypotheses"]
    assert set(hypotheses) == {
        "H1_RETRIEVAL", "H2_MULTIHOP", "H3_CROSS_DOMAIN",
        "H4_CONFLICT", "H5_ABSTENTION", "H6_CITATIONS",
        "H7_REGRESSION_PROTECTION",
    }


def test_exact_suite_names_counts_and_total_are_frozen() -> None:
    prereg = _json(OUT / "preregistration.json")
    assert prereg["suite_target_exact"] == author.SUITE_TARGETS
    assert prereg["total_rows_exact"] == 4800
    assert sorted(prereg["suite_target_exact"].values()) == sorted(
        [600, 550, 800, 700, 450, 800, 250, 650])


def test_all_32_floors_are_canonical_identical_to_r10() -> None:
    r11 = _json(OUT / "validation_contract.json")
    r10 = _json(ROOT / "evaluations" / "t21r10" /
                "validation_contract.json")
    assert sum(len(group) for group in r11["floors"].values()) == 32
    assert _canonical(r11["floors"]) == _canonical(r10["floors"])
    assert r11["floor_difference"] == []
    assert r11["floor_canonical_sha256"] == hashlib.sha256(
        _canonical(r10["floors"])).hexdigest()


def test_one_shot_semantics_fail_closed() -> None:
    rules = _json(OUT / "preregistration.json")["one_shot"]
    assert rules == {
        "existing_ledger": "REFUSE", "existing_raw": "REFUSE",
        "existing_results": "REFUSE", "failed_run": "PERMANENT",
        "automatic_retry": "FORBIDDEN",
    }


def test_prior_exclusion_is_hash_only_11_by_8() -> None:
    artifact = _json(OUT / "prior_exclusion.json")
    decoded = uniqueness.validate_artifact(artifact)
    assert artifact["raw_values_included"] is False
    assert tuple(decoded) == uniqueness.MILESTONES
    assert len(decoded) == 11
    assert all(set(value) == set(uniqueness.DIMENSIONS)
               for value in decoded.values())
    assert len(uniqueness.DIMENSIONS) == 8


def test_r10_is_preserved_as_consumed_historical_exclusion() -> None:
    r10 = _json(OUT / "prior_exclusion.json")["milestones"][
        "T21R10_SEALED"]
    assert r10["sealed_commit"] == \
        "9f63d94ecd68299f0397e98048bb29bef937220d"
    assert r10["official_commit"] == \
        "247f13656a8392472b0c669d6e1c113071979a62"
    assert r10["official_result"] == "T21R10_OFFICIAL_EVALUATION_FAIL"
    assert r10["raw_material_committed"] is False


def test_open_remediation_exclusion_is_hash_only_and_complete() -> None:
    artifact = _json(OUT / "remediation_exclusion.json")
    decoded = uniqueness.validate_remediation_artifact(artifact)
    assert artifact["class"] == "OPEN_REMEDIATION_MATERIAL"
    assert artifact["raw_values_included"] is False
    assert set(decoded) == set((*uniqueness.DIMENSIONS, "relations"))
    assert all(values for values in decoded.values())
    assert {entry["path"] for entry in artifact["source_artifacts"]} >= {
        "evaluations/t21r11_diagnostics/dev_suites.jsonl",
        "evaluations/t21r11_diagnostics/validation_suites.jsonl",
        "tests/test_t21r11_remediation.py",
    }


def test_candidate_runtime_freeze_identity_and_scope() -> None:
    runtime = _json(OUT / "runtime_freeze.json")
    identity = runtime["identity"]
    candidate = "d4b1902c9b93cae4931a348e460ce2da3e776c6f"
    candidate_tree = "dc3ca7f14375e3e71356b166a2e78a24ac3f668b"
    assert identity["branch"] == "t21r11-clean-seal"
    assert identity["HEAD"] == candidate
    assert identity["candidate_commit"] == candidate
    assert identity["parent"] == \
        "247f13656a8392472b0c669d6e1c113071979a62"
    assert identity["candidate_base"] == identity["parent"]
    assert identity["tree_sha"] == candidate_tree
    assert identity["candidate_tree"] == candidate_tree
    assert identity["HEAD"] != identity["parent"]
    assert identity["working_tree"] == "CLEAN"
    assert identity["working_tree_status"] == []
    assert set(runtime["changed_production_files"]) == set(
        qualification.CHANGED_PRODUCTION_FILES)
    assert len(runtime["component_sha256"]) == 15
    assert len(runtime["components"]) == 15
    assert runtime["auto_refresh"] is False
    assert runtime["fallback"] is False
    for component in runtime["components"]:
        assert component["candidate_commit"] == candidate
        assert component["candidate_tree"] == candidate_tree
        assert component["sha256"] == runtime["component_sha256"][
            component["path"]]


def test_runtime_freeze_rehashes_every_component() -> None:
    report = freeze.verify_component_freeze(
        ROOT, OUT / "runtime_freeze.json", "T21R11_RUNTIME_FREEZE")
    assert report["status"] == "VERIFIED"
    assert report["verified_components"] == len(
        qualification.RUNTIME_COMPONENTS)
    runtime = _json(OUT / "runtime_freeze.json")
    for relative, expected in runtime["component_sha256"].items():
        assert _sha(ROOT / relative) == expected


def test_evaluator_freeze_rehashes_every_component() -> None:
    report = freeze.verify_component_freeze(
        ROOT, OUT / "evaluator_freeze.json", "T21R11_EVALUATOR_FREEZE")
    assert report["status"] == "VERIFIED"
    evaluator = _json(OUT / "evaluator_freeze.json")
    assert set(evaluator["required_components"]) == {
        "validation_contract", "scoring_semantics", "construction_contract",
        "official_evaluator", "retrieval_mirror", "official_runner",
    }
    assert evaluator["auto_refresh"] is False
    assert evaluator["fallback"] is False


def test_component_freeze_rejects_one_byte_drift(tmp_path: Path) -> None:
    component = tmp_path / "component.txt"
    component.write_text("before\n", encoding="utf-8")
    artifact = tmp_path / "freeze.json"
    artifact.write_text(json.dumps({
        "artifact": "T21R11_RUNTIME_FREEZE", "status": "FROZEN",
        "runtime_execution_count": 0,
        "component_sha256": {"component.txt": _sha(component)},
    }), encoding="utf-8")
    component.write_text("before!\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        freeze.verify_component_freeze(
            tmp_path, artifact, "T21R11_RUNTIME_FREEZE")


def test_remediation_provenance_binds_every_production_change() -> None:
    artifact = _json(OUT / "remediation_provenance.json")
    changes = artifact["changes"]
    assert {change["file"] for change in changes} == set(
        qualification.CHANGED_PRODUCTION_FILES)
    assert artifact["raw_t21r10_blind_content_included"] is False
    assert all(change["sha256"] == _sha(ROOT / change["file"])
               for change in changes)
    assert all(change["open_diagnostic_evidence"] and
               change["validation_evidence"] and
               change["tests_protecting_behavior"] for change in changes)


def test_builder_firewall_has_no_import_call_or_leakage_findings() -> None:
    report = blindness.audit_scripts(ROOT)
    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["candidate_leakage"] == []
    assert report["historical_blind_leakage"] == []
    assert report["remediation_validation_leakage"] == []


def test_world_builder_refuses_wrong_namespace_and_disposable_real_ids() -> None:
    spec = qualification.synthetic_world_spec()
    with pytest.raises(ValueError, match="disposable"):
        world.validate_world_spec(spec)
    wrong = copy.deepcopy(spec)
    wrong["namespace"] = "not-r11"
    with pytest.raises(ValueError, match="namespace"):
        world.validate_world_spec(wrong, qualification_disposable=True)


def test_suite_builder_refuses_duplicates_and_manual_windows() -> None:
    contract = qualification.miniature_contract()
    spec = qualification.synthetic_suite_spec()
    duplicate = copy.deepcopy(spec)
    duplicate["rows"][1]["case_id"] = duplicate["rows"][0]["case_id"]
    with pytest.raises(ValueError, match="unique"):
        suites.validate_suite_spec(duplicate, contract)
    window = copy.deepcopy(spec)
    window["rows"][0]["construction"] = {
        "initial_window_chunk_ids": ["pre11q-chunk-quartz"]}
    with pytest.raises(ValueError, match="initial retrieval windows"):
        suites.validate_suite_spec(window, contract)


def test_retrieval_window_is_independently_derived() -> None:
    chunks = qualification.synthetic_world_spec()["chunks"]
    trace = retrieval.derive_initial_window(
        "What is the Pre11q Quartz Subject qualification value?", chunks)
    assert trace.chunk_ids == ["pre11q-chunk-quartz"]
    assert trace.to_dict()["top_k"] == 8


def test_temporal_and_security_regression_allocations_are_frozen() -> None:
    contract = _json(OUT / "holdout_construction_contract.json")
    assert contract["temporal_exact_design"] == {
        "explicit_current": 70, "stale_snapshot": 70,
        "static_unnecessary_web": 60, "historical_as_of": 50,
    }
    assert sum(contract["security_exact_design"].values()) == 650
    assert set(contract["security_exact_design"]) == {
        "prompt_injection", "citation_id_spoof",
        "source_authority_escalation", "memory_backfill",
        "retrieved_code_execution", "unauthorized_network",
        "unauthorized_memory_write",
    }


def test_synthetic_protocol_all_registered_stages_pass() -> None:
    report = _json(OUT / "synthetic_protocol_report.json")
    assert report["status"] == "PASS"
    expected = {
        "world_construction", "corpus_load", "suite_construction",
        "uniqueness", "prior_exclusion", "open_remediation_exclusion",
        "retrieval_semantics", "conflict_semantics", "citation_semantics",
        "spoof_handling", "blindness", "component_freeze",
        "seal_generation", "official_preflight",
    }
    assert set(report["stages"]) == expected
    assert all(stage["status"] == "PASS"
               for stage in report["stages"].values())


def test_exact_twenty_negative_controls_pass_by_rejection() -> None:
    report = _json(OUT / "synthetic_protocol_report.json")
    controls = report["negative_controls"]
    assert tuple(control["name"] for control in controls) == \
        qualification.NEGATIVE_CONTROL_NAMES
    assert len(controls) == 20
    assert all(control["status"] == "PASS" for control in controls)
    assert report["negative_control_passed_count"] == 20


def test_synthetic_rehearsal_deleted_and_executed_no_r11_rows() -> None:
    report = _json(OUT / "synthetic_protocol_report.json")
    assert report["synthetic_workspace_deleted"] is True
    assert report["real_R11_rows"] == 0
    assert report["candidate_R11_rows_executed"] == 0
    assert report["official_evaluator_invocations"] == 0
    assert report["official_preflight_runtime_rows"] == 0


def test_every_real_r11_blind_and_exposure_path_is_absent() -> None:
    audit = qualification.real_path_audit()
    assert audit["status"] == "PASS"
    assert audit["present"] == []
    assert audit["absent_count"] == len(author.PROHIBITED_REAL_PATHS) == 7


def test_validation_claim_is_explicitly_non_official() -> None:
    claim = _json(OUT / "preregistration.json")[
        "remediation_evidence_interpretation"]
    assert claim["DEV"] == "OPEN"
    assert claim["VALIDATION"] == "FROZEN_INTERNAL_VALIDATION"
    assert claim["OFFICIAL_BLIND"] == "NOT_BUILT"
    assert "no official capability claim" in claim["claim"]
