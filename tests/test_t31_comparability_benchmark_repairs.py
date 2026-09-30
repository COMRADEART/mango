"""T31 tests: benchmark presentation defects found and repaired for BOTH arms.

The brief: "Any discovered benchmark bug must be repaired for BOTH base and
adapter and the affected evaluations rerun." Two were found by measuring the
pinned revisions before any generation ran, and both are repaired at the item
level — which is what makes them arm-symmetric by construction rather than by
discipline.

**Defect 1 — ARC's option labels are not uniform.** arc_easy's test split
labels 2,268 items ``A-D`` and 97 items ``1-4``; arc_challenge labels 1,144
``A-D`` and 21 ``1-4``; and 7 + 4 items offer three or five options rather
than four. The single frozen prompt asks for "the single letter of the correct
option", so 4% of items would have contradicted their own instruction, and
items would have differed from each other in a way unrelated to capability.
Repair: labels rewritten to canonical letters in their original order, for
both arms, with the original labels and answer key retained on the item.

**Defect 2 — SciQ items whose distractor repeats the correct answer.** 9 of
1,000 items carry ``duplicate_option_text``: the correct answer's text appears
at two labels. A model that writes out the right answer could be read as
having chosen the twin and marked wrong. Repair: at the text-matching tier
only, a written answer that names the gold option's text is accepted — while a
letter the model chose itself is still judged against the gold label exactly.

Neither repair changes which answer is right; both change only how an answer
is named or read. Both apply to every item of every arm.
"""
from __future__ import annotations

import pytest

from sciencemath.comparability.extractors import extract
from sciencemath.comparability.loaders import (
    EvalItem, _arc_options, item_id_for,
)
from sciencemath.comparability.scorers import score

from t31_comparability_support import raw_row, scored_row


def _arc_row(labels, answer_key, texts=None):
    texts = texts or [f"option {i}" for i in range(len(labels))]
    return {"id": "Mercury_1", "question": "Which?",
            "answerKey": answer_key,
            "choices": {"label": list(labels), "text": list(texts)}}


# ---------------------------------------------------------------------------
# defect 1 — ARC option labels
# ---------------------------------------------------------------------------
def test_numeric_labels_are_rewritten_to_letters():
    choices, gold, gold_label, notes, meta = _arc_options(
        _arc_row(["1", "2", "3", "4"], "2"))
    assert [label for label, _ in choices] == ["A", "B", "C", "D"]
    assert gold_label == "B"          # original label "2" is the second option
    assert gold == "B"
    assert meta["original_option_labels"] == ["1", "2", "3", "4"]
    assert meta["original_answer_key"] == "2"
    assert "options_relabelled" in notes


def test_option_texts_and_their_order_are_untouched():
    texts = ["gravity", "magnetism", "friction", "pressure"]
    choices, gold, gold_label, _, _ = _arc_options(
        _arc_row(["1", "2", "3", "4"], "3", texts))
    assert [text for _, text in choices] == texts
    assert choices[2] == ("C", "friction")
    assert gold == gold_label == "C"


def test_already_canonical_labels_are_untouched_and_unnoted():
    choices, _, gold_label, notes, _ = _arc_options(
        _arc_row(["A", "B", "C", "D"], "C"))
    assert [label for label, _ in choices] == ["A", "B", "C", "D"]
    assert gold_label == "C"
    assert "options_relabelled" not in notes


def test_three_option_items_keep_three_options():
    choices, _, gold_label, _, _ = _arc_options(
        _arc_row(["A", "B", "C"], "C"))
    assert len(choices) == 3
    assert gold_label == "C"


def test_five_option_items_keep_five_options():
    choices, _, gold_label, _, _ = _arc_options(
        _arc_row(["A", "B", "C", "D", "E"], "E"))
    assert len(choices) == 5
    assert gold_label == "E"


def test_the_relabelling_preserves_which_answer_is_right():
    """The mapping must move the gold label with the option, not beside it."""
    for labels, key in ((["1", "2", "3", "4"], k) for k in "1234"):
        choices, _, gold_label, _, _ = _arc_options(_arc_row(labels, key))
        index = labels.index(key)
        original = ["A", "B", "C", "D"][index]
        assert gold_label == original


def test_a_non_canonical_key_maps_through_the_rewrite():
    _, _, gold_label, _, _ = _arc_options(_arc_row(["1", "2", "3", "4"], "4"))
    assert gold_label == "D"


def test_an_answer_key_outside_the_options_is_recorded_not_invented():
    _, gold, gold_label, notes, _ = _arc_options(
        _arc_row(["A", "B", "C", "D"], "Z"))
    assert gold_label is None
    assert gold == "Z"
    assert "answer_key_not_in_choices" in notes


