"""T31 tests, brief categories 6-10, 12 and 13 at the pass level.

The extractor and scorer tests check individual cases. These check the *pass*:
that every captured row is scored, that a short capture is refused instead of
scored, that a malformed generation becomes a scored failure rather than a
missing row, and that scoring is a pure function of the raw evidence.

The last of those is the one that matters most for the report. If scoring were
not reproducible, the scored hash the brief asks for would authenticate
nothing, since a rerun could produce a different file from the same
generations.
"""
from __future__ import annotations

import pytest

from sciencemath.comparability import scoring as S
from sciencemath.comparability.contract import ARM_ADAPTER, ARM_BASE
from sciencemath.comparability.rows import (
    append_rows, raw_path, read_rows, scored_path,
)

from t31_comparability_support import item, mcq, raw_row

CONFIG = "c" * 64


def capture(root, arm, benchmark, subjects, generations):
    """Write raw rows with chosen generations, the way a real run would."""
    rows = [raw_row(subject, arm=arm, generation=text)
            for subject, text in zip(subjects, generations)]
    append_rows(raw_path(root, arm, benchmark), rows)
    return rows


# ---------------------------------------------------------------------------
# the pass
# ---------------------------------------------------------------------------
def test_every_captured_row_becomes_a_scored_row(tmp_path):
    subjects = [item("gsm8k", question=f"Q{i}?", gold=str(i), native_id=f"n{i}")
                for i in range(3)]
    capture(tmp_path, ARM_BASE, "gsm8k", subjects, ["#### 0", "#### 1",
                                                    "#### 2"])
    progress = S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)
    assert progress.scored == 3 and progress.total == 3 and progress.correct == 3
    rows, bad = read_rows(scored_path(tmp_path, ARM_BASE, "gsm8k"))
    assert not bad and len(rows) == 3
    assert all(row["content_valid"] and row["schema_valid"] for row in rows)


def test_the_scored_row_carries_the_raw_generation_unchanged(tmp_path):
    """The scored file is evidence in its own right, not a summary that
    replaces the generation it judged."""
    subjects = [item("gsm8k", gold="72", native_id="n0")]
    capture(tmp_path, ARM_BASE, "gsm8k", subjects, ["working...\n#### 72"])
    S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)
    rows, _ = read_rows(scored_path(tmp_path, ARM_BASE, "gsm8k"))
    assert rows[0]["raw_generation"] == "working...\n#### 72"
    assert rows[0]["normalized_generation"] == "working...\n#### 72"
    assert rows[0]["extracted_answer"] == "72"


def test_an_unreadable_generation_is_scored_not_dropped(tmp_path):
    """Dropping it would raise every rate by shrinking the denominator."""
    subjects = [item("gsm8k", gold="72", native_id="n0"),
                item("gsm8k", gold="1", native_id="n1")]
    capture(tmp_path, ARM_BASE, "gsm8k", subjects, ["I cannot solve this.",
                                                    "#### 1"])
    progress = S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)
    assert progress.scored == 2
    assert progress.correct == 1
    rows, _ = read_rows(scored_path(tmp_path, ARM_BASE, "gsm8k"))
    by_id = {row["item_id"]: row for row in rows}
    failed = by_id[subjects[0].item_id]
    assert failed["content_valid"] is False
    assert failed["error_category"] == "abstention"
    assert failed["extraction_status"] == "FAILED"


def test_a_short_capture_is_refused_rather_than_scored(tmp_path):
    """Category 12: an incomplete run must fail, not report a rate."""
    subjects = [item("gsm8k", gold=str(i), native_id=f"n{i}") for i in range(3)]
    capture(tmp_path, ARM_BASE, "gsm8k", subjects[:2], ["#### 0", "#### 1"])
    with pytest.raises(Exception, match="INCOMPLETE"):
        S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)


def test_an_empty_capture_is_refused(tmp_path):
    """The vacuity case: no rows must never score as a clean sweep."""
    subjects = [item("gsm8k", gold="1", native_id="n0")]
    with pytest.raises(Exception, match="INCOMPLETE"):
        S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)


def test_scoring_can_be_asked_for_over_a_deliberately_short_set(tmp_path):
    """Used by the smoke test, where a partial run is the point — but the
    caller has to say so, and nothing downstream may report a rate from it."""
    subjects = [item("gsm8k", gold=str(i), native_id=f"n{i}") for i in range(3)]
    capture(tmp_path, ARM_BASE, "gsm8k", subjects[:1], ["#### 0"])
    progress = S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path,
                           require=False)
    assert progress.scored == 1 and progress.total == 1


def test_a_row_for_an_item_outside_the_suite_is_refused(tmp_path):
    """Otherwise a results table could carry a row no item accounts for."""
    subjects = [item("gsm8k", gold="1", native_id="n0")]
    stranger = item("gsm8k", question="Different?", gold="1", native_id="other")
    capture(tmp_path, ARM_BASE, "gsm8k", [stranger], ["#### 1"])
    with pytest.raises(S.ScoringError, match="not in the frozen suite"):
        S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path, require=False)


