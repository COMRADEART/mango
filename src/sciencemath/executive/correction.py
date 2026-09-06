"""T7.16/T7.17/T7.18 — Self-correction, redesigned.

Correction is allowed ONLY when external, contradictory evidence exists
(a failed CHECK against a tool recomputation, a detected contradiction
between observations). The model never "reviews its answer" generically.
The correction contract passes structured feedback (what failed, which
evidence contradicts it, what the evidence says). Overcorrection
protection: a correction that changes a correct answer is a measured
harm (T7.36), so corrections are gated and bounded (max 1 per run).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Callable

MAX_CORRECTIONS = 1


class FeedbackTrust(str, Enum):
    VERIFIED = "VERIFIED"
    SUPPORTED = "SUPPORTED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"


class CorrectionDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"


AUTHORITATIVE_SOURCES = frozenset({
    "T4_VERIFIER", "MATH_TOOL", "UNIT_CHECK", "SCHEMA_VALIDATOR",
    "TEST_HARNESS",
})
SUPPORTED_SOURCES = frozenset({"RETRIEVAL_EVIDENCE", "CITATION_CHECK"})
FEEDBACK_SOURCES = AUTHORITATIVE_SOURCES | SUPPORTED_SOURCES | {
    "UNVERIFIED_MODEL_FEEDBACK"
}


@dataclass(frozen=True)
class CorrectionState:
    initial_answer: str
    initial_verification: str
    feedback_type: str
    feedback_trust: str
    repair_required: bool
    repair_scope: str | None
    revised_answer: str | None
    final_verification: str
    correction_decision: str

    def to_dict(self) -> dict:
        return asdict(self)


def determine_feedback_trust(source: str, validation: str) -> FeedbackTrust:
    """Map provenance and independent validation to a fail-closed trust level."""
    if source not in FEEDBACK_SOURCES:
        raise ValueError(f"unknown correction provenance: {source!r}")
    verdict = str(validation).upper()
    if verdict == "CONTRADICTED" or verdict == "PASS":
        return FeedbackTrust.CONTRADICTED
    if source == "UNVERIFIED_MODEL_FEEDBACK" or verdict == "UNKNOWN":
        return FeedbackTrust.UNVERIFIED
    if verdict != "FAIL":
        return FeedbackTrust.UNVERIFIED
    if source in AUTHORITATIVE_SOURCES:
        return FeedbackTrust.VERIFIED
    return FeedbackTrust.SUPPORTED


def targeted_repair_prompt(question: str, answer: str, component: str,
                           evidence: str, expected: str | None = None) -> str:
    """Build a bounded repair request; never asks for whole-answer review."""
    expected_line = f"\nVerified expected value: {expected}" if expected else ""
    return (
        f"Question: {question}\nCurrent answer: {answer}\n"
        f"Repair only this component: {component}\n"
        f"Validated evidence: {evidence}{expected_line}\n"
        "Preserve every other claim and citation. Return the complete answer with "
        "only that component changed. End with the repaired final value inside "
        "\\boxed{} on the last line."
    )


def correction_firewall(*, initial_answer: str, feedback_type: str,
                        feedback_source: str, validation: dict,
                        repair_scope: str | None = None,
                        repair: Callable[[str], str] | None = None,
                        reverify: Callable[[str], str] | None = None,
                        question: str = "") -> CorrectionState:
    """Validate feedback, optionally run one targeted repair, and re-verify it.

    UNVERIFIED feedback is deferred. Feedback contradicted by verification is
    rejected while preserving the original. Citation-only failures are kept
    separate by requiring a citation repair scope.
    """
    initial_verification = str(validation.get("original_status", "UNKNOWN")).upper()
    trust = determine_feedback_trust(feedback_source,
                                     str(validation.get("feedback_status", "UNKNOWN")))
    if trust == FeedbackTrust.CONTRADICTED:
        return CorrectionState(initial_answer, initial_verification,
                               feedback_type, trust.value, False, None, None,
                               initial_verification, CorrectionDecision.REJECT.value)
    if trust == FeedbackTrust.UNVERIFIED:
        return CorrectionState(initial_answer, initial_verification,
                               feedback_type, trust.value, False, None, None,
                               initial_verification, CorrectionDecision.DEFER.value)

    scope = repair_scope or validation.get("failed_component")
    if not scope:
        return CorrectionState(initial_answer, initial_verification,
                               feedback_type, trust.value, False, None, None,
                               initial_verification, CorrectionDecision.DEFER.value)
    if feedback_type == "CITATION_ERROR" and not str(scope).startswith("citation"):
        scope = "citation"
    if repair is None or reverify is None:
        return CorrectionState(initial_answer, initial_verification,
                               feedback_type, trust.value, True, str(scope), None,
                               "UNKNOWN", CorrectionDecision.DEFER.value)

    prompt = targeted_repair_prompt(
        question, initial_answer, str(scope),
        str(validation.get("evidence", "validated correction signal")),
        validation.get("expected"),
    )
    revised = repair(prompt)
    final = str(reverify(revised)).upper()
    accepted = final == "PASS"
    return CorrectionState(
        initial_answer, initial_verification, feedback_type, trust.value, True,
        str(scope), revised if accepted else None, final,
        (CorrectionDecision.ACCEPT if accepted else CorrectionDecision.REJECT).value,
    )

CORRECTION_PROMPT = """Question: {question}

