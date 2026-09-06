"""Strategy evaluations for a checkpoint: task decomposition plans
(T6.14) and self-correction (T6.18).

  * Decomposition arm (T6.14): for multi-hop / mixed / cross-domain items,
    the model is asked for a structured plan (the PLAN_TEMPLATE schema:
    goal, subproblems, needs_math_tool, needs_retrieval — no hidden
    chain-of-thought). Measured: JSON validity rate, plan-schema
    validation rate, routing agreement of the plan's derived label with
    the item's frozen routing_label.
  * Self-correction arm (T6.18): for items the checkpoint got WRONG in
    its closed-book run, the model is re-prompted to check its own answer.
    Measured: correction rate (wrong -> right) and over-correction rate
    (right -> wrong on a matched sample of correct items).

Outputs evaluations/t6/strategy_results/<label>/{decomposition.jsonl,
self_correction.jsonl, metrics.json}.

Usage:
  python scripts/run_strategy_evals.py --label mango-v0.1 \
      --adapter training/adapters/sciencemath-v0.1-t3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.curriculum.decomposition import (  # noqa: E402
    parse_plan_from_output, routing_label_from_plan, validate_plan,
)
from sciencemath.evaluation.extraction import (  # noqa: E402
    answers_match, extract_answer, strip_think_block,
)
from sciencemath.evaluation.runner import render_for_model  # noqa: E402
from sciencemath.utils.io_utils import read_jsonl, write_json  # noqa: E402

SUITE = REPO / "evaluations" / "eval-core" / "v1"
CORE_RESULTS = REPO / "evaluations" / "t6" / "core_results"
OUT_BASE = REPO / "evaluations" / "t6" / "strategy_results"
MODEL_ID = "Qwen/Qwen3-1.7B"
PARENT_ADAPTER = REPO / "training" / "adapters" / "sciencemath-v0.1-t3"

PLAN_INSTRUCTION = (
    "Before answering, output a JSON plan for solving this problem on the "
    "first line, then give the final answer. Use exactly this schema:\n"
    '{"problem_type": "math"|"science"|"mixed"|"insufficient", '
    '"subproblems": [{"id": 1, "goal": "<short step>", '
    '"needs_math_tool": true|false, "needs_retrieval": true|false}, ...]}\n'
    "Rules: problem_type and subproblems are required; each subproblem "
    "needs a unique integer id, a short goal (one sentence, no worked "
    "arithmetic), and boolean needs_math_tool / needs_retrieval flags. "
    "Do not put anything else inside the JSON.")

CORRECTION_INSTRUCTION = (
    "Your previous answer to this question was: \"{prev}\". Check it "
    "step by step. If it is correct, restate it; if it is wrong, give "
    "the corrected answer. End with 'Answer: \\boxed{...}'.")


def _generate(model, tok, question: str, *, max_new_tokens: int = 1024,
              seed: int = 42) -> tuple[str, float]:
    import torch
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    templ = render_for_model(tok, question, enable_thinking=False)
    inputs = tok(templ, return_tensors="pt", truncation=True,
                 max_length=4096)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    t0 = time.time()
    with torch.no_grad():
        out = model.generate(
            **inputs, do_sample=False, max_new_tokens=max_new_tokens,
            pad_token_id=tok.pad_token_id or tok.eos_token_id)
    raw = tok.decode(out[0][inputs["input_ids"].shape[1]:],
                     skip_special_tokens=True)
    return strip_think_block(raw), time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--adapter", type=Path, default=None)
    ap.add_argument("--decomposition-limit", type=int, default=20)
    args = ap.parse_args()

    out_dir = OUT_BASE / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    suite = read_jsonl(SUITE / "questions.jsonl")
    by_id = {r["eval_id"]: r for r in suite}

    # wrong + matched-correct records from the closed-book run
    preds_path = CORE_RESULTS / args.label / "predictions.jsonl"
    if not preds_path.exists():
        print(f"run scripts/run_core_eval.py for {args.label} first "
              f"(missing {preds_path})")
        return 2
    preds = read_jsonl(preds_path)
    wrong = [p for p in preds if p["correct"] is False]
    right = [p for p in preds if p["correct"] is True][:len(wrong)]

    from sciencemath.training.attach import load_base_with_adapter
    tok, model, info = load_base_with_adapter(
        MODEL_ID, str(args.adapter or PARENT_ADAPTER))
    if not info.get("ok"):
        print("model load failed:", info)
        return 1

    # ---- T6.14 decomposition arm ----------------------------------------
    eligible = [it for it in suite
                if it["category"] in ("mixed_quantitative", "interdisciplinary")
                or it["multi_hop"]][:args.decomposition_limit]
    decomp = []
    for item in eligible:
        raw, latency = _generate(model, tok,
                                 item["question"] + "\n\n"
                                 + PLAN_INSTRUCTION)
        plan = parse_plan_from_output(raw)
        record = {
            "eval_id": item["eval_id"], "category": item["category"],
            "expected_routing_label": item.get("routing_label"),
            "raw_model_output": raw[:2000], "latency_s": round(latency, 2),
            "plan_valid": False, "json_valid": plan is not None,
            "plan_routing_label": None,
            "routing_agreement": None,
        }
        if plan is not None:
            errs = validate_plan(plan)
            record["plan_valid"] = not errs
            record["plan_errors"] = errs[:5]
            label = routing_label_from_plan(plan)
            record["plan_routing_label"] = label
            expected = item.get("routing_label")
            record["routing_agreement"] = (label == expected) \
                if expected else None
        decomp.append(record)
    write_json(out_dir / "decomposition.jsonl", decomp)

    # ---- T6.18 self-correction arm ----------------------------------------
    correction = []
    for group, was_correct in ((wrong, False), (right, True)):
        for p in group:
            item = by_id.get(p["eval_id"])
            if not item:
                continue
            prev = p.get("extracted_answer") or p.get("raw_model_output", "")
            prompt = (item["question"] + "\n\n"
                      + CORRECTION_INSTRUCTION.replace(
                          "{prev}", str(prev)[:200]))
            raw, latency = _generate(model, tok, prompt)
            extracted = extract_answer(raw, item["answer_type"],
                                       item.get("choices"))
            if item["category"] == "uncertainty_calibration":
                from sciencemath.evaluation.extraction import \
                    signals_uncertainty
                correct_now = signals_uncertainty(raw)
            else:
                correct_now = extracted is not None and answers_match(
                    str(item["expected_answer"]), extracted or "")
            correction.append({
                "eval_id": p["eval_id"], "was_correct": was_correct,
                "previous_answer": str(prev)[:120],
                "corrected_answer": extracted,
                "correct_after_correction": bool(correct_now),
                "latency_s": round(latency, 2),
            })
    write_json(out_dir / "self_correction.jsonl", correction)

    # ---- metrics -----------------------------------------------------------
    n = len(decomp) or 1
    sc_wrong = [c for c in correction if not c["was_correct"]]
    sc_right = [c for c in correction if c["was_correct"]]
    metrics = {
        "decomposition": {
            "n": len(decomp),
            "json_valid_rate": sum(1 for d in decomp
                                   if d["json_valid"]) / n,
            "schema_valid_rate": sum(1 for d in decomp
                                     if d["plan_valid"]) / n,
            "routing_agreement": (
                sum(1 for d in decomp if d["routing_agreement"]) /
                max(1, sum(1 for d in decomp
                           if d["routing_agreement"] is not None)))
            if any(d["routing_agreement"] is not None for d in decomp)
            else None,
        },
        "self_correction": {
            "wrong_items": len(sc_wrong),
            "correction_rate": (sum(1 for c in sc_wrong
                                    if c["correct_after_correction"])
                                / len(sc_wrong)) if sc_wrong else None,
            "overcorrection_rate": (sum(1 for c in sc_right
                                        if not c["correct_after_correction"])
                                    / len(sc_right)) if sc_right else None,
            "n_correct_sampled": len(sc_right),
        },
    }
    metrics["self_correction"]["wrong_items"] = len(sc_wrong)
    write_json(out_dir / "metrics.json", metrics)
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())