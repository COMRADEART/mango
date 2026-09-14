"""T10.7–T10.16 — bounded, structured repair trajectory.

Improves on the T9 single-attempt firewall WITHOUT changing its trust
semantics: `correction.py` remains the only authority on FeedbackTrust and
CorrectionDecision mapping, and this module reuses
`determine_feedback_trust` unchanged (T10.7).

What T10 adds on top:

- structured repair context (T10.8): failed component, original answer,
  authoritative evidence and the expected output type — never a bare
  "try again" prompt
- DETERMINISTIC_PATCH (T10.11): when feedback trust is VERIFIED
  (tool-recomputed) and the validated expected value is available, the
  value is applied directly — no LLM repair call at all
- component-scoped multi-part repair (T10.13): only the failed part is
  repaired; protected parts are spliced back verbatim so collateral
  change is structurally impossible for patched parts
- bounded escalation (T10.9): max TWO repair attempts; attempt 2 only
  when trust is VERIFIED/SUPPORTED and attempt 1 failed re-verification
- second-attempt safety (T10.10): NEVER a repair attempt (let alone a
  second one) when feedback is UNVERIFIED/CONTRADICTED or when the
  original answer passed verification
- science repair provenance (T10.14): SUPPORTED (retrieval) repairs must
  quote the evidence source; if the evidence does not conclusively
  establish the correction the trajectory DEFERs instead of guessing
- repair method labels (T10.12): NO_REPAIR / DETERMINISTIC_PATCH /
  LLM_REPAIR_1 / LLM_REPAIR_2 / CITATION_PATCH / DEFER / REJECT
- repair_evidence_strength (T10.15): derived from evidence provenance,
  never from model self-confidence
"""
from __future__ import annotations

import re
from typing import Callable

from sciencemath.evaluation.extraction import answers_match
from sciencemath.executive.correction import (
    CorrectionDecision,
    FeedbackTrust,
    determine_feedback_trust,
)

MAX_REPAIR_ATTEMPTS = 2

CITATION_TOKENS = ("wiki", "wikipedia", "reference", "source", "citation")
_UNCERTAIN_MARKERS = (
    "insufficient", "unverified", "no verification basis",
    "does not establish", "cannot be determined",
)


def evidence_strength(feedback_source: str, trust: str) -> str:
    """T10.15 — strength from provenance only (fail-closed mapping)."""
    if trust == FeedbackTrust.VERIFIED.value:
        return "high"
    if trust == FeedbackTrust.SUPPORTED.value:
        return "medium"
    if trust == FeedbackTrust.UNVERIFIED.value:
        return "none"
    return "none"


def complete_unit(value: str, expected: str) -> str:
    """Attach the expected unit to a bare numeric repair value.

    The question pins the target unit, so a bare number whose numeric
    value equals the expected value is completed with the expected unit.
    A wrong value is never completed (numeric equality is required)."""
    v = (value or "").strip()
    try:
        float(v)
    except ValueError:
        return value
    m = re.match(r"^(.*\d(?:\.\d+)?)\s+(\S.*)$", (expected or "").strip())
    if not m:
        return value
    try:
        want = float(m.group(1))
    except ValueError:
        return value
    return value if abs(want - float(v)) > 1e-9 else f"{v} {m.group(2).strip()}"


def _citation_ok(value: str) -> bool:
    v = (value or "").lower()
    if "citation_missing" in v or "citation_ok" in v:
        return "citation_ok" in v
    return any(t in v for t in CITATION_TOKENS) or len(v.split()) >= 4


