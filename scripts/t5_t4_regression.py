"""T5.22 T4-regression check — verify the T5 retrieval layer did not
change T4 math behavior or scoring.

Two checks, no frozen artifact is modified:
  1. RE-VERIFY: the 150 frozen no-tool predictions are re-scored with the
     CURRENT T4 verifier (deterministic; catches any verification drift
     from code that landed with T5).
  2. REGENERATE: the 30 mev1-* questions are re-generated fresh through
     the identical no-tool harness (same prompt, same greedy config) and
     scored — catches any generation-path drift.

Output: evaluations/tool-suite/v1/t5_regression/t4_regression_metrics.json
(with per-question agreement against the frozen verdicts).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SUITE = ROOT / "evaluations" / "tool-suite" / "v1"
DEFAULT_OUT = SUITE / "t5_regression"
FROZEN_NOTOOL = SUITE / "Qwen3-1.7B" / "notool" / "predictions.jsonl"
FROZEN_METRICS = SUITE / "Qwen3-1.7B" / "t4_metrics.json"

GENERATION = {"seed": 42, "do_sample": False, "max_new_tokens": 1024}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=None,
                    help="output dir (default: the frozen T5 dir; T5R runs "
                         "MUST pass a new dir, e.g. t5r_regression, so "
                         "frozen T5 artifacts are never overwritten)")
    args = ap.parse_args()
    OUT_DIR = Path(args.out_dir) if args.out_dir else DEFAULT_OUT
    if args.out_dir is None and (DEFAULT_OUT / "t4_regression_metrics.json")\
            .exists():
        raise SystemExit(
            "refusing to overwrite the frozen T5 regression dir — "
            "pass --out-dir evaluations/tool-suite/v1/t5r_regression")
    from sciencemath.tools.benchmark import (PredictionWriter, load_suite,
                                             run_tool_enabled, summarize,
                                             verify_model)
    from sciencemath.utils.io_utils import write_json

    rows = {r["eval_id"]: r for r in load_suite(SUITE)}
    frozen = {}
    for line in (FROZEN_NOTOOL).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            frozen[r["eval_id"]] = r

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. re-verify every frozen prediction with the current verifier
    agree = disagree = 0
    disagreements = []
    regen_ids = []
    pred_path = OUT_DIR / "notool_predictions.jsonl"
    writer = PredictionWriter(pred_path)
    try:
        for eid, rec in frozen.items():
            item = rows.get(eid)
            if item is None:
                continue
            rec2 = verify_model(rec["raw_model_output"],
                                item.get("expected_answer"),
                                item["answer_type"], item.get("choices"))
            v_old, v_new = rec["verdict"], rec2["verdict"]
            if v_old == v_new:
                agree += 1
            else:
                disagree += 1
                disagreements.append({"eval_id": eid, "frozen": v_old,
                                      "current": v_new})
            rec2["eval_id"] = eid
            rec2["question"] = item["question"]
            writer.write(rec2)
            if not rec.get("reused_from"):
                regen_ids.append(eid)
    finally:
        writer.close()

    # 2. regenerate the fresh mev1-* questions through the same harness
    regenerated = 0
    if regen_ids:
        from sciencemath.evaluation.model_loader import load_model_safely
        tok, model, info = load_model_safely("Qwen/Qwen3-1.7B",
                                             quantized_4bit=True)
        if not info.get("ok"):
            raise SystemExit(f"model load failed: {info.get('error')}")
        res = run_tool_enabled(
            model=model, tokenizer=tok, rows=list(rows.values()),
            out_dir=OUT_DIR, generation=GENERATION,
            model_id="Qwen/Qwen3-1.7B", tools_enabled=False,
            max_new_tokens=1024, max_seq_tokens=8192,
            enable_thinking=False, question_ids=set(regen_ids))
        regenerated = res["questions_run"]
        del model
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # summarize CURRENT state over all questions
    cur = {}
    for line in pred_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            r["correct"] = r["verdict"] == "PASS"   # verify_model has no
            cur[r["eval_id"]] = r                   # 'correct' field
    # overlay fresh generations (run_tool_enabled writes its own file)
    regen_path = OUT_DIR / "predictions.jsonl"
    if regen_path.exists():
        for line in regen_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r["eval_id"] in cur:
                    cur[r["eval_id"]] = r
    correct = sum(1 for r in cur.values() if r.get("correct"))
    frozen_comp = json.loads(FROZEN_METRICS.read_text(
        encoding="utf-8"))["comparison"]
    out = {
        "purpose": "T5.22 T4-regression check (frozen artifacts untouched)",
        "frozen_no_tool_accuracy": frozen_comp.get("no_tool_accuracy"),
        "current_no_tool_accuracy": round(correct / len(cur), 4)
        if cur else None,
        "n_questions": len(cur),
        "verifier_agreement": {"agree": agree, "disagree": disagree},
        "regenerated_fresh": regenerated,
        "regression_gate": "PASS" if disagree == 0 else "FAIL",
        "disagreements": disagreements[:20],
    }
    write_json(OUT_DIR / "t4_regression_metrics.json", out)
    print(json.dumps(out, indent=2))
    return 0 if disagree == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())