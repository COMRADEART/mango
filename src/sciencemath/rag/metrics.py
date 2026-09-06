"""metrics — retrieval metrics (T5.18).

Measured SEPARATELY from answer generation quality (T5.18 requirement:
never hide retrieval quality inside final answer accuracy):
  Recall@1 / Recall@3 / Recall@5, MRR, nDCG@k,
  domain-routing accuracy, irrelevant-chunk rate.

Ground truth shape per query (from the frozen RAG eval suite):
  {"query", "domain": expected canonical domain,
   "relevant": [chunk_id, ...]  (any of these counts as relevant),
   "graded": {chunk_id: 0..3}   (optional graded relevance for nDCG),
   "irrelevant_ids": [chunk_id, ...] (distractors that must NOT surface)}
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def _rank_of(retrieved: list[str], relevant: set[str]) -> int | None:
    for i, cid in enumerate(retrieved, 1):
        if cid in relevant:
            return i
    return None


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """1 if ANY relevant chunk appears in the top-k (T5 treats a hit as
    binary; graded relevance is nDCG's job)."""
    return float(any(cid in relevant for cid in retrieved[:k]))


def mrr(retrieved: list[str], relevant: set[str]) -> float:
    rank = _rank_of(retrieved, relevant)
    return 1.0 / rank if rank else 0.0


def ndcg_at_k(retrieved: list[str], graded: dict[str, float], k: int) -> float:
    """nDCG@k with graded relevance; binary relevance -> standard nDCG."""
    if not graded:
        return 0.0
    dcg = sum((2 ** graded.get(cid, 0) - 1) / math.log2(i + 2)
              for i, cid in enumerate(retrieved[:k]) if graded.get(cid, 0) > 0)
    ideal = sorted(graded.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2)
               for i, g in enumerate(ideal) if g > 0)
    return dcg / idcg if idcg > 0 else 0.0


@dataclass
class RetrievalMetrics:
    n_queries: int = 0
    recall_at_1: float = 0.0
    recall_at_3: float = 0.0
    recall_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    domain_routing_accuracy: float = 0.0
    irrelevant_chunk_rate: float = 0.0   # distractors in top-5 / 5 per query
    per_domain: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "n_queries": self.n_queries,
            "recall_at_1": round(self.recall_at_1, 4),
            "recall_at_3": round(self.recall_at_3, 4),
            "recall_at_5": round(self.recall_at_5, 4),
            "mrr": round(self.mrr, 4),
            "ndcg_at_5": round(self.ndcg_at_5, 4),
            "domain_routing_accuracy": round(self.domain_routing_accuracy, 4),
            "irrelevant_chunk_rate": round(self.irrelevant_chunk_rate, 4),
            "per_domain": self.per_domain,
        }


def evaluate_retrieval(results: list[dict]) -> RetrievalMetrics:
    """Aggregate metrics over per-query records:
    {"query", "retrieved": [chunk_id...] (rank-ordered),
     "expected_domain", "predicted_domain",
     "relevant": [...], "graded": {...}, "irrelevant_ids": [...]}"""
    n = len(results)
    if n == 0:
        return RetrievalMetrics()
    r1 = r3 = r5 = m = nd = route_ok = irr = 0
    per_domain: dict[str, dict] = {}
    for res in results:
        retrieved = list(res.get("retrieved", []))
        relevant = set(res.get("relevant", []))
        graded = {k: float(v) for k, v in (res.get("graded") or {}).items()}
        if not graded:
            graded = {cid: 1.0 for cid in relevant}
        r1 += recall_at_k(retrieved, relevant, 1)
        r3 += recall_at_k(retrieved, relevant, 3)
        r5 += recall_at_k(retrieved, relevant, 5)
        m += mrr(retrieved, relevant)
        nd += ndcg_at_k(retrieved, graded, 5)
        ok = res.get("expected_domain") == res.get("predicted_domain")
        route_ok += ok
        top5 = retrieved[:5]
        irr += sum(1 for cid in top5
                   if cid in set(res.get("irrelevant_ids", [])))
        d = res.get("expected_domain", "?")
        acc = per_domain.setdefault(d, {"n": 0, "hits": 0, "route_ok": 0})
        acc["n"] += 1
        acc["hits"] += recall_at_k(retrieved, relevant, 5)
        acc["route_ok"] += int(ok)
    metrics = RetrievalMetrics(
        n_queries=n,
        recall_at_1=r1 / n, recall_at_3=r3 / n, recall_at_5=r5 / n,
        mrr=m / n, ndcg_at_5=nd / n,
        domain_routing_accuracy=route_ok / n,
        irrelevant_chunk_rate=irr / (n * 5) if n else 0.0)
    metrics.per_domain = {
        d: {"n": v["n"],
            "recall_at_5": round(v["hits"] / v["n"], 4),
            "routing_accuracy": round(v["route_ok"] / v["n"], 4)}
        for d, v in per_domain.items()}
    return metrics