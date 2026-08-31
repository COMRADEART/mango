"""Canonical dataset schema for ScienceMath-v0.1.

Every training/evaluation example, from any source, is converted to this
schema (one JSON object per line):

{
  "id":         "unique id (deterministic from source + content)",
  "domain":     "mathematics|physics|chemistry|biology|astronomy|"
                "earth_science|computer_science|general_science|"
                "scientific_reasoning|tool_use",
  "subject":    "algebra|mechanics|genetics|..." (free-form, recommended),
  "difficulty": 1..5 (optional, integer),
  "question":   required, non-empty,
  "answer":     required, non-empty (short final answer),
  "solution":   optional step-by-step reasoning (math),
  "explanation": optional explanatory prose (science),
  "source":     required, dataset slug (must exist in datasets.json),
  "source_id":  optional original example id,
  "license":    required, license identifier string,
  "split":      "train|validation|test|\" (assigned by build_splits.py)",
  "answer_type": optional, e.g. numeric|expression|multiple_choice|free_text
}

Unknown extra fields are passed through untouched (forward compatibility).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

DOMAINS = frozenset({
    "mathematics", "physics", "chemistry", "biology", "astronomy",
    "earth_science", "computer_science", "general_science",
    "scientific_reasoning", "tool_use",
})

REQUIRED_FIELDS = ("id", "domain", "question", "answer", "source", "license")
OPTIONAL_FIELDS = (
    "subject", "difficulty", "solution", "explanation",
    "source_id", "split", "answer_type",
)
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

VALID_SPLITS = frozenset({"train", "validation", "test", ""})

MIN_QUESTION_CHARS = 8
MIN_ANSWER_CHARS = 1

# Any character outside letters/numbers/whitespace/normal punctuation plus a
# small curated math/science symbol set is "unsupported" for our purposes and
# gets flagged by normalize_text.
_SUPPORTED_MATH_SYMBOLS = frozenset(
    "°±×÷≈≠≤≥√∑∏∫πσµΔδθλΩ∞′″·←→⇌⁺⁻²³⁴½¼¾"
)


def make_id(source: str, source_id: str, question: str) -> str:
    """Deterministic, collision-resistant id without external deps."""
    payload = f"{source}::{source_id}::{question.strip().lower()}".encode()
    return f"{source[:32].replace(' ', '_')}--{hashlib.sha1(payload).hexdigest()[:16]}"


def _check_text(value: Any, field: str, min_chars: int, max_chars: int,
                violations: list[str]) -> None:
    if not isinstance(value, str):
        violations.append(f"{field}: not a string")
        return
    if len(value.strip()) < min_chars:
        violations.append(f"{field}: empty or below {min_chars} chars")
    if len(value) > max_chars:
        violations.append(f"{field}: exceeds {max_chars} chars")


def validate_example(example: dict, *, min_question_chars: int = MIN_QUESTION_CHARS,
                     min_answer_chars: int = MIN_ANSWER_CHARS) -> list[str]:
    """Validate one canonical example. Returns a list of violations; an empty
    list means the record is schema-valid. Never raises."""
    v: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in example or example[field] is None:
            v.append(f"{field}: missing required field")
        elif isinstance(example[field], str) and not example[field].strip():
            v.append(f"{field}: empty string")

    if "domain" in example and example["domain"] not in DOMAINS:
        v.append(f"domain: unknown domain {example['domain']!r} "
                 f"(allowed: {sorted(DOMAINS)})")

    if "difficulty" in example and example["difficulty"] is not None:
        d = example["difficulty"]
        if not isinstance(d, int) or isinstance(d, bool) or not (1 <= d <= 5):
            v.append(f"difficulty: expected int in 1..5, got {d!r}")

    if "split" in example and example["split"]:
        if example["split"] not in VALID_SPLITS:
            v.append(f"split: invalid {example['split']!r}")

    if "question" in example:
        _check_text(example["question"], "question", min_question_chars, 8000, v)
    if "answer" in example:
        _check_text(example["answer"], "answer", min_answer_chars, 4000, v)

    for field in ("subject", "source", "license", "source_id", "answer_type"):
        if field in example and example[field] is not None and not isinstance(example[field], str):
            v.append(f"{field}: not a string")

    return v


def is_malformed_answer(answer: Any) -> bool:
    """Heuristic malformed-answer detection: placeholder/noise answers that
    some scraped corpora contain and that should never be trained on."""
    if not isinstance(answer, str):
        return True
    a = answer.strip()
    if len(a) < MIN_ANSWER_CHARS:
        return True
    placeholders = {"n/a", "na", "none", "null", "tbd", "?", "??", "-", "--",
                    "answer", "unknown", "nan", "#ref!", "#value!", "undefined"}
    if a.lower() in placeholders:
        return True
    # all punctuation/noise
    if not re.search(r"[\w]", a, re.UNICODE):
        return True
    # repeated single NON-alphanumeric char ("-----", "......", "===");
    # repeated digits/letters ("444", "aaa") are legitimate short answers
    if len(set(a)) == 1 and len(a) >= 3 and not re.match(r"[\w]", a, re.UNICODE):
        return True
    return False