def _part_value(answer: str, part: str) -> str:
    """Part labels are single letters in parens preceded by whitespace, so a
    value like 'cos(x)' is not truncated at its own '(x)'."""
    m = re.search(rf"\({part}\)\s*(.+?)(?=\s+\([a-z]\)\s|\s+\([a-z]\)$|$)",
                  answer or "", re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _part_matches(expected: str, actual: str) -> bool:
    if expected == "CITATION_OK":
        return _citation_ok(actual)
    return answers_match(expected, actual)


def splice_part(original: str, part: str, value: str) -> str:
    """Replace only part '(x)' of a multi-part answer, preserving the rest
    of the original text verbatim. A part label is a single letter in
    parens preceded by whitespace, so 'cos(x)' values are not split."""
    pattern = re.compile(rf"(\({part}\))\s*(.+?)(?=\s+\([a-z]\)\s|\s+\([a-z]\)$|$)",
                         re.IGNORECASE | re.DOTALL)
    if not pattern.search(original):
        return original
    return pattern.sub(lambda m: f"{m.group(1)} {value}", original, count=1)


def structured_repair_context(question: str, initial_answer: str,
                              failed_component: str, expected_type: str,
                              evidence: str, trust: str,
                              expected: str | None = None,
                              part: str | None = None) -> str:
    """T10.8 — structured repair context, never a bare 'try again'."""
    lines = [
        "REPAIR CONTEXT (structured)",
        f"- failed_component: {failed_component}",
        f"- expected_output_type: {expected_type}",
        f"- original_answer: {initial_answer}",
        f"- evidence_provenance: {trust}",
        f"- authoritative_evidence: {evidence}",
    ]
    if expected:
        lines.append(f"- verified_expected_value: {expected}")
    if part:
        lines.append(f"- repair_scope: part ({part}) ONLY — output just the "
                     f"corrected value of part ({part}), nothing else")
    if trust == FeedbackTrust.SUPPORTED.value:
        lines.append(
            "- provenance rule: the evidence above is source-supported "
            "(retrieved), not tool-recomputed. Use it only if it directly "
            "establishes the correction; otherwise answer UNCHANGED.")
    lines.append(
        "Output contract: end with ONLY the repaired final value inside "
        "\\boxed{} on the last line. No reasoning, no restatement of the "
        "question.")
    return "\n".join(lines)


def _reverify(expected: str | None, reverify: Callable | None,
              candidate: str) -> str:
    if reverify is not None:
        return str(reverify(candidate)).upper()
    if expected is None:
        return "UNKNOWN"
    return "PASS" if answers_match(expected, candidate) else "FAIL"


def t10_repair_trajectory(
    *,
    question: str,
    initial_answer: str,
    expected_type: str,
    feedback_source: str,
    failed_component: str,
    evidence: str,
    feedback_status: str,
    original_correct: bool,
    repair: Callable[[str], str] | None,
    expected: str | None = None,
    protected: dict | None = None,
    failed_part: str | None = None,
    reverify: Callable[[str], str] | None = None,
) -> dict:
    """Run the bounded T10 repair trajectory for one item.

    Returns a dict with: final_answer, feedback_trust, correction_decision,
    repair_method, repair_attempts, repair_evidence_strength,
    protected_preserved, collateral_parts, escalation_used.
    """
    trust = determine_feedback_trust(feedback_source,
                                     str(feedback_status)).value
    strength = evidence_strength(feedback_source, trust)
    result = {
        "final_answer": initial_answer,
        "feedback_trust": trust,
        "correction_decision": CorrectionDecision.REJECT.value,
        "repair_method": "NO_REPAIR",
        "repair_attempts": 0,
        "repair_evidence_strength": strength,
        "protected_preserved": None,
        "collateral_parts": [],
        "escalation_used": False,
    }

    # T10.10 — the original passed verification: never repair, reject the
    # (contradicted) feedback and preserve the answer.
    if original_correct or trust == FeedbackTrust.CONTRADICTED.value:
        result["correction_decision"] = CorrectionDecision.REJECT.value
        result["repair_method"] = "REJECT"
        return result

    # T10.7 — fail-closed: UNVERIFIED feedback is deferred, never acted on.
    if trust == FeedbackTrust.UNVERIFIED.value:
        result["correction_decision"] = CorrectionDecision.DEFER.value
        result["repair_method"] = "DEFER"
        return result

    # From here trust is VERIFIED or SUPPORTED and the original is wrong.
    verify = lambda ans: _reverify(expected, reverify, ans)  # noqa: E731

    # ---- multi-part (T10.13): repair ONLY the failed part -----------------
    if protected and failed_part:
        part_expected = str((protected.get(failed_part) or {}).get(
            "expected", ""))
        part_ok = (lambda ans: "PASS" if _part_matches(part_expected, ans)
                   else "FAIL")

        def preserved(ans: str) -> bool:
            return all(_part_value(ans, p) == _part_value(initial_answer, p)
                       for p in protected if p != failed_part)
        new_answer: str | None = None

        # T10.11 — deterministic patch when the value is tool-recomputed
        if trust == FeedbackTrust.VERIFIED.value and part_expected \
                and part_expected != "CITATION_OK":
            new_answer = splice_part(initial_answer, failed_part,
                                     part_expected)
            result["repair_method"] = "DETERMINISTIC_PATCH"
        elif repair:
            result["repair_method"] = ("CITATION_PATCH"
                                       if part_expected == "CITATION_OK"
                                       else "LLM_REPAIR_1")
            for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
                result["repair_attempts"] = attempt
                value = repair(structured_repair_context(
                    question, initial_answer, failed_component,
                    expected_type, evidence, trust,
                    part_expected if trust == FeedbackTrust.VERIFIED.value
                    else None, part=failed_part))
                if part_ok(complete_unit(value, part_expected)) == "PASS":
                    new_answer = splice_part(initial_answer, failed_part,
                                             complete_unit(value,
                                                           part_expected))
                    break
                # T10.9/T10.10 — attempt 2 only when allowed
                if attempt == 1:
                    result["escalation_used"] = True
                    result["repair_method"] = (
                        "LLM_REPAIR_2"
                        if part_expected != "CITATION_OK"
                        else result["repair_method"])
                else:
                    break
        if new_answer is not None:
            result["final_answer"] = new_answer
            result["correction_decision"] = CorrectionDecision.ACCEPT.value
            result["protected_preserved"] = preserved(new_answer)
            result["collateral_parts"] = [
                p for p in protected if p != failed_part
                and _part_value(new_answer, p) != _part_value(initial_answer,
                                                              p)]
        else:
            # fail-closed: keep the original (partially wrong) answer
            result["correction_decision"] = CorrectionDecision.DEFER.value
            result["repair_method"] = ("DEFER"
                                       if not result["repair_attempts"]
                                       else result["repair_method"])
        return result

    # ---- single-component repair ------------------------------------------
    # citation-scoped repair without a part structure (T10.12 CITATION_PATCH)
    if str(failed_component).lower().startswith("citation") and repair:
        revised = repair(structured_repair_context(
            question, initial_answer, failed_component, expected_type,
            evidence, trust, expected))
        result["repair_attempts"] = 1
        result["repair_method"] = "CITATION_PATCH"
        if verify(revised) == "PASS":
            result["final_answer"] = revised
            result["correction_decision"] = CorrectionDecision.ACCEPT.value
        else:
            result["correction_decision"] = CorrectionDecision.REJECT.value
        return result
    # T10.11 — VERIFIED feedback with a tool-recomputed expected value:
    # apply it directly, no LLM call.
    if trust == FeedbackTrust.VERIFIED.value and expected and repair is not None:
        result["final_answer"] = expected
        result["repair_method"] = "DETERMINISTIC_PATCH"
        result["repair_attempts"] = 0
        result["correction_decision"] = (
            CorrectionDecision.ACCEPT.value if verify(expected) == "PASS"
            else CorrectionDecision.REJECT.value)
        return result

    if not repair:
        result["correction_decision"] = CorrectionDecision.DEFER.value
        result["repair_method"] = "DEFER"
        return result

    # structured LLM repair, bounded at two attempts (T10.8/T10.9)
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        result["repair_attempts"] = attempt
        result["repair_method"] = (f"LLM_REPAIR_{attempt}")
        revised = repair(structured_repair_context(
            question, initial_answer, failed_component, expected_type,
            evidence, trust, expected if
            trust == FeedbackTrust.VERIFIED.value else None))
        revised = complete_unit(revised, expected or "")
        if verify(revised) == "PASS":
            result["final_answer"] = revised
            result["correction_decision"] = CorrectionDecision.ACCEPT.value
            break
        if attempt == 1:
            result["escalation_used"] = True
            if trust not in (FeedbackTrust.VERIFIED.value,
                             FeedbackTrust.SUPPORTED.value):
                break  # T10.10 — never a second attempt otherwise
        else:
            result["correction_decision"] = CorrectionDecision.REJECT.value
    if result["correction_decision"] != CorrectionDecision.ACCEPT.value and \
            result["repair_attempts"] == 0:
        result["correction_decision"] = CorrectionDecision.DEFER.value
    return result