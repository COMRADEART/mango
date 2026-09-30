"""T31 tests, brief categories 17 and 18: paired results and delta arithmetic.

- 17  paired-result calculation
- 18  delta calculation

The arithmetic here is trivial; the failure modes are not. A paired analysis
that inner-joins two arms with different item sets returns a perfectly
well-formed table over the wrong denominator; a delta that is computed as
``abs(adapter - base)`` loses the sign the brief insists must be shown; and an
interval computed by resampling individual items is too narrow on ARC, where
items share question stems. Each test below pins one of those.
"""
from __future__ import annotations

import pytest

from sciencemath.comparability import analysis as A
from sciencemath.comparability.contract import (
    COMPARISON_EQUAL, COMPARISON_LIFT, COMPARISON_REGRESSION,
)

from t31_comparability_support import arm_rows, item, mcq


def _subjects(n: int, benchmark: str = "gsm8k"):
    return [item(benchmark, question=f"Question {i}?") for i in range(n)]


def _scenario(n: int, base_idx, adapter_idx, *, benchmark: str = "gsm8k"):
    """Both arms over the SAME n items; the index sets say who got them right.

    Deliberately not "rows only for the correct items" — that would hand
    ``pair_rows`` two arms of different sizes, which is the very thing it
    exists to refuse.
    """
    subjects = _subjects(n, benchmark)
    ids = [subject.item_id for subject in subjects]
    base = arm_rows(subjects, arm="base",
                    correct_ids={ids[i] for i in base_idx})
    adapter = arm_rows(subjects, arm="adapter",
                       correct_ids={ids[i] for i in adapter_idx})
    return subjects, base, adapter


def _paired(n: int, base_idx, adapter_idx, *, benchmark: str = "gsm8k"):
    subjects, base, adapter = _scenario(n, base_idx, adapter_idx,
                                        benchmark=benchmark)
    outcomes = A.pair_rows(base, adapter, benchmark=benchmark)
    return subjects, outcomes


# ---------------------------------------------------------------------------
# category 17 — paired results
# ---------------------------------------------------------------------------
def test_paired_table_splits_all_four_cells():
    _, outcomes = _paired(4, {0, 1}, {1, 2})
    assert A.paired_table(outcomes) == {
        "both_correct": 1, "base_only": 1, "adapter_only": 1, "neither": 1}


def test_pairing_refuses_two_arms_over_different_items():
    """The inner-join trap: fewer items than either arm, silently."""
    subjects = [item("gsm8k", question=f"Question {i}?") for i in range(4)]
    base = arm_rows(subjects[:3], arm="base",
                    correct_ids={s.item_id for s in subjects[:3]})
    adapter = arm_rows(subjects[1:], arm="adapter",
                       correct_ids={s.item_id for s in subjects[1:]})
    with pytest.raises(A.AnalysisError, match="arms cover different items"):
        A.pair_rows(base, adapter, benchmark="gsm8k")


def test_pairing_refuses_an_empty_set():
    with pytest.raises(A.AnalysisError, match="zero paired items"):
        A.pair_rows([], [], benchmark="gsm8k")


def test_paired_outcomes_are_keyed_by_item_not_by_position():
    subjects = [item("gsm8k", question=f"Question {i}?") for i in range(3)]
    base = arm_rows(subjects, arm="base", correct_ids={subjects[0].item_id})
    # Adapter rows arrive in a different order; pairing must not care.
    adapter = arm_rows(list(reversed(subjects)), arm="adapter",
                       correct_ids={subjects[2].item_id})
    outcomes = A.pair_rows(base, adapter, benchmark="gsm8k")
    assert A.paired_table(outcomes) == {
        "both_correct": 0, "base_only": 1, "adapter_only": 1, "neither": 1}
    assert [o.item_id for o in outcomes] == sorted(s.item_id for s in subjects)


