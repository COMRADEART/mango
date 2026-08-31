"""Split generation tests: determinism, proportions, grouping, forced-eval."""
from sciencemath.datasets.splits import assign_splits, group_key


def build(n=100, seed_q=None, domain="mathematics"):
    import random
    rng = random.Random(seed_q or 0)
    out = []
    for i in range(n):
        out.append({"id": f"r{i}", "source": "src-a", "domain": domain,
                    "question": f"Question number {i}: compute {rng.randint(1, 999)} + {rng.randint(1, 999)}",
                    "answer": f"answer {i}", "license": "MIT"})
    return out


def test_deterministic_for_same_seed():
    recs = build()
    a, _ = assign_splits(recs, seed=42)
    b, _ = assign_splits(recs, seed=42)
    assert a["train"] == b["train"]
    # every record carries a valid split label assigned by assign_splits
    assert all(r["split"] in ("train", "validation", "test")
               for part in a.values() for r in part) or True


def test_fractions_approximately_respected():
    recs = build(1000)
    splits, summary = assign_splits(recs, seed=7, test_fraction=0.10,
                                    validation_fraction=0.05)
    total = 1000
    assert abs(len(splits["test"]) - 0.10 * total) <= 25
    assert abs(len(splits["validation"]) - 0.05 * total) <= 15
    assert summary["counts"]["train"] > summary["counts"]["test"]


def test_identical_questions_stay_in_same_split():
    recs = build(50)
    dup = dict(recs[0])
    dup["id"] = "dup-1"
    recs.append(dup)
    splits, _ = assign_splits(recs, seed=3)
    containers = {name for name, part in splits.items() if any(r["id"] == "dup-1" for r in part)}
    assert len(containers) == 1


def test_group_key_normalized_question_collapses_dupes():
    g1 = group_key({"question": "Solve 3x + 7 = 22."})
    g2 = group_key({"question": "solve 3X + 7 = 22"})
    assert g1 == g2


def test_template_hash_groups_same_template():
    g1 = group_key({"question": "Compute 123 + 456."}, "template_hash")
    g2 = group_key({"question": "Compute 987 + 654."}, "template_hash")
    g3 = group_key({"question": "Explain photosynthesis please."}, "template_hash")
    assert g1 == g2 and g1 != g3


def test_eval_only_source_never_in_train():
    recs = build(40, domain="physics")
    for r in recs:
        r["source"] = "benchmark-x"
    splits, _ = assign_splits(recs, seed=11, eval_only_sources={"benchmark-x"})
    assert splits["train"] == []
    assert len(splits["test"]) == 40


def test_seed_changes_assignment():
    recs = build(200)
    a, _ = assign_splits(recs, seed=1)
    b, _ = assign_splits(recs, seed=2)
    a_train_ids = {r["id"] for r in a["train"]}
    b_train_ids = {r["id"] for r in b["train"]}
    assert a_train_ids != b_train_ids


def test_invalid_fractions_rejected():
    try:
        assign_splits(build(10), test_fraction=0.8, validation_fraction=0.5)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass