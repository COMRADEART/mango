"""Mechanical preregistration checks for the qualified T21R8 evaluator."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r8_run_eval as evaluator  # noqa: E402


OUT_DIR = ROOT / "evaluations" / "t21r8"
SEMANTICS_PATH = OUT_DIR / "scoring_semantics.json"
CONTRACT_PATH = OUT_DIR / "validation_contract.json"
QUALIFICATION_PATH = OUT_DIR / "evaluator_qualification.json"
EXPECTED_SEMANTICS_SHA256 = \
    "47ff909a2f7db41334833faba195d777d6192c30bfa73b521f3c8b793be8ccbd"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scoring_semantics_file_is_the_single_preregistered_source() -> None:
    document = _json(SEMANTICS_PATH)
    assert document["milestone"] == "T21R8"
    assert "single_source_note" in document
    canonical = json.dumps(
        document["definition"], sort_keys=True, separators=(",", ":"),
        ensure_ascii=True)
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == \
        EXPECTED_SEMANTICS_SHA256
    assert document["scoring_semantics_sha256"] == EXPECTED_SEMANTICS_SHA256


def test_validation_contract_binds_the_same_semantics() -> None:
    contract = _json(CONTRACT_PATH)
    semantics = _json(SEMANTICS_PATH)
    assert contract["scoring_semantics"] == semantics["definition"]
    assert contract["scoring_semantics_sha256"] == EXPECTED_SEMANTICS_SHA256
    assert contract["scoring_semantics_path"] == \
        "evaluations/t21r8/scoring_semantics.json"


def test_evaluator_derives_correctness_from_the_file_semantics() -> None:
    assert evaluator.scoring_semantics_sha256() == EXPECTED_SEMANTICS_SHA256
    assert evaluator.validate_semantics_artifacts(
        _json(CONTRACT_PATH)) == EXPECTED_SEMANTICS_SHA256


def test_evaluator_source_matches_the_qualified_source() -> None:
    qualification = _json(QUALIFICATION_PATH)
    expected = _sha256_file(ROOT / "scripts" / "t21r8_run_eval.py")
    assert qualification["evaluator_source_sha256"] == expected
    assert qualification["evaluator_path"] == "scripts/t21r8_run_eval.py"


def test_qualification_passed_every_recorded_case() -> None:
    qualification = _json(QUALIFICATION_PATH)
    assert qualification["n_cases"] >= 55
    assert qualification["n_passed"] == qualification["n_cases"]
    assert qualification["all_cases_pass"] is True
    assert qualification["qualification_passed"] is True
    assert qualification["all_metric_paths_exercised"] is True
    assert qualification["uncaught_exceptions"] == 0
    assert qualification["scoring_semantics_sha256"] == \
        EXPECTED_SEMANTICS_SHA256
    assert qualification["groups"], "qualification groups must be recorded"


def test_qualification_covers_the_official_conjunction_and_groups() -> None:
    qualification = _json(QUALIFICATION_PATH)
    semantics = _json(SEMANTICS_PATH)["definition"]
    case_ids = {case["id"] for case in qualification["cases"]}
    assert "r8-03" in case_ids, "conjunction case must be qualified"
    assert "r8-28" in case_ids, "absent-entity precedence must be qualified"
    conjunction = semantics["answer_row_correctness"]["conjunction"]
    assert "citations_ok" in conjunction
    assert "required_domains_ok" in conjunction
    assert "zero_tolerance_all_zero" in conjunction


def test_qualification_rejects_an_unknown_conjunct() -> None:
    raw = {"status_match": True, "contains_ok": True, "citations_ok": True,
           "required_sources_ok": True, "required_domains_ok": True,
           "claims_supported": True, "counters_nonzero": []}
    with pytest.raises(SystemExit, match="T21R8_EVALUATOR_INVALID"):
        evaluator._check_conjunction(["unknown_conjunct"], raw)


def test_qualification_is_not_an_evaluator_freeze() -> None:
    assert not (OUT_DIR / "evaluator_freeze.json").exists()
    assert not (OUT_DIR / "runtime_freeze.json").exists()
    assert not (OUT_DIR / "HOLDOUT_FROZEN").exists()


def test_official_command_is_preregistered_without_execution() -> None:
    contract = _json(CONTRACT_PATH)
    official = contract["official_evaluation"]
    assert official["official_command"] == "python scripts/t21r8_official_eval.py"
    assert official["official_runner"] == "scripts/t21r8_official_eval.py"
    assert "one_shot_rule" in official
    # The wrapper may exist, but it must never have been executed: no
    # official-run artifact may exist in this phase.
    for artifact in ("evaluation_run_ledger.json", "raw_results.jsonl",
                     "holdout_results.json"):
        assert not (OUT_DIR / artifact).exists()