def test_pairing_uses_content_validity_not_schema_validity():
    """A protocol-perfect wrong answer is not a correct answer."""
    subjects = [item("gsm8k", question="Only question?")]
    base = arm_rows(subjects, arm="base", correct_ids={subjects[0].item_id})
    adapter = arm_rows(subjects, arm="adapter", correct_ids=set())
    # Flip the adapter row to be schema-valid but content-invalid.
    adapter[0]["schema_valid"] = True
    adapter[0]["content_valid"] = False
    outcomes = A.pair_rows(base, adapter, benchmark="gsm8k")
    assert outcomes[0].adapter_correct is False
    assert A.paired_table(outcomes)["base_only"] == 1


# ---------------------------------------------------------------------------
# category 18 — deltas
# ---------------------------------------------------------------------------
def test_delta_is_computed_in_percentage_points_with_its_sign():
    # base 4 correct, adapter 7 correct.
    _, outcomes = _paired(10, set(range(4)), set(range(7)))
    summary = A.benchmark_summary(outcomes)
    assert summary["base_correct"] == 4
    assert summary["adapter_correct"] == 7
    assert summary["base_accuracy"] == pytest.approx(0.4)
    assert summary["adapter_accuracy"] == pytest.approx(0.7)
    assert summary["delta_pp"] == pytest.approx(30.0)
    assert summary["relative_delta"] == pytest.approx(0.75)


def test_a_negative_delta_is_reported_negative_not_absolute():
    _, outcomes = _paired(10, set(range(7)), set(range(4)))
    summary = A.benchmark_summary(outcomes)
    assert summary["delta_pp"] == pytest.approx(-30.0)
    assert summary["relative_delta"] == pytest.approx(-3 / 7)
    # Ten items cannot establish a 30pp difference, so the label is EQUAL even
    # though the point estimate is negative and large. The sign is never
    # hidden; the label is what the sample can support.
    assert summary["comparison"] == COMPARISON_EQUAL


def test_a_regression_on_an_adequate_sample_is_labelled():
    _, outcomes = _paired(200, set(range(140)), set(range(80)))
    summary = A.benchmark_summary(outcomes)
    assert summary["delta_pp"] == pytest.approx(-30.0)
    assert summary["comparison"] == COMPARISON_REGRESSION
    assert summary["uncertainty"]["ci_high_pp"] < 0


def test_an_identical_result_is_reported_as_no_clear_lift():
    _, outcomes = _paired(10, set(range(5)), set(range(5)))
    summary = A.benchmark_summary(outcomes)
    assert summary["delta_pp"] == 0.0
    assert summary["comparison"] == COMPARISON_EQUAL
    assert summary["mcnemar"]["n_discordant"] == 0
    assert summary["mcnemar"]["p_value"] is None


def test_a_clear_lift_is_labelled_only_when_the_interval_excludes_zero():
    # Adapter right everywhere, base right on 20 only: unambiguous.
    _, outcomes = _paired(200, set(range(20)), set(range(200)))
    summary = A.benchmark_summary(outcomes)
    assert summary["comparison"] == COMPARISON_LIFT
    assert summary["uncertainty"]["excludes_zero"] is True
    assert summary["uncertainty"]["ci_low_pp"] > 0


def test_a_small_gap_is_not_dressed_up_as_lift():
    """The brief: 'Do not claim an improvement is meaningful merely because
    adapter_accuracy > base_accuracy.'"""
    _, outcomes = _paired(40, set(range(20)), set(range(21)))
    summary = A.benchmark_summary(outcomes)
    assert summary["adapter_accuracy"] > summary["base_accuracy"]
    assert summary["comparison"] == COMPARISON_EQUAL
    assert summary["uncertainty"]["excludes_zero"] is False


def test_zero_denominator_relative_delta_is_none_not_a_number():
    _, outcomes = _paired(4, set(), set(range(4)))
    summary = A.benchmark_summary(outcomes)
    assert summary["base_accuracy"] == 0.0
    assert summary["relative_delta"] is None      # division by zero, stated


