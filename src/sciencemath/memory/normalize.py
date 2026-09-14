"""Normalized content and subject keys for duplicate/conflict matching."""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)

_SUBJECT_SPECS = (
    (re.compile(r"\b(favorite|preferred)\s+editor\b", re.I), "favorite_editor"),
    (re.compile(r"\blives?\s+in\b", re.I), "lives_in"),
    (re.compile(r"\bemployer\b", re.I), "employer"),
    (re.compile(r"\bdatabase\b", re.I), "database"),
    (re.compile(r"\barchitecture\b", re.I), "architecture"),
    (re.compile(r"\btest count\b", re.I), "test_count"),
    (re.compile(r"\brenewal date\b", re.I), "renewal_date"),
    (re.compile(r"\bconstraint\b", re.I), "constraint"),
)


def normalize_content(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("\x00", "")
    t = _WS.sub(" ", t).strip().lower()
    return t


def subject_key(subject: str | None, content: str, *,
                scope_id: str = "") -> str:
    if subject and str(subject).strip():
        base = normalize_content(str(subject))
        return _WS.sub("_", _PUNCT.sub("", base)).strip("_")[:120]
    blob = content or ""
    for rx, key in _SUBJECT_SPECS:
        if rx.search(blob):
            if key == "database" and scope_id:
                return f"database:{scope_id}"
            return key
    m = re.search(r"\bproject\s+(\S+)\s+uses\b", blob, re.I)
    if m:
        rest = blob.lower()
        if any(db in rest for db in (
                "postgres", "sqlite", "mysql", "mongo", "redis")):
            return f"database:{m.group(1).lower()}"
        return f"stack:{m.group(1).lower()}"
    m = re.match(
        r"^(?:remember that\s+)?([a-z0-9][a-z0-9 _-]{1,40}?)\s+(?:is|equals)\s+",
        normalize_content(blob))
    if m:
        return _WS.sub("_", m.group(1).strip())[:120]
    # fallback: first 8 tokens of normalized content
    toks = normalize_content(blob).split()[:8]
    return "subj:" + "_".join(toks)[:120]


def value_key(value: str | None, content: str) -> str:
    if value and str(value).strip():
        return normalize_content(str(value))[:240]
    return normalize_content(content)[:240]


def extract_value(content: str) -> str:
    t = (content or "").strip()
    for sep in (" is ", " = ", ": ", " uses ", " in "):
        if sep in t.lower():
            idx = t.lower().rfind(sep)
            return t[idx + len(sep):].strip().rstrip(".")
    return t
