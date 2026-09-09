"""T9 generalization regression: run ONLY the missing decomposition pass
(T8.8) for the stabilized Qwen3-4B capacity arm.

The fresh stabilized-cap run completed the main 131-question pass
(predictions.jsonl present) but no plans.jsonl / decomposition summary was
saved. This script reuses the frozen run_capacity_eval.py code paths
(PLAN_PROMPT, repair_json, score_plan, sampling profile, greedy-safe
loading) unchanged so the results are directly comparable with the T8S
decomposition reference (subset 24, raw/repaired valid rates).

Usage:
  python scripts/t9_decomp_pass.py --model Qwen/Qwen3-4B-Instruct-2507 \
      --label qwen3-4b-stabilized-cap
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import run_capacity_eval as rce  # frozen runner: identical helpers

OUT = REPO / "evaluations" / "t8" / "runs" / "qwen3-4b-stabilized-cap" / "model"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    ap.add_argument("--decomp-subset", type=int, default=24)
    ap.add_argument("--max-new-tokens", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--thinking", default="off", choices=["off", "on"])
    ap.add_argument("--compute-dtype", default="bfloat16")
    args = ap.parse_args()

    import torch
    from sciencemath.evaluation.model_loader import load_model_safely
    from sciencemath.evaluation.prompts import render_for_model
    from sciencemath.executive.plan import PLAN_SCHEMA_DOC

    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "plans.jsonl").exists():
        print("plans.jsonl already present; nothing to do")
        return 0

    items = rce.load_suite()[: args.decomp_subset]
    torch.manual_seed(args.seed)
    tok, model, load_info = load_model_safely(
        args.model, compute_dtype=args.compute_dtype)
    if not load_info.get("ok"):
        print("MODEL LOAD FAILED:", load_info["error"])
        return 1
    torch.cuda.reset_peak_memory_stats()
    samp = rce.sampling_profile_for(args.model)
    print("sampling profile:", samp)

    plan_records = []
    for i, it in enumerate(items):
        prompt = render_for_model(
            tok, rce.PLAN_PROMPT.format(
                question=it["question"], schema=PLAN_SCHEMA_DOC),
            enable_thinking=(args.thinking == "on"))
        raw, m = rce.generate(model, tok, prompt, args.max_new_tokens, samp)
        plan_raw = rce.repair_json(raw)
        try:
            direct = json.loads((raw or "").strip())
            raw_valid = rce.score_plan(
                direct if isinstance(direct, dict) else None, it)
            raw_valid_raw = raw_valid["schema_valid"]
        except Exception:  # noqa: BLE001
            raw_valid_raw = False
        rep = rce.score_plan(plan_raw, it)
        plan_records.append({
            "eval_id": it["eval_id"], "dimension": rce.dimension_of(it),
            "raw_valid": raw_valid_raw, "repaired_valid": rep["schema_valid"],
            "semantic_ok": rep["semantic_ok"],
            "executable_ok": rep["executable_ok"],
            "raw_extract": (raw or "")[:400],
        })
        print(f"[{i+1}/{len(items)}] {it['eval_id']} raw_valid={raw_valid_raw} "
              f"repaired_valid={rep['schema_valid']}", flush=True)
        # checkpoint after every item
        with open(OUT / "plans.jsonl", "w", encoding="utf-8") as f:
            for r in plan_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = max(1, len(plan_records))
    preds = [json.loads(l) for l in
             (OUT / "predictions.jsonl").read_text(encoding="utf-8")
             .splitlines() if l.strip()]
    decomposition = {
        "subset": len(plan_records),
        "raw_valid_rate": sum(1 for r in plan_records if r["raw_valid"]) / n,
        "repaired_valid_rate": sum(1 for r in plan_records
                                   if r["repaired_valid"]) / n,
        "semantic_valid_rate": sum(1 for r in plan_records
                                   if r["semantic_ok"]) / n,
        "executable_rate": sum(1 for r in plan_records
                               if r["executable_ok"]) / n,
        "unnecessary_plan_rate": (sum(1 for p in preds
                                      if p["spontaneous_plan"])
                                  / max(1, len(preds))),
    }
    (OUT / "decomposition.json").write_text(
        json.dumps(decomposition, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decomposition, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())