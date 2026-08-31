"""Normalization: unicode cleanup, unsupported-character handling, answer and
question normalization. Used by the data pipeline (T1) and reused for
contamination checks and answer extraction later (T2/T4)."""
from __future__ import annotations

import re
import sys
import unicodedata

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_ZW_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")

# Characters we treat as illegitimate noise in question/answer text (they are
# dropped and the record is flagged for review).
_NOISE_CHARS_RE = re.compile(r"[\uFFFD\u25AF\u25A1\u22EF\u2207\u21E8]")

# Characters that get translated to ASCII equivalents (smart quotes, fancy
# dashes, unicode minus) so dedup/leakage fingerprints match across sources.
_TRANSLATE = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2212": "-",   # minus sign
    "\u00a0": " ", "\u202f": " ", "\u2028": " ",
})


def clean_text(text: str, *, max_chars: int | None = None,
               min_chars: int = 0) -> tuple[str, list[str]]:
    """Clean free text. Returns (cleaned, issue_flags)."""
    if not isinstance(text, str):
        return "", [f"non_string:{type(text).__name__}"]
    issues: list[str] = []
    out = text.translate(_TRANSLATE)

    zw_left = len(_ZW_RE.findall(out))
    ctrl_left = len(_CTRL_RE.findall(out))
    if zw_left:
        issues.append("removed_zero_width")
    if ctrl_left:
        issues.append("removed_control_chars")
    out = _ZW_RE.sub("", out)
    out = _CTRL_RE.sub("", out)

    noise_left = len(_NOISE_CHARS_RE.findall(out))
    if noise_left:
        issues.append("removed_noise_chars")
    out = _NOISE_CHARS_RE.sub("", out)

    if out != text:
        issues.append("unicode_normalized")
    new_out = unicodedata.normalize("NFKC", out)
    if new_out != out:
        issues.append("nfkc_normalized")
        out = new_out

    out = _WS_RE.sub(" ", out)
    out = _MULTI_NL_RE.sub("\n\n", out)
    out = out.strip()
    if out != text and "unicode_normalized" not in issues:
        issues.append("whitespace_normalized")

    if min_chars and len(out) < min_chars:
        issues.append("too_short")
    if max_chars is not None and len(out) > max_chars:
        issues.append("too_long")
    return out, issues


_UNSUPPORTED_RE = re.compile(
    r"[^\w\s.,;:!?'\-\"()\[\]{}=%+\*/^<>§µ" + re.escape("°±×÷≈≤≥√∫πΔθΩσλ·→½¼¾$#@&_«»|~`\u0300-\u036f") + r"]"
)


def unsupported_characters(text: str) -> list[str]:
    """List (up to 20) of characters considered unsupported — anything that is
    not alphanumeric, whitespace, standard punctuation, or a curated
    math/science symbol. Used by answer-format validation."""
    return sorted({ch for ch in text if _UNSUPPORTED_RE.match(ch)})[:20]


_FINGERPRINT_RE = re.compile(r"[^a-z0-9]+")
_ANSWER_FINGERPRINT_RE = re.compile(r"[\s,]+")


def text_fingerprint(text: str) -> str:
    """Aggressive normalized form of a question used for deduplication,
    leakage detection and split grouping: case-folded, NFKC-stripped to
    [a-z0-9]. Two questions sharing a fingerprint are treated as the same
    item for contamination purposes."""
    cleaned, _ = clean_text(text)
    return _FINGERPRINT_RE.sub(" ", cleaned.lower()).strip()


def answer_fingerprint(answer: str) -> str:
    """Normalized answer string for duplicate-answer checks: drops $ signs,
    thousands separators, trailing periods, LaTeX wrappers, and a leading
    simple variable assignment ("x = 5" -> "5")."""
    cleaned, _ = clean_text(answer)
    a = cleaned.strip().strip(".").strip()
    a = re.sub(r"^answer\s*(is|:)\s*", "", a, flags=re.IGNORECASE)
    a = a.replace("$", "").strip()   # unwrap $x = 5$ -> x = 5
    m = re.fullmatch(r"\\boxed\{(.*)\}", a)
    if m:
        a = m.group(1)
    a = re.sub(r"^\s*[A-Za-z]\s*=\s*", "", a)   # "x = 5" / "x=5." -> "5"
    a = a.strip().rstrip(".")
    a = re.sub(r"(?<=\d),(?=\d{3}\b)", "", a)   # 1,234,567 -> 1234567
    a = _ANSWER_FINGERPRINT_RE.sub(" ", a)
    return a.strip().lower()


_NUMERIC_ONLY = re.compile(r"^[-+]?\d+([.,]\d+)?$")


def normalize_numeric(text: str) -> str | None:
    """Return a canonical numeric string, or None if the text is not a bare
    number. Thousands separators ('1,234') are removed; decimal comma is
    converted to a point."""
    a = answer_fingerprint(text)
    bare = a.strip().strip("$").replace("$", "")
    if bare.count(",") and "." not in bare:
        parts = bare.split(",")
        if len(parts[-1]) == 3 and len(parts) > 1:
            bare = "".join(parts)          # 1,234,567 -> 1234567
    bare = bare.replace(",", ".")
    if _NUMERIC_ONLY.match(bare):
        s = bare.rstrip("0").rstrip(".") if "." in bare else bare
        if s in ("-0", "-0."):
            s = "0"
        return s.lstrip("+")
    return None


def normalize_example(example: dict, *, min_question: int = 8,
                      max_question: int = 4000, max_answer: int = 2000,
                      max_solution: int = 16000) -> tuple[dict | None, list[str]]:
    """Clean one raw record into canonical form. Returns (record, issues).
    Returns (None, issues) when the record must be rejected. Cosmetic
    cleanups (unicode, whitespace, control chars) do NOT reject a record —
    only substantive problems do (too short/long, malformed answer, schema
    violations). Never mutates the input."""
    issues: list[str] = []
    rec = dict(example)

    q, _ = clean_text(str(rec.get("question", "")), max_chars=max_question)
    a, _ = clean_text(str(rec.get("answer", "")), max_chars=max_answer)

    if rec.get("solution"):
        rec["solution"], _ = clean_text(str(rec["solution"]), max_chars=max_solution)
    if rec.get("explanation"):
        rec["explanation"], _ = clean_text(str(rec["explanation"]),
                                           max_chars=max_solution)

    rec["question"] = q
    rec["answer"] = a

    # --- rejection checks ---
    reject: list[str] = []
    if len(q) < min_question:
        reject.append("question:too_short")
    if len(q) > max_question:
        reject.append("question:too_long")
    if len(a) > max_answer:
        reject.append("answer:too_long")
    from sciencemath.datasets.schema import is_malformed_answer, make_id, validate_example
    if is_malformed_answer(a):
        reject.append("malformed_answer")

    if not rec.get("id"):
        rec["id"] = make_id(str(rec.get("source", "unknown")),
                            str(rec.get("source_id", "")), q)
    if not rec.get("subject"):
        rec["subject"] = ""
    if rec.get("difficulty") is None:
        rec.pop("difficulty", None)

    if reject:
        return None, reject

    violations = validate_example(rec, min_question_chars=min_question,
                                  min_answer_chars=1)
    if violations:
        issues.extend(f"schema:{v}" for v in violations)
        return None, issues
    return rec, issues