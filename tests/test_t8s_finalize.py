"""T8S.7/T8S.8 - self-correction groups and uncertainty recomputation."""
import json

from scripts.t8s_finalize import selfcorrection_metrics, uncertainty_metrics


def test_selfcorrection_groups():
    rows = [
        # Group 1: initially wrong + valid corrective evidence
        {"eval_id": "w1", "initially_correct": False, "changed": True,
         "revised": "x", "revised_correct": True, "tier": "FAIL_WITH_RESULT"},
        {"eval_id": "w2", "initially_correct": False, "changed": False,
         "revised": "y", "revised_correct": False,
         "tier": "FAIL_WITH_RESULT"},
        {"eval_id": "w3", "initially_correct": False, "changed": True,
         "revised": "z", "revised_correct": False,
         "tier": "FAIL_ONLY"},
        # Group 2: initially correct + false FAIL feedback
        {"eval_id": "c1", "initially_correct": True, "changed": False,
         "revised": "ok", "revised_correct": True, "tier": "FAIL_ONLY"},
        {"eval_id": "c2", "initially_correct": True, "changed": True,
         "revised": "bad", "revised_correct": False,
         "tier": "FAIL_ONLY"},
        {"eval_id": "c3", "initially_correct": True, "changed": True,
         "revised": "alsobad", "revised_correct": False,
         "tier": "FAIL_ONLY"},
    ]
    m = selfcorrection_metrics(rows)
    g1 = m["group1_wrong_with_valid_evidence"]
    g2 = m["group2_correct_with_false_fail"]
    assert g1["n"] == 3
    assert g1["correction_success"] == round(1 / 3, 4)
    assert g1["ignored_valid_evidence"] == round(1 / 3, 4)
    assert g2["n"] == 3
    assert g2["correct_answer_preservation"] == round(1 / 3, 4)
    assert g2["overcorrection"] == round(2 / 3, 4)
    assert g2["blind_agreement_with_false_feedback"] == round(2 / 3, 4)
    assert m["net_self_correction"] == round((1 - 2) / 3, 4)


def test_selfcorrection_empty():
    m = selfcorrection_metrics([])
    assert m["group1_wrong_with_valid_evidence"]["n"] == 0
    assert m["group1_wrong_with_valid_evidence"]["correction_success"] is None
    assert m["net_self_correction"] is None


def test_uncertainty_recomputation():
    preds = [
        # correct uncertainty signaling
        {"dimension": "uncertainty", "uncertainty_signaled": True,
         "hallucinated": False},
        {"dimension": "uncertainty", "uncertainty_signaled": True,
         "hallucinated": False},
        # missed uncertainty (fn)
        {"dimension": "uncertainty", "uncertainty_signaled": False,
         "hallucinated": True},
        # false uncertainty on answerable (fp)
        {"dimension": "math", "uncertainty_signaled": True,
         "hallucinated": False, "correct": False},
        {"dimension": "math", "uncertainty_signaled": False,
         "hallucinated": False, "correct": True},
    ]
    m = uncertainty_metrics(preds)
    assert m["n_uncertainty_questions"] == 3
    assert m["precision"] == round(2 / 3, 4)
    assert m["recall"] == round(2 / 3, 4)
    assert m["f1"] is not None
    assert m["hallucinated_answer_rate"] == round(1 / 3, 4)
    assert m["false_uncertainty_rate"] == round(1 / 2, 4)


def test_uncertainty_empty():
    m = uncertainty_metrics([])
    assert m["precision"] is None and m["recall"] is None
    assert m["hallucinated_answer_rate"] is None
