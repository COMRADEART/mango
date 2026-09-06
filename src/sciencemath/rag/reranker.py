"""reranker — second-stage ranking (T5.10).

Goal: reduce semantically related but scientifically irrelevant
retrieval. Two concrete rerankers, both local:

  * CrossEncoderReranker  — cross-encoder (ms-marco-MiniLM-L-6-v2);
    quality first, CPU-friendly at top_n<=20 scale.
  * BM25Reranker          — deterministic lexical rerank (rank_bm25);
    zero-model fallback, useful where the query is keyword-driven.

Whether reranking actually improves Recall@k / MRR / nDCG / answer
accuracy is decided by measurement (scripts/eval_reranker.py), not by
assumption. The retriever treats reranking as an optional stage.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np


class Reranker(Protocol):
    name: str
    def rerank(self, query: str, candidates: list[dict], top_n: int) -> list[dict]:
        """Each candidate: {"chunk_id", "text", "score" (retrieval score),
        ...}. Returns top_n candidates with "rerank_score" added, best
        first. Must be deterministic for fixed inputs."""


class CrossEncoderReranker:
    name = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
                 *, device: str = "cpu", batch_size: int = 32):
        from sentence_transformers import CrossEncoder
        self._model = CrossEncoder(model, device=device)
        self.batch_size = batch_size

    def rerank(self, query, candidates, top_n):
        if not candidates:
            return []
        pairs = [(query, c["text"]) for c in candidates]
        scores = self._model.predict(
            pairs, batch_size=self.batch_size, show_progress_bar=False)
        order = np.argsort(-np.asarray(scores))[:top_n]
        out = []
        for i in order:
            c = dict(candidates[i])
            c["rerank_score"] = float(scores[i])
            out.append(c)
        return out


class BM25Reranker:
    """Lexical rerank over the candidate set only (not the corpus) —
    cheap, deterministic, no model download."""
    name = "bm25-candidate-rerank"

    def __init__(self):
        self._bm25 = None  # built per-call over candidates

    def rerank(self, query, candidates, top_n):
        if not candidates:
            return []
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            raise ImportError("rank_bm25 required for BM25Reranker")
        tok = lambda t: [w for w in t.lower().split() if w]  # noqa: E731
        corpus = [tok(c["text"]) for c in candidates]
        if not any(doc for doc in corpus):
            return [dict(c, rerank_score=0.0) for c in candidates[:top_n]]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(tok(query))
        order = np.argsort(-np.asarray(scores))[:top_n]
        return [dict(candidates[i], rerank_score=float(scores[i]))
                for i in order]


class IdentityReranker:
    """No-op reranker — the 'embedding-only' arm of the T5.10 comparison."""
    name = "none"

    def rerank(self, query, candidates, top_n):
        out = [dict(c, rerank_score=c.get("score", 0.0)) for c in candidates]
        return out[:top_n]