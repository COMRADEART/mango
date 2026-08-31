"""Normalization tests: unicode cleanup, fingerprints, numerics, full-record
normalization."""
from sciencemath.datasets.normalize import (
    answer_fingerprint,
    clean_text,
    normalize_example,
    normalize_numeric,
    text_fingerprint,
    unsupported_characters,
)


def test_control_and_zero_width_removed():
    text, issues = clean_text("sol​ve \x07this")
    assert "\x07" not in text and "​" not in text
    assert "removed_control_chars" in issues
    assert "removed_zero_width" in issues


def test_smart_punctuation_translated():
    text, _ = clean_text("Newton’s law — F = ma − 5")
    assert "Newton's law - F = ma - 5" == text


def test_whitespace_collapsed():
    text, _ = clean_text("a   b\t\tc")
    assert text == "a b c"


def test_fingerprint_is_language_normalized():
    assert text_fingerprint("Solve 3X + 7 = 22.") == \
           text_fingerprint("solve   3x + 7 = 22")


def test_fingerprint_strips_formatting():
    assert text_fingerprint("What is 2 + 2?") == \
           text_fingerprint("What is 2 + 2 ?")


def test_answer_fingerprint_variants_converge():
    variants = ["x = 5", "x=5.", "$x = 5$", "Answer: 5", "\\boxed{5}"]
    fps = {answer_fingerprint(v) for v in variants}
    assert fps == {"5"}


def test_normalize_numeric():
    assert normalize_numeric("1,234,567") == "1234567"
    assert normalize_numeric("2.50") == "2.5"
    assert normalize_numeric("  -3.90 ") == "-3.9"
    assert normalize_numeric("$1,000") == "1000"
    assert normalize_numeric("forty-two") is None


def test_unsupported_characters_detected():
    bad = ""  # emoji are unsupported in our whitelist
    out = unsupported_characters(bad)
    assert out == []
    assert unsupported_characters("2 \U0001F600  3") == ["\U0001F600"]


def test_normalize_example_happy_path():
    rec, issues = normalize_example({
        "source": "t", "license": "MIT", "domain": "mathematics",
        "question": "What  is\t2 + 2?", "answer": "4",
        "solution": "Add.",
    })
    assert rec is not None, issues
    assert rec["question"] == "What is 2 + 2?"
    assert rec["id"].startswith("t-") or rec["id"]
    assert issues == []


def test_normalize_example_rejects_malformed_answer():
    rec, issues = normalize_example({
        "source": "t", "license": "MIT", "domain": "physics",
        "question": "What is the escape velocity?",
        "answer": "n/a", "id": "x",
    })
    assert rec is None
    assert any("malformed_answer" in i for i in issues)


def test_normalize_example_too_short_question():
    rec, issues = normalize_example({
        "source": "t", "license": "MIT", "domain": "mathematics",
        "question": "?", "answer": "1",
    })
    assert rec is None
    assert any("too_short" in i for i in issues)


def test_normalize_preserves_optional_fields():
    rec, _ = normalize_example({
        "source": "t", "license": "MIT", "subject": "genetics",
        "domain": "biology", "question": "What molecule carries heredity?",
        "answer": "DNA", "difficulty": 2, "explanation": "DNA stores info.",
        "answer_type": "free_text",
    })
    assert rec is not None
    assert rec["subject"] == "genetics"
    assert rec["difficulty"] == 2
    assert rec["answer_type"] == "free_text"