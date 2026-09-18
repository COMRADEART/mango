"""T21R7 development-gate and evaluator-semantics invariants."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from sciencemath.knowledge.evaluator_semantics import (
    SCORING_SEMANTICS,
    answer_row_correct,
    scoring_semantics_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "evaluations" / "t21r7"


def _load(name: str) -> dict:
    return json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))


def test_scoring_semantics_hash_is_identical_everywhere() -> None:
    expected = scoring_semantics_sha256()
    semantics = _load("scoring_semantics.json")
    contract = _load("validation_contract.json")
    qualification = _load("evaluator_qualification.json")

    assert semantics["scoring_semantics_sha256"] == expected
    assert contract["scoring_semantics_sha256"] == expected
    assert qualification["scoring_semantics_sha256"] == expected
    assert semantics["definition"] == SCORING_SEMANTICS
    assert contract["scoring_semantics"] == SCORING_SEMANTICS


def test_qualification_matches_current_evaluator_source() -> None:
    qualification = _load("evaluator_qualification.json")
    evaluator_path = ROOT / qualification["evaluator_path"]
    assert hashlib.sha256(evaluator_path.read_bytes()).hexdigest() == \
        qualification["evaluator_source_sha256"]


def test_required_domains_is_part_of_answer_correctness() -> None:
    row = {
        "expected_status": "ANSWER",
        "status_match": True,
        "contains_ok": True,
        "citations_ok": True,
        "required_sources_ok": True,
        "required_domains_ok": False,
        "claims_supported": True,
        "counters_nonzero": [],
    }
    assert answer_row_correct(row) is False


def test_non_answer_correctness_uses_status_and_zero_tolerance() -> None:
    row = {
        "expected_status": "CONFLICTING_EVIDENCE",
        "status_match": True,
        "contains_ok": False,
        "citations_ok": False,
        "required_sources_ok": False,
        "required_domains_ok": False,
        "claims_supported": False,
        "counters_nonzero": [],
    }
    assert answer_row_correct(row) is True
    row["counters_nonzero"] = ["false_resolution"]
    assert answer_row_correct(row) is False


def test_evaluator_qualification_exceeds_gate_without_exceptions() -> None:
    qualification = _load("evaluator_qualification.json")
    assert qualification["qualification_passed"] is True
    assert qualification["all_paths_exercised"] is True
    assert qualification["uncaught_exceptions"] == 0
    assert qualification["n_cases"] >= 45
    assert qualification["n_passed"] == qualification["n_cases"]


def test_t21r6_replay_is_complete_and_non_promotional() -> None:
    replay = _load("t21r6_replay_non_promotional.json")
    assert replay["development_gate_pass"] is True
    assert replay["all_rows_executed"] is True
    assert replay["expected_rows"] == 3753
    assert replay["old_failures_remaining"] == 0
    assert replay["floors_all_pass"] is True
    assert len(replay["floors_comparison"]) == 32
    assert replay["zero_tolerance_all_zero"] is True


def test_failure_freeze_has_five_disjoint_classes_and_142_rows() -> None:
    freeze = _load("t21r6_failure_freeze.json")
    assertions = freeze["mechanical_assertions"]
    assert assertions["all_counts_match"] is True
    assert assertions["distinct_rows"] == 142
    assert sorted(assertions["actual_counts"].values()) == [3, 5, 28, 42, 64]
    assert freeze["classification_contract"]["classes_are_disjoint"] is True