Your previous answer was: {prev}

This answer FAILED verification. Structured feedback:
- Failing check: {failing_check}
- Contradicting evidence: {contradicting_evidence}
- Expected consistency: {expected}

Re-answer the question using the evidence above. If the evidence does \
not actually change your answer, keep it and say so explicitly on a \
line starting with "Unchanged:". Otherwise end with a line \
"Answer: <revised answer>". Do not change your answer without a \
specific reason from the evidence."""


def correction_eligible(state: dict, verification: dict,
                        corrections_used: int) -> tuple[bool, str]:
    """Gate: only a FAILED verification with a specific contradicting
    artifact, and the correction budget not spent."""
    if corrections_used >= MAX_CORRECTIONS:
        return False, "correction budget spent"
    verdict = verification.get("verdict")
    if verdict != "FAILED":
        return False, f"verification verdict {verdict} does not warrant " \
                      "correction (only FAILED does)"
    evidence = str(verification.get("contradicting_evidence") or "").strip()
    if not evidence or evidence == "(none)":
        return False, "no external contradicting evidence (generic " \
                      "self-review is forbidden)"
    return True, "FAILED verdict with contradicting evidence"


def build_correction_input(state: dict, verification: dict,
                           prev_answer: str) -> str:
    """The structured correction contract (T7.17)."""
    return CORRECTION_PROMPT.format(
        question=state["problem"],
        prev=str(prev_answer)[:200],
        failing_check=verification.get("failing_check", "verification "
                                       "mismatch"),
        contradicting_evidence=str(verification.get(
            "contradicting_evidence", ""))[:600],
        expected=str(verification.get("expected", ""))[:200],
    )


def parse_correction(raw: str, prev_answer: str) -> dict:
    """Parse the correction output; keeps the previous answer when the
    model explicitly says Unchanged (overcorrection protection)."""
    text = (raw or "").strip()
    unchanged = any(line.lower().startswith("unchanged:")
                    for line in text.splitlines())
    answer = None
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.lower().startswith("answer:"):
            answer = line.split(":", 1)[1].strip()
            break
    if answer is None and not unchanged:
        # no explicit revision marker: treat last line as the answer only
        # if it differs from prev; otherwise keep prev
        answer = text.splitlines()[-1].strip() if text else prev_answer
        if answer == prev_answer:
            unchanged = True
    revised = bool(answer and not unchanged and answer != prev_answer)
    return {
        "unchanged": unchanged or not revised,
        "answer": answer if revised else prev_answer,
        "raw": text[:2000],
    }
