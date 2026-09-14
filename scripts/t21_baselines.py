"""T21.40-T21.42 baselines for the general-knowledge RAG milestone.

- **T21.40 model-only baseline**: Qwen3-4B-Instruct-2507 (cached locally),
  retrieval DISABLED — every question goes straight to the model with no
  corpus, no citations, no gates. Runs on a deterministic recorded subset
  (stratified across the knowledge / abstention / adversarial suites) and
  grades with the same mechanical substring checks as the main runner.
  The point of the baseline is to record, not to pass: absent-entity
  questions answered from model memory are counted as
  model_memory_backfill_events, the failure mode T21.21 forbids in the
  runtime.

- **T21.41 simple BM25 baseline**: retrieval-only ranking with plain BM25
  (no coverage-primary rerank, no dedup beyond exact chunk, no gates) over
  the mango-general-retrieval-v1 final split, for apples-to-apples
  recall/MRR/nDCG comparison against the runtime.

- **T21.42 SCIENCE_RAG non-regression** is asserted separately by running
  the frozen T5R protection tests (tests/test_rag_t5r.py) and the registry
  consistency tests; see evaluations/t21/science_rag_regression.json
  (written by scripts/t21_final_audit.py callers or the protection step).

Deterministic; local GPU only; no network, no training, no paid compute.
Output: evaluations/t21/baselines.json.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402

SUITES_DIR = ROOT / "evaluations" / "t21" / "suites"
OUT_PATH = ROOT / "evaluations" / "t21" / "baselines.json"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
SEED = 20260914

# Deterministic stratified subset for the model-only baseline: the first N
# rows of each named category in positional (frozen) order.
SUBSET_SPEC = {
    "mango-general-knowledge-rag-v1": 12,
    "mango-general-abstention-v1": 12,
    "mango-general-adversarial-v1": 12,
}


def load_rows(suite: str, split: str) -> list[dict]:
    path = SUITES_DIR / suite / f"{split}.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pick_subset(suite: str) -> list[dict]:
    rows = load_rows(suite, "final")
    per_cat: dict[str, list[dict]] = {}
    for row in rows:
        per_cat.setdefault(row["category"], []).append(row)
    n = SUBSET_SPEC[suite]
    cats = sorted(per_cat)
    picked: list[dict] = []
    i = 0
    while len(picked) < n and any(per_cat[c] for c in cats):
        c = cats[i % len(cats)]
        if per_cat[c]:
            picked.append(per_cat[c].pop(0))
        i += 1
    return picked


# ---------------------------------------------------------------------------
# T21.40 model-only baseline
# ---------------------------------------------------------------------------
def run_model_only(subsets: dict[str, list[dict]]) -> dict:
    from sciencemath.evaluation.model_loader import load_model_safely
    from sciencemath.executive.llm import call_model

    tok, model, info = load_model_safely(MODEL)
    if not info["ok"]:
        return {"ok": False, "error": info["error"]}

    records: list[dict] = []
    vram_peak = 0
    t0 = time.time()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:  # noqa: BLE001
        torch = None  # type: ignore[assignment]

    for suite, rows in sorted(subsets.items()):
        for row in rows:
            gold = row["gold"]
            prompt = (f"Question: {row['request']['query']}\n"
                      f"Answer the question directly.")
            try:
                text, _, _ = call_model(
                    model, tok, prompt,
                    {"seed": SEED, "max_new_tokens": 128})
            except Exception as e:  # noqa: BLE001
                text = f"MODEL_CALL_FAILED: {e}"
            lowered = text.lower()
            expect_answer = gold["expect_status"] == "ANSWER"
            contains_ok = all(
                s in lowered for s in gold.get("expect_answer_contains", []))
            correct = expect_answer and contains_ok
            # model answered a should-abstain question from memory, or
            # asserted a source it was never given: the exact failure mode
            # the T21.21 firewall forbids in the runtime.
            backfill = (not expect_answer and bool(text.strip())
                        and "MODEL_CALL_FAILED" not in text)
            fake_citation = bool(re.search(r"\[\w?\d+", text))
            rec = {
                "suite": suite, "case_id": row["case_id"],
                "category": row["category"],
                "query": row["request"]["query"],
                "expect_status": gold["expect_status"],
                "expect_answer_contains":
                    gold.get("expect_answer_contains", []),
                "response": text[:600],
                "answered_from_memory": backfill,
                "fabricated_citation": fake_citation,
                "correct": correct,
            }
            records.append(rec)
            print(f"[model-only] {row['case_id']} correct={correct} "
                  f"backfill={backfill}")
        if torch is not None and torch.cuda.is_available():
            vram_peak = max(vram_peak,
                            int(torch.cuda.max_memory_allocated()))

    by_suite: dict[str, dict] = {}
    for suite in sorted(subsets):
        recs = [r for r in records if r["suite"] == suite]
        answered = [r for r in recs if r["response"].strip()
                    and "MODEL_CALL_FAILED" not in r["response"]]
        by_suite[suite] = {
            "n": len(recs),
            "answer_accuracy_on_answer_rows": round(sum(
                1 for r in recs if r["correct"]) /
                max(1, sum(1 for r in recs
                           if r["expect_status"] == "ANSWER")), 4),
            "abstention_rate_on_should_abstain_rows": round(sum(
                1 for r in recs if r["expect_status"] != "ANSWER"
                and not r["answered_from_memory"]) /
                max(1, sum(1 for r in recs
                           if r["expect_status"] != "ANSWER")), 4),
            "model_memory_backfill_events": sum(
                1 for r in recs if r["answered_from_memory"]),
            "fabricated_citation_events": sum(
                1 for r in recs if r["fabricated_citation"]),
            "n_answered": len(answered),
        }
    return {
        "ok": True,
        "model": {"id": MODEL, "mode": "response-only, retrieval disabled",
                  "seed": SEED},
        "subset_sizes": {s: len(r) for s, r in subsets.items()},
        "by_suite": by_suite,
        "records": records,
        "wall_seconds": round(time.time() - t0, 1),
        "vram_peak_bytes": vram_peak,
    }


# ---------------------------------------------------------------------------
# T21.41 simple BM25 baseline (no rerank, no gates)
# ---------------------------------------------------------------------------
def run_bm25_baseline(corpus) -> dict:
    rows = load_rows("mango-general-retrieval-v1", "final")
    ranks: list[int] = []
    for row in rows:
        gold_id = row["gold"]["gold_chunk_id"]
        # full-depth BM25 ranking (chunk_id asc on ties) — no rerank, no dedup
        ordered = corpus.index.search(row["request"]["query"],
                                      top_k=corpus.index.n_docs)
        rank = 0
        for i, (chunk_id, _score) in enumerate(ordered, start=1):
            if chunk_id == gold_id:
                rank = i
                break
        ranks.append(rank)

    def recall(k: int) -> float:
        return sum(1 for r in ranks if 0 < r <= k) / len(ranks)

    mrr = sum(1.0 / r for r in ranks if r) / len(ranks)
    ndcg = sum(1.0 / math.log2(r + 1) for r in ranks if 0 < r <= 5) \
        / len(ranks)
    return {
        "benchmark": "mango-general-retrieval-v1",
        "split": "final",
        "mode": "plain BM25, no coverage rerank, no dedup, no gates",
        "n": len(rows),
        "recall_at_5": round(recall(5), 4),
        "recall_at_10": round(recall(10), 4),
        "mrr": round(mrr, 4),
        "ndcg_at_5": round(ndcg, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-model", action="store_true",
                    help="record the BM25 baseline only (no GPU run)")
    args = ap.parse_args()

    out: dict = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "corpus_manifest_checksum": load_corpus().manifest.get(
            "manifest_checksum"),
    }

    corpus = load_corpus()
    out["bm25_baseline"] = run_bm25_baseline(corpus)
    print(json.dumps(out["bm25_baseline"], indent=2))

    if not args.skip_model:
        subsets = {s: pick_subset(s) for s in sorted(SUBSET_SPEC)}
        out["model_only_baseline"] = run_model_only(subsets)
        if not out["model_only_baseline"].get("ok"):
            print("MODEL LOAD FAILED:",
                  out["model_only_baseline"].get("error"))
            OUT_PATH.write_text(json.dumps(out, indent=2) + "\n",
                                encoding="utf-8")
            return 2

    OUT_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())