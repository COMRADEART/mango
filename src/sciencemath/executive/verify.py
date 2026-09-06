"""T7.11 — Verification (deterministic-first routing).

Verification is decided by deterministic checks wherever possible:
  - math answers -> T4 verify_answer / answers_match against tool
    recomputation
  - retrieval-backed claims -> chunk-id containment (citation anchor
    check, generate-then-parse)
  - structural claims -> observation status checks
The model is never asked "is this right?" in free text (T7.16: no
generic review-your-answer prompt).
"""
from __future__ import annotations

import re

VERDICTS = ("VERIFIED", "FAILED", "UNKNOWN")


def verify_math_answer(extracted: str, tool_result) -> str:
    """T4-anchored math verification."""
    if extracted is None or tool_result is None:
        return "UNKNOWN"
    from sciencemath.evaluation.extraction import answers_match
    # tool recomputations are the raw ToolResult.result payload: a scalar
    # for some tools, a dict ({"expression", "value", "exact"}) for the
    # calculator family — compare against the VALUE, never its dict repr
    if isinstance(tool_result, dict):
        expected = None
        for key in ("value", "exact", "result", "answer"):
            if tool_result.get(key) is not None:
                expected = tool_result[key]
                break
        if expected is None:
            return "UNKNOWN"
        expected = str(expected)
    else:
        try:
            expected = str(tool_result)
        except Exception:  # noqa: BLE001
            return "UNKNOWN"
    return "VERIFIED" if answers_match(expected, extracted) else "FAILED"


# Chunk ids in the frozen corpus contain colons
# (e.g. "wiki-18716923:intro_3cee6746:0") — the character class must
# include them, or every real citation parses as nothing and retrieval
# answers can never be verified.
_CHUNK_ID_RE = re.compile(r"\[([A-Za-z0-9_:\-]+)\]")


def verify_citations(answer_text: str, supplied_chunks: list[dict]) -> dict:
    """Chunk citations are bracketed ids the model was instructed to emit
    (e.g. [c1]). Every cited id must be in the supplied set; fail closed
    on ids never supplied (fabricated reference). Plain prose is NOT
    treated as a citation — absence of citations is UNKNOWN, not FAILED
    (see verify_final)."""
    supplied = {c.get("chunk_id") for c in supplied_chunks or []}
    cited = set()
    for m in _CHUNK_ID_RE.finditer(answer_text or ""):
        cited.add(m.group(1))

    def _anchored(cited_id: str) -> bool:
        """A citation is anchored when it names a supplied chunk id
        exactly, or names it with a source prefix ("w:c1" for "c1" —
        models commonly decorate ids with the source). Anything else is
        a fabricated reference."""
        if cited_id in supplied:
            return True
        return any(cited_id.endswith(":" + s) for s in supplied if s)

    invalid = sorted(c for c in cited if not _anchored(c))
    return {
        "valid_refs": sorted(c for c in cited if _anchored(c)),
        "invalid_refs": invalid,
        "ok": not invalid,
    }


def verify_step_consistency(observations: dict, plan: dict) -> dict:
    """Deterministic consistency pass over executed steps:
    FAILED/CHECK-contradicted observations are surfaced as triggers."""
    failed = [sid for sid, ob in observations.items()
              if ob.get("status") == "FAILED"]
    contradictions = [sid for sid, ob in observations.items()
                      if ob.get("action") == "CHECK" and ob.get("status")
                      == "FAILED"]
    return {
        "failed_steps": failed,
        "contradictions": contradictions,
        "replan_triggers": sorted(set(failed) | set(contradictions)),
    }


def verify_final(extracted_answer: str | None, final_text: str,
                 tool_results: list, supplied_chunks: list[dict]) -> dict:
    """Aggregate final verification. VERIFIED requires either a T4 match
    against a tool recomputation or (retrieval case) clean citations
    with non-empty evidence. Citing a chunk id that was never supplied
    is a fabrication -> FAILED. Producing no citations at all is NOT a
    failure — it just leaves the verdict UNKNOWN (honest unverified)."""
    verdict = "UNKNOWN"
    if extracted_answer is not None and tool_results:
        for tr in tool_results:
            v = verify_math_answer(extracted_answer, tr)
            if v == "VERIFIED":
                verdict = "VERIFIED"
                break
            if v == "FAILED":
                verdict = "FAILED"
    cit = verify_citations(final_text, supplied_chunks or [])
    if verdict == "UNKNOWN" and supplied_chunks:
        if cit["invalid_refs"]:
            verdict = "FAILED"      # fabricated chunk reference
        elif cit["valid_refs"]:
            verdict = "VERIFIED"    # clean, anchored citations
        # no citations at all: stays UNKNOWN (unverified, not failed)
    return {"verdict": verdict, "citations": cit}


def extract_final_answer(raw: str, answer_type: str,
                         choices: list | None = None):
    """Executive final-answer extraction: prefer an explicit final
    'Answer:' line, else fall back to the frozen T6 extractor so OFF/ON
    scoring stays comparable."""
    if not raw or not raw.strip():
        return None
    from sciencemath.evaluation.extraction import extract_answer
    tail = None
    for line in reversed(raw.splitlines()):
        s = line.strip()
        if s.lower().startswith("answer:"):
            tail = s.split(":", 1)[1].strip()
            break
    if tail:
        extracted = extract_answer(tail, answer_type, choices)
        if extracted is not None:
            return extracted
    return extract_answer(raw, answer_type, choices)