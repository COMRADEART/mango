"""embeddings — local embedding model interface (T5.7).

Local inference only (no paid APIs). The model is loaded behind a small
interface so candidates can be swapped during evaluation (see
scripts/eval_embeddings.py) and the winning configuration recorded in
rag/embeddings/embedding_manifest.json.

Candidate selection criteria (T5.7): scientific terminology, formula-
adjacent text, short questions vs long explanations, cross-domain
retrieval, local hardware fit (6 GB RTX 4050 / CPU), license, dimension,
latency. Popularity alone is not a criterion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class EmbeddingSpec:
    """Candidate model description (license facts recorded, not guessed)."""
    model: str                 # HF id
    revision: str              # pinned revision hash
    license: str
    dimension: int
    normalize: bool            # cosine-ready output
    query_prefix: str = ""     # e.g. e5/bge query instruction
    passage_prefix: str = ""
    notes: str = ""


# candidates evaluated in T5.7 (all small, CPU/GPU-friendly, permissive
# licenses). Revisions are pinned at manifest write time.
CANDIDATES: dict[str, EmbeddingSpec] = {
    "all-MiniLM-L6-v2": EmbeddingSpec(
        model="sentence-transformers/all-MiniLM-L6-v2",
        revision="",  # pinned at manifest build time
        license="Apache-2.0", dimension=384, normalize=True,
        notes="fastest; strong general baseline"),
    "bge-small-en-v1.5": EmbeddingSpec(
        model="BAAI/bge-small-en-v1.5",
        revision="", license="MIT", dimension=384, normalize=True,
        query_prefix="Represent this sentence for searching relevant passages: ",
        notes="retrieval-tuned; requires query instruction prefix"),
    "e5-small-v2": EmbeddingSpec(
        model="intfloat/e5-small-v2",
        revision="", license="MIT", dimension=384, normalize=True,
        query_prefix="query: ", passage_prefix="passage: ",
        notes="asymmetric query/passage prefixes"),
}


class EmbeddingModel(Protocol):
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...
    @property
    def spec(self) -> EmbeddingSpec: ...


class SentenceTransformerEmbedder:
    """sentence-transformers wrapper (local). Device auto-picked: CUDA
    when free, else CPU (the 6 GB GPU is reserved for generation)."""

    def __init__(self, spec: EmbeddingSpec, *, device: str | None = None,
                 batch_size: int = 64):
        from sentence_transformers import SentenceTransformer
        self.spec = spec
        self.batch_size = batch_size
        if device is None:
            device = "cpu"  # default: leave the GPU to the reasoner
        self.device = device
        self._model = SentenceTransformer(spec.model, device=device)
        self._dim = self._model.get_sentence_embedding_dimension()

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        prefixed = [self.spec.passage_prefix + t for t in texts]
        vecs = self._model.encode(
            prefixed, batch_size=self.batch_size,
            normalize_embeddings=self.spec.normalize,
            show_progress_bar=False, convert_to_numpy=True)
        return np.asarray(vecs, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        vec = self._model.encode(
            [self.spec.query_prefix + text], normalize_embeddings=self.spec.normalize,
            show_progress_bar=False, convert_to_numpy=True)
        return np.asarray(vec, dtype=np.float32)[0]

    @property
    def dimension(self) -> int:
        return self._dim

    def info(self) -> dict:
        import torch
        return {
            "model": self.spec.model, "revision": self.spec.revision,
            "license": self.spec.license, "dimension": self._dim,
            "normalize": self.spec.normalize, "device": self.device,
            "torch_cuda": torch.cuda.is_available(),
            "batch_size": self.batch_size,
        }