"""T8S.2/T8S.4/T8S.5 - metric recomputation from prediction records."""
import json

import pytest

from scripts.t8s_metrics import (t4_arm_metrics, t4_pair_metrics,
                                 t5r_variant_metrics)


def _write(tmp_path, name, rows):
    p = tmp_path / name
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


def _t4_row(i, *, correct, extracted="42", tools=(), verdict=None,
            latency=1.0, tin=10, tout=20, category="arithmetic"):
    return {"eval_id": f"ev1-{i}", "category": category,
            "extracted_answer": extracted if extracted is not None else None,
            "verdict": verdict or ("PASS" if correct else "FAIL"),
            "correct": correct,
            "tool_calls": list(tools),
            "latency_s": latency, "input_tokens": tin,
            "output_tokens": tout}


def test_t4_notool_metrics(tmp_path):
    rows = [_t4_row(1, correct=True), _t4_row(2, correct=False,
                                              extracted=None),
            _t4_row(3, correct=True, category="algebra")]
    p = _write(tmp_path, "predictions.jsonl", rows)
    m = t4_arm_metrics(p, arm="no_tool")
    assert m["n"] == 3
    assert m["overall_accuracy"] == round(2 / 3, 4)
    assert m["extraction_rate"] == round(2 / 3, 4)
    assert m["tool_call_rate"] == 0.0
    assert m["by_category"]["arithmetic"] == 0.5
    assert m["by_category"]["algebra"] == 1.0
    assert m["mean_latency_s"] == 1.0
    assert m["mean_output_tokens"] == 20.0


def test_t4_tool_metrics_and_result_use(tmp_path):
    rows = [
        # valid call + correct final use
        _t4_row(1, correct=True, tools=[{"tool": "calculator",
                                         "status": "ok"}],
                verdict="PASS"),
        # valid call but model got it wrong anyway
        _t4_row(2, correct=False, tools=[{"tool": "calculator",
                                          "status": "ok"}],
                verdict="FAIL"),
        # errored call does not count as valid
        _t4_row(3, correct=True, tools=[{"tool": "unit_converter",
                                         "status": "error"}],
                verdict="PASS"),
        # no tool call at all
        _t4_row(4, correct=False),
    ]
    p = _write(tmp_path, "predictions.jsonl", rows)
    m = t4_arm_metrics(p, arm="tool")
    assert m["tool_call_rate"] == 0.75
    assert m["total_tool_calls"] == 3
    assert m["valid_tool_calls"] == 2
    assert m["valid_tool_call_rate"] == round(2 / 3, 4)
    use = m["correct_use_of_tool_result"]
    assert use["n_questions_with_valid_call"] == 2
    assert use["n_pass_after_valid_call"] == 1
    assert use["rate"] == 0.5


def test_t4_pair_delta(tmp_path):
    nt = {"n": 150, "overall_accuracy": 0.6}
    tl = {"n": 150, "overall_accuracy": 0.7}
    pair = t4_pair_metrics(nt, tl)
    assert pair["tool_gain_pp"] == 10.0
    assert pair["matched_questions"] == 150


def test_t5r_metrics_citation_coverage_vs_integrity(tmp_path):
    rows = [
        {"category": "factual_science_qa", "correct": True,
         "retrieval_used": True, "citation_report": {
             "n_citations": 2, "n_fabricated": 0, "n_unsupported": 0,
             "invalid_refs": []},
         "latency_s": 2.0, "input_tokens": 100, "output_tokens": 50},
        {"category": "multi_hop_science_qa", "correct": False,
         "retrieval_used": False, "citation_report": None,
         "latency_s": 4.0, "input_tokens": 90, "output_tokens": 60},
    ]
    p = _write(tmp_path, "predictions.jsonl", rows)
    m = t5r_variant_metrics(p, variant="G")
    assert m["n"] == 2
    assert m["overall_accuracy"] == 0.5
    assert m["citation"]["coverage"][
        "coverage_rate"] == 0.5    # 1 of 2 citation-requiring cited
    integ = m["citation"]["integrity"]
    assert integ["integrity_ok"] is True
    assert integ["fabricated_accepted"] == 0
    assert m["retrieval_used_rate"] == 0.5


def test_t5r_zero_citations_is_not_integrity_evidence(tmp_path):
    # all-citations-violating run: coverage low, integrity FAILS
    rows = [{"category": "factual_science_qa", "correct": True,
             "retrieval_used": True, "citation_report": {
                 "n_citations": 1, "n_fabricated": 1, "n_unsupported": 0,
                 "invalid_refs": ["chunk-x"]},
             "latency_s": 1.0, "input_tokens": 1, "output_tokens": 1}]
    p = _write(tmp_path, "predictions.jsonl", rows)
    m = t5r_variant_metrics(p, variant="G")
    assert m["citation"]["coverage"]["coverage_rate"] == 1.0
    assert m["citation"]["integrity"]["integrity_ok"] is False


def test_empty_predictions(tmp_path):
    p = _write(tmp_path, "predictions.jsonl", [])
    assert t4_arm_metrics(p, arm="x")["n"] == 0
    assert t5r_variant_metrics(p, variant="G")["n"] == 0
