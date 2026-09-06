"""T5 index/retrieval tests — vector stores, retriever pipeline, corpus
integrity, index manifest, rerankers (T5.8/T5.9/T5.10/T5.16).

No model downloads: a deterministic hash-based fake embedder stands in
for the sentence-transformer (real models are measured in
scripts/eval_embeddings.py / scripts/eval_reranker.py).
"""
from __future__ import annotations

import hashlib
import json
import re

import numpy as np
import pytest

from sciencemath.rag.chunking import estimate_tokens
from sciencemath.rag.retriever import (CorruptCorpusError, RetrievalConfig,
                                       Retriever, load_corpus, normalize_query)
from sciencemath.rag.reranker import BM25Reranker, IdentityReranker
from sciencemath.rag.vectorstore import (BruteForceVectorStore,
                                         build_index_manifest,
                                         file_sha256,
                                         finalize_index_manifest)

DIM = 64


def _vec(text: str, dim: int = DIM) -> np.ndarray:
    """Deterministic token-bucket embedding: documents sharing tokens
    get high cosine — enough geometry for retrieval tests, zero model."""
    v = np.zeros(dim, dtype=np.float32)
    for tok in __import__("re").findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
        v[h % dim] += 1.0
    n = float(np.linalg.norm(v))
    return v / n if n else v


class _Spec:
    model = "fake-embedder"
    revision = "test-revision"
    license = "test"


class FakeEmbedder:
    """Deterministic stand-in: shared vocabulary -> cosine similarity."""
    spec = _Spec()

    def embed_query(self, q):
        return _vec(q)

    def embed_passages(self, texts):
        return np.vstack([_vec(t) for t in texts])


CHUNKS = {
    "wiki-1:ribosome:0": {
        "chunk_id": "wiki-1:ribosome:0", "source_id": "wikipedia_en",
        "title": "Ribosome", "domain": "biology",
        "text": "Ribosomes carry out protein synthesis by translating "
                "messenger RNA into polypeptide chains."},
    "wiki-2:newton:0": {
        "chunk_id": "wiki-2:newton:0", "source_id": "wikipedia_en",
        "title": "Newton's laws", "domain": "physics",
        "text": "Newton's second law: F = ma relates force, mass, "
                "acceleration."},
    "wiki-3:climate:0": {
        "chunk_id": "wiki-3:climate:0", "source_id": "wikipedia_en",
        "title": "Climate", "domain": "earth_science",
        "text": "The climate system includes the atmosphere, oceans and "
                "ice sheets."},
}
Q_RIBOSOME = "Ribosomes carry out protein synthesis by translating " \
             "messenger RNA into polypeptide chains."
Q_NEWTON = "Newton's second law: F = ma relates force, mass, acceleration."


def _make_store(engine="numpy", ids_texts=None):
    store = BruteForceVectorStore(DIM) if engine == "numpy" else \
        pytest.importorskip("faiss") and _faiss_store(DIM)
    if ids_texts is None:
        ids_texts = [(cid, c["text"]) for cid, c in CHUNKS.items()]
    vecs = np.vstack([_vec(t) for _cid, t in ids_texts])
    store.add(vecs, [cid for cid, _t in ids_texts])
    return store


def _faiss_store(dim):
    from sciencemath.rag.vectorstore import FaissVectorStore
    return FaissVectorStore(dim)


def _retriever(store=None, config=None, reranker=None) -> Retriever:
    store = store or _make_store()
    return Retriever(store=store, chunk_by_id=CHUNKS,
                     embedder=FakeEmbedder(), config=config or RetrievalConfig(),
                     reranker=reranker)


# ---------------------------------------------------------------------------
# T5.8 vector store contract
# ---------------------------------------------------------------------------

def test_brute_force_store_search_order_and_topk():
    store = _make_store()
    hits = store.search(_vec(Q_RIBOSOME), top_k=3)
    assert hits[0][0] == "wiki-1:ribosome:0"
    assert hits[0][1] > 0.99
    assert len(hits) == 3
    assert len(store) == 3


def test_brute_force_store_rejects_length_mismatch():
    store = BruteForceVectorStore(DIM)
    with pytest.raises(ValueError):
        store.add(np.zeros((2, DIM)), ["a"])


def test_brute_force_save_load_roundtrip(tmp_path):
    store = _make_store()
    path = tmp_path / "index.npz"
    store.save(path)
    loaded = BruteForceVectorStore.load(path)
    assert len(loaded) == 3
    hits = store.search(_vec(Q_NEWTON), top_k=1)
    hits2 = loaded.search(_vec(Q_NEWTON), top_k=1)
    assert hits[0][0] == hits2[0][0]
    assert hits[0][1] == pytest.approx(hits2[0][1], abs=1e-5)


