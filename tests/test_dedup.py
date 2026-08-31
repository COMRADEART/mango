"""Deduplication tests: exact, normalized, and near-duplicate detection."""
from sciencemath.datasets.dedup import deduplicate, jaccard, shingles


def rec(i, q, answer="4", solution=None, source="s"):
    return {"id": f"{source}-{i}", "source": source, "domain": "mathematics",
            "question": q, "answer": answer, "license": "MIT",
            **({"solution": solution} if solution else {})}


def test_exact_duplicates_removed():
    result = deduplicate([rec(1, "What is 2+2?"), rec(2, "What is 2+2?")],
                         near_enabled=False)
    assert result.n_kept == 1
    assert result.counts["exact"] == 1


def test_normalized_duplicates_removed():
    # identical after fingerprinting ("2 + 2" vs "2+2"), but distinct as raw
    # lowercased strings, so the normalized-text rule is what catches them
    result = deduplicate(
        [rec(1, "What is 2 + 2?"), rec(2, "what is 2+2?")],
        near_enabled=False)
    assert result.n_kept == 1
    assert result.counts["normalized"] == 1


def test_distinct_questions_kept():
    result = deduplicate([rec(1, "What is 2+2?"), rec(2, "Define entropy.")],
                         near_enabled=False)
    assert result.n_kept == 2


def test_prefer_record_with_solution():
    bare = rec(1, "What is 7 times 6?")
    rich = rec(2, "What is 7 times 6?", solution="Multiply 7 and 6.")
    result = deduplicate([bare, rich], near_enabled=False)
    assert result.n_kept == 1
    assert result.kept[0] is rich


def test_near_duplicates_clustered():
    qs = [
        "Compute the derivative of the function f where f(x) = 3x squared plus 2",
        "Compute the derivative of the function f where f(x) = 3x squared plus two",
        "Explain why the sky is blue during the day.",
    ]
    result = deduplicate([rec(i + 1, q) for i, q in enumerate(qs)])
    assert result.n_kept == 2
    assert result.counts["near_duplicate"] >= 1


def test_jaccard_basics():
    a = shingles("what is the derivative of sine", 4)
    b = shingles("what is the derivative of sine", 4)
    assert jaccard(a, b) == 1.0
    c = shingles("photosynthesis converts light energy", 4)
    assert jaccard(a, c) < 0.2


def test_no_crash_on_empty_and_tiny_questions():
    result = deduplicate([rec(1, ""), rec(2, "?"), rec(3, "ok so this is fine")],
                         near_enabled=False)
    # both empty and "?" fingerprint to "" so they collapse; the distinct
    # real question stays. Content checks reject such records elsewhere.
    assert result.n_kept == 2
    assert set(result.counts) >= {"exact", "normalized", "near_duplicate"}