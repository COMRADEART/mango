"""Independent, data-only mirror of the frozen T21 retrieval arithmetic.

This module intentionally imports no ``sciencemath`` package.  It mirrors
normalization, BM25, bounded reranking, same-source deduplication, source
reservation, and top-8 truncation from the frozen runtime so blind static
audits can derive their own evidence windows without executing Mango.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


TOP_K = 8
CANDIDATE_MULTIPLIER = 3
K1 = 1.2
B = 0.75
JACCARD_THRESHOLD = 0.85
MAX_PER_SOURCE = 3
WINDOW_RESERVE_FRACTION = 0.5
COVERAGE_WEIGHT = 1.0
RERANK_TIEBREAK_WEIGHT = 0.01
AUTHORITY_BONUS = 0.02

AUTHORITY_RANK = {
    "PRIMARY_REFERENCE": 6,
    "ENCYCLOPEDIC": 5,
    "ACADEMIC_REFERENCE": 4,
    "GOVERNMENT_PUBLICATION": 4,
    "INSTITUTIONAL": 3,
    "GENERAL_REFERENCE": 2,
    "UNKNOWN": 0,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset({
    "a", "an", "the", "of", "to", "in", "and", "or", "is", "are",
    "was", "were", "be", "been", "it", "its", "as", "at", "by", "for",
    "on", "with", "that", "this", "from", "which", "who", "whom", "what",
    "when", "where", "how", "why", "did", "does", "do", "have", "has",
    "had", "many", "much", "there", "their", "about", "into", "also",
})
_QUERY_OVERRIDE_PATTERNS = (
    re.compile(r"ignore (?:the )?(?:citations|sources|provenance)", re.I),
    re.compile(r"answer (?:from|with|using) (?:your )?(?:memory|own "
               r"knowledge|internal knowledge|training)", re.I),
    re.compile(r"say you (?:found|have|used) (?:a |the )?source", re.I),
    re.compile(r"(?:return|include|make up|fabricate) (?:a |the )?"
               r"(?:fake|nonexistent|dummy) (?:url|citation|source)", re.I),
    re.compile(r"use (?:the |this )?source even if (?:it is |it's |you are "
               r"|they are )?unrelated", re.I),
    re.compile(r"skip (?:the )?(?:verification|evidence gate|claim check)",
               re.I),
    re.compile(r"ignore (?:all |any |the )?(?:previous|prior|above|earlier)"
               r" (?:instructions|prompts|rules)", re.I),
    re.compile(r"(?:i am|this is) (?:the )?(?:system|administrator|developer|"
               r"official|authoritative)", re.I),
)


def normalize_query(query: str) -> str:
    return " ".join(str(query).split()).strip().rstrip("?!. ")


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(str(text).lower())
            if token not in _STOP]


def effective_query(query: str) -> str:
    """Independently strip frozen query-override phrases before retrieval."""
    cleaned = str(query)
    flagged = False
    for pattern in _QUERY_OVERRIDE_PATTERNS:
        for match in list(pattern.finditer(cleaned)):
            cleaned = cleaned.replace(match.group(0), " ")
            flagged = True
    if flagged and ":" in cleaned:
        cleaned = cleaned.rsplit(":", 1)[-1]
    return normalize_query(cleaned)


def _metadata(chunk: dict) -> dict:
    value = chunk.get("metadata")
    return value if isinstance(value, dict) else {}


def _shingles(text: str, n: int = 4) -> frozenset:
    tokens = tokenize(text)
    if len(tokens) < n:
        return frozenset({" ".join(tokens)}) if tokens else frozenset()
    return frozenset(tuple(tokens[index:index + n])
                     for index in range(len(tokens) - n + 1))


def _jaccard(left: frozenset, right: frozenset) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


@dataclass(frozen=True)
class RetrievalTrace:
    query: str
    effective_query: str
    ranked: tuple[tuple[str, float], ...]
    reranked: tuple[tuple[str, float], ...]
    deduped: tuple[tuple[str, float], ...]
    final_window: tuple[tuple[str, float], ...]

    @property
    def chunk_ids(self) -> list[str]:
        return [chunk_id for chunk_id, _score in self.final_window]

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "effective_query": self.effective_query,
            "ranked": [list(item) for item in self.ranked],
            "reranked": [list(item) for item in self.reranked],
            "deduped": [list(item) for item in self.deduped],
            "final_window": [list(item) for item in self.final_window],
            "top_k": TOP_K,
        }


class RetrievalMirror:
    """Corpus-bound independent implementation of the frozen arithmetic."""

    def __init__(self, chunks: list[dict]):
        self.chunks = list(chunks)
        self.chunks_by_id = {
            str(chunk["chunk_id"]): chunk for chunk in self.chunks}
        self.chunk_ids = [str(chunk["chunk_id"]) for chunk in self.chunks]
        self.docs: list[dict[str, int]] = []
        self.doc_len: list[int] = []
        self.inverted: dict[str, dict[int, int]] = {}
        for position, chunk in enumerate(self.chunks):
            frequencies: dict[str, int] = {}
            for token in tokenize(str(chunk.get("text") or "")):
                frequencies[token] = frequencies.get(token, 0) + 1
            self.docs.append(frequencies)
            self.doc_len.append(sum(frequencies.values()))
            for token, frequency in frequencies.items():
                self.inverted.setdefault(token, {})[position] = frequency
        self.n_docs = len(self.docs)
        self.avg_len = (sum(self.doc_len) / self.n_docs) \
            if self.n_docs else 0.0

    def _idf(self, term: str) -> float:
        postings = self.inverted.get(term)
        if not postings:
            return 0.0
        df = len(postings)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def _score(self, query_tokens: list[str], position: int) -> float:
        total = 0.0
        document_length = self.doc_len[position] or 1
        norm = K1 * (1.0 - B + B * document_length /
                     (self.avg_len or 1.0))
        for term in query_tokens:
            frequency = self.docs[position].get(term)
            if not frequency:
                continue
            total += self._idf(term) * (
                frequency * (K1 + 1.0) / (frequency + norm))
        return total

    def bm25(self, query: str, limit: int) -> list[tuple[str, float]]:
        query_tokens = tokenize(normalize_query(query))
        candidates: set[int] = set()
        for term in query_tokens:
            candidates.update(self.inverted.get(term, ()))
        scored = [(self._score(query_tokens, position),
                   self.chunk_ids[position]) for position in candidates]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [(chunk_id, score) for score, chunk_id in scored[:limit]]

    def rerank(self, ranked: list[tuple[str, float]], query: str,
               top_k: int) -> list[tuple[str, float]]:
        candidates = ranked[:max(top_k, top_k * CANDIDATE_MULTIPLIER)]
        query_terms = set(tokenize(normalize_query(query)))
        max_score = max((score for _chunk_id, score in candidates),
                        default=0.0) or 1.0
        output: list[tuple[str, float]] = []
        for chunk_id, score in candidates:
            chunk = self.chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            authority = AUTHORITY_RANK.get(
                str(_metadata(chunk).get("authority_class") or "UNKNOWN"), 0)
            terms = set(tokenize(str(chunk.get("text") or "")))
            coverage = len(query_terms & terms) / len(query_terms) \
                if query_terms else 0.0
            reranked_score = (
                COVERAGE_WEIGHT * coverage
                + RERANK_TIEBREAK_WEIGHT * (score / max_score)
                + AUTHORITY_BONUS * authority / 10.0
            )
            output.append((chunk_id, reranked_score))
        output.sort(key=lambda item: (-item[1], item[0]))
        return output

    def dedup(self, ranked: list[tuple[str, float]]) \
            -> list[tuple[str, float]]:
        kept: list[tuple[str, float]] = []
        kept_shingles: dict[str, list[frozenset]] = {}
        per_source: dict[str, int] = {}
        for chunk_id, score in ranked:
            chunk = self.chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            source_id = str(chunk.get("source_id") or "")
            if per_source.get(source_id, 0) >= MAX_PER_SOURCE:
                continue
            shingles = _shingles(str(chunk.get("text") or ""))
            if any(_jaccard(shingles, prior) >= JACCARD_THRESHOLD
                   for prior in kept_shingles.get(source_id, ())):
                continue
            kept.append((chunk_id, score))
            kept_shingles.setdefault(source_id, []).append(shingles)
            per_source[source_id] = per_source.get(source_id, 0) + 1
        return kept

    def select_window(self, deduped: list[tuple[str, float]],
                      top_k: int) -> list[tuple[str, float]]:
        if len(deduped) <= top_k:
            return list(deduped)
        window = list(deduped[:top_k])
        max_score = max(score for _chunk_id, score in deduped) or 0.0
        window_sources = {
            str(self.chunks_by_id[chunk_id].get("source_id") or "")
            for chunk_id, _score in window if chunk_id in self.chunks_by_id}
        reserved: list[tuple[str, float]] = []
        seen_sources: set[str] = set()
        for chunk_id, score in deduped[top_k:]:
            chunk = self.chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            source_id = str(chunk.get("source_id") or "")
            if source_id in window_sources or source_id in seen_sources:
                continue
            seen_sources.add(source_id)
            if score >= WINDOW_RESERVE_FRACTION * max_score:
                reserved.append((chunk_id, score))
        for chunk_id, score in reserved:
            counts: dict[str, int] = {}
            for current_id, _current_score in window:
                current = self.chunks_by_id.get(current_id)
                if current is not None:
                    source_id = str(current.get("source_id") or "")
                    counts[source_id] = counts.get(source_id, 0) + 1
            droppable = [
                index for index, (current_id, _current_score) in
                enumerate(window)
                if current_id in self.chunks_by_id and counts.get(str(
                    self.chunks_by_id[current_id].get("source_id") or ""), 0)
                > 1
            ]
            if not droppable:
                droppable = list(range(len(window)))
            drop = min(droppable,
                       key=lambda index: (window[index][1], window[index][0]))
            window[drop] = (chunk_id, score)
        window.sort(key=lambda item: (-item[1], item[0]))
        return window

    def retrieve(self, query: str, top_k: int = TOP_K) -> RetrievalTrace:
        effective = effective_query(query)
        ranked = self.bm25(effective, top_k * CANDIDATE_MULTIPLIER)
        reranked = self.rerank(ranked, effective, top_k)
        deduped = self.dedup(reranked)
        window = self.select_window(deduped, top_k)
        return RetrievalTrace(
            query=str(query), effective_query=effective,
            ranked=tuple(ranked), reranked=tuple(reranked),
            deduped=tuple(deduped), final_window=tuple(window))


def derive_initial_window(query: str, chunks: list[dict],
                          top_k: int = TOP_K) -> RetrievalTrace:
    return RetrievalMirror(chunks).retrieve(query, top_k=top_k)
