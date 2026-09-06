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

MAX_CORRECTIONS = 1

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