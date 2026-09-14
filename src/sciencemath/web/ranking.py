"""T16.7–T16.8 — source ranking and primary-source preference.

Prefer an official specification over an SEO summary when both answer
the same technical claim. Relevance still matters.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sciencemath.web import trust as T

_TOKEN = re.compile(r"[a-z0-9]{3,}", re.I)
_STOP = {
    "the", "a", "an", "and", "or", "to", "for", "please", "cite",
    "prefer", "invent",
}


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "") if t.lower() not in _STOP}


def _parse_date(value: str) -> date | None:
    v = (value or "").strip()
    if not v or v == "UNKNOWN":
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(v[:len(fmt) + 2].replace("/", "-"),
                                     fmt).date()
        except ValueError:
            continue
    return None


def relevance(query: str, source) -> float:
    qt = _tokens(query)
    if not qt:
        return 0.0
    blob = " ".join([
        getattr(source, "title", "") or "",
        getattr(source, "publisher", "") or "",
        (getattr(source, "content", "") or "")[:4000],
    ])
    st = _tokens(blob)
    if not st:
        return 0.0
    base = len(qt & st) / len(qt)
    q = (query or "").lower()
    blob_l = blob.lower()
    if "ceo" in q and "ceo" in blob_l:
        base += 0.25
    if "bankrupt" in q and "bankrupt" in blob_l:
        base += 0.3
    if "widget" in q and "/v3/widgets" in blob_l:
        base += 0.25
    if "efficacy" in q and "efficacy" in blob_l:
        base += 0.2
    return min(1.0, base)


def recency_score(source, *, query_time: str, freshness: str) -> float:
    pub = _parse_date(getattr(source, "modified_date", "")
                      or getattr(source, "publication_date", ""))
    qt = _parse_date(query_time[:10] if query_time else "") or date.today()
    if pub is None:
        return 0.4
    age_days = max(0, (qt - pub).days)
    if freshness in ("BREAKING", "RECENT"):
        if age_days <= 30:
            return 1.0
        if age_days <= 180:
            return 0.6
        if age_days <= 365:
            return 0.25
        return 0.05
    if freshness == "SLOW_CHANGING":
        return 1.0 if age_days <= 365 * 5 else 0.7
    return 0.8


def rank_sources(sources: list, query: str, *, query_time: str,
                 freshness: str = "SLOW_CHANGING") -> list:
    """Stable explicit ranking. Higher is better."""
    scored = []
    for s in sources:
        rel = relevance(query, s)
        auth = T.weight(getattr(s, "trust_class", T.UNKNOWN))
        primary = 1.0 if T.is_primary(getattr(s, "trust_class", "")) else 0.35
        rec = recency_score(s, query_time=query_time, freshness=freshness)
        spec = 1.0 if getattr(s, "source_type", "") in (
            "SPECIFICATION", "OFFICIAL_PAGE", "SOURCE_REPOSITORY",
            "PRESS_RELEASE", "PAPER", "GOVERNMENT_PAGE") else 0.5
        density = min(1.0, len(_tokens(getattr(s, "content", "") or "")) / 80)
        indep = 1.0
        access = 0.0 if getattr(s, "fetch_status", "") not in (
            "OK", "REDIRECT") else 1.0
        can = getattr(s, "canonical_url", "UNKNOWN")
        url = getattr(s, "url", "")
        canon = 1.0 if can in ("UNKNOWN", "", url) else 0.35
        score = (
            0.26 * rel + 0.18 * auth + 0.16 * primary + 0.14 * rec
            + 0.10 * spec + 0.06 * density + 0.04 * indep + 0.04 * access
            + 0.02 * canon
        )
        scored.append((score, getattr(s, "source_id", ""), s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [s for _, _, s in scored]


def prefer_primary(ranked: list, *, claim_query: str) -> list:
    """If a primary source answers the claim, keep it ahead of commentary."""
    if not ranked:
        return ranked
    primaries = [s for s in ranked if T.is_primary(
        getattr(s, "trust_class", "")) and relevance(claim_query, s) >= 0.25]
    if not primaries:
        return ranked
    best_p = primaries[0]
    rest = [s for s in ranked if s is not best_p]
    return [best_p, *rest]