def test_summarising_zero_items_fails_closed():
    with pytest.raises(A.AnalysisError, match="zero scored items"):
        A.benchmark_summary([])


def test_aggregate_refuses_an_empty_benchmark_list():
    with pytest.raises(A.AnalysisError, match="no benchmark summaries"):
        A.aggregate([])


def test_aggregate_is_a_micro_average_over_items():
    _, small = _paired(10, set(range(5)), set(range(6)))
    _, big = _paired(100, set(range(10)), set(range(10)))
    agg = A.aggregate([A.benchmark_summary(small), A.benchmark_summary(big)])
    assert agg["total_items"] == 110
    assert agg["aggregation"] == "micro_average_over_items"
    assert agg["delta_pp"] == pytest.approx(
        100.0 * (16 - 15) / 110, abs=1e-3)


# ---------------------------------------------------------------------------
# uncertainty
# ---------------------------------------------------------------------------
def test_bootstrap_is_deterministic_for_a_fixed_seed():
    _, outcomes = _paired(50, set(range(20)), set(range(30)))
    first = A.cluster_bootstrap_delta(outcomes)
    second = A.cluster_bootstrap_delta(outcomes)
    assert first == second


def test_clustering_is_applied_when_question_stems_repeat():
    """ARC's test split contains one stem with several option sets."""
    stem = "What keeps the planets in orbit around the Sun?"
    # Four distinct ARC items sharing one stem, as arc_easy's test split really
    # contains (Mercury_400065 and Mercury_401603 among them) — same question,
    # different options, different gold answers, distinct native ids.
    subjects = [mcq(question=stem, native_id=f"Mercury_40160{i}",
                    gold_label="A",
                    choices=(("A", f"gravity{i}"), ("B", f"magnetism{i}"),
                             ("C", f"friction{i}"), ("D", f"pressure{i}")))
                for i in range(4)]
    subjects.append(mcq(question="Which is a chemical change?",
                        native_id="Mercury_SC_400001"))
    outcomes = A.pair_rows(
        arm_rows(subjects, arm="base", correct_ids={subjects[0].item_id}),
        arm_rows(subjects, arm="adapter", correct_ids={s.item_id
                                                       for s in subjects[:2]}),
        benchmark="arc_easy")
    result = A.cluster_bootstrap_delta(outcomes)
    assert result["cluster_count"] == 2
    assert result["item_count"] == 5
    assert result["clustering_material"] is True
    assert "correlated" in result["note"]


def test_clustering_degenerates_cleanly_when_every_stem_is_unique():
    _, outcomes = _paired(20, set(range(8)), set(range(12)))
    result = A.cluster_bootstrap_delta(outcomes)
    assert result["cluster_count"] == result["item_count"] == 20
    assert result["clustering_material"] is False
    assert "reduces to item resampling" in result["note"]


def test_bootstrap_refuses_an_empty_set():
    with pytest.raises(A.AnalysisError, match="empty outcome set"):
        A.cluster_bootstrap_delta([])


# ---------------------------------------------------------------------------
# McNemar
# ---------------------------------------------------------------------------
def test_mcnemar_is_symmetric_in_the_two_arms():
    assert A.mcnemar_exact(3, 17)["p_value"] == \
        A.mcnemar_exact(17, 3)["p_value"]


def test_mcnemar_reports_no_p_value_when_nothing_disagrees():
    result = A.mcnemar_exact(0, 0)
    assert result["p_value"] is None
    assert "undefined" in result["note"]


def test_mcnemar_detects_a_lopsided_split():
    result = A.mcnemar_exact(2, 20)
    assert result["p_value"] < 0.001
    assert result["n_discordant"] == 22


def test_mcnemar_does_not_call_a_small_split_significant():
    assert A.mcnemar_exact(5, 7)["p_value"] > 0.5


def test_mcnemar_states_the_narrow_question_it_answers():
    result = A.mcnemar_exact(1, 9)
    assert "not a test of overall capability" in result["question_answered"]
    assert "not evidence that the arms are equivalent" in \
        result["question_answered"]


