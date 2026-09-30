"""T31 tests, brief categories 11, 12, 14, 15, 16.

- 11  zero-item failure
- 12  incomplete-run failure
- 14  raw-output persistence
- 15  resume logic
- 16  duplicate prevention

These are the categories that decide whether a number in the report is a
number over the benchmark or over whatever happened to finish. Each test here
exists because the natural implementation gets it wrong: the naive form of a
resume loop appends a second row, the naive form of a completeness check
asserts ``rows > 0``, and the naive form of a paired analysis inner-joins and
quietly shrinks its own denominator.
"""
from __future__ import annotations

import json

import pytest

from sciencemath.comparability import rows as R
from sciencemath.comparability.contract import ARM_BASE

from t31_comparability_support import item, mcq, raw_row, scored_row


def _items(n: int, *, benchmark: str = "gsm8k"):
    return [item(benchmark, question=f"Question number {i}?") for i in range(n)]


# ---------------------------------------------------------------------------
# category 14 — raw-output persistence
# ---------------------------------------------------------------------------
def test_raw_row_carries_every_field_the_brief_requires(tmp_path):
    row = raw_row(mcq(), ARM_BASE, generation="B")
    for field in R.RAW_FIELDS:
        assert field in row
    # The brief lists these by name; check the ones with unusual spellings.
    for field in ("raw_generation", "latency_s", "prompt_tokens",
                  "output_tokens", "gold", "system_prompt", "user_prompt"):
        assert field in row


def test_raw_row_persists_exactly_and_including_failures(tmp_path):
    path = tmp_path / "base.jsonl"
    good = raw_row(item(question="Good?"), ARM_BASE, generation="#### 72")
    bad = raw_row(item(question="Bad?"), ARM_BASE, generation="I am not sure",
                  finish_reason="stop")
    R.append_rows(path, [good, bad])
    back, corrupt = R.read_rows(path)
    assert corrupt == []
    assert len(back) == 2
    assert {r["raw_generation"] for r in back} == {"#### 72", "I am not sure"}
    # Incorrect and empty generations are retained, not filtered.
    empty = raw_row(item(question="Empty?"), ARM_BASE, generation="")
    R.append_rows(path, [empty])
    back, _ = R.read_rows(path)
    assert len(back) == 3
    assert any(r["raw_generation"] == "" for r in back)


def test_unicode_and_math_survive_a_round_trip(tmp_path):
    path = tmp_path / "base.jsonl"
    row = raw_row(item(question="What is ½ of π? ≤ 2?"),
                  ARM_BASE, generation="\\boxed{\\frac{\\pi}{2}} ± 0")
    R.append_rows(path, [row])
    back, _ = R.read_rows(path)
    assert back[0]["question"] == row["question"]
    assert back[0]["raw_generation"] == row["raw_generation"]


def test_scored_row_keeps_every_raw_field(tmp_path):
    raw = raw_row(item(), ARM_BASE)
    scored = scored_row(raw, content_valid=True)
    for field in R.RAW_FIELDS:
        assert scored[field] == raw[field]
    for field in R.SCORED_FIELDS:
        assert field in scored


def test_content_validity_is_separate_from_schema_validity():
    """The brief's permanent separation, asserted at the row level."""
    raw = raw_row(item(), ARM_BASE, generation="#### 11")
    row = scored_row(raw, content_valid=False, schema_valid=True,
                     error_category="wrong_final_answer")
    assert row["schema_valid"] is True
    assert row["content_valid"] is False
    assert row["correct"] is False          # never inherited from schema
    assert row["error_category"] != "correct"


def test_a_truncated_generation_is_flaggged_without_discarding_it():
    raw = raw_row(item(), ARM_BASE, generation="The answer is",
                  finish_reason="length")
    row = scored_row(raw, content_valid=False, status="FAILED",
                     extracted=None, error_category="truncated_generation")
    assert row["truncated"] is True
    assert row["invalid_output"] is True
    assert row["raw_generation"] == "The answer is"


def test_row_paths_refuse_unknown_coordinates(tmp_path):
    with pytest.raises(R.RowError, match="unknown arm"):
        R.raw_path(tmp_path, "nope", "gsm8k")
    with pytest.raises(R.RowError, match="unknown benchmark"):
        R.raw_path(tmp_path, "base", "gsm10k")


