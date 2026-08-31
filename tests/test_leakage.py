"""Leakage / contamination detection tests."""
import pytest

from sciencemath.datasets.leakage import check_splits, find_direct_leakage
from sciencemath.datasets.normalize import text_fingerprint
from sciencemath.datasets.splits import build_and_check


def rec(i, q, source="src", split="", domain="mathematics"):
    return {"id": f"{source}-{i}", "source": source, "domain": domain,
            "question": q, "answer": f"ans {i}", "license": "MIT", "split": split}


def test_direct_leakage_detected_across_splits():
    train = [rec(1, "What is Coulomb's law?", split="train")]
    test = [rec(2, "what is   coulomb's law ?", source="eval", split="test")]
    result = find_direct_leakage(train, {"test": test})
    assert result.has_direct
    assert result.direct[0].train_id == "src-1"


def test_no_false_positive_on_distinct_questions():
    train = [rec(1, "What is Coulomb's law?", split="train")]
    test = [rec(2, "Describe the process of mitosis.", source="eval", split="test")]
    assert not find_direct_leakage(train, {"test": test}).has_direct


def test_check_splits_raises_on_direct_leakage():
    train = [rec(1, "Solve 2x + 3 = 7 for x.", split="train")]
    test = [rec(2, "Solve 2x + 3 = 7 for x.", source="bench", split="test")]
    with pytest.raises(Exception):
        check_splits({"train": train, "test": test}, fail_on_direct=True)


def test_check_splits_passes_clean_data():
    train = [rec(i, f"Question {i} about arithmetic operations {i * 37}",
                 split="train") for i in range(20)]
    test = [rec(i, f"Biology question number {i} about cells {i * 53}",
                source="other", split="test") for i in range(5)]
    report = check_splits({"train": train, "test": test})
    assert report["passed"]


def test_eval_only_source_in_train_is_violation():
    train = [rec(1, "Which planet is largest?", source="astro-bench", split="train")]
    test = [rec(2, "Different physics query about heat.", source="other", split="test")]
    report = check_splits({"train": train, "test": test},
                          eval_only_sources={"astro-bench"}, fail_on_direct=False)
    assert report["eval_only_source_violations"]
    assert not report["passed"]


def test_near_leakage_flagged():
    q = ("Define the first law of thermodynamics and explain what it "
         "means for energy conservation in a closed system.")
    train = [rec(1, q, split="train")]
    test = [rec(2, q + " Please be thorough.", source="eval", split="test")]
    report = check_splits({"train": train, "test": test},
                          near_threshold=0.85, fail_on_direct=False)
    assert report["near_leakage"], "expected near-leakage to be detected"


def test_identical_questions_within_pipeline_do_not_leak():
    """Grouped by normalized question, exact duplicates collapse into the
    same split, so they can never leak across splits."""
    recs = [rec(1, "Leaky question about orbital mechanics.", source="a"),
            rec(2, "Leaky question about orbital mechanics.", source="a"),
            rec(3, "Unrelated chemistry question about acids.", source="a")]
    splits, summary, leakage = build_and_check(recs, seed=1)
    assert summary["leakage_passed"]
    assert not leakage["direct_leakage"]


def test_build_and_check_fails_on_leakage_when_groups_bypassed():
    """With group_by=source_id, same-text questions land in different groups
    and can leak; the check must then refuse (fail loudly, not silently)."""
    r1 = rec(1, "Leaky question about orbital mechanics.", source="a")
    r2 = rec(2, "Leaky question about orbital mechanics.", source="b")
    r3 = rec(3, "Unrelated chemistry question about acids.", source="b")
    # holdout source 'b' forces its records out of train, so r2 (leaky text)
    # goes to eval while r1 stays in train -> direct leakage must be caught
    with pytest.raises(Exception):
        build_and_check([r1, r2, r3], seed=1, group_by="source_id",
                        holdout_sources={"b"})


def test_fingerprint_collision_on_semantic_same_text():
    assert text_fingerprint("the mitochondrion produces ATP") == \
           text_fingerprint("The mitochondrion  produces ATP!")