"""T16.17–T16.18 — temporal / freshness model and stale-source handling.

Do not use age alone. Use age relative to claim volatility.
"""
from __future__ import annotations

import re
from datetime import date, datetime

TIME_INSENSITIVE = "TIME_INSENSITIVE"
SLOW_CHANGING = "SLOW_CHANGING"
RECENT = "RECENT"
BREAKING = "BREAKING"

FRESHNESS_CLASSES = (TIME_INSENSITIVE, SLOW_CHANGING, RECENT, BREAKING)


def classify_freshness(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in ("breaking", "this hour", "right now")):
        return BREAKING
    if "today" in q and any(k in q for k in
                            ("weather", "temperature", "forecast",
                             "headline", "price")):
        return BREAKING
    if any(k in q for k in ("current", "latest", "now the ceo",
                            "current ceo", "current mayor", "this week",
                            "this year", "still the", "revenue", "earnings",
                            "q1 ", "q2 ", "q3 ", "q4 ", "weather",
                            "bankrupt", "appointed", "as of", "population",
                            "ceo", "mayor")):
        return RECENT
    if "today" in q:
        return BREAKING
    if any(k in q for k in ("passed in", "enacted", "law of",
                            "historical", "codata", "planck constant",
                            "defining constant")):
        return TIME_INSENSITIVE
    if re.search(r"\b(in|of) 19\d{2}\b", q):
        return TIME_INSENSITIVE
    return SLOW_CHANGING


def _parse(value: str) -> date | None:
    v = (value or "").strip()
    if not v or v == "UNKNOWN":
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(v[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def source_age_days(source, query_time: str) -> int | None:
    pub = None
    for attr in ("modified_date", "publication_date"):
        raw = getattr(source, attr, "") or ""
        if raw and raw != "UNKNOWN":
            pub = _parse(raw)
            if pub is not None:
                break
    qt = _parse((query_time or "")[:10])
    if pub is None or qt is None:
        return None
    return max(0, (qt - pub).days)


def is_stale(source, *, question: str, query_time: str,
             freshness: str | None = None) -> bool:
    freshness = freshness or classify_freshness(question)
    age = source_age_days(source, query_time)
    if age is None:
        return False
    if freshness == TIME_INSENSITIVE:
        return False
    if freshness == SLOW_CHANGING:
        return age > 365 * 8
    if freshness == RECENT:
        return age > 365
    if freshness == BREAKING:
        return age > 30
    return False