# ---------------------------------------------------------------------------
# category 11 — zero-item failure
# ---------------------------------------------------------------------------
def test_zero_rows_against_a_non_empty_expectation_fails():
    with pytest.raises(R.CompletenessError, match="missing"):
        R.require_complete([], ["t31-gsm8k-aaa", "t31-gsm8k-bbb"],
                           arm=ARM_BASE, benchmark="gsm8k")


def test_zero_rows_against_a_zero_expectation_also_fails():
    """An empty benchmark is a construction bug, not a perfect score."""
    report = R.validate_complete([], [], arm=ARM_BASE, benchmark="gsm8k")
    assert not report.complete
    with pytest.raises(R.CompletenessError):
        R.require_complete([], [], arm=ARM_BASE, benchmark="gsm8k")


# ---------------------------------------------------------------------------
# category 12 — incomplete-run failure
# ---------------------------------------------------------------------------
def test_a_run_missing_one_item_is_refused():
    subjects = _items(5)
    rows = [raw_row(subject, ARM_BASE) for subject in subjects[:4]]
    ids = [subject.item_id for subject in subjects]
    report = R.validate_complete(rows, ids, arm=ARM_BASE, benchmark="gsm8k")
    assert not report.complete
    assert report.expected == 5 and report.present == 4
    assert report.missing == (subjects[4].item_id,)
    assert "1 items missing" in report.describe()
    with pytest.raises(R.CompletenessError):
        R.require_complete(rows, ids, arm=ARM_BASE, benchmark="gsm8k")


def test_a_complete_run_passes_and_reports_counts():
    subjects = _items(5)
    rows = [raw_row(subject, ARM_BASE) for subject in subjects]
    report = R.require_complete(rows, [s.item_id for s in subjects],
                                arm=ARM_BASE, benchmark="gsm8k")
    assert report.complete
    assert report.to_dict()["present"] == 5
    assert "complete" in report.describe()


def test_rows_outside_the_frozen_item_set_are_refused():
    """A row for an item the frozen set does not contain is not extra data."""
    subjects = _items(3)
    intruder = item("gsm8k", question="A question from another revision?")
    rows = [raw_row(s, ARM_BASE) for s in subjects] + \
        [raw_row(intruder, ARM_BASE)]
    report = R.validate_complete(rows, [s.item_id for s in subjects],
                                 arm=ARM_BASE, benchmark="gsm8k")
    assert not report.complete
    assert report.unexpected == (intruder.item_id,)
    assert "outside the frozen item set" in report.describe()


def test_rows_from_two_configurations_cannot_be_mixed():
    subjects = _items(2)
    rows = [raw_row(subjects[0], ARM_BASE, config_hash="a" * 64),
            raw_row(subjects[1], ARM_BASE, config_hash="b" * 64)]
    report = R.validate_complete(rows, [s.item_id for s in subjects],
                                 arm=ARM_BASE, benchmark="gsm8k")
    assert not report.complete
    assert len(report.config_hashes) == 2
    assert "one configuration" in report.describe()


# ---------------------------------------------------------------------------
# category 15 — resume logic
# ---------------------------------------------------------------------------
def test_resume_sees_exactly_the_items_already_done(tmp_path):
    path = tmp_path / "base.jsonl"
    subjects = _items(6)
    R.append_rows(path, [raw_row(s, ARM_BASE) for s in subjects[:3]])
    back, _ = R.read_rows(path)
    done = R.completed_item_ids(back)
    assert done == {s.item_id for s in subjects[:3]}
    remaining = [s for s in subjects if s.item_id not in done]
    assert len(remaining) == 3


def test_resuming_the_same_item_overwrites_rather_than_appends(tmp_path):
    path = tmp_path / "base.jsonl"
    subject = _items(1)[0]
    R.append_rows(path, [raw_row(subject, ARM_BASE, generation="first")])
    R.append_rows(path, [raw_row(subject, ARM_BASE, generation="second")])
    back, _ = R.read_rows(path)
    assert len(back) == 1
    assert back[0]["raw_generation"] == "second"
    assert R.duplicate_item_ids(back) == []


def test_resume_after_a_full_run_reports_nothing_left(tmp_path):
    path = tmp_path / "base.jsonl"
    subjects = _items(4)
    ids = [s.item_id for s in subjects]
    R.append_rows(path, [raw_row(s, ARM_BASE) for s in subjects])
    back, _ = R.read_rows(path)
    assert R.completed_item_ids(back) == set(ids)
    assert R.require_complete(back, ids, arm=ARM_BASE,
                              benchmark="gsm8k").complete


