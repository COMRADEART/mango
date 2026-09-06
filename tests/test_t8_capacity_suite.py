"""T8.29 — frozen capacity-suite integrity tests (mango-capacity-eval-v1).

The suite is frozen and immutable; these tests guard it against silent
corruption and enforce the pre-registered minimum composition.
"""
import json
from pathlib import Path

import pytest

from sciencemath.evaluation.extraction import normalize_symbolic

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / "evaluations" / "t8" / "capacity-suite" / "v1"
MIN_PER_DIM = {
    "math": 20, "science": 20, "compositional": 8, "cross_domain": 8,
    "uncertainty": 8, "counterfactual": 8, "distractor_clean": 8,
    "distractor_loaded": 8,
}


@pytest.fixture(scope="module")
def suite():
    lines = (SUITE / "questions.jsonl").read_text(encoding="utf-8") \
        .splitlines()
    items = [json.loads(l) for l in lines if l.strip()]
    return items


def test_suite_frozen_and_checksummed(suite):
    assert SUITE.exists()
    checksums = json.loads((SUITE / "checksum.json").read_text(
        encoding="utf-8"))
    assert len(checksums) == len(suite)


def test_suite_min_composition(suite):
    counts = {}
    for it in suite:
        counts[it["capacity_dimension"]] = \
            counts.get(it["capacity_dimension"], 0) + 1
    for dim, lo in MIN_PER_DIM.items():
        assert counts.get(dim, 0) >= lo, f"{dim}: {counts.get(dim, 0)} < {lo}"


def test_numeric_tool_checks_agree(suite):
    """Every tool_check expression must evaluate to expected_answer
    (deterministic, sympy-verified)."""
    import sympy
    checked = 0
    for it in suite:
        tc = it.get("tool_check")
        if not tc:
            continue
        got = float(sympy.sympify(tc["args"]["expression"]).evalf(15))
        expected = float(it["expected_answer"].replace(",", ""))
        assert abs(got - expected) <= 1e-9 + 1e-9 * abs(expected), \
            f"{it['author_key']}: {got} != {expected}"
        checked += 1
    assert checked >= 50, "too few numerically verified items"


def test_distractor_twins_share_answers(suite):
    groups = {}
    for it in suite:
        pk = it.get("distractor_pair_key")
        if pk:
            groups.setdefault(pk, []).append(it["expected_answer"])
    assert groups, "no distractor pairs found"
    for pk, answers in groups.items():
        assert len(set(normalize_symbolic(a) for a in answers)) == 1, pk


def test_cf_children_reference_parents_and_differ(suite):
    by_key = {it["author_key"]: it for it in suite}
    for it in suite:
        pk = it.get("cf_parent_key")
        if not pk:
            continue
        assert pk in by_key, f"missing parent {pk}"
        parent = by_key[pk]
        assert it["question"] != parent["question"]
        assert it.get("cf_change_type") in ("numbers", "units",
                                            "constraint", "relationship")


def test_uncertainty_items_genuinely_unanswerable_flag(suite):
    for it in suite:
        if it["capacity_dimension"] == "uncertainty":
            assert it["insufficient_info"]
            assert it["expected_answer"] == "__UNKNOWN__"


def test_no_duplicate_questions(suite):
    qs = [" ".join(it["question"].lower().split()) for it in suite]
    assert len(qs) == len(set(qs))


def test_item_schema_required_fields(suite):
    for it in suite:
        for f in ("category", "capability_track", "generalization_split",
                  "requires_math_tool", "requires_retrieval",
                  "insufficient_info", "multi_hop", "answer_type",
                  "question", "expected_answer", "eval_id", "license"):
            assert f in it, f"{it.get('author_key')}: missing {f}"
        assert it["license"] == "CC0-1.0"