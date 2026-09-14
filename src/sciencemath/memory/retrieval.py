"""Deterministic local retrieval: scope → status → FTS/exact → rank.

Preferred baseline is SQLite FTS5 / BM25 plus exact and normalized
keyword matching. No paid embeddings.
FTS5: https://www.sqlite.org/fts5.html
"""
from __future__ import annotations

from datetime import datetime, timezone

from sciencemath.memory.limits import DEFAULT_TOP_K, MAX_TOP_K
from sciencemath.memory.models import RetrievalExplanation
from sciencemath.memory.normalize import normalize_content

TRUST = {
    "VERIFIED": 1.0,
    "HIGH": 0.85,
    "MEDIUM": 0.60,
    "LOW": 0.35,
    "UNKNOWN": 0.20,
}

_ALIASES = {
    "database": {"postgres", "postgresql", "sqlite", "mysql", "mongodb",
                 "redis", "db"},
    "editor": {"cursor", "vscode", "vim", "emacs"},
    "employer": {"employer", "company", "works"},
    "city": {"lives", "city"},
}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    t = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def recency_score(updated_at: str, now: str) -> float:
    u = _parse(updated_at)
    n = _parse(now)
    if u is None or n is None:
        return 0.5
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    if u.tzinfo is None:
        u = u.replace(tzinfo=timezone.utc)
    days = max(0.0, (n - u).total_seconds() / 86400.0)
    return 1.0 / (1.0 + days / 30.0)


def token_overlap(query: str, content: str) -> tuple[float, list[str]]:
    q = set(normalize_content(query).split())
    c = set(normalize_content(content).split())
    extra = set()
    for key, vals in _ALIASES.items():
        if key in q or q & vals:
            extra |= vals | {key}
    q = q | extra
    if not q:
        return 0.0, []
    hit = sorted(q & c)
    return len(hit) / max(1, len(q)), hit


def rank(hits: list, *, query: str, now: str, top_k: int = DEFAULT_TOP_K
         ) -> tuple[list, list[RetrievalExplanation]]:
    k = max(1, min(int(top_k or DEFAULT_TOP_K), MAX_TOP_K))
    scored = []
    nq = normalize_content(query)
    for rec, fts_score in hits:
        overlap, terms = token_overlap(query, rec.content + " " + rec.subject_key)
        exact = 1.0 if nq and nq in rec.normalized_content else 0.0
        recency = recency_score(rec.updated_at, now)
        trust = TRUST.get(rec.confidence, 0.2)
        # conflicted never ranks as VERIFIED; already excluded from ACTIVE set
        retrieval = (
            0.40 * max(fts_score, overlap) +
            0.25 * exact +
            0.20 * recency +
            0.15 * trust
        )
        if exact:
            retrieval = min(1.0, retrieval + 0.15)
        if rec.subject_key and any(
                tok and tok in rec.subject_key
                for tok in normalize_content(query).split() if len(tok) > 3):
            retrieval = min(1.0, retrieval + 0.2)
        if "database" in nq and rec.subject_key.startswith("database"):
            retrieval = min(1.0, retrieval + 0.35)
        scored.append((retrieval, rec, terms, recency, trust))
    scored.sort(key=lambda x: (x[0], x[1].updated_at, x[1].revision),
                reverse=True)
    kept = scored[:k]
    recs = [x[1] for x in kept]
    expl = [
        RetrievalExplanation(
            memory_id=x[1].memory_id,
            matching_terms=x[2],
            scope_match=True,
            recency_score=round(x[3], 4),
            trust_score=round(x[4], 4),
            retrieval_score=round(x[0], 4),
        )
        for x in kept
    ]
    return recs, expl