def test_faiss_store_matches_brute_force_and_survives_reload(tmp_path):
    faiss = pytest.importorskip("faiss")
    from sciencemath.rag.vectorstore import FaissVectorStore
    store = FaissVectorStore(DIM)
    vecs = np.vstack([_vec(c["text"]) for c in CHUNKS.values()])
    ids = list(CHUNKS)
    store.add(vecs, ids)
    plain = store.search(_vec(Q_RIBOSOME), top_k=2)
    assert plain[0][0] == "wiki-1:ribosome:0"
    # save -> load -> filtered search must still work (regression:
    # the vector matrix used by the filtered path must survive reload)
    path = tmp_path / "idx.faiss"
    store.save(path)
    loaded = FaissVectorStore.load(path)
    assert len(loaded) == 3
    filt = loaded.search(_vec(Q_RIBOSOME), top_k=2,
                         allowed_chunk_ids=["wiki-2:newton:0",
                                            "wiki-3:climate:0"])
    assert all(cid != "wiki-1:ribosome:0" for cid, _s in filt)
    assert filt and filt[0][0] in ("wiki-2:newton:0", "wiki-3:climate:0")


def test_make_store_factory():
    from sciencemath.rag.vectorstore import make_store
    assert isinstance(make_store("numpy", 8), BruteForceVectorStore)
    with pytest.raises(ValueError):
        make_store("hnsw", 8)


def test_index_manifest_roundtrip(tmp_path):
    idx = tmp_path / "index.faiss"
    idx.write_bytes(b"fake-index-bytes")
    m = build_index_manifest(
        corpus_version="mango-science-corpus-v0.1", corpus_checksum="abc",
        embedding_model="intfloat/e5-small-v2",
        embedding_revision="ffb93f3", engine="faiss", index_path=idx,
        chunk_count=3, source_distribution={"wikipedia_en": 3},
        domain_distribution={"biology": 1, "physics": 1,
                             "earth_science": 1},
        build_seconds=1.0)
    m = finalize_index_manifest(m, dimension=DIM, vector_count=3)
    assert m["checksum"] == file_sha256(idx)
    assert m["dimension"] == DIM and m["vector_count"] == 3
    assert m["corpus_version"] == "mango-science-corpus-v0.1"


# ---------------------------------------------------------------------------
# T5.9 retrieval pipeline
# ---------------------------------------------------------------------------

def test_normalize_query_keeps_units_and_symbols():
    n = normalize_query("What is the function of ribosomes?")
    assert "ribosomes" in n and "function" in n
    n2 = normalize_query("A 2 kg object accelerates at 4 m/s².")
    assert "2" in n2 and "kg" in n2 and "m/s²" in n2


def test_retriever_selects_exact_passage():
    r = _retriever()
    res = r.retrieve("What carries out protein synthesis?")
    # the exact ribosome passage must rank first (deterministic fake)
    assert res.chunks
    assert res.chunks[0]["chunk_id"] == "wiki-1:ribosome:0"
    assert res.chunks[0]["score"] > 0.30
    assert res.used_retrieval is True
    assert res.total_context_tokens > 0
    assert res.error is None


def test_retriever_below_threshold_reports_insufficient():
    r = _retriever(config=RetrievalConfig(similarity_threshold=0.9,
                                          top_k=8, top_n=4))
    res = r.retrieve("What is the capital of France?")
    assert res.used_retrieval is False
    assert res.chunks == []
    assert res.rejected              # low-scoring candidates recorded


def test_retriever_metadata_filtering():
    r = _retriever()
    res = r.retrieve(Q_NEWTON, domain_filters=["physics"])
    assert res.chunks and res.chunks[0]["chunk_id"] == "wiki-2:newton:0"
    # a filter with no matching chunks -> explicit no-retrieval, not crash
    res2 = r.retrieve(Q_RIBOSOME, domain_filters=["astronomy"])
    assert res2.used_retrieval is False and res2.chunks == []
    assert res2.error is None


def test_retriever_respects_context_token_budget():
    r = _retriever(config=RetrievalConfig(
        max_context_tokens=estimate_tokens(Q_RIBOSOME) + 10,
        similarity_threshold=0.05))
    res = r.retrieve(Q_RIBOSOME + " " + Q_NEWTON)
    assert sum(estimate_tokens(c["text"]) for c in res.chunks) <= \
        estimate_tokens(Q_RIBOSOME) + 10 + 5
    dropped = [c for c in res.rejected if c.get("dropped_for_budget")]
    assert dropped


def test_retriever_reranker_stage_runs():
    r = _retriever(reranker=BM25Reranker())
    res = r.retrieve(Q_NEWTON)
    assert res.chunks
    assert "rerank_score" in res.chunks[0]


