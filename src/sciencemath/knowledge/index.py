"""T21.8 — deterministic lexical retrieval index (BM25).

Offline, local, reproducible, bounded: no remote calls, no hidden network
fallback. A pure-Python BM25 (Okapi, k1=1.2, b=0.75) over the frozen chunk
list; identical corpus content builds an identical index (sorted insertion,
deterministic tokenization, fixed field weights). Index build performance
and size are measured by scripts/t21_performance.py.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

from sciencemath.knowledge.schema import KnowledgeChunk

K1 = 1.2
B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Very small stop list — retrieval over a curated corpus does not need an
# aggressive stoplist, and keeping tokenization minimal keeps IDs stable.
_STOP = frozenset({
    "a", "an", "the", "of", "to", "in", "and", "or", "is", "are", "was",
    "were", "be", "been", "it", "its", "as", "at", "by", "for", "on", "with",
    "that", "this", "from", "which", "who", "whom", "what", "when", "where",
    "how", "why", "did", "does", "do", "does", "have", "has", "had", "many",
    "much", "there", "their", "about", "into", "also",
})


def tokenize(text: str) -> list[str]:
    """Deterministic lowercase word tokenization with stopword removal."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def normalize_query(query: str) -> str:
    """T21.7 query normalization: collapse whitespace, strip punctuation
    framing, keep case-insensitive content words."""
    cleaned = " ".join(query.split()).strip().rstrip("?!. ")
    return cleaned


class BM25Index:
    """Deterministic BM25 inverted index over knowledge chunks."""

    def __init__(self, chunks: list[KnowledgeChunk], k1: float = K1,
                 b: float = B):
        self.k1 = k1
        self.b = b
        self.chunk_ids: list[str] = [c.chunk_id for c in chunks]
        self._pos: dict[str, int] = {cid: i
                                     for i, cid in enumerate(self.chunk_ids)}
        self.docs: list[dict[str, int]] = []
        self.doc_len: list[int] = []
        self.inverted: dict[str, dict[int, int]] = {}
        for chunk in chunks:
            toks = tokenize(chunk.text)
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            pos = len(self.docs)
            self.docs.append(tf)
            self.doc_len.append(len(toks))
            for term, freq in tf.items():
                self.inverted.setdefault(term, {})[pos] = freq
        self.n_docs = len(self.docs)
        self.avg_len = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

    # -- scoring ----------------------------------------------------------
    def _idf(self, term: str) -> float:
        postings = self.inverted.get(term)
        if not postings:
            return 0.0
        n = self.n_docs
        df = len(postings)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def score(self, query_tokens: list[str], pos: int) -> float:
        total = 0.0
        dl = self.doc_len[pos] or 1
        norm = self.k1 * (1.0 - self.b + self.b * dl / (self.avg_len or 1.0))
        for term in query_tokens:
            freq = self.docs[pos].get(term)
            if not freq:
                continue
            idf = self._idf(term)
            tf_norm = (freq * (self.k1 + 1.0)) / (freq + norm)
            total += idf * tf_norm
        return total

    def search(self, query: str, top_k: int = 10) \
            -> list[tuple[str, float]]:
        """Deterministic top-k: BM25 score desc, then chunk_id asc for ties."""
        toks = tokenize(normalize_query(query))
        candidates: set[int] = set()
        for term in toks:
            candidates.update(self.inverted.get(term, ()))
        scored = [(self.score(toks, pos), self.chunk_ids[pos])
                  for pos in candidates]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [(cid, s) for s, cid in scored[:max(0, top_k)]]

    # -- persistence -------------------------------------------------------
    def manifest(self) -> dict:
        return {
            "kind": "knowledge-bm25-v1",
            "k1": self.k1,
            "b": self.b,
            "n_docs": self.n_docs,
            "avg_len": self.avg_len,
            "vocab": len(self.inverted),
        }

    def checksum(self) -> str:
        blob = json.dumps(self.manifest(), sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()