def test_a_multi_key_row_yields_no_gold_label_rather_than_a_guess():
    _, _, gold_label, notes, _ = _arc_options(
        _arc_row(["A", "B", "C", "D"], "A,C"))
    assert gold_label is None
    assert "multiple_answer_keys" in notes


def test_gold_label_is_always_one_of_the_items_own_labels():
    """The property the extractor depends on for both arms."""
    for labels, key in ((["A", "B", "C", "D"], "B"),
                        (["1", "2", "3", "4"], "1"),
                        (["A", "B", "C"], "C"),
                        (["1", "2", "3"], "3")):
        choices, _, gold_label, _, _ = _arc_options(_arc_row(labels, key))
        assert gold_label in {label for label, _ in choices}


def test_a_relabelled_item_scores_the_same_letter_either_way():
    """End to end: the model answers 'B', the item said '2'."""
    choices, gold, gold_label, _, _ = _arc_options(_arc_row(["1", "2", "3", "4"], "2"))
    subject = EvalItem(item_id=item_id_for("arc_easy", "test", "Mercury_1"),
                       benchmark="arc_easy", split="test",
                       native_id="Mercury_1", question="Which?", choices=choices,
                       gold=gold, gold_label=gold_label, meta={})
    right = extract(subject, "multiple_choice", "The answer is B.")
    wrong = extract(subject, "multiple_choice", "The answer is D.")
    assert score(subject, "multiple_choice", right, "The answer is B.").content_valid
    assert not score(subject, "multiple_choice", wrong, "The answer is D.").content_valid


# ---------------------------------------------------------------------------
# defect 2 — SciQ duplicate option text
# ---------------------------------------------------------------------------
TWIN = ("technological design")


def _sciq_twin() -> EvalItem:
    return EvalItem(
        item_id=item_id_for("sciq", "test", "twin"), benchmark="sciq",
        split="test", native_id=None,
        question="What term is used to describe the development of new technology?",
        choices=(("A", TWIN), ("B", "natural selection"),
                 ("C", TWIN), ("D", "photosynthesis")),
        gold="C", gold_label="C", meta={})


def test_the_gold_letter_is_correct_as_always():
    subject = _sciq_twin()
    result = extract(subject, "multiple_choice", "The answer is C.")
    scored = score(subject, "multiple_choice", result, "The answer is C.")
    assert scored.content_valid and scored.schema_valid
    assert scored.error_category == "correct"


def test_writing_the_gold_text_is_correct_even_if_read_as_the_twin():
    subject = _sciq_twin()
    result = extract(subject, "multiple_choice", TWIN)
    assert result.label == "A"                    # the twin, not the gold "C"
    scored = score(subject, "multiple_choice", result, TWIN)
    assert scored.content_valid is True
    assert "duplicate-text twin" in " ".join(scored.notes)


def test_the_repair_keeps_content_and_schema_separate():
    """Answered correctly, but not in the requested format."""
    subject = _sciq_twin()
    result = extract(subject, "multiple_choice", TWIN)
    scored = score(subject, "multiple_choice", result, TWIN)
    assert scored.content_valid is True
    assert scored.schema_valid is False


def test_a_different_option_text_is_still_wrong():
    subject = _sciq_twin()
    result = extract(subject, "multiple_choice", "photosynthesis")
    assert score(subject, "multiple_choice", result,
                 "photosynthesis").content_valid is False


def test_the_repair_does_not_fire_when_the_model_chose_a_letter():
    """A model that writes "A" has made a choice; it does not get the twin."""
    subject = _sciq_twin()
    result = extract(subject, "multiple_choice", "The answer is A.")
    scored = score(subject, "multiple_choice", result, "The answer is A.")
    assert scored.content_valid is False
    assert scored.error_category == "wrong_final_answer"


def test_the_repair_is_a_no_op_on_an_item_without_duplicate_text():
    subject = EvalItem(
        item_id=item_id_for("sciq", "test", "plain"), benchmark="sciq",
        split="test", native_id=None, question="Plain?",
        choices=(("A", "alpha"), ("B", "beta"), ("C", "gamma"),
                 ("D", "delta")),
        gold="C", gold_label="C", meta={})
    good = extract(subject, "multiple_choice", "gamma")
    bad = extract(subject, "multiple_choice", "beta")
    assert score(subject, "multiple_choice", good, "gamma").content_valid
    assert not score(subject, "multiple_choice", bad, "beta").content_valid
    assert "duplicate-text twin" not in " ".join(
        score(subject, "multiple_choice", good, "gamma").notes)


def test_the_repair_is_recorded_on_the_scored_row():
    subject = _sciq_twin()
    row = scored_row(raw_row(subject, "adapter", generation=TWIN),
                     content_valid=True, schema_valid=False,
                     extracted="A", tier="option_text", status="OK")
    assert row["content_valid"] is True and row["truncated"] is False
