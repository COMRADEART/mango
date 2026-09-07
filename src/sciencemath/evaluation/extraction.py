"""Answer extraction, strictly separated from generation.

extract_answer() reads the RAW model output and never alters it. Both the
raw output and the extracted answer are stored in predictions.jsonl.
Scoring is deterministic string/numeric normalization only — no LLM judging.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- thinking
# Qwen3 reasoning tags, constructed from pieces so doc/rendering layers
# can never mangle them into live markup: they must stay inert constants.
THINK_OPEN = "<" + "think" + ">"
THINK_CLOSE = "<" + "/" + "think" + ">"


def strip_think_block(raw: str) -> str:
    """Remove model reasoning content and return only the visible answer.

    The gradable content is everything AFTER the closing reasoning tag.
    An opening tag with no closing tag means the reasoning never
    finished: the visible answer is empty (unfinished reasoning is never
    exposed as the answer). The raw model output itself is preserved
    untouched by the caller. Tags: THINK_OPEN / THINK_CLOSE above.
    """
    if not raw:
        return raw
    if THINK_CLOSE in raw:
        return raw.rsplit(THINK_CLOSE, 1)[1].strip()
    if THINK_OPEN in raw:
        # opening tag without closing tag: nothing gradable
        return ""
    return raw.strip()


_CHOICE_LETTER_RE = re.compile(r"(?<![A-Za-z])([A-E])(?![A-Za-z])")

_MCQ_INSTRUCTION = (
    "Answer with the letter of the correct option (A, B, C, D, or E) inside "
    "\\boxed{}, e.g. \\boxed{C}."
)


def _last_boxed(text: str) -> str | None:
    """Extract the contents of the last \\boxed{...} (balanced braces)."""
    idx = text.rfind("\\boxed{")
    if idx == -1:
        return None
    depth = 0
    start = idx + len("\\boxed")
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i].strip()
    return None


def _after_hash_marker(text: str) -> str | None:
    m = re.findall(r"####\s*(.+)", text)
    if m:
        return m[-1].strip()
    return None


_ANSWER_IS_RE = re.compile(
    r"(?:answer\s*is|answer:)\s*\$?([^$\n]+?)\$?\s*$", re.IGNORECASE)
_STRUCTURED_ANSWER_RE = re.compile(
    r'["\']?(?:final_?answer|answer)["\']?\s*[:=]\s*["\']?([^\n,}\"]+)',
    re.IGNORECASE)
_CONCISE_VALUE_RE = re.compile(
    r"^(?:therefore|thus|so),?\s+(.+?)\.?$", re.IGNORECASE)

# ---------------------------------------------------------------- symbolic
def normalize_symbolic(text: str) -> str:
    """Deterministic normalization for exact-answer comparison of short
    symbolic answers. NOT symbolic equivalence (that arrives with the T4
    SymPy verifier) — documented limitation of T2 scoring.

    T10: also folds LaTeX/symbol formatting variants that denote the same
    value (\\times and unicode × to *, unicode minus to -, '\\ ' spacing,
    atomic fraction parens from \\dfrac) — pure false-negative fixes; no
    semantic loosening (units and values must still agree)."""
    a = (text or "").strip()
    a = re.sub(r"^(?:\*\*|__)(.*)(?:\*\*|__)$", r"\1", a)
    a = a.strip("$ ")
    # strip \left \right wrappers
    a = a.replace("\\left", "").replace("\\right", "")
    # multiplication command and unicode variants → *
    a = a.replace("\\times", "*").replace("\\cdot", "*")
    a = a.replace("×", "*").replace("−", "-").replace("–", "-")
    a = re.sub(r"(?<=\d)\s*x\s*(?=10\^)", "*", a)   # 3 x 10^8
    # \dfrac / \tfrac / \frac{a}{b} -> a/b
    for _ in range(3):
        m = re.fullmatch(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", a.strip())
        if not m:
            break
        a = f"({m.group(1)})/({m.group(2)})"
    a = re.sub(r"\\text\{([^{}]*)\}", r"\1", a)
    a = a.replace("\\ ", "")                  # backslash spacing: 98\ N
    a = re.sub(r"\\[a-zA-Z]+", "", a)        # remaining commands dropped
    a = a.replace("^{\\circ}", "°").replace("^{o}", "°")
    # (13)/(12) -> 13/12 when both sides are atomic (no operator inside)
    a = re.sub(r"\(([\w.]+)\)/\(([\w.]+)\)", r"\1/\2", a)
    a = a.replace(" ", "").lower()
    a = a.rstrip(".")
    return a


def answers_match(expected: str, extracted: str) -> bool:
    """Deterministic exact-match with numeric tolerance awareness."""
    if extracted is None:
        return False
    ne = normalize_symbolic(expected)
    nx = normalize_symbolic(extracted)
    if ne == nx:
        return True
    from sciencemath.datasets.normalize import normalize_numeric

    n1, n2 = normalize_numeric(expected), normalize_numeric(extracted)
    if n1 is not None and n2 is not None:
        try:
            return abs(float(n1) - float(n2)) <= (1e-9 + 1e-9 * abs(float(n2)))
        except ValueError:
            return False
    return False


def _clean_choice_text(letter_text: str) -> str | None:
    s = strip_think_block(letter_text or "")
    s = _last_boxed(s)
    if s is not None:
        s = re.sub(r"^(option|answer)\s*", "", s.strip(), flags=re.IGNORECASE)
        s = s.strip(".:")
    return s


def extract_mcq(raw: str, choices: list[str] | None) -> str | None:
    """Extract a choice letter A-E. Valid choice index letters only."""
    s = _clean_choice_text(raw)
    if s is None:
        # no \boxed{} — fall back to the bare (think-stripped) output
        s = strip_think_block(raw or "")
    # the letter must not be the tail of a word: the unanchored fallback
    # matched the last letter of ANY trailing word ("B. mitochondria" -> A)
    m = re.search(r"(?<![A-Za-z0-9])([A-Ea-e])(?:\s*\)|\s*\.|\s*:)?\s*$", s)
    if m:
        letter = m.group(1).upper()
        if choices and letter.upper() not in {chr(65 + i) for i in range(len(choices))}:
            return None
        if not choices and letter not in "ABCDE":
            return None
        return letter
    return None


def extract_answer(raw: str, answer_type: str,
                   choices: list[str] | None = None) -> str | None:
    """Extract the final answer from raw model output. Returns None when no
    extractable answer exists (caller records EXTRACTION_FAILURE)."""
    gradable = strip_think_block(raw or "")
    if not gradable.strip():
        return None
    if answer_type == "multiple_choice":
        return extract_mcq(gradable, choices)

    # boxed first (MATH convention), then #### marker (GSM8K convention),
    # then 'answer is X' prose
    candidate = _last_boxed(gradable)
    if candidate is None:
        candidate = _after_hash_marker(gradable)
    if candidate is None:
        m = _ANSWER_IS_RE.search(gradable.strip().splitlines()[-1])
        if m:
            candidate = m.group(1).strip()
    if candidate is None:
        m = _STRUCTURED_ANSWER_RE.search(gradable.strip().splitlines()[-1])
        if m:
            candidate = m.group(1).strip(" '\"")
    if candidate is None:
        m = _CONCISE_VALUE_RE.fullmatch(gradable.strip())
        if m and len(m.group(1)) <= 80:
            candidate = m.group(1)
    if candidate is None:
        # last non-empty short line as a last resort for bare outputs
        lines = [l.strip() for l in gradable.strip().splitlines() if l.strip()]
        if lines and len(lines[-1]) <= 40:
            candidate = lines[-1]
    if candidate is None:
        return None
    candidate = candidate.strip()
    candidate = re.sub(r"^(?:\*\*|__)(.*)(?:\*\*|__)$", r"\1", candidate)
    return candidate.strip()


_UNCERTAIN_PATTERNS = (
    "i cannot", "i can't", "cannot be determined", "cannot be answered",
    "not enough information", "insufficient information",
    "impossible to know", "no way to know", "unknown", "unclear",
    "i don't know", "i do not know", "no evidence", "unsure",
)


def signals_uncertainty(text: str) -> bool:
    """Deterministic uncertainty detection for the calibration category."""
    t = strip_think_block(text or "").lower()
    return any(p in t for p in _UNCERTAIN_PATTERNS)