def test_retriever_never_crashes_on_embedder_failure():
    class Broken:
        spec = _Spec()

        def embed_query(self, q):
            raise RuntimeError("boom")

        def embed_passages(self, t):
            raise RuntimeError("boom")

    r = Retriever(store=_make_store(), chunk_by_id=CHUNKS,
                  embedder=Broken(), config=RetrievalConfig())
    res = r.retrieve(Q_RIBOSOME)
    assert res.used_retrieval is False
    assert res.chunks == []
    assert "boom" in res.error


def test_identity_reranker_is_embedding_only_arm():
    cands = [{"chunk_id": "a", "text": "t", "score": 0.5},
             {"chunk_id": "b", "text": "u", "score": 0.9}]
    out = IdentityReranker().rerank("q", cands, 2)
    assert [c["chunk_id"] for c in out] == ["a", "b"]   # order preserved
    assert out[1]["rerank_score"] == 0.9


def test_bm25_reranker_prefers_keyword_overlap():
    cands = [
        {"chunk_id": "x", "text": "photosynthesis converts light energy "
                                  "into chemical energy in plants",
         "score": 0.4},
        {"chunk_id": "y", "text": "respiration releases energy from "
                                  "glucose inside cells", "score": 0.42},
        {"chunk_id": "z", "text": "the mitochondrion produces ATP",
         "score": 0.41},
    ]
    out = BM25Reranker().rerank("photosynthesis light energy plants",
                                cands, top_n=3)
    assert out[0]["chunk_id"] == "x"
    assert out[0]["rerank_score"] > 0
    # determinism for fixed inputs
    out2 = BM25Reranker().rerank("photosynthesis light energy plants",
                                 [dict(c) for c in cands], top_n=3)
    assert [c["chunk_id"] for c in out2] == [c["chunk_id"] for c in out]


def test_cross_encoder_reranker_smoke_if_cached():
    """Only runs when the cross-encoder weights are already in the HF
    cache (download happens in scripts/eval_reranker.py, not in tests)."""
    try:
        from sentence_transformers import CrossEncoder  # noqa: F401
    except ImportError:
        pytest.skip("sentence-transformers unavailable")
    import os
    cache_root = os.environ.get("HF_HOME", os.path.expanduser(
        "~/.cache/huggingface"))
    marker = "models--cross-encoder--ms-marco-MiniLM-L-6-v2"
    if not any(os.path.isdir(os.path.join(cache_root, *p))
               for p in [("hub", marker), (marker,)]):
        pytest.skip("cross-encoder weights not cached")
    from sciencemath.rag.reranker import CrossEncoderReranker
    ce = CrossEncoderReranker()
    cands = [{"chunk_id": "good", "text": "Ribosomes carry out protein "
                                          "synthesis.", "score": 0.5},
             {"chunk_id": "bad", "text": "The best pizza toppings "
                                         "include basil.", "score": 0.6}]
    out = ce.rerank("What carries out protein synthesis?", cands, 2)
    assert out[0]["chunk_id"] == "good"


# ---------------------------------------------------------------------------
# T5.16 corpus integrity / versioning
# ---------------------------------------------------------------------------

def _write_corpus(tmp_path: "object", chunks: list[dict]):
    path = tmp_path / "wikipedia_en.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in chunks),
                    encoding="utf-8")
    manifest = {"corpus_version": "mango-science-corpus-v0.1",
                "file_checksums": {"wikipedia_en.jsonl": file_sha256(path)}}
    (tmp_path / "corpus_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    return manifest


def test_load_corpus_verifies_checksums(tmp_path):
    _write_corpus(tmp_path, list(CHUNKS.values()))
    chunk_by_id, manifest = load_corpus(tmp_path)
    assert set(chunk_by_id) == set(CHUNKS)
    assert manifest["corpus_version"] == "mango-science-corpus-v0.1"


def test_load_corpus_rejects_tampered_file(tmp_path):
    _write_corpus(tmp_path, list(CHUNKS.values()))
    path = tmp_path / "wikipedia_en.jsonl"
    # append a VALID jsonl record: only the manifest checksum can detect it
    path.write_text(path.read_text(encoding="utf-8") + "\n" +
                    json.dumps({"chunk_id": "extra:1", "title": "X"}),
                    encoding="utf-8")
    with pytest.raises(CorruptCorpusError):
        load_corpus(tmp_path, verify_checksum=True)
    # verification can be explicitly disabled (dev path) — never by default
    chunk_by_id, _ = load_corpus(tmp_path, verify_checksum=False)
    assert "extra:1" in chunk_by_id