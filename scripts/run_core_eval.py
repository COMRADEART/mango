"""Evaluate one checkpoint on the frozen mango-eval-core-v1 suite.

Arms (T6.15/T6.16):
  A. closed-book — evaluate_model over all 151 items (caller-provided
     adapter-attached model, non_thinking, greedy; same protocol as the
     T3/T5 evaluations).
  B. routing metrics — deterministic route classifier over every item,
     scored against each item's frozen routing_label (T6.15).
  C. RAG arm — answer_question_t5r on RETRIEVAL/BOTH items with citation
     integrity checks (T5R firewall semantics preserved).

Outputs evaluations/t6/core_results/<label>/ : predictions.jsonl,
routing_predictions.jsonl, rag_predictions.jsonl, metrics.json (with the
nine pre-declared gate dimensions + Pareto capability vector).

Usage:
  python scripts/run_core_eval.py --label mango-v0.1 \
      --adapter training/adapters/sciencemath-v0.1-t3 [--skip-rag]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.curriculum.eval_core import routing_label  # noqa: E402
from sciencemath.curriculum.failure_memory import (  # noqa: E402
    append_failures, classify_error_type, make_record,
)
from sciencemath.curriculum.routing import routing_metrics  # noqa: E402
from sciencemath.evaluation.runner import evaluate_model  # noqa: E402
from sciencemath.rag.pipeline import answer_question_t5r  # noqa: E402
from sciencemath.rag.route import classify_route  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, write_json  # noqa: E402

SUITE = REPO / "evaluations" / "eval-core" / "v1"
RESULTS = REPO / "evaluations" / "t6" / "core_results"
FAILURES = REPO / "training" / "curriculum" / "failure_memory.jsonl"
MODEL_ID = "Qwen/Qwen3-1.7B"
PARENT_ADAPTER = REPO / "training" / "adapters" / "sciencemath-v0.1-t3"

GENERATION = {"seed": 42, "do_sample": False, "max_new_tokens": 1024}

MATH_CATEGORIES = {"math_foundation", "algebra", "geometry", "trig",
                   "calculus", "probability_statistics"}
SCIENCE_CATEGORIES = {"physics", "chemistry", "biology", "earth_space",
                      "scientific_reasoning"}

ROUTE_TO_LABEL = {"MATH": "TOOL", "MIXED": "BOTH", "SCIENCE": "RETRIEVAL",
                  "GENERAL": "NONE"}


def _acc(records: list[dict]) -> float | None:
    if not records:
        return None
    return sum(1 for r in records if r["correct"]) / len(records)


def _macro(records: list[dict], keys) -> float | None:
    vals = []
    by = defaultdict(list)
    for r in records:
        key = None
        for k, pick in keys:
            if pick(r):
                key = k
                break
        if key:
            by[key].append(r)
    for key, rs in by.items():
        a = _acc(rs)
        if a is not None:
            vals.append(a)
    return sum(vals) / len(vals) if vals else None


def compute_metrics(predictions: list[dict], routing_pred: list[dict],
                    rag_pred: list[dict]) -> dict:
    graded = [r for r in predictions if r["correct"] is not None]
    overall = _acc(graded)
    math_macro = _macro(graded, [
        ("math", lambda r: r["category"] in MATH_CATEGORIES)])
    science_macro = _macro(graded, [
        ("sci", lambda r: r["category"] in SCIENCE_CATEGORIES)])
    inter = [r for r in graded if r["category"] == "interdisciplinary"]
    cross_domain = _acc(inter)
    comp = [r for r in graded if r.get("generalization_split")
            == "COMPOSITIONAL"]
    oot = [r for r in graded if r.get("generalization_split")
           == "OUT_OF_TEMPLATE"]
    cd_split = [r for r in graded if r.get("generalization_split")
                == "CROSS_DOMAIN"]
    comps = {"COMPOSITIONAL": _acc(comp), "OUT_OF_TEMPLATE": _acc(oot),
             "CROSS_DOMAIN": _acc(cd_split)}
    gen_vals = [v for v in comps.values() if v is not None]
    extraction_ok = (sum(1 for r in graded
                         if r["failure"] != "EXTRACTION_FAILURE")
                     / len(graded)) if graded else None
    unc = [r for r in graded if r["category"] == "uncertainty_calibration"]

    rm = routing_metrics(routing_pred)
    rag_acc = _acc([r for r in rag_pred if r["correct"] is not None]) \
        if rag_pred else None
    fab = sum(1 for r in rag_pred if r.get("citations_fabricated"))

    metrics = {
        "overall": overall,
        "math_macro": math_macro,
        "science_macro": science_macro,
        "cross_domain": cross_domain,
        "compositional": comps["COMPOSITIONAL"],
        "tool_routing": (rm["tool_needed_precision"]
                         + rm["tool_needed_recall"]) / 2
        if rm["tool_needed_precision"] is not None else None,
        "retrieval_routing": (rm["retrieval_needed_precision"]
                              + rm["retrieval_needed_recall"]) / 2
        if rm["retrieval_needed_precision"] is not None else None,
        "extraction": extraction_ok,
        "uncertainty": _acc(unc),
        # Pareto / dashboard extras
        "generalization_macro": (sum(gen_vals) / len(gen_vals))
        if gen_vals else None,
        "cross_domain_macro": comps["CROSS_DOMAIN"],
        "splits": comps,
        "routing_details": rm,
        "rag_arm": {"accuracy": rag_acc, "n": len(rag_pred),
                    "fabricated_citations": fab},
        "counts": {"graded": len(graded)},
    }
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--adapter", type=Path, default=None,
                    help="adapter dir; omitted => bare base model")
    ap.add_argument("--skip-rag", action="store_true")
    ap.add_argument("--skip-closed-book", action="store_true")
    args = ap.parse_args()

    out_dir = RESULTS / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    suite = read_jsonl(SUITE / "questions.jsonl")
    by_id = {r["eval_id"]: r for r in suite}

    # ---- arm B: routing metrics (deterministic, no GPU) -----------------
    routing_pred = []
    for item in suite:
        rl = item.get("routing_label") or routing_label(item)
        if rl == "INSUFFICIENT_INFO":
            continue   # measured by the uncertainty dimension, not routing
        route = classify_route(item["question"])["route"]
        label = ROUTE_TO_LABEL.get(route, "NONE")
        routing_pred.append({
            "routing_label": rl,
            "invoked_tool": label in ("TOOL", "BOTH"),
            "invoked_retrieval": label in ("RETRIEVAL", "BOTH"),
            "signalled_insufficient": False,
        })
    rm = routing_metrics(routing_pred)

    # ---- single model load shared by arms A and C (6 GB VRAM) -----------
    model = tok = None
    if not (args.skip_closed_book and args.skip_rag):
        from sciencemath.training.attach import load_base_with_adapter
        tok, model, info = load_base_with_adapter(
            MODEL_ID, str(args.adapter or PARENT_ADAPTER))
        if not info.get("ok"):
            print("model load failed:", info)
            return 1

    # ---- arm A: closed-book ---------------------------------------------
    predictions_path = out_dir / "predictions.jsonl"
    if not args.skip_closed_book:
        print(f"[{args.label}] closed-book arm: {len(suite)} questions ...",
              flush=True)
        t0 = time.time()
        summary = evaluate_model(
            model_id=MODEL_ID, mode="non_thinking", model_slug=args.label,
            suite_dir=SUITE, out_dir=out_dir, generation=GENERATION,
            model=model, tokenizer=tok, enable_thinking=False)
        print(f"closed-book done in {time.time() - t0:.0f}s "
              f"({summary.get('status')})", flush=True)

    predictions = read_jsonl(predictions_path) if predictions_path.exists() \
        else []
    for p in predictions:
        item = by_id.get(p["eval_id"])
        if item:
            p["generalization_split"] = item["generalization_split"]
            p["routing_label"] = item.get("routing_label") \
                or routing_label(item)
            p["capability_track"] = item["capability_track"]
            p["family"] = item.get("family")
            p["requires_math_tool"] = item["requires_math_tool"]
            p["requires_retrieval"] = item["requires_retrieval"]

    # ---- arm C: RAG -------------------------------------------------------
    rag_pred = []
    if not args.skip_rag:
        sys.path.insert(0, str(REPO / "scripts"))
        from run_rag_eval_t5r import build_retriever
        retriever = build_retriever()
        rag_items = [it for it in suite
                     if (it.get("routing_label")
                         or routing_label(it)) in ("RETRIEVAL", "BOTH")]
        print(f"[{args.label}] RAG arm: {len(rag_items)} questions ...",
              flush=True)
        t0 = time.time()
        for item in rag_items:
            ans = answer_question_t5r(
                model=model, tokenizer=tok, question=item["question"],
                question_id=item["eval_id"], retriever=retriever,
                generation=GENERATION)
            rag_pred.append({
                "eval_id": item["eval_id"],
                "routing_label": item.get("routing_label"),
                "retrieval_used": ans.retrieval_used,
                "raw_model_output": ans.raw_model_output,
                "answer_with_sources": ans.answer_with_sources,
                "chunk_ids_supplied": ans.to_dict()["chunk_ids_supplied"],
                "invalid_refs": ans.invalid_refs,
                "latency_s": ans.latency_s,
                "error": ans.error,
                "expected_answer": item["expected_answer"],
                "answer_type": item["answer_type"],
                "choices": item.get("choices"),
                "category": item["category"],
            })
        print(f"RAG arm done in {time.time() - t0:.0f}s", flush=True)
        _score_rag(rag_pred)

    # ---- failure memory (T6.19) -------------------------------------------
    from sciencemath.curriculum.capabilities import family_of
    failures = []
    for p in predictions:
        if p["correct"] is False:
            track = p.get("capability_track", "general")
            try:
                domain = family_of(track) if track else "general"
            except KeyError:
                domain = "general"
            failures.append(make_record(
                problem_id=p["eval_id"], suite="mango-eval-core-v1",
                domain=domain,
                capability_track=track,
                tool_needed=bool(p.get("requires_math_tool")),
                retrieval_needed=bool(p.get("requires_retrieval")),
                expected_answer=str(p.get("expected_answer")),
                actual_wrong_answer=p.get("extracted_answer"),
                checkpoint=args.label, run_record={
                    k: p.get(k) for k in
                    ("raw_model_output", "extracted_answer", "failure",
                     "error", "evaluation_method")},
                verification_evidence=(
                    f"closed-book predictions.jsonl row {p['eval_id']} "
                    f"(correct=false, expected="
                    f"{p.get('expected_answer')}, extracted="
                    f"{p.get('extracted_answer')})")))
    if failures:
        n = append_failures(FAILURES, failures)
        print(f"failure memory: appended {n} records")

    metrics = compute_metrics(predictions, routing_pred, rag_pred)
    write_json(out_dir / "metrics.json", {
        "label": args.label,
        "adapter": str(args.adapter or PARENT_ADAPTER),
        "suite": "mango-eval-core-v1",
        "metrics": metrics,
    })
    write_json(out_dir / "rag_predictions.jsonl", rag_pred)
    write_json(out_dir / "routing_predictions.jsonl", routing_pred)
    print(json.dumps(metrics, indent=2, default=str)[:2000])
    return 0


def _score_rag(rag_pred: list[dict]) -> None:
    from sciencemath.evaluation.extraction import answers_match, extract_answer
    for r in rag_pred:
        extracted = extract_answer(r["raw_model_output"] or "",
                                   r["answer_type"], r.get("choices"))
        r["extracted_answer"] = extracted
        r["correct"] = bool(answers_match(str(r["expected_answer"]),
                                          extracted or "")) \
            if extracted is not None else False
        r["citations_fabricated"] = bool(r["invalid_refs"])
        r["evaluation_method"] = "rag_arm"


if __name__ == "__main__":
    raise SystemExit(main())