# ---------------------------------------------------------------------------
# failure taxonomy and the T32 handoff
# ---------------------------------------------------------------------------
def test_error_taxonomy_counts_per_arm_without_reclassification():
    _, outcomes = _paired(4, {0, 1}, {1, 2})
    taxonomy = A.error_taxonomy(outcomes)
    assert taxonomy["shared_failures"] == 1          # item 3, wrong for both
    assert taxonomy["base_error_counts"] == {"wrong_final_answer": 2}
    assert taxonomy["adapter_error_counts"] == {"wrong_final_answer": 2}
    assert "no failure was reclassified" in taxonomy["note"]


def test_a_successful_extraction_is_not_counted_as_an_extraction_failure():
    """The regression guard for a defect that made the taxonomy contradict
    itself.

    Scored rows carry the extractors' status constant, ``"OK"`` — the value
    ``build_scored_row`` writes. The taxonomy compared it against the
    lower-case literal ``"ok"``, which matches nothing, so *every* item was
    reported as an extraction failure while the error counts beside it — the
    same rows, since an unreadable answer is scored
    ``answer_extraction_failure`` — reported only the genuinely wrong ones.
    Two numbers in one artifact, describing one set of rows, that could not
    both be true.
    """
    _, outcomes = _paired(4, {0, 1}, {1, 2})          # all four extracted: "OK"
    taxonomy = A.error_taxonomy(outcomes)

    assert taxonomy["extraction_failures"] == {"base": 0, "adapter": 0}
    assert taxonomy["extraction_failure_status"] == {"base": {}, "adapter": {}}
    # Base got 2 of the 4 right, so 2 rows are wrong — and none of them is
    # wrong because its answer could not be read.
    assert taxonomy["base_error_counts"] == {"wrong_final_answer": 2}
    assert sum(taxonomy["extraction_failures"].values()) == 0


def test_unreadable_and_ambiguous_answers_are_both_failures_but_kept_apart():
    """``FAILED`` and ``AMBIGUOUS`` are different facts — the extractors make a
    point of distinguishing "said nothing" from "said two things" — so the
    taxonomy counts both as failures and still reports which was which."""
    subjects = _subjects(3)
    ids = [subject.item_id for subject in subjects]
    base = arm_rows(subjects, arm="base", correct_ids=set())
    adapter = arm_rows(subjects, arm="adapter", correct_ids=set())
    for row, status, category in ((base[0], "FAILED", "answer_extraction_failure"),
                                  (base[1], "AMBIGUOUS", "answer_extraction_failure")):
        row["extraction_status"] = status
        row["error_category"] = category
        row["content_valid"] = False
    for row, status, category in ((adapter[0], "AMBIGUOUS", "answer_extraction_failure"),):
        row["extraction_status"] = status
        row["error_category"] = category
        row["content_valid"] = False

    taxonomy = A.error_taxonomy(A.pair_rows(base, adapter, benchmark="gsm8k"))

    assert taxonomy["extraction_failures"] == {"base": 2, "adapter": 1}
    assert taxonomy["extraction_failure_status"] == {
        "base": {"AMBIGUOUS": 1, "FAILED": 1},
        "adapter": {"AMBIGUOUS": 1},
    }


def test_diagnostic_handoff_holds_only_disagreements_and_shared_failures():
    subjects, base, adapter = _scenario(4, {0, 1}, {1, 2})
    outcomes = A.pair_rows(base, adapter, benchmark="gsm8k")
    diagnostic = A.diagnostic_rows(outcomes, base, adapter)
    assert {row["outcome"] for row in diagnostic} == {
        "base_only", "adapter_only", "neither"}
    assert len(diagnostic) == 3
    assert all(row["benchmark"] == "gsm8k" for row in diagnostic)
    assert all("raw_generation" in row["base"] for row in diagnostic)
