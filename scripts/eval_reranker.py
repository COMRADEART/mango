"""T5.10 reranker evaluation — measured, not assumed.

Question: does a second-stage reranker actually improve retrieval over
the embedding-only ranking? Arms (all local):

  * none           — embedding-only (the baseline arm)
  * bm25           — deterministic lexical rerank over candidates
  * cross-encoder  — ms-marco-MiniLM-L-6-v2 (skipped if weights are not
                     available; the decision records the skip)

Probes: the frozen suite's retrieval_relevance questions (they carry
supporting_fact) plus a fixed scientific probe set. Ground truth is
CORPUS-REFRESH TOLERANT: a retrieved chunk is relevant iff
claim_support_score(supporting_fact, chunk_text) >= 0.45 — no chunk ids
are frozen, so a corpus rebuild cannot invalidate the eval.

Metrics per arm: Recall@5, MRR, nDCG@5, mean rerank latency.
Decision + rationale -> rag/reranker/reranker_decision.json
(selection rule: mean(recall@5, MRR, nDCG@5); latency tiebreak; a
reranker must BEAT the embedding-only arm to be adopted).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from sciencemath.rag.citations import claim_support_score
from sciencemath.rag.embeddings import (CANDIDATES, SentenceTransformerEmbedder)
from sciencemath.rag.metrics import evaluate_retrieval
from sciencemath.rag.retriever import Retriever, RetrievalConfig, load_corpus
from sciencemath.rag.reranker import (BM25Reranker, CrossEncoderReranker,
                                      IdentityReranker)
from sciencemath.rag.vectorstore import BruteForceVectorStore
from sciencemath.utils.io_utils import write_json

SUPPORT_THRESHOLD = 0.45

# fixed probes: (question, supporting fact). The fact must appear in the
# corpus for the probe to be answerable — grading is support-based.
PROBES = [
    ("What organelle produces ATP in eukaryotic cells?",
     "Mitochondria produce ATP through cellular respiration."),
    ("What is the function of ribosomes?",
     "Ribosomes carry out protein synthesis by translating messenger RNA."),
    ("State Newton's second law of motion.",
     "The acceleration of an object is proportional to the net force and "
     "inversely proportional to its mass: F = ma."),
    ("What causes the seasons on Earth?",
     "Seasons result from the tilt of Earth's rotational axis relative to "
     "its orbital plane."),
    ("What is the pH scale used for?",
     "The pH scale measures how acidic or basic a solution is; 7 is neutral."),
    ("What happens during photosynthesis?",
     "Plants convert carbon dioxide and water into glucose and oxygen "
     "using energy from sunlight absorbed by chlorophyll."),
    ("What is Ohm's law?",
     "The electric current through a conductor is proportional to the "
     "voltage across it: V = IR."),
    ("Why do earthquakes occur?",
     "Earthquakes occur when stress along geological faults exceeds the "
     "rock strength, causing sudden slip."),
    ("What is a covalent bond?",
     "A covalent bond forms when two atoms share one or more pairs of "
     "electrons."),
    ("What causes ocean tides?",
     "Ocean tides are caused mainly by the gravitational pull of the Moon "
     "and the Sun on Earth's oceans."),
    ("What is radioactive decay?",
     "Radioactive decay is the spontaneous transformation of an unstable "
     "nucleus into a more stable one, emitting radiation."),
    ("What is the water cycle?",
     "The water cycle describes evaporation, condensation into clouds, "
     "precipitation, and collection in oceans and rivers."),
]


def load_support_probes(suite_dir: Path) -> list[tuple[str, str]]:
    """Frozen retrieval_relevance questions (they carry supporting_fact)."""
    out = []
    for line in (suite_dir / "questions.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        if q.get("category") == "retrieval_relevance" and \
                q.get("supporting_fact"):
            out.append((q["question"], q["supporting_fact"]))
    return out


def main() -> int:
    corpus_dir = ROOT / "rag" / "corpus"
    if not (corpus_dir / "corpus_manifest.json").exists():
        print("corpus not built yet — run scripts/ingest_wikipedia.py first",
              file=sys.stderr)
        return 1
    chunk_by_id, manifest = load_corpus(corpus_dir)
    print(f"corpus: {len(chunk_by_id)} chunks "
          f"({manifest.get('corpus_version')})", file=sys.stderr)

    decision = json.loads((ROOT / "rag" / "embeddings" /
                           "embedding_decision.json").read_text(
        encoding="utf-8"))
    winner = next(r for r in decision["results"] if "error" not in r
                  and r["key"] == decision["winner"])
    spec = CANDIDATES[winner["key"]]
    embedder = SentenceTransformerEmbedder(spec, device="cpu")

    texts = [c["text"] for c in chunk_by_id.values()]
    ids = list(chunk_by_id)
    print(f"embedding {len(texts)} passages ...", file=sys.stderr)
    vecs = embedder.embed_passages(texts)
    store = BruteForceVectorStore(vecs.shape[1])
    store.add(vecs, ids)

    suite_dir = ROOT / "evaluations" / "rag-suite" / "v1"
    probes = PROBES + load_support_probes(suite_dir)
    print(f"{len(probes)} retrieval probes", file=sys.stderr)

    arms: dict[str, object] = {"none": IdentityReranker(),
                               "bm25": BM25Reranker()}
    try:
        arms["cross-encoder"] = CrossEncoderReranker()
    except Exception as exc:  # noqa: BLE001
        print(f"cross-encoder unavailable: {exc}", file=sys.stderr)

    cfg = RetrievalConfig(top_k=10, top_n=5, similarity_threshold=-1.0)
    results: dict[str, dict] = {}
    for name, reranker in arms.items():
        retriever = Retriever(store=store, chunk_by_id=chunk_by_id,
                              embedder=embedder, config=cfg,
                              reranker=reranker)
        rows, latencies = [], []
        for question, fact in probes:
            res = retriever.retrieve(question)
            latencies.append(res.latency_s)
            retrieved = [c["chunk_id"] for c in res.chunks] + \
                [c["chunk_id"] for c in res.rejected]
            relevant = {cid for cid in retrieved
                        if claim_support_score(
                            fact, (chunk_by_id.get(cid) or {})
                            .get("text", "")) >= SUPPORT_THRESHOLD}
            graded = {cid: 3.0 for cid in relevant}
            rows.append({
                "query": question,
                "retrieved": retrieved,
                "expected_domain": res.query_domain,
                "predicted_domain": res.query_domain,
                "relevant": sorted(relevant),
                "graded": graded,
                "irrelevant_ids": [],
            })
        m = evaluate_retrieval(rows)
        results[name] = {
            "arm": name, "reranker": getattr(reranker, "name", name),
            "n_probes": len(probes),
            "recall_at_5": round(m.recall_at_5, 4),
            "mrr": round(m.mrr, 4),
            "ndcg_at_5": round(m.ndcg_at_5, 4),
            "mean_latency_s": round(sum(latencies) / len(latencies), 4),
        }
        print(json.dumps(results[name]), file=sys.stderr)

    # selection: reranking must BEAT the embedding-only arm; otherwise
    # keep "none" (no adopted complexity without measured gain)
    base = results.get("none")
    def quality(r):
        return (r["recall_at_5"] + r["mrr"] + r["ndcg_at_5"]) / 3.0
    best_key, best = max(results.items(), key=lambda kv: quality(kv[1]))
    adopted = best_key if best_key != "none" and \
        quality(best) > quality(base) else "none"
    out = {
        "evaluated_at": time.strftime("%Y-%m-%d"),
        "corpus_version": manifest.get("corpus_version"),
        "embedding_model": spec.model,
        "embedding_revision": decision.get("winner_revision"),
        "n_probes": len(probes),
        "support_threshold": SUPPORT_THRESHOLD,
        "ground_truth": "claim_support_score(supporting_fact, chunk) >= "
                        f"{SUPPORT_THRESHOLD} (corpus-refresh tolerant)",
        "results": results,
        "selection_rule": "mean(recall@5, MRR, nDCG@5); reranker adopted "
                          "only if it beats the embedding-only arm",
        "adopted_reranker": adopted,
    }
    write_json(ROOT / "rag" / "reranker" / "reranker_decision.json", out)
    print(json.dumps(out["results"], indent=2))
    print("adopted reranker:", adopted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())