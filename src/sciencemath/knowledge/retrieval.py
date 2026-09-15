"""T21.7–T21.11, T21.21, T21.25 — retrieval, fusion, reranking, dedup.

Deterministic modular pipeline stages:

  query -> BM25 lexical retrieval (top-K)
        -> optional fusion (dense path absent: lexical only; RRF is the
           preregistered fusion rule if a dense retriever is ever added)
        -> bounded deterministic reranking (top-R -> top-K)
        -> deterministic deduplication (near-identical same-source chunks
           never dominate top-k)
        -> source-diversity measurement

No stage invents content, alters quotations, replaces provenance, or adds
unsupported evidence. No stage reads model memory: if evidence does not
cover the query, the pipeline abstains — it never backfills.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sciencemath.knowledge.index import BM25Index, normalize_query, tokenize
from sciencemath.knowledge.schema import KnowledgeChunk

JACCARD_THRESHOLD = 0.85
MAX_PER_SOURCE = 3
# T21R5 B1 — source-aware window reservation. When the naive top-k window
# is dominated by one source, the best chunk of an ABSENT source is
# reserved a slot, but only when it is adequately relevant (within this
# fraction of the best candidate score) and only by displacing a window
# item whose source retains another representative. Clearly superior
# evidence is never sacrificed for arbitrary diversity, and the naive
# window is returned unchanged when no absent source qualifies.
WINDOW_RESERVE_FRACTION = 0.5
# Rerank ordering (preregistered, frozen before FINAL): candidates are
# ordered primarily by whole-question coverage — the share of the query's
# terms the candidate span addresses — because same-entity attribute
# chunks share entity tokens and bare BM25 length normalization otherwise
# ranks by document length. BM25 enters as a bounded deterministic
# tie-break within equal coverage (normalized by the best candidate score).
COVERAGE_WEIGHT = 1.0
RERANK_TIEBREAK_WEIGHT = 0.01


def _shingles(text: str, n: int = 4) -> frozenset[str]:
    toks = tokenize(text)
    if len(toks) < n:
        return frozenset({" ".join(toks)}) if toks else frozenset()
    return frozenset(tuple(toks[i:i + n]) for i in range(len(toks) - n + 1))


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


@dataclass
class RetrievalStage:
    """Result of the retrieval stages for one (sub)query."""

    ranked: list[tuple[str, float]]      # (chunk_id, bm25_score)
    reranked: list[tuple[str, float]]
    deduped: list[tuple[str, float]]
    sources_kept: list[str]
    source_diversity: float

    def to_dict(self) -> dict:
        return {
            "ranked": [(c, s) for c, s in self.ranked],
            "reranked": [(c, s) for c, s in self.reranked],
            "deduped": [(c, s) for c, s in self.deduped],
            "sources_kept": list(self.sources_kept),
            "source_diversity": self.source_diversity,
        }


def dedup_chunks(
    ranked: list[tuple[str, float]],
    chunks_by_id: dict[str, KnowledgeChunk],
) -> list[tuple[str, float]]:
    """Deterministic dedup: drop a chunk whose 4-gram Jaccard similarity to
    an already-kept chunk from the SAME source is >= threshold; then cap
    per-source representation. Higher-ranked (better-scoring) chunks win.
    """
    kept: list[tuple[str, float]] = []
    kept_shingles: dict[str, list[frozenset[str]]] = {}
    per_source: dict[str, int] = {}
    for chunk_id, score in ranked:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        sid = chunk.source_id
        if per_source.get(sid, 0) >= MAX_PER_SOURCE:
            continue
        sh = _shingles(chunk.text)
        duplicate = False
        for other in kept_shingles.get(sid, ()):
            if _jaccard(sh, other) >= JACCARD_THRESHOLD:
                duplicate = True
                break
        if duplicate:
            continue
        kept.append((chunk_id, score))
        kept_shingles.setdefault(sid, []).append(sh)
        per_source[sid] = per_source.get(sid, 0) + 1
    return kept


def rerank(
    ranked: list[tuple[str, float]],
    chunks_by_id: dict[str, KnowledgeChunk],
    query: str,
    *,
    top_k: int,
    candidate_multiplier: int = 3,
    authority_bonus: float = 0.02,
) -> list[tuple[str, float]]:
    """Bounded deterministic rerank: BM25 score + coverage prior + small
    authority prior, evaluated on the top candidate_multiplier * top_k
    candidates.

    The priors are preregistered constants, frozen before FINAL. The
    reranker only reorders retrieved items — it cannot introduce evidence
    that retrieval did not return.
    """
    from sciencemath.knowledge.conflicts import AUTHORITY_RANK
    candidates = ranked[:max(top_k, top_k * candidate_multiplier)]
    q_terms = set(tokenize(normalize_query(query)))
    max_score = max((s for _, s in candidates), default=0.0) or 1.0
    out: list[tuple[str, float]] = []
    for chunk_id, score in candidates:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        meta = chunk.metadata or {}
        bonus = authority_bonus * AUTHORITY_RANK.get(
            meta.get("authority_class", "UNKNOWN"), 0) / 10.0
        span_terms = set(tokenize(chunk.text))
        coverage = (len(q_terms & span_terms) / len(q_terms)) if q_terms \
            else 0.0
        reranked_score = (COVERAGE_WEIGHT * coverage
                          + RERANK_TIEBREAK_WEIGHT * (score / max_score)
                          + bonus)
        out.append((chunk_id, reranked_score))
    out.sort(key=lambda item: (-item[1], item[0]))
    return out


def select_window(
    deduped: list[tuple[str, float]],
    chunks_by_id: dict[str, KnowledgeChunk],
    top_k: int,
) -> list[tuple[str, float]]:
    """T21R5 B1 — source-aware evidence-window selection.

    Deterministic two-phase policy over the FULL deduplicated ranking
    (before the top-k cut, so a source squeezed out entirely by
    same-source domination can still be reserved):

      1. take the naive top-k window (unchanged behavior when no source
         is dominated),
      2. for every source ABSENT from the naive window whose best
         candidate scores >= WINDOW_RESERVE_FRACTION * best candidate
         score, reserve its best chunk a slot,
      3. each reservation displaces the lowest-scoring window item whose
         source keeps another representative in the window (never the
         sole representative of its source),
      4. the final window is re-sorted deterministically by (-score,
         chunk_id).

    Irrelevant diverse sources never displace relevant evidence: a
    source below the reservation fraction is never reserved, and a
    source already represented is never re-reserved.
    """
    if len(deduped) <= top_k:
        return list(deduped)
    window = list(deduped[:top_k])
    max_score = max(s for _, s in deduped) or 0.0
    window_sources = {chunks_by_id[c].source_id for c, _ in window
                      if c in chunks_by_id}
    reserved: list[tuple[str, float]] = []
    seen_sources: set[str] = set()
    for chunk_id, score in deduped[top_k:]:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        sid = chunk.source_id
        if sid in window_sources or sid in seen_sources:
            continue
        seen_sources.add(sid)
        if score >= WINDOW_RESERVE_FRACTION * max_score:
            reserved.append((chunk_id, score))
    if not reserved:
        return window
    for chunk_id, score in reserved:
        source_counts: dict[str, int] = {}
        for cid, _s in window:
            ch = chunks_by_id.get(cid)
            if ch is not None:
                source_counts[ch.source_id] = \
                    source_counts.get(ch.source_id, 0) + 1
        droppable = [i for i, (cid, _s) in enumerate(window)
                     if chunks_by_id.get(cid) is not None
                     and source_counts.get(chunks_by_id[cid].source_id,
                                           0) > 1]
        if not droppable:
            droppable = list(range(len(window)))
        drop_i = min(droppable, key=lambda i: (window[i][1], window[i][0]))
        window[drop_i] = (chunk_id, score)
    window.sort(key=lambda item: (-item[1], item[0]))
    return window


def retrieve(
    index: BM25Index,
    chunks_by_id: dict[str, KnowledgeChunk],
    query: str,
    *,
    top_k: int = 8,
    min_score: float = 0.0,
) -> RetrievalStage:
    normalized = normalize_query(query)
    ranked = index.search(normalized, top_k=top_k * 3)
    reranked = rerank(ranked, chunks_by_id, normalized, top_k=top_k)
    deduped = select_window(dedup_chunks(reranked, chunks_by_id),
                            chunks_by_id, top_k)
    sources: list[str] = []
    for chunk_id, _ in deduped:
        chunk = chunks_by_id.get(chunk_id)
        if chunk and chunk.source_id not in sources:
            sources.append(chunk.source_id)
    n = len(deduped)
    diversity = (len(sources) / n) if n else 0.0
    return RetrievalStage(
        ranked=ranked,
        reranked=reranked,
        deduped=deduped,
        sources_kept=sources,
        source_diversity=diversity,
    )


def coverage_ratio(query: str, spans: list[str]) -> float:
    """Fraction of query content terms covered by the evidence spans."""
    q_terms = [t for t in tokenize(normalize_query(query)) if len(t) > 3]
    if not q_terms:
        return 0.0
    span_terms: set[str] = set()
    for span in spans:
        span_terms.update(tokenize(span))
    covered = sum(1 for t in q_terms if t in span_terms)
    return covered / len(q_terms)


_SUBQUERY_RE = re.compile(r"\b(?:and also|in addition|second|then)\b",
                          re.IGNORECASE)


def decompose_query(query: str, max_subqueries: int = 4) -> list[str]:
    """Bounded decomposition (T21.24): at most max_subqueries subqueries,
    no recursion. Deterministic split on explicit coordination cues only;
    a simple question stays a single subquery.
    """
    parts = _SUBQUERY_RE.split(query)
    parts = [p.strip(" ,;.") for p in parts if p.strip()]
    if len(parts) <= 1:
        return [query]
    return parts[:max_subqueries]