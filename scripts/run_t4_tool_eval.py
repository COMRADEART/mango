"""T4.5 run: mango-tool-eval-v1 on the T2 base model (Qwen3-1.7B).

No-tool arm: raw predictions for the 120 reused eval_ids are taken from
the frozen T2 non-thinking run (identical prompt, identical greedy decode
config) and RE-VERIFIED with the T4 verifier; the 30 new mev1-* questions
are generated fresh through the identical harness with tools_enabled=False.
Tool arm: all 150 questions through the JSON tool-call protocol loop.

Artifacts (evaluations/tool-suite/v1/<model_slug>/):
  notool/predictions.jsonl   - no-tool records (reused + generated)
  tool/predictions.jsonl     - tool-enabled records
  tool/tool_calls.jsonl      - mandatory audit log of every tool invocation
  t4_metrics.json            - verifier selftest + router metrics + summary
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SUITE = ROOT / "evaluations" / "tool-suite" / "v1"
BASE_PRED = ROOT / "evaluations" / "base" / "qwen3-1.7b_non_thinking" / \
    "predictions.jsonl"

GENERATION = {"seed": 42, "do_sample": False, "max_new_tokens": 1024}
TOOL_MAX_NEW_TOKENS = 1024       # per protocol round — budget parity with
# the no-tool arm (a model that never calls a tool must get the same
# 1024-token generation budget; 320/round truncated 126/150 answers and
# confounded the comparison with extraction failures)


def reuse_no_tool_predictions(rows, out_dir: Path) -> int:
    """Copy raw reused predictions from the frozen T2 run and re-verify
    them with the T4 verifier (predictions are never modified — the raw
    text is copied byte-identical and re-scored separately)."""
    from sciencemath.tools.benchmark import PredictionWriter, done_eval_ids, \
        verify_model
    base = {}
    with open(BASE_PRED, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                base[r["eval_id"]] = r
    pred_path = out_dir / "predictions.jsonl"
    done = set()
    if pred_path.exists():
        with open(pred_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line)["eval_id"])
    n = 0
    writer = PredictionWriter(pred_path)
    try:
        for item in rows:
            eid = item["eval_id"]
            if eid in done or eid not in base:
                continue
            src = base[eid]
            raw = src.get("raw_model_output")
            if raw is None:
                continue
            rec = verify_model(raw, item.get("expected_answer"),
                               item["answer_type"], item.get("choices"))
            writer.write({
                "eval_id": eid,
                "category": item.get("category"),
                "source_suite": item.get("source_suite"),
                "question": item["question"],
                "expected_answer": item.get("expected_answer"),
                "answer_type": item["answer_type"],
                "model_id": src.get("model_id"),
                "arm": "no_tool",
                "reused_from": str(BASE_PRED.relative_to(ROOT)),
                "raw_model_output": raw,          # byte-identical copy
                "extracted_answer": rec.get("extracted_answer"),
                "verdict": rec["verdict"],
                "verdict_method": rec.get("method"),
                "correct": rec["verdict"] == "PASS",
                "generation": GENERATION,
            })
            n += 1
    finally:
        writer.close()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["notool", "tool", "both"],
                    default="both")
    ap.add_argument("--limit", type=int, default=None,
                    help="smoke-test: cap questions per arm")
    ap.add_argument("--model-id", default="Qwen/Qwen3-1.7B")
    args = ap.parse_args()

    from sciencemath.tools.benchmark import (load_suite, run_tool_enabled,
                                             summarize, router_metrics,
                                             verifier_selftest)
    from sciencemath.tools.base import ensure_json_safe
    from sciencemath.utils.io_utils import write_json

    rows = load_suite(SUITE)
    if args.limit:
        rows = rows[: args.limit]
    slug = args.model_id.split("/")[-1]
    base_out = SUITE / slug

    written = 0
    if args.arm in ("notool", "both"):
        written = reuse_no_tool_predictions(rows, base_out / "notool")
        print(f"no-tool arm: reused {written} frozen T2 predictions")

    missing = []
    if args.arm in ("notool", "both"):
        from sciencemath.tools.benchmark import done_eval_ids
        done = done_eval_ids(base_out / "notool" / "predictions.jsonl")
        missing = [r for r in rows if r["eval_id"] not in done]
        if missing:
            tok, model, load_info = _load(args.model_id)
            res = run_tool_enabled(
                model=model, tokenizer=tok, rows=rows,
                out_dir=base_out / "notool",
                generation={**GENERATION, "max_new_tokens": 1024},
                model_id=args.model_id, tools_enabled=False,
                max_new_tokens=1024, max_seq_tokens=8192,
                enable_thinking=False,
                question_ids={r["eval_id"] for r in missing})
            print("no-tool generation:", res["status"],
                  res["questions_run"], "questions")
            del model
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    if args.arm in ("tool", "both"):
        from sciencemath.tools.benchmark import done_eval_ids
        done = done_eval_ids(base_out / "tool" / "predictions.jsonl")
        todo = [r for r in rows if r["eval_id"] not in done]
        tok, model, load_info = _load(args.model_id)
        res = run_tool_enabled(
            model=model, tokenizer=tok, rows=rows,
            out_dir=base_out / "tool",
            generation=GENERATION, model_id=args.model_id,
            tools_enabled=True, max_new_tokens=TOOL_MAX_NEW_TOKENS,
            max_seq_tokens=8192, enable_thinking=False,
            question_ids={r["eval_id"] for r in todo})
        print("tool arm:", res["status"], res["questions_run"], "questions")

    if args.arm == "both":
        metrics = {
            "suite": "mango-tool-eval-v1",
            "model_id": args.model_id,
            "verifier_selftest": verifier_selftest(load_suite(SUITE)),
            "router_metrics": router_metrics(load_suite(SUITE)),
            "comparison": _summarize(base_out),
        }
        ensure_json_safe(metrics)          # hard check: must be JSON-safe
        write_json(base_out / "t4_metrics.json", metrics)
        comp = metrics["comparison"]
        print("\n=== T4.5 summary ===")
        print("no-tool accuracy :", comp.get("no_tool_accuracy"))
        print("tool accuracy    :", comp.get("tool_enabled_accuracy"))
        print("delta            :", comp.get("delta"))
        print("verdicts         :", comp.get("verdict_counts"))
        print("tool usage       :", comp.get("tool_usage"))
        vs = metrics["verifier_selftest"]
        print("false-PASS gate  :", vs["critical_gate"],
              f"(false_pass_rate={vs['false_pass_rate']})")


def _summarize(base_out: Path):
    from sciencemath.tools.benchmark import summarize
    return summarize(base_out / "notool" / "predictions.jsonl",
                     base_out / "tool" / "predictions.jsonl")


def _load(model_id: str):
    from sciencemath.evaluation.model_loader import load_model_safely
    tok, model, info = load_model_safely(model_id, quantized_4bit=True)
    if not info.get("ok"):
        raise SystemExit(f"model load failed: {info.get('error')}")
    return tok, model, info


if __name__ == "__main__":
    main()