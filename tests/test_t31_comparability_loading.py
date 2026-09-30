"""T31 categories 1, 2, 11, 12 — benchmark loading, item ids, non-vacuity.

Category 1 is benchmark loading, category 2 is stable item ids, and
categories 11 and 12 are the fail-closed rules: a zero-item load must fail,
and a run that did not reach the pinned item count must fail rather than
report a rate over whatever it happened to finish.

The default suite exercises the loader's *logic* against synthetic rows, so
it stays fast and needs no network — the repository's standing promise is
that ``python -m pytest`` runs without downloads. The real pinned datasets are
loaded by an opt-in test at the bottom, which is what the pre-run validation
actually executes.
"""
from __future__ import annotations

import os

import pytest

from sciencemath.comparability import contract, identity
from sciencemath.comparability.loaders import (
    BenchmarkLoaderError, _build_item, item_id_for, load_benchmark, load_all,
    suite_hash,
)

import t31_comparability_support as S

REAL_DATASETS = os.environ.get("T31_REAL_DATASETS") == "1"


# ---------------------------------------------------------------------------
# category 1 — identities and dispatch
# ---------------------------------------------------------------------------
def test_every_benchmark_has_a_pinned_identity():
    for name, entry in identity.BENCHMARK_IDENTITIES.items():
        assert entry["revision"], name
        assert len(entry["revision"]) == 40, name
        assert entry["expected_items"] > 0, name
        assert entry["split"], name


def test_the_benchmark_registry_and_the_identity_table_agree():
    assert set(contract.BENCHMARKS) == set(identity.BENCHMARK_IDENTITIES)
    assert set(contract.BENCHMARK_ORDER) == set(contract.BENCHMARKS)


def test_the_expected_total_is_the_sum_of_the_parts():
    assert identity.TOTAL_EXPECTED_ITEMS == sum(
        entry["expected_items"]
        for entry in identity.BENCHMARK_IDENTITIES.values())


def test_an_unknown_benchmark_is_refused():
    with pytest.raises(BenchmarkLoaderError):
        load_benchmark("mmlu")


def test_an_unknown_benchmark_in_a_batch_is_refused():
    with pytest.raises(BenchmarkLoaderError):
        load_all(("gsm8k", "not_a_benchmark"))


# ---------------------------------------------------------------------------
# categories 11 and 12 — fail closed
# ---------------------------------------------------------------------------
def _fake_rows(benchmark: str, count: int):
    if benchmark == "gsm8k":
        return [{"question": f"q{i}", "answer": f"working\n#### {i}"}
                for i in range(count)]
    if benchmark == "math500":
        return [{"problem": f"p{i}", "answer": str(i), "subject": "algebra",
                 "level": "1", "unique_id": f"u{i}"} for i in range(count)]
    return [{"id": f"id{i}", "question": f"q{i}",
             "choices": {"label": ["A", "B", "C", "D"],
                         "text": ["a", "b", "c", "d"]},
             "answerKey": "A"} for i in range(count)]


@pytest.mark.parametrize("count,message", [
    (0, "loaded 0 items"),
    (5, "loaded 5 items"),
])
def test_a_load_that_misses_the_pinned_count_is_refused(monkeypatch, count,
                                                         message):
    """A short load is the exact failure the brief forbids reporting on."""
    monkeypatch.setattr("sciencemath.comparability.loaders._load_raw",
                        lambda name: _fake_rows(name, count))
    with pytest.raises(BenchmarkLoaderError) as caught:
        load_benchmark("gsm8k")
    assert message in str(caught.value)
    assert "1319" in str(caught.value)


def test_an_empty_load_never_produces_a_benchmark(monkeypatch):
    monkeypatch.setattr("sciencemath.comparability.loaders._load_raw",
                        lambda name: [])
    for name in contract.BENCHMARK_ORDER:
        with pytest.raises(BenchmarkLoaderError):
            load_benchmark(name)


def test_a_duplicate_item_id_is_refused(monkeypatch):
    """Two identical questions would make resume drop one of them."""
    rows = _fake_rows("gsm8k", 1319)
    rows[1] = dict(rows[0])
    monkeypatch.setattr("sciencemath.comparability.loaders._load_raw",
                        lambda name: rows)
    with pytest.raises(BenchmarkLoaderError) as caught:
        load_benchmark("gsm8k")
    assert "duplicate item ids" in str(caught.value)


# ---------------------------------------------------------------------------
# category 2 — stable item ids
# ---------------------------------------------------------------------------
def test_item_ids_are_stable_across_calls():
    assert item_id_for("gsm8k", "test", "same text") == \
        item_id_for("gsm8k", "test", "same text")


def test_item_ids_are_content_addressed_not_positional():
    """Reordering the dataset must not renumber the items."""
    monkeypatch_rows = _fake_rows("gsm8k", 1319)
    forward = [_build_item("gsm8k", "test", dict(row))
               for row in monkeypatch_rows]
    backward = [_build_item("gsm8k", "test", dict(row))
                for row in reversed(monkeypatch_rows)]
    assert {item.item_id for item in forward} == \
        {item.item_id for item in backward}
    assert suite_hash(forward) == suite_hash(backward)


