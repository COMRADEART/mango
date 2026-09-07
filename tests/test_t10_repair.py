"""T10 tests: bounded repair trajectory, safety gates, method labels,
v2 suite integrity, final-set isolation, collateral-change scoring."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.evaluation.correction_metrics import (  # noqa: E402
    correction_metrics_v2,
)
from sciencemath.evaluation.extraction import answers_match  # noqa: E402
from sciencemath.executive.repair import (  # noqa: E402
    MAX_REPAIR_ATTEMPTS,
    complete_unit,
    splice_part,
    t10_repair_trajectory,
)

V2 = ROOT / "evaluations/t10/correction-suite/v2"


def run(**kw):
    base = dict(question="Q", initial_answer="5/10",
                expected_type="short_answer",
                feedback_source="MATH_TOOL", failed_component="numeric_result",
                evidence="3/4 + 2/6 = 13/12", feedback_status="FAIL",
                original_correct=False, repair=None)
    base.update(kw)
    return t10_repair_trajectory(**base)


# ------------------------------------------------------------- safety gates
def test_deterministic_patch_no_llm_call():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return "anything"

    traj = run(repair=repair, expected="13/12")
    assert calls == []  # T10.11 — no LLM repair when value is tool-verified
    assert traj["final_answer"] == "13/12"
    assert traj["repair_method"] == "DETERMINISTIC_PATCH"
    assert traj["repair_attempts"] == 0
    assert traj["correction_decision"] == "ACCEPT"
    assert traj["feedback_trust"] == "VERIFIED"


def test_no_repair_when_original_correct():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return "x"

    traj = run(original_correct=True, repair=repair, expected="5/10")
    assert calls == []
    assert traj["correction_decision"] == "REJECT"
    assert traj["repair_method"] == "REJECT"
    assert traj["final_answer"] == "5/10"


def test_unverified_feedback_deferred_no_attempt():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return "x"

    traj = run(feedback_source="UNVERIFIED_MODEL_FEEDBACK",
               feedback_status="UNKNOWN", repair=repair)
    assert calls == []  # T10.10 — no attempt at all on UNVERIFIED feedback
    assert traj["correction_decision"] == "DEFER"
    assert traj["repair_method"] == "DEFER"
    assert traj["repair_evidence_strength"] == "none"


def test_contradicted_feedback_rejected_no_attempt():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return "x"

    traj = run(feedback_status="PASS", repair=repair)
    assert calls == []
    assert traj["correction_decision"] == "REJECT"
    assert traj["repair_method"] == "REJECT"


# --------------------------------------------------- bounded escalation
def test_two_attempt_limit_and_escalation():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return "9/12"  # never correct

    traj = run(repair=repair, feedback_source="RETRIEVAL_EVIDENCE",
               expected="13/12")
    assert len(calls) == MAX_REPAIR_ATTEMPTS == 2
    assert traj["repair_attempts"] == 2
    assert traj["repair_method"] == "LLM_REPAIR_2"
    assert traj["escalation_used"] is True
    assert traj["correction_decision"] == "REJECT"
    assert traj["final_answer"] == "5/10"  # reverted, original preserved


def test_second_attempt_only_after_failed_reverify():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return "13/12"

    traj = run(repair=repair, feedback_source="RETRIEVAL_EVIDENCE",
               expected="13/12")
    assert len(calls) == 1  # first attempt succeeded → no escalation
    assert traj["repair_method"] == "LLM_REPAIR_1"
    assert traj["escalation_used"] is False
    assert traj["final_answer"] == "13/12"
    assert traj["correction_decision"] == "ACCEPT"


def test_structured_context_in_repair_prompt():
    seen = {}

    def repair(prompt):
        seen["p"] = prompt
        return "9/12"

    run(repair=repair, feedback_source="RETRIEVAL_EVIDENCE",
        failed_component="probability_value", expected_type="probability",
        evidence="Favorable outcomes: 6 of 36")
    p = seen["p"]
    assert "failed_component: probability_value" in p
    assert "expected_output_type" in p
    assert "original_answer" in p
    assert "authoritative_evidence" in p
    assert "provenance rule" in p  # T10.14 — supported-source provenance


# ------------------------------------------------- partial-fail handling
PARTIAL_INITIAL = "(a) 1101 (b) 70 (c) 24"
PARTIAL_PROTECTED = {
    "a": {"expected": "1081", "given": "1101"},
    "b": {"expected": "70", "given": "70"},
    "c": {"expected": "24", "given": "24"},
}


def test_deterministic_patch_preserves_protected_parts():
    traj = run(initial_answer=PARTIAL_INITIAL, protected=PARTIAL_PROTECTED,
               failed_part="a", expected="(a) 1081 (b) 70 (c) 24")
    assert traj["repair_method"] == "DETERMINISTIC_PATCH"
    assert traj["repair_attempts"] == 0
    assert traj["final_answer"] == "(a) 1081 (b) 70 (c) 24"
    assert traj["protected_preserved"] is True
    assert traj["collateral_parts"] == []


def test_part_scoped_llm_repair_preserves_protected_parts():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return "1081"

    traj = run(initial_answer=PARTIAL_INITIAL, protected=PARTIAL_PROTECTED,
               failed_part="a", feedback_source="RETRIEVAL_EVIDENCE",
               repair=repair, expected="(a) 1081 (b) 70 (c) 24")
    assert traj["final_answer"] == "(a) 1081 (b) 70 (c) 24"
    assert traj["protected_preserved"] is True
    assert traj["collateral_parts"] == []
    assert "part (a)" in calls[0]  # part-scoped contract


def test_part_scoped_failure_defers_without_collateral():
    def repair(prompt):
        return "garbage"

    traj = run(initial_answer=PARTIAL_INITIAL, protected=PARTIAL_PROTECTED,
               failed_part="a", feedback_source="RETRIEVAL_EVIDENCE",
               repair=repair, expected="(a) 1081 (b) 70 (c) 24")
    assert traj["final_answer"] == PARTIAL_INITIAL  # original preserved
    assert traj["correction_decision"] == "DEFER"
    assert traj["repair_attempts"] == 2  # bounded, both used


def test_citation_patch_method():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return "CITATION_OK with source: Wikipedia big bang"

    traj = run(initial_answer="(a) 1 (b) 2 (c) CITATION_MISSING",
               protected={"c": {"expected": "CITATION_OK", "given": "x"}},
               failed_part="c", failed_component="citation",
               feedback_source="CITATION_CHECK", repair=repair)
    assert traj["repair_method"] == "CITATION_PATCH"
    assert traj["protected_preserved"] is True


# ------------------------------------------------------------ helpers
def test_splice_part_keeps_other_parts_verbatim():
    out = splice_part(PARTIAL_INITIAL, "a", "1081")
    assert out == "(a) 1081 (b) 70 (c) 24"


def test_complete_unit_only_on_numeric_equality():
    assert complete_unit("3500", "3500 g") == "3500 g"
    assert complete_unit("0.45", "0.45 L") == "0.45 L"
    assert complete_unit("3500", "4500 g") == "3500"   # wrong value untouched
    assert complete_unit("3500 g", "3500 g") == "3500 g"


def test_evidence_strength_from_provenance():
    from sciencemath.executive.repair import evidence_strength
    assert evidence_strength("MATH_TOOL", "VERIFIED") == "high"
    assert evidence_strength("RETRIEVAL_EVIDENCE", "SUPPORTED") == "medium"
    assert evidence_strength("UNVERIFIED_MODEL_FEEDBACK", "UNVERIFIED") == "none"


def test_normalized_matching_fixes_t10_6_false_negatives():
    assert answers_match("13/12", "\\dfrac{13}{12}")
    assert answers_match("98 N", "98\\ \\text{N}")
    assert answers_match("3 x 10^8 m/s", "3 \\times 10^8 \\text{ m/s}")
    assert answers_match("11x − 12", "11x - 12")
    assert not answers_match("3500 g", "3500 kg")   # no semantic loosening
    assert not answers_match("x = 7, y = 3", "(7, 3)")


# ------------------------------------------------- v2 suite integrity
def test_v2_suite_checksum_and_manifest():
    manifest = json.loads((V2 / "manifest.json").read_text(encoding="utf-8"))
    checksum = json.loads((V2 / "checksum.json").read_text(encoding="utf-8"))
    data = (V2 / "questions.jsonl").read_bytes()
    assert hashlib.sha256(data).hexdigest() == manifest["sha256"] == \
        checksum["questions.jsonl"]
    rows = [r for r in data.decode("utf-8").splitlines() if r]
    assert len(rows) == manifest["questions"] == 194


def test_v2_final_set_isolation():
    manifest = json.loads((V2 / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in
            (V2 / "questions.jsonl").read_text(encoding="utf-8").splitlines()
            if l]
    dev = {r["eval_id"] for r in rows if r["split"] == "dev"}
    final = {r["eval_id"] for r in rows if r["split"] == "final"}
    assert dev and final
    assert not (dev & final)          # no question leakage across splits
    assert len(dev) == len(final)
    assert manifest["dev_final_question_overlap"] == 0
    # every class is represented in both splits
    for cls in ("TRUE_FAIL", "FALSE_FAIL", "PARTIAL_FAIL", "AMBIGUOUS"):
        assert any(r["case_class"] == cls and r["split"] == "final"
                   for r in rows)


# ------------------------------------------- collateral-change scoring
def test_collateral_change_scoring():
    rows = [
        {**r, "case_class": "PARTIAL_FAIL",
         "protected": {"a": {"expected": "1081"}, "b": {"expected": "70"}},
         "failed_part": "a",
         "final_answer": fa,
         "initial_answer": "(a) 1101 (b) 70",
         "failed_part_x": "a"}
        for r, fa in [({}, "(a) 1081 (b) 70"),      # clean repair
                      ({}, "(a) 1081 (b) 71")]]     # collateral change
    m = correction_metrics_v2(rows)
    assert m["partial_fail_repair_rate"] == 0.5
    assert m["collateral_change_rate"] == 0.5


def test_repair_method_labels_are_bounded():
    allowed = {"NO_REPAIR", "DETERMINISTIC_PATCH", "LLM_REPAIR_1",
               "LLM_REPAIR_2", "CITATION_PATCH", "DEFER", "REJECT"}
    traj = run(expected="13/12", repair=lambda p: "13/12")
    assert traj["repair_method"] in allowed
    traj2 = run(repair=lambda p: "bad", feedback_source="UNVERIFIED_MODEL_FEEDBACK",
                feedback_status="UNKNOWN")
    assert traj2["repair_method"] in allowed
    assert MAX_REPAIR_ATTEMPTS == 2