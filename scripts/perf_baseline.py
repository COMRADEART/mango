"""T5.25 performance baseline — measured latencies and memory for the
retrieval layer and one retrieval-augmented generation, on this hardware
(RTX 4050 6 GB). Numbers feed the final T5 report; nothing is estimated.

Stages measured (median over N repetitions, deterministic inputs):
  * embed_query          (selected embedding model, device per manifest)
  * vector_search        (adopted store: faiss or numpy)
  * rerank               (adopted reranker; 'none' = passthrough)
  * retrieval_end_to_end (Retriever.retrieve)
  * generation           (Mango-v0.1 answering one SCIENCE question with
                          retrieved context — model loaded once)
  * peak memory          (torch.cuda.max_memory_allocated during a
                          generation; embedding/RSS noted separately)

Output: evaluations/rag-results/v1/perf_baseline.json
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from sciencemath.rag.embeddings import CANDIDATES, SentenceTransformerEmbedder
from sciencemath.rag.retriever import Retriever, RetrievalConfig, load_corpus
from sciencemath.rag.vectorstore import BruteForceVectorStore, make_store
from sciencemath.utils.io_utils import write_json

OUT = ROOT / "evaluations" / "rag-results" / "v1" / "perf_baseline.json"
QUERIES = [
    "What is the function of ribosomes?",
    "State Newton's second law of motion.",
    "What causes ocean tides?",
    "Define an exothermic reaction.",
    "What is escape velocity?",
    "How do vaccines work?",
    "What is the water cycle?",
    "What is a semiconductor?",
]


def _median(xs: list[float]) -> float:
    return round(statistics.median(xs), 5)


def main() -> int:
    corpus_dir = ROOT / "rag" / "corpus"
    chunk_by_id, manifest = load_corpus(corpus_dir)
    decision = json.loads((ROOT / "rag" / "embeddings" /
                           "embedding_decision.json").read_text(encoding="utf-8"))
    spec = CANDIDATES[decision["winner"]]
    device = "cpu"  # GPU reserved for the reasoner (6 GB budget)
    embedder = SentenceTransformerEmbedder(spec, device=device)

    print("embedding corpus ...", file=sys.stderr)
    t0 = time.perf_counter()
    texts = [c["text"] for c in chunk_by_id.values()]
    vecs = embedder.embed_passages(texts)
    embed_all_s = time.perf_counter() - t0

    engine = "faiss"
    try:
        store = make_store("faiss", vecs.shape[1])
    except Exception:  # noqa: BLE001
        store = BruteForceVectorStore(vecs.shape[1])
        engine = "numpy"
    store.add(vecs, list(chunk_by_id))

    # adopted reranker (read BEFORE the retriever is built)
    rd_path = ROOT / "rag" / "reranker" / "reranker_decision.json"
    rerank_name = "none"
    if rd_path.exists():
        rerank_name = json.loads(rd_path.read_text(encoding="utf-8")) \
            .get("adopted_reranker", "none")

    cfg = RetrievalConfig(top_k=8, top_n=4, similarity_threshold=0.30)
    # attach the ADOPTED reranker so the measured rerank stage is the
    # one actually used by the system (not a passthrough)
    reranker = None
    if rerank_name == "bm25":
        from sciencemath.rag.reranker import BM25Reranker
        reranker = BM25Reranker()
    elif rerank_name == "cross-encoder":
        from sciencemath.rag.reranker import CrossEncoderReranker
        reranker = CrossEncoderReranker()
    retriever = Retriever(store=store, chunk_by_id=chunk_by_id,
                          embedder=embedder, config=cfg, reranker=reranker)

    e_lat, s_lat, r_lat, e2e = [], [], [], []
    for q in QUERIES:
        t = time.perf_counter()
        qvec = embedder.embed_query(q)
        e_lat.append(time.perf_counter() - t)
        t = time.perf_counter()
        hits = store.search(qvec, top_k=cfg.top_k)
        s_lat.append(time.perf_counter() - t)
        res = retriever.retrieve(q)
        e2e.append(res.latency_s)
        r_lat.append(max(0.0, res.latency_s - e_lat[-1] - s_lat[-1]))

    base = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hardware_note": "RTX 4050 6 GB; embeddings/rerank on CPU, "
                         "generation on CUDA",
        "corpus_version": manifest.get("corpus_version"),
        "n_chunks": len(chunk_by_id),
        "embedding_model": spec.model,
        "embedding_dimension": int(vecs.shape[1]),
        "vector_engine": engine,
        "reranker": rerank_name,
        "embed_corpus_seconds": round(embed_all_s, 2),
        "embed_throughput_passages_per_s": round(len(texts) / embed_all_s, 1),
        "latency_ms_median": {
            "embed_query": round(1000 * _median(e_lat), 3),
            "vector_search": round(1000 * _median(s_lat), 3),
            "rerank_and_select": round(1000 * _median(r_lat), 3),
            "retrieval_end_to_end": round(1000 * _median(e2e), 3),
        },
        "latency_ms_max_end_to_end": round(1000 * max(e2e), 3),
    }

    gen_block = None
    try:
        import torch
        import yaml
        from sciencemath.evaluation.model_loader import load_model_safely
        model_cfg = yaml.safe_load((ROOT / "configs" / "model.yaml")
                                   .read_text(encoding="utf-8"))
        train_cfg = yaml.safe_load((ROOT / "configs" / "training.yaml")
                                   .read_text(encoding="utf-8"))
        model_id = model_cfg.get("model_id") or "Qwen/Qwen3-1.7B"
        tokenizer, model, info = load_model_safely(model_id)
        if not info["ok"]:
            raise RuntimeError(info["error"])
        adapter_dir = ROOT / train_cfg["training"]["adapter_output_dir"]
        if adapter_dir.exists():
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, str(adapter_dir))
            model.eval()
        from sciencemath.rag.pipeline import answer_question
        latencies, peak = [], 0
        for q in QUERIES[:3]:
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            t = time.perf_counter()
            ans = answer_question(
                model=model, tokenizer=tokenizer, question=q,
                question_id=f"perf-{abs(hash(q)) % 10**8}",
                retriever=retriever,
                generation={"seed": 42, "do_sample": False,
                            "max_new_tokens": 256})
            latencies.append(time.perf_counter() - t)
            if torch.cuda.is_available():
                peak = max(peak, torch.cuda.max_memory_allocated())
            print(f"gen {q!r}: {latencies[-1]:.2f}s", file=sys.stderr)
        gen_block = {
            "generation_latency_s_median": round(
                statistics.median(latencies), 3),
            "generation_max_new_tokens": 256,
            "peak_cuda_memory_bytes": int(peak) if peak else None,
            "peak_cuda_memory_gb": round(peak / 1e9, 2) if peak else None,
        }
    except Exception as exc:  # noqa: BLE001
        gen_block = {"error": f"{type(exc).__name__}: {exc}"}
    base["generation"] = gen_block

    write_json(OUT, base)
    print(json.dumps(base, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())