def test_two_items_with_one_id_are_refused():
    subjects = [item("gsm8k", question="A?", gold="1", native_id="n0"),
                item("gsm8k", question="B?", gold="2", native_id="n0")]
    with pytest.raises(S.ScoringError, match="share the id"):
        S.item_index(subjects)


# ---------------------------------------------------------------------------
# category 13 - malformed output, end to end
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("benchmark,subjects,generations", [
    ("gsm8k",
     [item("gsm8k", question="Q?", gold="72", native_id="n0")],
     ["", "   ", "\n\n", "no digits at all", "#### ", "????"]),
    ("arc_easy",
     [mcq(gold_label="A")],
     ["", "   ", "I do not know", "none of them", "?????"]),
])
def test_malformed_generations_fail_closed_at_every_stage(
        tmp_path, benchmark, subjects, generations):
    """A generation with no answer must never be read as a right one."""
    for text in generations:
        root = tmp_path / text.strip().replace(" ", "_").replace("?", "q") or \
            tmp_path / "empty"
        capture(root, ARM_BASE, benchmark, subjects, [text])
        S.score_arm(benchmark, ARM_BASE, subjects, root=root, require=False)
        rows, _ = read_rows(scored_path(root, ARM_BASE, benchmark))
        assert rows[0]["content_valid"] is False, text
        assert rows[0]["schema_valid"] is False, text
        assert rows[0]["error_category"] in (
            "answer_extraction_failure", "abstention", "truncated_generation")


def test_a_truncated_generation_keeps_its_raw_text(tmp_path):
    subjects = [item("gsm8k", gold="72", native_id="n0")]
    append_rows(raw_path(tmp_path, ARM_BASE, "gsm8k"),
                [raw_row(subjects[0], arm=ARM_BASE, generation="First, she",
                         finish_reason="length")])
    S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)
    rows, _ = read_rows(scored_path(tmp_path, ARM_BASE, "gsm8k"))
    assert rows[0]["truncated"] is True
    assert rows[0]["invalid_output"] is True
    assert rows[0]["error_category"] == "truncated_generation"
    assert rows[0]["raw_generation"] == "First, she"


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------
def test_rescoring_produces_a_byte_identical_file(tmp_path):
    """The scored hash the brief asks for must authenticate something."""
    subjects = [item("gsm8k", gold=str(i), native_id=f"n{i}") for i in range(4)]
    capture(tmp_path, ARM_BASE, "gsm8k", subjects,
            ["#### 0", "so it is 1", "#### 99", "I cannot say"])
    S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)
    before = scored_path(tmp_path, ARM_BASE, "gsm8k").read_bytes()
    assert S.rescore_is_identical("gsm8k", ARM_BASE, subjects, root=tmp_path)
    S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)
    assert scored_path(tmp_path, ARM_BASE, "gsm8k").read_bytes() == before


def test_rescoring_detects_a_row_that_no_longer_matches(tmp_path):
    subjects = [item("gsm8k", gold="72", native_id="n0")]
    capture(tmp_path, ARM_BASE, "gsm8k", subjects, ["#### 72"])
    S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)
    row = read_rows(scored_path(tmp_path, ARM_BASE, "gsm8k"))[0][0]
    row["content_valid"] = False          # simulate tampering with the file
    append_rows(scored_path(tmp_path, ARM_BASE, "gsm8k"), [row])
    assert not S.rescore_is_identical("gsm8k", ARM_BASE, subjects, root=tmp_path)


def test_scoring_does_not_depend_on_the_other_arm(tmp_path):
    """Both arms are scored by the same function; a difference between the
    two scored sets can only come from the generations."""
    subjects = [item("gsm8k", gold="72", native_id="n0"),
                item("gsm8k", gold="5", native_id="n1")]
    capture(tmp_path, ARM_BASE, "gsm8k", subjects, ["#### 72", "#### 9"])
    capture(tmp_path, ARM_ADAPTER, "gsm8k", subjects, ["#### 72", "#### 5"])
    base = S.score_arm("gsm8k", ARM_BASE, subjects, root=tmp_path)
    adapter = S.score_arm("gsm8k", ARM_ADAPTER, subjects, root=tmp_path)
    assert base.correct == 1 and adapter.correct == 2
    base_rows = {r["item_id"]: r for r in
                 read_rows(scored_path(tmp_path, ARM_BASE, "gsm8k"))[0]}
    adapter_rows = {r["item_id"]: r for r in
                    read_rows(scored_path(tmp_path, ARM_ADAPTER, "gsm8k"))[0]}
    for item_id, row in base_rows.items():
        # Everything but the outcome and the generation is the same evidence.
        assert row["gold"] == adapter_rows[item_id]["gold"]
        assert row["question"] == adapter_rows[item_id]["question"]
        assert row["config_hash"] == adapter_rows[item_id]["config_hash"]
