"""Validation report generation tests."""
from sciencemath.datasets.report import build_validation_report, render_markdown
from sciencemath.datasets.splits import assign_splits
from sciencemath.utils.io_utils import write_jsonl, read_jsonl

import pytest


@pytest.fixture
def small_corpus():
    recs = []
    for i in range(60):
        domain = ["mathematics", "physics", "chemistry"][i % 3]
        recs.append({"id": f"r{i}", "source": "src-a" if i % 2 else "src-b",
                     "domain": domain, "subject": "algebra" if i % 3 == 0 else "mechanics",
                     "difficulty": (i % 5) + 1,
                     "question": f"Sample question {i} about topic {i % 7}",
                     "answer": str(i), "license": "MIT"})
    return recs


def test_report_counts_domains_and_sources(small_corpus):
    splits, summary = assign_splits(small_corpus, seed=42)
    for part in splits.values():
        for r in part:
            r["split"] = "x"
    report = build_validation_report(
        records=sum(splits.values(), []),
        split_summary=summary)
    assert report["total_examples"] == 60
    assert sum(report["by_domain"].values()) == 60
    assert set(report["by_source"]) == {"src-a", "src-b"}
    assert len(report["by_difficulty"]) == 5 or "unspecified" in report["by_difficulty"]


def test_report_counts_duplicates_and_rejections(small_corpus):
    rejected = {"malformed_answer": 3, "too_short": 1}
    report = build_validation_report(
        records=small_corpus,
        duplicates=[{"reason": "exact_question"}, {"reason": "exact_question"},
                    {"reason": "near_duplicate"}],
        rejected=rejected)
    assert report["duplicate_count"] == 3
    assert report["duplicates_by_reason"]["exact_question"] == 2
    assert report["rejected_count"] == 4


def test_markdown_renders_key_sections(small_corpus):
    report = build_validation_report(records=small_corpus[:10])
    md = render_markdown(report)
    for heading in ("Split distribution", "by Domain", "by Source"):
        assert heading in md


def test_jsonl_roundtrip(small_corpus, tmp_path):
    p = tmp_path / "c.jsonl"
    write_jsonl(p, small_corpus)
    loaded = read_jsonl(p)
    assert loaded == small_corpus