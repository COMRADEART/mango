"""Deterministic failure taxonomy for evaluation predictions.

Classification order is fixed so runs are reproducible:
  GENERATION_ERROR -> OOM -> CONTEXT_OVERFLOW -> TRUNCATED_OUTPUT ->
  REFUSAL -> INVALID_CHOICE -> EXTRACTION_FAILURE -> WRONG_ANSWER -> PASS
(and UNKNOWN only when nothing else applies). HALLUCINATED_FACT is NOT
assigned automatically in T2 — it requires evidence beyond output-vs-gold
comparison and is reserved for later analysis; it is defined for the
taxonomy but never produced by classify_failure().
"""
from __future__ import annotations

CATEGORIES = (
    "WRONG_ANSWER", "EXTRACTION_FAILURE", "FORMAT_FAILURE", "REFUSAL",
    "HALLUCINATED_FACT", "INVALID_CHOICE", "TRUNCATED_OUTPUT",
    "CONTEXT_OVERFLOW", "GENERATION_ERROR", "OOM", "UNKNOWN",
)

_REFUSAL_PATTERNS = (
    "i cannot", "i can't", "i'm sorry", "i am sorry", "as an ai",
    "i will not", "i won't", "i apologize", "against my guidelines",
)

_REFUSAL_ONLY_CATEGORIES = {"uncertainty_calibration"}


def is_refusal(raw: str) -> bool:
    t = (raw or "").lower()
    return any(p in t for p in _REFUSAL_PATTERNS)


def classify_failure(*, correct: bool, extracted: str | None,
                     answer_type: str, choices: list[str] | None,
                     raw: str, error: str | None = None,
                     finish_reason: str | None = None,
                     expected_answer: str | None = None,
                     category: str = "") -> str | None:
    """Return a failure category string, or None when the prediction passed
    and no failure applies. Deterministic: same inputs -> same category."""
    if error:
        e = error.lower()
        if "out of memory" in e or "oom" in e or "cuda error" in e:
            return "OOM"
        if "max length" in e or "context length" in e or "too long" in e:
            return "CONTEXT_OVERFLOW"
        return "GENERATION_ERROR"
    if correct:
        return None
    if finish_reason == "length" and extracted:
        # ran out of tokens mid-answer
        return "TRUNCATED_OUTPUT"
    if answer_type == "multiple_choice" and extracted is not None \
            and extracted not in {chr(65 + i) for i in range(len(choices or []))}:
        return "INVALID_CHOICE"
    if extracted is None and is_refusal(raw):
        return "REFUSAL"
    if answer_type == "multiple_choice" and extracted is None:
        return "EXTRACTION_FAILURE"
    if expected_answer == "__UNKNOWN__":
        # calibration item answered with a (wrong) confident assertion
        return "WRONG_ANSWER"
    if is_refusal(raw):
        return "REFUSAL"
    if extracted is None:
        return "EXTRACTION_FAILURE"
    if not str(raw or "").strip():
        return "FORMAT_FAILURE"
    return "WRONG_ANSWER"