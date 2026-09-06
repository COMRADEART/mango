"""Counterfactual evaluation for one checkpoint (T6.17).

Runs the frozen counterfactual suite (evaluations/t6/counterfactual/v1,
145 perturbation variants derived from mango-eval-core-v1 parents) and
measures whether the model's answer behaves as the perturbation demands:

  ANSWER_CHANGES      — variant answered with its recomputed gold answer
                        (recomputed with the live T4 tool layer at suite
                        build time) AND different from the parent answer
  ANSWER_UNCHANGED    — variant answered with the parent's gold answer
                        (distractor ignored, unit not swapped)
  ANSWER_INSUFFICIENT — the model declines / signals insufficiency
                        instead of inventing an answer

Outputs evaluations/t6/counterfactual/results/<label>/ :
predictions.jsonl (from the shared runner), metrics.json.

Usage:
  python scripts/run_counterfactual_eval.py --label mango-v0.1 \
      --adapter training/adapters/sciencemath-v0.1-t3
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

from sciencemath.evaluation.extraction import (  # noqa: E402
    answers_match, extract_answer, signals_uncertainty,
)
from sciencemath.evaluation.runner import evaluate_model  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, write_json  # noqa: E402

SUITE = REPO / "evaluations" / "t6" / "counterfactual" / "v1"
RESULTS = REPO / "evaluations" / "t6" / "counterfactual" / "results"
CORE_RESULTS = REPO / "evaluations" / "t6" / "core_results"
MODEL_ID = "Qwen/Qwen3-1.7B"
PARENT_ADAPTER = REPO / "training" / "adapters" / "sciencemath-v0.1-t3"

GENERATION = {"seed": 42, "do_sample": False, "max_new_tokens": 1024}


def score_variants(variants: list[dict], preds: dict[str, dict],
                   parent_ans: dict[str, str | None]) -> list[dict]:
    """Score each variant against its expected counterfactual behavior."""
    scored = []
    for v in variants:
        meta = v["counterfactual"]
        pred = preds.get(v["eval_id"], {})
        extracted = pred.get("extracted_answer")
        raw = pred.get("raw_model_output") or ""
        behavior = meta["expected_behavior"]
        if behavior == "ANSWER_CHANGES":
            correct = (extracted is not None and answers_match(
                str(v["expected_answer"]), extracted))
            changed = (extracted is not None
                       and parent_ans.get(meta["parent_eval_id"]) is not None
                       and not answers_match(
                           str(parent_ans[meta["parent_eval_id"]]),
                           extracted))
            passed = correct and changed
        elif behavior == "ANSWER_UNCHANGED":
            passed = (extracted is not None and answers_match(
                str(v["expected_answer"]), extracted))
        else:   # ANSWER_INSUFFICIENT
            passed = extracted is None or signals_uncertainty(raw)
        scored.append({
            "eval_id": v["eval_id"],
            "parent_eval_id": meta["parent_eval_id"],
            "kind": meta["kind"],
            "expected_behavior": behavior,
            "expected_answer": str(v["expected_answer"]),
            "extracted_answer": extracted,
            "correct": pred.get("correct"),
            "behavior_passed": bool(passed),
        })
    return scored


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--adapter", type=Path, default=None)
    args = ap.parse_args()

    suite = read_jsonl(SUITE / "questions.jsonl")
    variants = [r for r in suite if r.get("counterfactual")]
    if not variants:
        print("no counterfactual variants found — aborting")
        return 2

    out_dir = RESULTS / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    from sciencemath.training.attach import load_base_with_adapter
    tok, model, info = load_base_with_adapter(
        MODEL_ID, str(args.adapter or PARENT_ADAPTER))
    if not info.get("ok"):
        print("model load failed:", info)
        return 1

    print(f"[{args.label}] counterfactual arm: {len(variants)} variants ...",
          flush=True)
    t0 = time.time()
    evaluate_model(
        model_id=MODEL_ID, mode="non_thinking", model_slug=args.label,
        suite_dir=SUITE, out_dir=out_dir, generation=GENERATION,
        model=model, tokenizer=tok, enable_thinking=False)
    print(f"counterfactual arm done in {time.time() - t0:.0f}s", flush=True)

    preds = {p["eval_id"]: p for p in read_jsonl(out_dir / "predictions.jsonl")}

    # parent answers from the checkpoint's closed-book core-eval run
    parent_path = CORE_RESULTS / args.label / "predictions.jsonl"
    parent_ans: dict[str, str | None] = {}
    if parent_path.exists():
        for p in read_jsonl(parent_path):
            parent_ans[p["eval_id"]] = p.get("extracted_answer")

    scored = score_variants(variants, preds, parent_ans)
    write_json(out_dir / "behavior_predictions.jsonl", scored)

    by_kind = defaultdict(list)
    for s in scored:
        by_kind[s["kind"]].append(s)
    metrics = {
        "label": args.label,
        "suite": "mango-counterfactual-v1",
        "n_variants": len(scored),
        "behavior_pass_rate": (
            sum(1 for s in scored if s["behavior_passed"]) / len(scored))
        if scored else None,
        "by_kind": {
            k: {
                "n": len(rs),
                "pass_rate": sum(1 for s in rs
                                 if s["behavior_passed"]) / len(rs),
                "expected_behavior": rs[0]["expected_behavior"],
            }
            for k, rs in sorted(by_kind.items())
        },
    }
    write_json(out_dir / "metrics.json", metrics)
    print(json.dumps(metrics, indent=2, default=str)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())