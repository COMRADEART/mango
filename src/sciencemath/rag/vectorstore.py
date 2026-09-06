"""vectorstore — abstracted local vector index (T5.8).

The interface is deliberately narrow (add/search/save/load) so Mango can
later swap FAISS for Qdrant/Chroma/another local engine without touching
retrieval logic. FAISS (IndexFlatIP, exact cosine over normalized
vectors) is the first implementation — at this corpus scale (<10^5
vectors) exact search is both cheapest to reason about and fastest
enough; IVF/HNSW would be premature optimization (T5.25: baseline first).

The index manifest pins corpus version, embedding revision, checksums
and source distribution (T5.16 freshness/versioning contract).
"""
from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from sciencemath.utils.io_utils import write_json, load_json


class VectorStore(ABC):
    """Minimal contract every backend must implement."""

    @abstractmethod
    def add(self, vectors: np.ndarray, chunk_ids: list[str]) -> None: ...

    @abstractmethod
    def search(self, query_vec: np.ndarray, top_k: int,
               allowed_chunk_ids: list[str] | None = None) -> list[tuple[str, float]]:
        """Return [(chunk_id, cosine_score), ...] best-first.
        allowed_chunk_ids: metadata pre-filter (None = all)."""

    @abstractmethod
    def __len__(self) -> int: ...

    @abstractmethod
    def save(self, path) -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, path) -> "VectorStore": ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


class BruteForceVectorStore(VectorStore):
    """Exact in-memory search (numpy). Used in tests and as the fallback
    when faiss is unavailable; same results as FAISS IndexFlatIP."""

    def __init__(self, dim: int):
        self._dim = dim
        self._vectors = np.zeros((0, dim), dtype=np.float32)
        self._ids: list[str] = []
        self._id_to_row: dict[str, int] = {}

    def add(self, vectors, chunk_ids):
        v = np.asarray(vectors, dtype=np.float32)
        if v.ndim == 1:
            v = v[None, :]
        if v.shape[0] != len(chunk_ids):
            raise ValueError("vectors/chunk_ids length mismatch")
        start = self._vectors.shape[0]
        self._vectors = np.vstack([self._vectors, v])
        for i, cid in enumerate(chunk_ids):
            self._id_to_row[cid] = start + i
        self._ids.extend(chunk_ids)

    def search(self, query_vec, top_k, allowed_chunk_ids=None):
        q = np.asarray(query_vec, dtype=np.float32)
        rows = range(len(self._ids))
        if allowed_chunk_ids is not None:
            rows = [self._id_to_row[c] for c in allowed_chunk_ids
                    if c in self._id_to_row]
        if not rows:
            return []
        scores = self._vectors[list(rows)] @ q
        order = np.argsort(-scores)[:top_k]
        return [(self._ids[list(rows)[i]], float(scores[i])) for i in order]

    def __len__(self):
        return len(self._ids)

    @property
    def dimension(self):
        return self._dim

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path.with_suffix(".npz"), vectors=self._vectors,
                 ids=np.array(self._ids, dtype=object))

    @classmethod
    def load(cls, path):
        path = Path(path)
        data = np.load(path.with_suffix(".npz"), allow_pickle=True)
        store = cls(data["vectors"].shape[1])
        store._vectors = data["vectors"]
        store._ids = list(data["ids"])
        store._id_to_row = {cid: i for i, cid in enumerate(store._ids)}
        return store


class FaissVectorStore(VectorStore):
    """FAISS IndexFlatIP over L2-normalized vectors (cosine). IDs map
    rows -> chunk_ids; metadata filtering happens in retriever via
    allowed_chunk_ids (brute-force exactness retained)."""

    def __init__(self, dim: int):
        import faiss  # local import: optional dependency
        self._faiss = faiss
        self._dim = dim
        self._index = faiss.IndexFlatIP(dim)
        self._ids: list[str] = []
        self._id_to_row: dict[str, int] = {}
        self._vectors = np.zeros((0, dim), dtype=np.float32)

    def add(self, vectors, chunk_ids):
        v = np.ascontiguousarray(np.asarray(vectors, dtype=np.float32))
        if v.ndim == 1:
            v = v[None, :]
        if v.shape[0] != len(chunk_ids):
            raise ValueError("vectors/chunk_ids length mismatch")
        self._index.add(v)
        self._vectors = np.vstack([self._vectors, v])
        for cid in chunk_ids:
            self._id_to_row[cid] = len(self._ids)
            self._ids.append(cid)

    def search(self, query_vec, top_k, allowed_chunk_ids=None):
        q = np.ascontiguousarray(
            np.asarray(query_vec, dtype=np.float32)[None, :])
        if allowed_chunk_ids is None:
            k = min(top_k, len(self._ids))
            if k == 0:
                return []
            scores, rows = self._index.search(q, k)
            return [(self._ids[r], float(s)) for s, r in zip(scores[0], rows[0])
                    if r >= 0]
        rows = [self._id_to_row[c] for c in allowed_chunk_ids
                if c in self._id_to_row]
        if not rows:
            return []
        scores = self._vectors[rows] @ q[0]
        order = np.argsort(-scores)[:top_k]
        return [(self._ids[rows[i]], float(scores[i])) for i in order]

    def __len__(self):
        return len(self._ids)

    @property
    def dimension(self):
        return self._dim

    def save(self, path):
        import faiss
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path))
        np.save(str(path) + ".ids.npy", np.array(self._ids, dtype=object))

    @classmethod
    def load(cls, path):
        import faiss
        path = Path(path)
        index = faiss.read_index(str(path))
        store = cls(index.d)
        store._index = index
        store._ids = list(np.load(str(path) + ".ids.npy", allow_pickle=True))
        store._id_to_row = {cid: i for i, cid in enumerate(store._ids)}
        # rebuild the vector matrix so metadata-filtered (brute-force)
        # search works exactly as before save/load
        if index.ntotal:
            store._vectors = np.vstack(
                [index.reconstruct(i) for i in range(index.ntotal)])
        return store


def make_store(engine: str, dim: int) -> VectorStore:
    """Factory (configs/rag.yaml retrieval.vector_store)."""
    if engine == "faiss":
        return FaissVectorStore(dim)
    if engine == "numpy":
        return BruteForceVectorStore(dim)
    raise ValueError(f"unknown vector store engine: {engine!r}")


# -- index manifest --------------------------------------------------------

def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_index_manifest(*, corpus_version: str, corpus_checksum: str,
                         embedding_model: str, embedding_revision: str,
                         engine: str, index_path, chunk_count: int,
                         source_distribution: dict[str, int],
                         domain_distribution: dict[str, int],
                         build_seconds: float) -> dict:
    return {
        "index_manifest_version": "1.0.0",
        "corpus_version": corpus_version,
        "corpus_checksum": corpus_checksum,
        "embedding_model": embedding_model,
        "embedding_revision": embedding_revision,
        "engine": engine,
        "dimension": None,          # filled by caller (store.dimension)
        "chunk_count": chunk_count,
        "vector_count": None,       # filled by caller (len(store))
        "checksum": file_sha256(index_path) if Path(index_path).exists() else None,
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "build_seconds": round(build_seconds, 2),
        "source_distribution": source_distribution,
        "domain_distribution": domain_distribution,
    }


def finalize_index_manifest(manifest: dict, *, dimension: int,
                            vector_count: int) -> dict:
    manifest["dimension"] = int(dimension)
    manifest["vector_count"] = int(vector_count)
    return manifest


def load_index_manifest(path) -> dict:
    return load_json(path)