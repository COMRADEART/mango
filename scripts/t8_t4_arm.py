"""T8.15 — T4 tool-integration secondary arm for a capacity candidate.

Runs the FROZEN mango-tool-eval-v1 suite with a candidate base model
through the existing JSON tool-call protocol loop (tools are NOT altered):
  - notool arm: fresh generation, tools disabled (no frozen-prediction
    reuse — that would import the 1.7B's answers)
  - tool arm: tools enabled, protocol loop, audit-logged

Outputs under evaluations/t8/runs/<label>/t4_{notool,tool}/.
Compares tool routing / tool-use success / math delta vs the model-only
arm. Also verifies T4 false-PASS safety stays intact (verifier selftest).

Usage:
  python scripts/t8_t4_arm.py --model ID --label slug [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

SUITE = REPO / "evaluations" / "tool-suite" / "v1"
RUNS = REPO / "evaluations" / "t8" / "runs"
GENERATION = {"seed": 42, "do_sample": False, "max_new_tokens": 1024}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-seq-tokens", type=int, default=8192)
    ap.add_argument("--max-new-tokens", type=int, default=1024,
                    help="1024 default; long-CoT models (phi4-mini-"
                    "reasoning) need 2048 — recorded as a T8.7 exception")
    args = ap.parse_args()

    from sciencemath.tools.benchmark import (load_suite, run_tool_enabled,
                                             router_metrics, summarize,
                                             verifier_selftest)

    rows = load_suite(SUITE)
    if args.limit:
        rows = rows[:args.limit]
    out_root = RUNS / args.label
    out_root.mkdir(parents=True, exist_ok=True)

    from sciencemath.evaluation.model_loader import load_model_safely
    tok, model, load_info = load_model_safely(args.model)
    if not load_info.get("ok"):
        print("MODEL LOAD FAILED:", load_info["error"])
        return 1

    import torch

    res = {}
    for arm, enabled in (("t4_notool", False), ("t4_tool", True)):
        res[arm] = run_tool_enabled(
            model=model, tokenizer=tok, rows=rows,
            out_dir=out_root / arm,
            generation=GENERATION, model_id=args.model,
            tools_enabled=enabled, max_new_tokens=args.max_new_tokens,
            max_seq_tokens=args.max_seq_tokens, enable_thinking=False)
        print(arm, res[arm]["status"], res[arm]["questions_run"],
              "questions")
        torch.cuda.empty_cache()

    del model
    import gc
    gc.collect()
    torch.cuda.empty_cache()

    summary = {
        "label": args.label, "model": args.model,
        "suite": "mango-tool-eval-v1",
        "max_new_tokens": args.max_new_tokens,
        "max_new_tokens_exception": (
            args.max_new_tokens != 1024),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "verifier_selftest": verifier_selftest(load_suite(SUITE)),
        "router_metrics": router_metrics(load_suite(SUITE)),
        "comparison": summarize(out_root / "t4_notool" / "predictions.jsonl",
                                out_root / "t4_tool" / "predictions.jsonl"),
        "arms": {k: {"status": v["status"],
                     "questions_run": v["questions_run"]}
                 for k, v in res.items()},
    }
    (out_root / "t4_arm_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8")
    comp = summary["comparison"]
    print(json.dumps({
        "no_tool_accuracy": comp.get("no_tool_accuracy"),
        "tool_accuracy": comp.get("tool_enabled_accuracy"),
        "delta": comp.get("delta"),
        "tool_usage": comp.get("tool_usage"),
        "verifier_selftest_ok": summary["verifier_selftest"].get("ok",
                                                                 None),
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())