"""Run extraction benchmark on a model."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SUITE = ROOT / "evaluations/t9/extraction-benchmark/v1/questions.jsonl"

from sciencemath.evaluation.extraction import extract_answer, strip_think_block, answers_match
from sciencemath.evaluation.model_loader import load_model_safely


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=160)
    args = ap.parse_args()

    items = [json.loads(line) for line in SUITE.read_text().splitlines() if line]
    tok, model, load = load_model_safely(args.model)
    if not load["ok"]:
        raise SystemExit(load["error"])

    rows = []
    for item in items:
        raw = item["raw_model_output"]
        extracted = extract_answer(raw, item["answer_type"], item.get("choices"))
        expected = item["expected_answer"]
        correct = answers_match(expected, extracted) if extracted is not None else False
        rows.append({
            **item,
            "extracted_answer": extracted,
            "correct": correct,
        })

    # Compute metrics
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    extracted = sum(1 for r in rows if r["extracted_answer"] is not None)
    precision = correct / extracted if extracted else 0
    recall = correct / total
    false_acceptance = sum(1 for r in rows if not r["correct"] and r["extracted_answer"] is not None)
    wrong_final_acceptance = sum(1 for r in rows if not r["correct"] and r["extracted_answer"] is not None and answers_match(r["expected_answer"], r["extracted_answer"]))

    out = ROOT / "evaluations/t9/runs" / args.label
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    summary = {
        "label": args.label,
        "model": args.model,
        "suite": "mango-extraction-benchmark-v1",
        "questions": total,
        "load": load,
        "metrics": {
            "extraction_recall": recall,
            "extraction_precision": precision,
            "false_extraction_acceptance": false_acceptance / total,
            "wrong_final_answer_acceptance": wrong_final_acceptance / total,
            "counts": {
                "total": total,
                "correct": correct,
                "extracted": extracted,
                "false_acceptance": false_acceptance,
                "wrong_final_acceptance": wrong_final_acceptance,
            }
        }
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())