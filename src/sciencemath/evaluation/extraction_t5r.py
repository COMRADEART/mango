"""T5R.11 — tolerant answer extraction for the T5R answering flow.

extract_answer() (evaluation/extraction.py) is FROZEN behavior used by the
T2/T4 scoring paths; this module adds extraction strategies for the answer
formats the T5R prompts produce — WITHOUT loosening what counts as correct:

  * deterministic "Sources: [...]" footer  -> stripped before extraction
  * bold MCQ (**C**)                       -> letter extraction
  * LaTeX numeric with units (\text{}, ~)  -> resolved to plain value+unit
  * structured hops ("Hop N answer: ...",  -> last hop / Final answer line
    "Final answer: ...")
  * sentence-form final answer             -> last short sentence, connective
    (no boxed/####/answer-is anywhere)        prefixes stripped

Every strategy only makes MORE model outputs extractable; comparison and
the verifier are unchanged. The base extract_answer is called first, so
behavior can only differ where the frozen extractor returned None (or a
strictly worse candidate).
"""
from __future__ import annotations

import re

from sciencemath.evaluation.extraction import (_ANSWER_IS_RE, _last_boxed,
                                                _after_hash_marker,
                                                extract_answer,
                                                strip_think_block)

_SOURCES_FOOTER_RE = re.compile(r"\n\s*Sources:.*$", re.DOTALL)
_BOLD_LETTER_RE = re.compile(r"\*\*\(?([A-Ea-e])\)?\*\*")
_HOP_ANSWER_RE = re.compile(r"^(?:Hop\s+\d+\s+answer|Final\s+answer)\s*:\s*(.+)$",
                            re.IGNORECASE | re.MULTILINE)
_LEADING_CONNECTIVE_RE = re.compile(
    r"^(?:therefore|so|thus|hence|that\s+means|in\s+conclusion|"
    r"the\s+answer\s+is|it\s+is)\s*[,:;]?\s*", re.IGNORECASE)


def strip_sources_footer(gradable: str) -> str:
    """Remove the deterministic 'Sources: [...]' citation footer the
    T5R formatter appends (T5R.7) — it is metadata, never the answer."""
    return _SOURCES_FOOTER_RE.sub("", gradable)


def _resolve_latex(text: str) -> str:
    """Resolve common LaTeX wrappers inside a boxed answer to plain
    value+unit text (deterministic; comparison still normalized)."""
    t = text
    t = re.sub(r"\\(?:text|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}", r"\1", t)
    t = t.replace("~", " ").replace("\\%", "%")
    t = re.sub(r"\\(?:left|right)", "", t)
    t = re.sub(r"\\\(", "", t)
    t = t.replace("$", "").strip()
    return t


def extract_answer_t5r(raw: str, answer_type: str,
                       choices: list[str] | None = None) -> str | None:
    """T5R extraction: frozen extract_answer first, then the T5R-specific
    strategies. Returns None when nothing extractable exists."""
    gradable = strip_think_block(raw or "")
    if not gradable.strip():
        return None
    gradable = strip_sources_footer(gradable)

    base = extract_answer(gradable, answer_type, choices)
    if answer_type == "multiple_choice":
        # bold letter fallback, then the base result
        m = _BOLD_LETTER_RE.search(gradable)
        letter = None
        if m:
            cand = m.group(1).upper()
            if choices:
                if cand in {chr(65 + i) for i in range(len(choices))}:
                    letter = cand
            elif cand in "ABCDE":
                letter = cand
        # T5R only fills gaps: the frozen extractor's result wins
        return base or letter

    candidate = base
    if candidate is not None:
        # the base extractor already handled the boxed path; resolve LaTeX
        # wrappers it returned verbatim (boxed content with \text units)
        if "\\text" in candidate or "\\mathrm" in candidate or "$" in candidate:
            candidate = _resolve_latex(candidate)
        return candidate

    # no boxed/####/answer-is candidate: try structured hop lines, then a
    # sentence-form final answer (T5R prompts produce both)
    hops = _HOP_ANSWER_RE.findall(gradable)
    if hops:
        last = hops[-1].strip()
        if last:
            bm = _last_boxed(last)
            return (_resolve_latex(bm) if bm else
                    _LEADING_CONNECTIVE_RE.sub("", last).rstrip(". "))
    lines = [l.strip() for l in gradable.strip().splitlines() if l.strip()]
    if lines:
        last = lines[-1]
        m = _ANSWER_IS_RE.search(last)
        if m:
            return m.group(1).strip()
        if 0 < len(last) <= 200 and last.count(". ") <= 1:
            # sentence-form: strip leading connective, trailing period
            s = _LEADING_CONNECTIVE_RE.sub("", last).rstrip(". ")
            if s and not s.lower().startswith(("note", "source")):
                return s
    return None