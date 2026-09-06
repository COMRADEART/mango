"""T7 regression tests — round-3 review fixes on the eval harness.

Covers:
- declined_flag honest-decline semantics (system failures and
  extraction failures are NOT declines)
- compute_metrics correction net gain MEASURED from correction events
  (declared T7.36 definition, no overcorrection proxy)
- compute_metrics citations_fabricated scoped to runs where evidence
  was actually supplied (+ unaudited counter)
- evaluate_gates G6/G8 driven by the measured fields
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from run_executive_eval import (  # noqa: E402
    compute_metrics, declined_flag, evaluate_gates)


def _rec(**kw):
    base = {
        "question_id": "q", "class": "simple", "expected_answer": "5",
        "extracted_answer": "5", "declined": False,
        "termination_reason": "SOLVED_VERIFIED", "fast_path": False,
        "first_attempt_plan_valid": None, "retry_plan_valid": None,
        "plan_fallback_used": False, "plan_attempts": 1,
        "steps_executed": 1, "replans": 0, "latency_s": 1.0,
        "input_tokens": 100, "output_tokens": 50, "tool_calls": 0,
        "retrievals": 0, "citations": None, "supplied_chunks": 0,
        "corrections_used": 0, "correction_event": None,
    }
    base.update(kw)
    return base


# ---- declined_flag -------------------------------------------------------

def test_declined_on_uncertainty_final_answer():
    res = {"final_answer":
           "There is insufficient information to answer.",
           "termination_reason": "INSUFFICIENT_INFORMATION"}
    assert declined_flag(res) is True


def test_declined_on_honest_no_answer_terminations():
    for reason in ("INSUFFICIENT_INFORMATION", "CONFLICTING_EVIDENCE",
                   "STALLED"):
        assert declined_flag({"final_answer": None,
                              "termination_reason": reason}) is True


def test_system_failures_are_not_declines():
    for reason in ("SYSTEM_ERROR", "BUDGET_EXHAUSTED"):
        assert declined_flag({"final_answer": None,
                              "termination_reason": reason}) is False


def test_extraction_failure_on_solved_run_is_not_a_decline():
    # SOLVED with no committed answer (extraction failed) — a run
    # failure, not an honest decline (round-3 finding)
    assert declined_flag({"final_answer": None,
                          "termination_reason": "SOLVED_UNVERIFIED"}) is False


def test_concrete_answer_is_not_a_decline_even_if_prose_hedged():
    # uncertainty phrases in surrounding prose must not flip a run
    # with a committed numeric answer (round-3 finding)
    assert declined_flag({"final_answer": "120",
                          "termination_reason": "SOLVED_VERIFIED"}) is False


# ---- correction net gain (G6) ---------------------------------------------

def test_correction_net_gain_measured_fix_minus_break():
    recs = [
        # fixed: pre wrong -> post right
        _rec(question_id="a", expected_answer="10",
             corrections_used=1,
             correction_event={"pre_answer": "7", "post_answer": "10"}),
        # broke: pre right -> post wrong
        _rec(question_id="b", expected_answer="20",
             corrections_used=1,
             correction_event={"pre_answer": "20", "post_answer": "25"}),
        # correction left the answer equivalent — no gain, no harm
        _rec(question_id="c", expected_answer="30",
             corrections_used=1,
             correction_event={"pre_answer": "30", "post_answer": "30.0"}),
        # used but unchanged answer: counts as used, no event
        _rec(question_id="d", corrections_used=1),
    ]
    m = compute_metrics(recs, "X")
    assert m["correction"]["fixes"] == 1
    assert m["correction"]["breaks"] == 1
    assert m["correction"]["net_gain"] == 0
    assert m["correction"]["used"] == 4


# ---- citation scoping (G8) -------------------------------------------------

def test_fabricated_citations_counted_only_with_supplied_chunks():
    recs = [
        # harness-failed retrieval: nothing supplied -> not counted
        _rec(question_id="a", citations={"invalid_refs": ["x1"],
                                         "valid_refs": []},
             supplied_chunks=0),
        # supplied evidence + fabricated ref -> counted
        _rec(question_id="b", citations={"invalid_refs": ["y1"],
                                         "valid_refs": ["c2"]},
             supplied_chunks=3),
        # supplied evidence, clean audit -> zero
        _rec(question_id="c", citations={"invalid_refs": [],
                                         "valid_refs": ["c1"]},
             supplied_chunks=2),
    ]
    m = compute_metrics(recs, "X")
    assert m["citations_fabricated"] == 1
    assert m["citations_unaudited"] == 0


def test_supplied_but_unaudited_run_is_reported():
    recs = [_rec(question_id="a", citations=None, supplied_chunks=4)]
    m = compute_metrics(recs, "X")
    assert m["citations_fabricated"] == 0
    assert m["citations_unaudited"] == 1


# ---- gate wiring ------------------------------------------------------------

GATES_CFG = {"G1_overall_gain_pp": {"on_off_delta_min": 3.0},
             "G2_distractor_robustness_pp": {"on_off_delta_min": 5.0},
             "G3_uncertainty_precision_min": {"min": 0.5},
             "G4_uncertainty_recall_min": {"min": 0.5},
             "G5_plan_validity_improvement": {"min": 0.3},
             "G6_correction_net_gain": {"min_net": 1},
             "G7_regression_bound_pp": {"max_regression": 5.0},
             "G8_t4_t5r_preservation": {"max": 0}}


def _metrics(**kw):
    m = {
        "arm": "E", "n": 10, "accuracy": 0.5,
        "accuracy_by_class": {"simple": 0.5, "distractor": 0.5},
        "uncertainty": {"precision": 0.9, "recall": 0.9, "tp": 1,
                        "fp": 0, "fn": 0},
        "plan": {"first_attempt_validity": 0.5, "retry_validity": None,
                 "fallback_rate": 0.0},
        "self_correction_accuracy": 0.5,
        "correction": {"used": 2, "net_gain": 2, "fixes": 2, "breaks": 0},
        "citations_fabricated": 0, "citations_unaudited": 0,
        "n": 102,
    }
    m.update(kw)
    return m


def test_g6_uses_measured_net_gain_not_proxy():
    # net gain from correction events decides the gate; the decline-FP
    # proxy is diagnostic only and must not flip the verdict
    on = _metrics(correction={"used": 2, "net_gain": 1, "fixes": 2,
                              "breaks": 1},
                  uncertainty={"precision": 1.0, "recall": 1.0, "tp": 1,
                               "fp": 50, "fn": 0})
    off = _metrics()
    g = evaluate_gates(off, on, GATES_CFG)["gates"]["G6_correction_net_gain"]
    assert g["measured"] == 1
    assert g["pass"] is True
    # 50 decline-FPs would have failed the old proxy; reported, not gating
    assert g["overcorrection_proxy_fp"] == 50


def test_g6_fails_on_net_negative_correction():
    on = _metrics(correction={"used": 3, "net_gain": -1, "fixes": 1,
                              "breaks": 2})
    g = evaluate_gates(_metrics(), on, GATES_CFG)["gates"]["G6_correction_net_gain"]
    assert g["pass"] is False


def test_g8_measured_from_scoped_count():
    on = _metrics(citations_fabricated=1)
    g = evaluate_gates(_metrics(), on, GATES_CFG)["gates"]["G8_t4_t5r_preservation"]
    assert g["measured"] == 1 and g["pass"] is False
    on = _metrics(citations_fabricated=0)
    g = evaluate_gates(_metrics(), on, GATES_CFG)["gates"]["G8_t4_t5r_preservation"]
    assert g["pass"] is True