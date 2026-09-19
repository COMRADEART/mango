"""Focused T21R12 contract/gate preconstruction tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r12_exact_design_lib as ed
import t21r12_fixtures as fx

OUT = ROOT / "evaluations" / "t21r12"


@pytest.fixture(scope="module")
def contract():
    return json.loads((OUT / "holdout_construction_contract.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def coverage():
    return json.loads((OUT / "contract_gate_coverage.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema():
    return json.loads((OUT / "exact_design_schema.json").read_text(encoding="utf-8"))


def test_all_contract_leaves_wired(schema, coverage):
    assert schema["unhandled_leaves"] == 0
    assert coverage["unwired_requirements"] == 0
    assert coverage["covered"] == coverage["leaf_requirements_registered"]
    assert coverage["coverage_percent"] == 100.0


def test_unknown_contract_leaf_fails(contract):
    bad = json.loads(json.dumps(contract))
    bad["citation_exact_design"]["not_a_real_leaf"] = 1
    with pytest.raises(ValueError, match="unknown contract fields"):
        ed.enumerate_leaves(bad)


def test_missing_tag_fails_count(contract):
    result = ed.check_exact_design_count(60, [], "wrong_locator")
    assert result["passed"] is False
    assert result["observed"] == 0


def test_extra_unknown_tag_fails(contract):
    rows = [{"construction_tags": ["wrong_locator", "totally_unknown_tag"]}]
    report = ed.evaluate_exact_design(
        contract, rows, {"prior_pair_template_overlap": 0, "prior_exact_query_overlap": 0})
    assert report["unknown_construction_tags"]
    assert report["status"] == "FAIL"


def test_off_by_one_exact_count_fails(contract):
    rows = [{"case_id": f"x{i}", "construction_tags": ["wrong_locator"]} for i in range(59)]
    result = ed.check_exact_design_count(60, rows, "wrong_locator")
    assert result["passed"] is False
    assert result["observed"] == 59


def test_boolean_inversion_fails(contract):
    result = ed.check_forbidden_overlap(
        True, {"prior_pair_template_overlap": 1}, "prior_exact_pair_templates_forbidden")
    assert result["passed"] is False


def test_forbidden_overlap_fails(contract):
    result = ed.check_forbidden_overlap(
        True, {"prior_exact_query_overlap": 3}, "prior_exact_pair_templates_forbidden")
    assert result["passed"] is False


def test_valid_synthetic_fixture_passes(contract):
    rows = fx.make_valid_fixture(contract)
    report = ed.evaluate_exact_design(
        contract, rows, {"prior_pair_template_overlap": 0, "prior_exact_query_overlap": 0})
    assert report["status"] == "PASS"
    assert report["failed"] == 0
    assert report["unhandled"] == 0


def test_r11_closure_tombstone_present():
    closure = json.loads(
        (ROOT / "evaluations/t21r11/T21R11_CLOSURE.json").read_text(encoding="utf-8"))
    assert closure["status"] == "CLOSED_INVALID_UNEVALUATED_HOLDOUT"
    assert closure["official_evaluation_policy"] == "T21R11_OFFICIAL_EVALUATION_PERMANENTLY_REFUSED"


def test_real_r12_paths_absent():
    assert not (ROOT / "rag" / "gk_holdout_t21r12").exists()
    assert not (OUT / "suites").exists()
    assert not (OUT / "holdout_manifest.json").exists()
    assert not (OUT / "HOLDOUT_FROZEN").exists()
    assert not (OUT / "evaluation_run_ledger.json").exists()


def test_prior_exclusion_includes_r11_invalid():
    prior = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    assert "T21R11_INVALID_SEALED" in prior["milestones"]
    assert prior["historical_milestones"] == 12
    assert len(prior["milestone_order"]) == 12


def test_floors_unchanged():
    r11 = json.loads(
        (ROOT / "evaluations/t21r11/validation_contract.json").read_text(encoding="utf-8"))
    r12 = json.loads((OUT / "validation_contract.json").read_text(encoding="utf-8"))
    assert r12["promotion_floor_count"] == 32
    assert r12["floor_canonical_sha256"] == r11["floor_canonical_sha256"]
    assert r12.get("floor_difference_vs_t21r11") == 0
