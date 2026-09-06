"""retriever — the retrieval pipeline (T5.9).

    question -> domain classification -> query normalization
             -> embedding -> vector retrieval -> metadata filtering
             -> reranking -> context selection

Nothing here calls a language model: retrieval is deterministic given
the corpus + index. Configurables (T5.9): top_k, top_n rerank,
similarity threshold, max context tokens, domain filters. Chunks below
the threshold are dropped, not silently passed to the model — that is
what makes INSUFFICIENT_EVIDENCE reachable (T5.14).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from sciencemath.rag.chunking import estimate_tokens
from sciencemath.rag.reranker import IdentityReranker, Reranker
from sciencemath.rag.vectorstore import VectorStore
from sciencemath.utils.io_utils import load_json, read_jsonl

_STOPWORDS = {
    "what", "is", "the", "a", "an", "of", "in", "on", "for", "to", "and",
    "are", "do", "does", "how", "why", "when", "which", "that", "this",
    "explain", "describe", "define", "tell", "about", "can", "you", "me",
}


@dataclass
class RetrievalConfig:
    top_k: int = 8            # vector retrieval candidates
    top_n: int = 4            # after reranking -> context selection
    similarity_threshold: float = 0.30   # below => dropped (uncertainty path)
    max_context_tokens: int = 1200
    domain_filters: list[str] | None = None   # canonical domains to allow
    reranker: str = "none"    # none | bm25 | cross-encoder


@dataclass
class RetrievalResult:
    """Full retrieval trace (goes into the audit record, T5.24)."""
    query: str
    normalized_query: str
    query_domain: str
    chunks: list[dict]                 # selected context (rerank-ordered)
    rejected: list[dict]               # candidates dropped (threshold/rank)
    used_retrieval: bool
    embedding_model: str
    latency_s: float
    total_context_tokens: int
    error: str | None = None


def normalize_query(question: str) -> str:
    """Query normalization: strip filler/interrogative glue but keep
    scientific keywords, symbols and units intact (units are strong
    retrieval signals — do not lowercase-strip them away entirely; we
    keep original case for symbols like 'N', 'pH', 'DNA')."""
    q = re.sub(r"^(?:hey|ok(?:ay)?|please)[,\s]+", "", question.strip())
    q = re.sub(r"\s+", " ", q)
    keywords = [w for w in q.split() if w.lower().strip(".,?!") not in _STOPWORDS]
    return " ".join(keywords) if keywords else q


def query_domain(question: str) -> str:
    from sciencemath.rag.taxonomy import classify_domain
    return classify_domain(question)


class Retriever:
    """Dense retrieval over an in-memory chunk store + vector index."""

    def __init__(self, *, store: VectorStore, chunk_by_id: dict[str, dict],
                 embedder, config: RetrievalConfig | None = None,
                 reranker: Reranker | None = None):
        self.store = store
        self.chunks = chunk_by_id
        self.embedder = embedder
        self.config = config or RetrievalConfig()
        self.reranker = reranker or IdentityReranker()

    def retrieve(self, question: str, *, domain_filters: list[str] | None = None,
                 top_k: int | None = None, top_n: int | None = None,
                 similarity_threshold: float | None = None) -> RetrievalResult:
        cfg = self.config
        top_k = top_k or cfg.top_k
        top_n = top_n or cfg.top_n
        threshold = (similarity_threshold if similarity_threshold is not None
                     else cfg.similarity_threshold)
        filters = domain_filters if domain_filters is not None else cfg.domain_filters
        start = time.perf_counter()
        try:
            normalized = normalize_query(question)
            qvec = self.embedder.embed_query(question)
            # metadata pre-filter (domain filters), then vector search
            allowed = None
            if filters:
                allowed = [cid for cid, c in self.chunks.items()
                           if c.get("domain") in filters]
                if not allowed:
                    return RetrievalResult(
                        query=question, normalized_query=normalized,
                        query_domain=query_domain(question), chunks=[],
                        rejected=[], used_retrieval=False,
                        embedding_model=self.embedder.spec.model,
                        latency_s=time.perf_counter() - start,
                        total_context_tokens=0)
            hits = self.store.search(qvec, top_k=top_k, allowed_chunk_ids=allowed)
            candidates = []
            for cid, score in hits:
                chunk = dict(self.chunks[cid])
                chunk["chunk_id"] = cid
                chunk["score"] = score
                candidates.append(chunk)
            # T5.10: rerank stage (measured, optional)
            reranked = self.reranker.rerank(normalized or question,
                                            candidates, top_n)
            selected, rejected = [], []
            for c in reranked:
                if c["score"] >= threshold:
                    selected.append(c)
                else:
                    rejected.append(c)
            # context budget: pack in rank order until token budget spent
            kept, budget = [], cfg.max_context_tokens
            for c in selected:
                t = estimate_tokens(c["text"])
                if budget - t < 0 and kept:
                    c["dropped_for_budget"] = True
                    rejected.append(c)
                    continue
                budget -= t
                kept.append(c)
            return RetrievalResult(
                query=question, normalized_query=normalized,
                query_domain=query_domain(question), chunks=kept,
                rejected=rejected, used_retrieval=bool(kept),
                embedding_model=self.embedder.spec.model,
                latency_s=time.perf_counter() - start,
                total_context_tokens=sum(estimate_tokens(c["text"])
                                         for c in kept))
        except Exception as exc:  # noqa: BLE001 — retrieval must never crash the answer
            return RetrievalResult(
                query=question, normalized_query=normalize_query(question),
                query_domain=query_domain(question), chunks=[], rejected=[],
                used_retrieval=False, embedding_model=getattr(
                    self.embedder.spec, "model", "unknown"),
                latency_s=time.perf_counter() - start,
                total_context_tokens=0, error=f"{type(exc).__name__}: {exc}")


# -- corpus loading (T5.16 versioning) --------------------------------------

def load_corpus(corpus_dir: str | Path, *,
                verify_checksum: bool = True) -> tuple[dict[str, dict], dict]:
    """Load rag/corpus/*.jsonl -> (chunk_by_id, corpus_manifest).

    Verifies the per-file checksums recorded in the manifest before
    returning; a mismatch raises CorruptCorpusError (a corrupt/stale
    corpus is refused, never silently served)."""
    from sciencemath.rag.vectorstore import file_sha256
    corpus_dir = Path(corpus_dir)
    manifest = load_json(corpus_dir / "corpus_manifest.json")
    chunk_by_id: dict[str, dict] = {}
    for path in sorted(corpus_dir.glob("*.jsonl")):
        if verify_checksum:
            recorded = (manifest.get("file_checksums") or {}).get(path.name)
            if recorded and recorded != file_sha256(path):
                raise CorruptCorpusError(
                    f"corpus file {path.name} does not match its manifest "
                    f"checksum — rebuild or re-freeze the corpus")
        for rec in read_jsonl(path):
            chunk_by_id[rec["chunk_id"]] = rec
    return chunk_by_id, manifest


class CorruptCorpusError(RuntimeError):
    pass