def test_different_questions_get_different_ids():
    assert item_id_for("gsm8k", "test", "a") != \
        item_id_for("gsm8k", "test", "b")


def test_the_same_question_in_two_benchmarks_does_not_collide():
    assert item_id_for("gsm8k", "test", "same") != \
        item_id_for("sciq", "test", "same")
    assert item_id_for("arc_easy", "test", "same") != \
        item_id_for("arc_challenge", "test", "same")


def test_item_ids_carry_their_benchmark_and_a_fixed_width_hash():
    item_id = item_id_for("math500", "test", "x")
    assert item_id.startswith("t31-math500-")
    assert len(item_id) == len("t31-math500-") + 12


def test_the_suite_hash_changes_when_any_item_changes():
    items = [_build_item("gsm8k", "test", dict(row))
             for row in _fake_rows("gsm8k", 3)]
    baseline = suite_hash(items)
    mutated = list(items)
    mutated[1] = _build_item("gsm8k", "test",
                             {"question": "different", "answer": "#### 1"})
    assert suite_hash(mutated) != baseline


# ---------------------------------------------------------------------------
# per-benchmark normalisation
# ---------------------------------------------------------------------------
def test_gsm8k_gold_is_read_after_the_marker():
    item = _build_item("gsm8k", "test",
                       {"question": "q", "answer": "steps\n#### 1,234"})
    assert item.gold == "1,234"
    assert item.choices == ()


def test_a_missing_gsm8k_marker_is_recorded_not_invented():
    item = _build_item("gsm8k", "test", {"question": "q", "answer": "42"})
    assert "missing_hash_marker" in item.notes


def test_arc_options_and_gold_map_to_labels():
    item = _build_item("arc_easy", "test",
                       {"id": "x", "question": "q",
                        "choices": {"label": ["A", "B", "C", "D"],
                                    "text": ["w", "x", "y", "z"]},
                        "answerKey": "C"})
    assert item.choices == (("A", "w"), ("B", "x"), ("C", "y"), ("D", "z"))
    assert item.gold_label == "C"
    assert item.native_id == "x"


def test_arc_with_several_answer_keys_is_flagged_rather_than_guessed():
    item = _build_item("arc_easy", "test",
                       {"id": "x", "question": "q",
                        "choices": {"label": ["A", "B"], "text": ["w", "x"]},
                        "answerKey": "A\nB"})
    assert item.gold_label is None
    assert "multiple_answer_keys" in item.notes


def test_arc_with_an_answer_key_outside_the_choices_is_flagged():
    item = _build_item("arc_easy", "test",
                       {"id": "x", "question": "q",
                        "choices": {"label": ["A", "B"], "text": ["w", "x"]},
                        "answerKey": "Z"})
    assert "answer_key_not_in_choices" in item.notes


# ---------------------------------------------------------------------------
# SciQ: the options have to be built, and the build must be defensible
# ---------------------------------------------------------------------------
def _sciq_row(correct: str = "oxidants") -> dict:
    return {"question": "what are they called?", "correct_answer": correct,
            "distractor1": "antioxidants", "distractor2": "Oxygen",
            "distractor3": "residues", "support": "a passage"}


def test_sciq_builds_four_labelled_options():
    item = _build_item("sciq", "test", _sciq_row())
    assert [label for label, _ in item.choices] == ["A", "B", "C", "D"]
    assert len({text for _, text in item.choices}) == 4


def test_sciq_gold_label_points_at_the_correct_text():
    item = _build_item("sciq", "test", _sciq_row())
    lookup = dict(item.choices)
    assert lookup[item.gold_label] == "oxidants"


def test_the_sciq_option_order_is_deterministic():
    first = _build_item("sciq", "test", _sciq_row())
    second = _build_item("sciq", "test", _sciq_row())
    assert first.choices == second.choices
    assert first.gold_label == second.gold_label


def test_the_sciq_option_order_varies_with_the_item():
    """A fixed position for the correct answer would let positional bias
    masquerade as accuracy."""
    labels = {_build_item("sciq", "test",
                          {**_sciq_row(f"answer {i}"),
                           "question": f"question number {i}"}).gold_label
              for i in range(24)}
    assert len(labels) > 1, labels


def test_sciq_support_passages_are_not_put_in_the_prompt():
    item = _build_item("sciq", "test", _sciq_row())
    assert "a passage" not in item.question
    assert item.meta["support_present"] is True


def test_a_sciq_item_with_duplicate_options_is_flagged():
    row = {**_sciq_row(), "distractor1": "oxidants"}
    item = _build_item("sciq", "test", row)
    assert "duplicate_option_text" in item.notes


# ---------------------------------------------------------------------------
# opt-in: the real pinned datasets
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not REAL_DATASETS,
                    reason="set T31_REAL_DATASETS=1 to load the pinned datasets")
def test_the_real_benchmarks_load_to_their_pinned_counts():
    loaded = load_all()
    for name, items in loaded.items():
        assert len(items) == identity.BENCHMARK_IDENTITIES[name]["expected_items"]
        assert len({item.item_id for item in items}) == len(items)
        for item in items:
            assert item.question.strip()
            assert item.gold.strip() or item.notes
    assert sum(len(items) for items in loaded.values()) == \
        identity.TOTAL_EXPECTED_ITEMS
