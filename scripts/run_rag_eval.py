"""T5.17-T5.21 RAG evaluation runner over the frozen mango-rag-eval-v1 suite.

Arms (all frozen suite, matched generation settings):
  routing    classify_route over every question -> routing accuracy +
             confusion (vs expected_route on domain_routing questions)
  retrieval  retrieval metrics for questions with corpus-tolerant ground
             truth (supporting_fact / expected_domain) — Recall@1/3/5,
             MRR, nDCG@5, domain-routing accuracy, irrelevant-chunk rate
  norag      generation WITHOUT retrieval (same generation settings, same
             tool protocol for MATH/MIXED — only retrieval is removed)
  rag        full retrieval-augmented generation + evidence contract +
             citation verification (T5.20)

T5.18: retrieval metrics are computed SEPARATELY from answer accuracy.
T5.19: comparison.json reports absolute pp deltas (rag vs norag).
T5.22: the runner records retrieval_used per question — MATH-routed
questions MUST show retrieval_used=false.

Usage:
  python scripts/run_rag_eval.py --arms routing,retrieval,norag,rag
  python scripts/run_rag_eval.py --arms rag --device cuda   # resume-safe
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.evaluation.extraction import (answers_match, extract_answer,
                                               signals_uncertainty,
                                               strip_think_block)
from sciencemath.evaluation.metrics import compute_metrics
from sciencemath.rag.citations import claim_support_score, verify_answer_citations
from sciencemath.rag.embeddings import CANDIDATES, SentenceTransformerEmbedder
from sciencemath.rag.metrics import evaluate_retrieval
from sciencemath.rag.pipeline import GENERAL_EVAL_INSTRUCTION
from sciencemath.rag.retriever import Retriever, RetrievalConfig, load_corpus
from sciencemath.rag.route import classify_route
from sciencemath.rag.vectorstore import BruteForceVectorStore
from sciencemath.tools.benchmark import TOOL_PROTOCOL_INSTRUCTION
from sciencemath.utils.io_utils import read_jsonl, write_json

SUITE_DIR = ROOT / "evaluations" / "rag-suite" / "v1"
OUT_DIR = ROOT / "evaluations" / "rag-results" / "v1"
SUPPORT_THRESHOLD = 0.45

GENERATION = {"seed": 42, "do_sample": False, "max_new_tokens": 1024}
GEN_ELIGIBLE_CATEGORIES = {
    # retrieval_relevance is deliberately EXCLUDED: the frozen suite
    # defines it as a retrieval-only probe (ground truth = supporting
    # fact, graded by the retrieval arm); it carries no expected_answer,
    # so answer-accuracy scoring would be undefined for it.
    "factual_science_qa", "multi_hop_science_qa",
    "quantitative_science", "insufficient_evidence", "distractor_retrieval",
    "conflicting_evidence", "source_attribution", "mixed_math_science",
}


def load_suite() -> list[dict]:
    return [json.loads(l) for l in
            (SUITE_DIR / "questions.jsonl").read_text(encoding="utf-8")
            .splitlines() if l.strip()]


def verify_suite_integrity() -> None:
    """Frozen-suite tamper check: per-line sha256 against checksum.json."""
    import hashlib
    checksums = json.loads((SUITE_DIR / "checksum.json").read_text(
        encoding="utf-8"))
    for line in (SUITE_DIR / "questions.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        eid = json.loads(line)["eval_id"]
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        assert checksums.get(eid) == digest, f"suite tampered: {eid}"
    print(f"suite integrity OK ({len(checksums)} questions)", file=sys.stderr)


def build_retriever() -> tuple[Retriever, dict]:
    corpus_dir = ROOT / "rag" / "corpus"
    chunk_by_id, manifest = load_corpus(corpus_dir)
    decision = json.loads((ROOT / "rag" / "embeddings" /
                           "embedding_decision.json").read_text(encoding="utf-8"))
    spec = CANDIDATES[decision["winner"]]
    embedder = SentenceTransformerEmbedder(spec, device="cpu")
    texts = [c["text"] for c in chunk_by_id.values()]
    vecs = embedder.embed_passages(texts)
    store = BruteForceVectorStore(vecs.shape[1])
    store.add(vecs, list(chunk_by_id))
    reranker_decision = {}
    rd_path = ROOT / "rag" / "reranker" / "reranker_decision.json"
    if rd_path.exists():
        reranker_decision = json.loads(rd_path.read_text(encoding="utf-8"))
    adopted = reranker_decision.get("adopted_reranker", "none")
    reranker = None
    if adopted == "bm25":
        from sciencemath.rag.reranker import BM25Reranker
        reranker = BM25Reranker()
    elif adopted == "cross-encoder":
        from sciencemath.rag.reranker import CrossEncoderReranker
        reranker = CrossEncoderReranker()
    cfg = RetrievalConfig()
    retriever = Retriever(store=store, chunk_by_id=chunk_by_id,
                          embedder=embedder, config=cfg, reranker=reranker)
    return retriever, manifest


# ---------------------------------------------------------------------------
# arm: routing
# ---------------------------------------------------------------------------

def run_routing_arm() -> dict:
    rows = load_suite()
    confusion: dict[str, dict[str, int]] = {}
    n_expected = n_ok = 0
    per_route = Counter()
    for r in rows:
        c = classify_route(r["question"])
        pred, exp = c["route"], r.get("expected_route")
        per_route[pred] += 1
        confusion.setdefault(exp or "?", {}).setdefault(pred, 0)
        confusion[exp or "?"][pred] += 1
        if exp:
            n_expected += 1
            n_ok += pred == exp
    metrics = {
        "n_questions": len(rows),
        "n_with_expected_route": n_expected,
        "routing_accuracy": round(n_ok / n_expected, 4) if n_expected else None,
        "route_distribution": dict(per_route),
        "confusion": confusion,
        "router": "sciencemath.rag.route.classify_route (rules, frozen T4 "
                  "route_question underneath)",
    }
    write_json(OUT_DIR / "routing_metrics.json", metrics)
    print(json.dumps(metrics, indent=2))
    return metrics


# ---------------------------------------------------------------------------
# arm: retrieval (corpus-refresh-tolerant ground truth)
# ---------------------------------------------------------------------------

def retrieval_rows(rows: list[dict], retriever: Retriever) -> list[dict]:
    out = []
    for r in rows:
        if not (r.get("supporting_fact") or r.get("expected_domain")):
            continue
        if r["category"] == "domain_routing":
            continue  # routing questions are graded in the routing arm
        res = retriever.retrieve(r["question"])
        retrieved = [c["chunk_id"] for c in res.chunks] + \
            [c["chunk_id"] for c in res.rejected]
        fact = r.get("supporting_fact")
        if fact:
            relevant = [cid for cid in retrieved
                        if claim_support_score(
                            fact, _text(retriever, cid)) >= SUPPORT_THRESHOLD]
            graded = {cid: 3.0 for cid in relevant}
        else:
            # domain-level grading (weaker, recorded separately)
            relevant = [cid for cid in retrieved
                        if _domain(retriever, cid) == r["expected_domain"]]
            graded = {cid: 1.0 for cid in relevant}
        distractors = []
        if r["category"] == "distractor_retrieval":
            # top-3 chunks from the WRONG domain count as distractor hits
            distractors = [cid for cid in retrieved[:3]
                           if _domain(retriever, cid) not in
                           (None, r["expected_domain"])]
        out.append({
            "eval_id": r["eval_id"], "category": r["category"],
            "query": r["question"], "retrieved": retrieved,
            "expected_domain": r.get("expected_domain"),
            "predicted_domain": res.query_domain,
            "relevant": relevant, "graded": graded,
            "irrelevant_ids": distractors,
            "grading": "supporting_fact" if fact else "domain_match",
            "used_retrieval": res.used_retrieval,
            "latency_s": round(res.latency_s, 4),
        })
    return out


def _text(retriever: Retriever, cid: str) -> str:
    return (retriever.chunks.get(cid) or {}).get("text", "")


def _domain(retriever: Retriever, cid: str) -> str | None:
    return (retriever.chunks.get(cid) or {}).get("domain")


def run_retrieval_arm(retriever: Retriever) -> dict:
    rows = retrieval_rows(load_suite(), retriever)
    by_grading: dict[str, list[dict]] = {}
    for row in rows:
        by_grading.setdefault(row["grading"], []).append(row)
    per_grading = {k: evaluate_retrieval(v).to_dict()
                   for k, v in sorted(by_grading.items())}
    m = evaluate_retrieval(rows)
    metrics = {
        "n_queries": len(rows),
        "metrics": m.to_dict(),
        "per_grading": per_grading,
        "corpus": "rag/corpus (checksum-verified)",
        "note": "supporting_fact grading is corpus-refresh tolerant; "
                "domain grading is a weaker secondary signal",
    }
    write_json(OUT_DIR / "retrieval_metrics.json", metrics)
    print(json.dumps(m.to_dict(), indent=2))
    return metrics


# ---------------------------------------------------------------------------
# arms: norag / rag generation
# ---------------------------------------------------------------------------

def score_question(row: dict, raw: str) -> tuple[bool, str | None, str | None]:
    """Returns (correct, extracted, failure). Deterministic."""
    if row["answer_type"] == "uncertainty":
        visible = strip_think_block(raw or "")
        return signals_uncertainty(visible), visible.strip() or None, \
            None if visible.strip() else "EXTRACTION_FAILURE"
    extracted = extract_answer(raw, row["answer_type"])
    if extracted is None:
        return False, None, "EXTRACTION_FAILURE"
    ok = answers_match(row.get("expected_answer", ""), extracted)
    if row["category"] == "source_attribution" and ok:
        pass  # citation validity is layered on by the caller (T5.20)
    return ok, extracted, None


def run_generation_arm(arm: str, rows: list[dict], retriever, model,
                       tokenizer, registry, tool_logger, audit_logger) -> dict:
    from sciencemath.rag.pipeline import answer_question
    arm_dir = OUT_DIR / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    pred_path = arm_dir / "predictions.jsonl"
    done = {p["eval_id"] for p in read_jsonl(pred_path)} \
        if pred_path.exists() else set()
    preds = list(read_jsonl(pred_path)) if pred_path.exists() else []
    eligible = [r for r in rows if r["category"] in GEN_ELIGIBLE_CATEGORIES]
    gen_rows = []
    for r in eligible:
        if r["eval_id"] in done:
            continue
        route = classify_route(r["question"])
        if arm == "norag":
            # matched settings: same generation, same tool protocol for
            # MATH/MIXED — ONLY retrieval is removed
            parts = [r["question"].strip()]
            if route["route"] in ("MATH", "MIXED"):
                parts.append(TOOL_PROTOCOL_INSTRUCTION)
            parts.append(GENERAL_EVAL_INSTRUCTION)
            override = "\n\n".join(parts)
            ans = answer_question(
                model=model, tokenizer=tokenizer, question=r["question"],
                question_id=r["eval_id"], retriever=None, registry=registry,
                tool_logger=tool_logger, audit_logger=audit_logger,
                generation=GENERATION, prompt_override=override)
        else:
            ans = answer_question(
                model=model, tokenizer=tokenizer, question=r["question"],
                question_id=r["eval_id"], retriever=retriever,
                registry=registry, tool_logger=tool_logger,
                audit_logger=audit_logger, generation=GENERATION)
        correct, extracted, failure = score_question(r, ans.raw_model_output)
        citation_report = None
        if arm == "rag":
            # T5.20: verify EVERY rag answer's citations — including the
            # no-citation case, which must FAIL a citation-required
            # category rather than silently skip verification
            seen = {c["chunk_id"]: c for c in
                    (ans.retrieval.chunks if ans.retrieval else [])}
            rep = verify_answer_citations(ans.raw_model_output,
                                          ans.citations, seen)
            citation_report = {
                "n_citations": len(ans.citations),
                "n_valid": len(rep.valid),
                "n_fabricated": len(rep.fabricated),
                "n_unsupported": len(rep.unsupported),
                "all_valid": rep.all_valid,
            }
            if r["category"] == "source_attribution":
                correct = correct and bool(rep.valid)
        rec = {
            "eval_id": r["eval_id"], "category": r["category"],
            "question": r["question"], "route": ans.route,
            "retrieval_used": bool(
                ans.retrieval and ans.retrieval.used_retrieval),
            "retrieved_chunk_ids": [c["chunk_id"] for c in
                                    (ans.retrieval.chunks
                                     if ans.retrieval else [])],
            "evidence_state": ans.contract.evidence_state,
            "raw_output": ans.raw_model_output,
            "extracted_answer": extracted,
            "expected_answer": r.get("expected_answer"),
            "correct": correct, "failure": failure,
            "citation_report": citation_report,
            "latency_s": round(ans.latency_s, 3),
            "input_tokens": ans.input_tokens, "output_tokens": ans.output_tokens,
            "retrieval_latency_s": round(
                ans.retrieval.latency_s, 4) if ans.retrieval else None,
        }
        gen_rows.append(rec)
        with open(pred_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{arm}] {r['eval_id']} route={ans.route['route']} "
              f"correct={correct}", file=sys.stderr)
    preds = list(read_jsonl(pred_path))
    return summarize_arm(arm, preds)


def summarize_arm(arm: str, preds: list[dict]) -> dict:
    # the predictions file may hold rows from earlier eligibility rules;
    # only score the frozen generation-eligible categories
    preds = [p for p in preds if p["category"] in GEN_ELIGIBLE_CATEGORIES]
    total = len(preds)
    correct = sum(1 for p in preds if p["correct"])
    by_cat: dict[str, list[int]] = {}
    for p in preds:
        by_cat.setdefault(p["category"], []).append(int(p["correct"]))
    per_cat = {c: round(sum(v) / len(v), 4) for c, v in sorted(by_cat.items())}
    unc = [p for p in preds
           if p["category"] in ("insufficient_evidence",
                                "conflicting_evidence")]
    metrics = {
        "arm": arm, "n": total, "correct": correct,
        "accuracy": round(correct / total, 4) if total else None,
        "per_category_accuracy": per_cat,
        "uncertainty_accuracy": round(
            sum(1 for p in unc if p["correct"]) / len(unc), 4)
        if unc else None,
        "retrieval_used_on_math_route": sum(
            1 for p in preds
            if p["route"]["route"] == "MATH" and p["retrieval_used"]),
        "citation_summary": _citation_summary(preds),
        "avg_latency_s": round(sum(p["latency_s"] for p in preds) / total, 3)
        if total else None,
    }
    write_json(OUT_DIR / arm / "metrics.json", metrics)
    return metrics


def _citation_summary(preds: list[dict]) -> dict:
    n_cit = sum((p.get("citation_report") or {}).get("n_citations", 0)
                for p in preds)
    n_fab = sum((p.get("citation_report") or {}).get("n_fabricated", 0)
                for p in preds)
    n_uns = sum((p.get("citation_report") or {}).get("n_unsupported", 0)
                for p in preds)
    return {"n_citations": n_cit, "n_fabricated": n_fab,
            "n_unsupported": n_uns}


def compare_arms() -> dict:
    norag = json.loads((OUT_DIR / "norag" / "metrics.json").read_text(
        encoding="utf-8"))
    rag = json.loads((OUT_DIR / "rag" / "metrics.json").read_text(
        encoding="utf-8"))
    cats = sorted(set(norag["per_category_accuracy"]) |
                  set(rag["per_category_accuracy"]))
    out = {
        "comparison": "T5.19 no-RAG vs RAG (matched generation settings)",
        "suite": "mango-rag-eval-v1",
        "n_norag": norag["n"], "n_rag": rag["n"],
        "accuracy_norag": norag["accuracy"],
        "accuracy_rag": rag["accuracy"],
        "absolute_delta_pp": round(
            100 * (rag["accuracy"] - norag["accuracy"]), 2),
        "per_category_pp_delta": {
            c: round(100 * (rag["per_category_accuracy"].get(c, 0) -
                            norag["per_category_accuracy"].get(c, 0)), 2)
            for c in cats},
        "uncertainty_accuracy_norag": norag["uncertainty_accuracy"],
        "uncertainty_accuracy_rag": rag["uncertainty_accuracy"],
        "t5_22_math_retrieval_violations": rag[
            "retrieval_used_on_math_route"],
        "citations_rag": rag["citation_summary"],
    }
    write_json(OUT_DIR / "comparison.json", out)
    return out


def load_model():
    """Mango-v0.1 = Qwen/Qwen3-1.7B + T3 LoRA adapter (never merged),
    adapter path from configs/training.yaml (same convention as
    scripts/evaluate_tuned.py). Loads via the T2 hardware-safe path."""
    import yaml
    from sciencemath.evaluation.model_loader import load_model_safely
    model_cfg = yaml.safe_load((ROOT / "configs" / "model.yaml").read_text(
        encoding="utf-8"))
    train_cfg = yaml.safe_load((ROOT / "configs" / "training.yaml")
                               .read_text(encoding="utf-8"))
    model_id = model_cfg.get("model_id") or "Qwen/Qwen3-1.7B"
    tok, model, info = load_model_safely(model_id)
    if not info["ok"]:
        raise RuntimeError(f"model load failed: {info['error']}")
    adapter_dir = ROOT / train_cfg["training"]["adapter_output_dir"]
    if adapter_dir.exists():
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(adapter_dir))
        model.eval()
        print(f"adapter attached: {adapter_dir}", file=sys.stderr)
    return model, tok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="routing,retrieval,norag,rag")
    ap.add_argument("--device", default=None, help="model device override")
    args = ap.parse_args()
    arms = {a.strip() for a in args.arms.split(",") if a.strip()}
    verify_suite_integrity()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_suite()

    retriever = None
    if arms & {"retrieval", "rag"}:
        retriever, _manifest = build_retriever()
    results: dict[str, dict] = {}

    if "routing" in arms:
        results["routing"] = run_routing_arm()
    if "retrieval" in arms:
        results["retrieval"] = run_retrieval_arm(retriever)

    if arms & {"norag", "rag"}:
        from sciencemath.tools.router import ToolCallLogger
        model, tokenizer = load_model()
        registry = None
        from sciencemath.tools.router import build_default_registry
        registry = build_default_registry()
        tool_logger = ToolCallLogger(OUT_DIR / "tool_calls.jsonl")
        from sciencemath.rag.audit import RetrievalAuditLogger
        audit = RetrievalAuditLogger(OUT_DIR / "audit.jsonl")
        for arm in ("norag", "rag"):
            if arm in arms:
                results[arm] = run_generation_arm(
                    arm, rows, retriever if arm == "rag" else None,
                    model, tokenizer, registry, tool_logger, audit)
        if "norag" in results and "rag" in results:
            results["comparison"] = compare_arms()
            print(json.dumps(results["comparison"], indent=2))
    write_json(OUT_DIR / "run_summary.json", {
        "ran_arms": sorted(arms), "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results_index": {k: {kk: vv for kk, vv in v.items()
                              if isinstance(vv, (int, float, str, type(None)))}
                          for k, v in results.items()}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())