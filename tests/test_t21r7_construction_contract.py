"""Mechanical preregistration checks for T21R7 blind construction."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r7_construction_gate as gate  # noqa: E402
import t21r7_construction_audit as construction_audit  # noqa: E402
import t21r7_freeze as freeze  # noqa: E402


CONTRACT_PATH = (
    ROOT / "evaluations" / "t21r7" / "holdout_construction_contract.json"
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _passing_metrics() -> dict:
    contract = _json(CONTRACT_PATH)
    return {
        "annotation_violations": 0,
        "total_rows": 4200,
        "suite_rows": {
            name: rule["minimum"]
            for name, rule in contract["suite_target_minimums"].items()
        },
        "stresses": {
            "relation_paraphrase_sensitive_rows": 500,
            "canonical_relations": [f"RELATION_{index:02d}"
                                    for index in range(12)],
            "relation_surface_mismatch_rows": 200,
            "qualifier_sensitive_rows": 200,
            "non_binding_qualifier": 100,
            "identity_critical_qualifier": 100,
            "routing_boundary_rows": 180,
            "absent_entity_conflict_stress_rows": 180,
            "source_injection_safe_fact_rows": 200,
            "query_injection_or_spoof_rows": 200,
        },
        "independence": {
            milestone: {dimension: 0 for dimension in
                        contract["independence_requirements"][
                            "zero_overlap_dimensions"]}
            for milestone in contract["independence_requirements"][
                "comparison_milestones"]
        },
    }


def test_contract_preregisters_exact_required_minima() -> None:
    contract = _json(CONTRACT_PATH)
    assert contract["total_rows"] == {"minimum": 4200, "op": ">="}
    assert {name: rule["minimum"] for name, rule in
            contract["suite_target_minimums"].items()} == {
        "retrieval": 600,
        "singlehop": 550,
        "multihop": 550,
        "crossdomain": 450,
        "citation_claim": 450,
        "conflict_abstention": 750,
        "temporal": 250,
        "adversarial": 600,
    }
    stress = contract["stress_requirements"]
    assert stress["relation_paraphrase_sensitive_rows"]["minimum"] == 500
    assert stress["canonical_relations_covered"]["minimum"] == 12
    assert stress["relation_surface_mismatch_fraction"]["minimum"] == 0.40
    assert stress["qualifier_sensitive_rows"]["minimum"] == 200
    assert stress["non_binding_qualifier"]["minimum"] == 100
    assert stress["identity_critical_qualifier"]["minimum"] == 100
    assert stress["routing_boundary_rows"]["minimum"] == 180
    assert stress["absent_entity_conflict_stress_rows"]["minimum"] == 180
    assert stress["source_injection_safe_fact_rows"]["minimum"] == 200
    assert stress["query_injection_or_spoof_rows"]["minimum"] == 200
    assert stress["fresh_attack_wording"]["required"] is True
    enforcement = contract["static_enforcement"]
    assert enforcement["audit_must_record_every_requirement"] is True
    assert enforcement["freeze_must_recompute_metrics_from_candidate_files"] \
        is True
    assert enforcement["freeze_must_refuse_incomplete_or_failed_audit"] is True


def test_independence_matrix_is_seven_by_eight_and_zero_overlap() -> None:
    independence = _json(CONTRACT_PATH)["independence_requirements"]
    assert independence["comparison_milestones"] == [
        "T21", "T21R", "T21R2", "T21R3", "T21R4", "T21R5", "T21R6",
    ]
    assert independence["zero_overlap_dimensions"] == [
        "case_ids", "entity_identities", "source_ids", "chunk_ids",
        "exact_queries", "exact_answers", "exact_source_text",
        "verbatim_attacks",
    ]
    assert independence["maximum_overlap"] == 0


def test_capability_floors_and_existing_suite_minimums_are_unchanged() -> None:
    r6 = _json(ROOT / "evaluations" / "t21r6" / "validation_contract.json")
    r7 = _json(ROOT / "evaluations" / "t21r7" / "validation_contract.json")
    assert r7["floors"] == r6["floors"]
    assert sum(len(group) for group in r7["floors"].values()) == 32
    assert r7["suite_minimums"] == {
        key.replace("t21r6", "t21r7"): value
        for key, value in r6["suite_minimums"].items()
    }


def test_gate_evaluates_every_requirement_and_accepts_exact_minima() -> None:
    contract = _json(CONTRACT_PATH)
    checks = gate.evaluate_metrics(contract, _passing_metrics())
    assert len(checks) == 79
    assert len({check["id"] for check in checks}) == len(checks)
    assert all(check["passed"] for check in checks)
    independence_checks = [check for check in checks
                           if check["id"].startswith("independence.")]
    assert len(independence_checks) == 7 * 8


@pytest.mark.parametrize(
    ("metric", "bad_value"),
    [
        ("relation_paraphrase_sensitive_rows", 499),
        ("qualifier_sensitive_rows", 199),
        ("non_binding_qualifier", 99),
        ("identity_critical_qualifier", 99),
        ("routing_boundary_rows", 179),
        ("absent_entity_conflict_stress_rows", 179),
        ("source_injection_safe_fact_rows", 199),
        ("query_injection_or_spoof_rows", 199),
    ],
)
def test_gate_rejects_each_underfilled_stress(metric: str,
                                              bad_value: int) -> None:
    contract = _json(CONTRACT_PATH)
    metrics = _passing_metrics()
    metrics["stresses"][metric] = bad_value
    checks = gate.evaluate_metrics(contract, metrics)
    assert not next(check for check in checks
                    if check["id"] == f"stress.{metric}")["passed"]


def test_gate_rejects_relation_coverage_and_surface_fraction_shortfalls() \
        -> None:
    contract = _json(CONTRACT_PATH)
    metrics = _passing_metrics()
    metrics["stresses"]["canonical_relations"] = [f"R{i}" for i in range(11)]
    metrics["stresses"]["relation_surface_mismatch_rows"] = 199
    checks = {check["id"]: check for check in
              gate.evaluate_metrics(contract, metrics)}
    assert checks["stress.canonical_relations_covered"]["passed"] is False
    assert checks["stress.relation_surface_mismatch_fraction"]["passed"] \
        is False


def test_gate_rejects_every_independence_overlap_including_attacks() -> None:
    contract = _json(CONTRACT_PATH)
    metrics = _passing_metrics()
    metrics["independence"]["T21R6"]["exact_queries"] = 1
    metrics["independence"]["T21"]["verbatim_attacks"] = 1
    checks = {check["id"]: check for check in
              gate.evaluate_metrics(contract, metrics)}
    assert checks["independence.T21R6.exact_queries"]["passed"] is False
    assert checks["independence.T21.verbatim_attacks"]["passed"] is False
    assert checks["stress.fresh_attack_wording"]["passed"] is False


def test_static_audit_validation_recomputes_and_detects_tampering() -> None:
    section = gate.build_audit_section(_passing_metrics())
    audit = {"status": "PASS", "construction_contract": section}
    assert gate.validate_static_audit(audit)["status"] == "PASS"

    tampered = deepcopy(audit)
    tampered["construction_contract"]["checks"].pop()
    with pytest.raises(ValueError, match="missing, stale, or tampered"):
        gate.validate_static_audit(tampered)


def test_static_audit_validation_rejects_a_failed_requirement() -> None:
    metrics = _passing_metrics()
    metrics["suite_rows"]["adversarial"] = 599
    metrics["total_rows"] = 4199
    section = gate.build_audit_section(metrics)
    audit = {"status": "PASS", "construction_contract": section}
    with pytest.raises(ValueError, match="requirements failed"):
        gate.validate_static_audit(audit)


def test_freeze_refuses_when_construction_audit_is_not_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freeze, "_require_prerequisites", lambda: None)

    def reject():
        raise ValueError("missing requirement")

    monkeypatch.setattr(freeze, "assert_static_audit_passes", reject)
    with pytest.raises(SystemExit, match="not a complete PASS"):
        freeze.main()
    assert not freeze.MARKER.exists()


def test_freeze_recomputes_candidate_metrics_and_rejects_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freeze, "_require_prerequisites", lambda: None)
    monkeypatch.setattr(
        freeze, "assert_static_audit_passes",
        lambda: {"metrics": _passing_metrics()},
    )
    measured = _passing_metrics()
    measured["total_rows"] += 1
    monkeypatch.setattr(
        freeze, "measure_candidate",
        lambda: {"metrics": measured, "annotation_violation_details": []},
    )
    with pytest.raises(SystemExit, match="differ from the static audit"):
        freeze.main()
    assert not freeze.MARKER.exists()


def test_construction_scanner_is_data_only_and_uses_literal_boundaries() \
        -> None:
    source = (ROOT / "scripts" / "t21r7_construction_audit.py").read_text(
        encoding="utf-8")
    assert "sciencemath" not in source
    assert construction_audit._contains_phrase(
        "The record says it was published in 1901.", "published")
    assert not construction_audit._contains_phrase(
        "The republished edition dates to 1901.", "published")


def test_no_r7_blind_material_exists_during_preregistration() -> None:
    assert not (ROOT / "evaluations" / "t21r7" / "HOLDOUT_FROZEN").exists()
    assert not (ROOT / "rag" / "gk_holdout_t21r7").exists()