def test_an_errored_row_still_counts_as_attempted(tmp_path):
    """Otherwise a persistently failing item makes a run unresumable."""
    path = tmp_path / "base.jsonl"
    subject = _items(1)[0]
    R.append_rows(path, [raw_row(subject, ARM_BASE, generation="",
                                 error="CUDA out of memory")])
    back, _ = R.read_rows(path)
    assert R.completed_item_ids(back) == {subject.item_id}


def test_appending_an_empty_batch_changes_nothing(tmp_path):
    path = tmp_path / "base.jsonl"
    subjects = _items(2)
    R.append_rows(path, [raw_row(s, ARM_BASE) for s in subjects])
    before, _ = R.read_rows(path)
    R.append_rows(path, [])
    after, _ = R.read_rows(path)
    assert before == after


def test_reads_do_not_create_a_file(tmp_path):
    path = tmp_path / "never-written.jsonl"
    assert R.read_rows(path) == ([], [])
    assert not path.exists()


# ---------------------------------------------------------------------------
# category 16 — duplicate prevention
# ---------------------------------------------------------------------------
def test_hand_written_duplicates_are_detected_not_averaged(tmp_path):
    path = tmp_path / "base.jsonl"
    subject = _items(1)[0]
    row = raw_row(subject, ARM_BASE)
    # Bypass append_rows to simulate a file from an older, buggier writer.
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n",
                    encoding="utf-8")
    back, _ = R.read_rows(path)
    assert R.duplicate_item_ids(back) == [subject.item_id]
    report = R.validate_complete(back, [subject.item_id], arm=ARM_BASE,
                                 benchmark="gsm8k")
    assert not report.complete
    assert "duplicate item ids" in report.describe()


def test_append_rows_repairs_duplicates_it_finds_on_disk(tmp_path):
    """``append_rows`` is read-merge-*deduplicate*-write, so merging into a
    file an older writer left duplicated must leave one row per item rather
    than faithfully preserving the duplicate. The key list is built from a
    dict, not appended per existing row."""
    path = tmp_path / "base.jsonl"
    subject = _items(1)[0]
    row = raw_row(subject, ARM_BASE)
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n",
                    encoding="utf-8")

    R.append_rows(path, [raw_row(_items(2)[1], ARM_BASE)])

    back, _ = R.read_rows(path)
    assert R.duplicate_item_ids(back) == []
    ids = [entry["item_id"] for entry in back]
    assert len(ids) == len(set(ids)) == 2


def test_two_different_items_are_never_collapsed():
    a = item("gsm8k", question="First?")
    b = item("gsm8k", question="Second?")
    assert a.item_id != b.item_id
    # The same question in two benchmarks is also two items.
    c = item("arc_challenge", question="First?")
    assert c.item_id != a.item_id


def test_unparseable_lines_are_reported_not_skipped(tmp_path):
    path = tmp_path / "base.jsonl"
    subject = _items(1)[0]
    path.write_text(json.dumps(raw_row(subject, ARM_BASE)) + "\n"
                    + '{"item_id": "t31-gsm8k-trunc"\n', encoding="utf-8")
    back, corrupt = R.read_rows(path)
    assert len(back) == 1
    assert corrupt == [2]
    # And a write over evidence that cannot be read is refused outright.
    with pytest.raises(R.RowError, match="unparseable lines"):
        R.append_rows(path, [raw_row(item(question="New?"), ARM_BASE)])


def test_a_write_never_leaves_a_partial_line(tmp_path):
    path = tmp_path / "base.jsonl"
    subjects = _items(40)
    R.append_rows(path, [raw_row(s, ARM_BASE) for s in subjects[:20]])
    R.append_rows(path, [raw_row(s, ARM_BASE) for s in subjects[20:]])
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    for line in text.splitlines():
        json.loads(line)                  # every line is complete JSON
    back, corrupt = R.read_rows(path)
    assert corrupt == [] and len(back) == 40


def test_no_temporary_files_are_left_behind(tmp_path):
    path = tmp_path / "base.jsonl"
    R.append_rows(path, [raw_row(s, ARM_BASE) for s in _items(3)])
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != path.name]
    assert leftovers == []
