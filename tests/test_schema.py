"""Canonical schema validation tests."""
from sciencemath.datasets.schema import (
    DOMAINS,
    is_malformed_answer,
    make_id,
    validate_example,
)


def make_record(**overrides):
    rec = {
        "id": "x1",
        "domain": "mathematics",
        "subject": "algebra",
        "difficulty": 2,
        "question": "Solve 3x + 7 = 22.",
        "answer": "x = 5",
        "solution": "Subtract 7 from both sides, then divide by 3.",
        "source": "test-source",
        "source_id": "t1",
        "license": "MIT",
        "split": "",
    }
    rec.update(overrides)
    return rec


def test_valid_record_has_no_violations():
    assert validate_example(make_record()) == []


def test_missing_required_field_flagged():
    rec = make_record()
    del rec["answer"]
    v = validate_example(rec)
    assert any("answer" in x and "missing" in x for x in v)


def test_empty_question_flagged():
    v = validate_example(make_record(question="   "))
    assert any("question" in x for x in v)


def test_unknown_domain_flagged():
    v = validate_example(make_record(domain="law"))
    assert any("domain" in x for x in v)


def test_difficulty_range_enforced():
    assert any("difficulty" in x for x in
               validate_example(make_record(difficulty=9)))
    assert any("difficulty" in x for x in
               validate_example(make_record(difficulty="3")))
    # bools are ints in Python; must still be rejected as invalid difficulty
    assert any("difficulty" in x for x in
               validate_example(make_record(difficulty=True)))
    assert validate_example(make_record(difficulty=5)) == []


def test_invalid_split_flagged():
    assert any("split" in x for x in
               validate_example(make_record(split="dev")))


def test_known_domains_cover_all_targets():
    for d in ("mathematics", "physics", "chemistry", "biology",
              "astronomy", "earth_science", "computer_science",
              "general_science", "scientific_reasoning", "tool_use"):
        assert d in DOMAINS


def test_malformed_answer_detection():
    assert is_malformed_answer("N/A")
    assert is_malformed_answer("???")
    assert is_malformed_answer("---")
    assert is_malformed_answer("")
    assert is_malformed_answer(None)
    assert is_malformed_answer("###")
    assert not is_malformed_answer("x = 5")
    assert not is_malformed_answer("42")
    assert not is_malformed_answer("The mitochondrion")
    assert not is_malformed_answer("-1.5e3")


def test_make_id_deterministic_and_distinct():
    a = make_id("src", "1", "Solve 3x + 7 = 22.")
    b = make_id("src", "1", "Solve 3x + 7 = 22.")
    c = make_id("src", "1", "Solve 3x + 9 = 31.")
    assert a == b and a != c