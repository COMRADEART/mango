import json

from sciencemath.evaluation.correction_metrics import correction_metrics
from sciencemath.executive.correction import (
    FeedbackTrust, correction_firewall, determine_feedback_trust,
)
from sciencemath.tools.router import build_default_registry, prevalidate_tool_call
from sciencemath.evaluation.extraction import answers_match, extract_answer


def test_trust_levels():
    assert determine_feedback_trust("T4_VERIFIER", "FAIL") == FeedbackTrust.VERIFIED
    assert determine_feedback_trust("RETRIEVAL_EVIDENCE", "FAIL") == FeedbackTrust.SUPPORTED
    assert determine_feedback_trust("UNVERIFIED_MODEL_FEEDBACK", "FAIL") == FeedbackTrust.UNVERIFIED
    assert determine_feedback_trust("MATH_TOOL", "PASS") == FeedbackTrust.CONTRADICTED


def test_false_fail_rejected_and_preserved():
    state = correction_firewall(initial_answer="36", feedback_type="CLAIM_ERROR",
        feedback_source="MATH_TOOL", validation={"original_status": "PASS", "feedback_status": "PASS"})
    assert state.correction_decision == "REJECT"
    assert state.revised_answer is None and state.initial_answer == "36"


def test_true_fail_targeted_repair_accepted():
    state = correction_firewall(initial_answer="42", feedback_type="CLAIM_ERROR",
        feedback_source="MATH_TOOL", repair_scope="numeric_result", question="17+19?",
        validation={"original_status": "FAIL", "feedback_status": "FAIL", "expected": "36"},
        repair=lambda prompt: "36" if "numeric_result" in prompt else "bad",
        reverify=lambda answer: "PASS" if answer == "36" else "FAIL")
    assert state.correction_decision == "ACCEPT" and state.revised_answer == "36"
    assert set(state.to_dict()) == {"initial_answer", "initial_verification", "feedback_type",
        "feedback_trust", "repair_required", "repair_scope", "revised_answer",
        "final_verification", "correction_decision"}


def test_unverified_feedback_deferred_without_model_call():
    called = []
    state = correction_firewall(initial_answer="H2O", feedback_type="CLAIM_ERROR",
        feedback_source="UNVERIFIED_MODEL_FEEDBACK",
        validation={"original_status": "UNKNOWN", "feedback_status": "FAIL"},
        repair=lambda _: called.append(True) or "CO2", reverify=lambda _: "PASS")
    assert state.correction_decision == "DEFER" and not called


def test_citation_error_scope_is_separate():
    state = correction_firewall(initial_answer="Water is H2O [bad].",
        feedback_type="CITATION_ERROR", feedback_source="CITATION_CHECK",
        repair_scope="claim", validation={"original_status": "FAIL", "feedback_status": "FAIL"})
    assert state.repair_scope == "citation" and state.repair_required


def test_tool_prevalidation_and_single_normalization():
    registry = build_default_registry()
    ok = prevalidate_tool_call(registry, "calculator", json.dumps({"expression": "2+2"}))
    assert ok["ok"] and ok["normalized"] and ok["arguments"]["expression"] == "2+2"
    assert prevalidate_tool_call(registry, "missing", {})["category"] == "WRONG_TOOL"
    assert prevalidate_tool_call(registry, "calculator", "not-json")["category"] == "MALFORMED_ARGUMENT"
    assert prevalidate_tool_call(registry, "calculator", {"expression": "x" * 5000})["category"] == "RESOURCE_CAP"


def test_correction_metrics_score_harms_separately():
    rows = [
        {"case_class": "TRUE_FAIL", "initial_correct": False, "final_correct": True,
         "changed": True, "feedback_trust": "VERIFIED"},
        {"case_class": "FALSE_FAIL", "initial_correct": True, "final_correct": False,
         "changed": True, "feedback_trust": "UNVERIFIED"},
    ]
    m = correction_metrics(rows)
    assert m["overcorrection"] == 1 and m["under_correction"] == 0
    assert m["blind_agreement"] == 0.5 and m["net_correction_benefit"] == 0


def test_extraction_accepts_markdown_value_without_loosening_match():
    assert extract_answer("Thus the result is\n**2000 m**", "short_answer") == "2000 m"
    assert answers_match("2000 m", "**2000 m**")
    assert not answers_match("2000 m", "**200 m**")
