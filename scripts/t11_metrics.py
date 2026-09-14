"""T11.20/T11.24/T11.41 — head-to-head comparison, four-layer
decomposition metrics, and failure taxonomy.

Reads arm A and arm B prediction files and writes
evaluations/t11/head_to_head.json:
  - arm summaries side by side with deltas
  - the four evaluation layers (COMPUTE_SUCCESS / NUMERICAL_VALIDITY /
    MODEL_ADOPTION / SCIENTIFIC_INTERPRETATION)
  - failure taxonomy over every arm-B miss (T11.41)

Usage:
  python scripts/t11_metrics.py --arm-a <label> --arm-b <label>
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "evaluations/t11/runs"

TAXONOMY = [
    "no_compute_attempted_on_numeric",     # planner declined; numeric item missed
    "request_malformed",                   # JSON/schema invalid
    "unknown_operation",                   # operation not in registry
    "prevalidation_rejected",              # structural gate
    "engine_resource_limit",               # RESOURCE_LIMIT
    "engine_invalid_input",                # INVALID_INPUT on a legit item
    "engine_failure",                      # FAIL/UNKNOWN/NUMERICAL_WARNING
    "engine_success_model_misread",        # PASS envelope, model reported a
    #                                        different (wrong) number
    "engine_success_model_ignored",        # PASS envelope, model gave no number
    "tolerance_miss_close",                # right approach, precision slightly out
    "conceptual_compute_attempted",        # computed on a conceptual question
    "adversarial_number_asserted",         # asserted a number despite failure
    "model_mutated_problem_input",         # 'corrected' invalid parameters
    #                                        instead of transmitting them
    "no_compute_attempted_on_adversarial",
    "unclassified",
]


def load_rows(label: str) -> list[dict]:
    path = RUNS / label / "predictions.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def classify_miss(row: dict) -> str:
    if row["kind"] == "conceptual":
        return ("conceptual_compute_attempted" if row.get("invoked")
                else "unclassified")
    if row["kind"] == "adversarial":
        if row.get("asserted_number_on_failure"):
            return "adversarial_number_asserted"
        if row.get("envelope_status") == "PASS":
            return "model_mutated_problem_input"
        if not row.get("invoked"):
            return "no_compute_attempted_on_adversarial"
        return "unclassified"
    # numeric / mixed miss
    if not row.get("invoked"):
        return "no_compute_attempted_on_numeric"
    if not row.get("request_valid"):
        return "request_malformed"
    if row.get("request_valid") and row.get("request", {}).get("operation") \
            not in (None, "NO_COMPUTE"):
        from sciencemath.scicomp.registry import build_registry
        if row["request"]["operation"] not in build_registry():
            return "unknown_operation"
    status = row.get("envelope_status")
    if status == "RESOURCE_LIMIT":
        return "engine_resource_limit"
    if status == "INVALID_INPUT":
        return "engine_invalid_input"
    if status in ("FAIL", "UNKNOWN", "NUMERICAL_WARNING"):
        return "engine_failure"
    if status == "PASS":
        if row.get("numeric_correct") is False:
            return ("engine_success_model_misread"
                    if row.get("final_answer") else
                    "engine_success_model_ignored")
        return "tolerance_miss_close"
    return "unclassified"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm-a", required=True)
    ap.add_argument("--arm-b", required=True)
    args = ap.parse_args()

    sys_path = str(ROOT / "src")
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)

    rows_a = load_rows(args.arm_a)
    rows_b = load_rows(args.arm_b)
    by_id_a = {r["eval_id"]: r for r in rows_a}

    sys.path.insert(0, str(ROOT / "scripts"))
    import t11_scicomp_head_to_head as h
    items = h.verify_suite()
    by_item = {it["eval_id"]: it for it in items}

    summary_a = h.grade_arm(items, rows_a)
    summary_b = h.grade_arm(items, rows_b)

    # ---- four-layer decomposition (T11.24), arm B ----
    invocations = [r for r in rows_b if r.get("invoked")]
    passes = [r for r in invocations if r.get("envelope_status") == "PASS"]
    numeric_items = [r for r in rows_b
                     if r["kind"] in ("numeric_oracle", "mixed")]
    numeric_ok = [r for r in numeric_items if r.get("numeric_correct")]
    conceptual = [r for r in rows_b if r["kind"] == "conceptual"]
    conceptual_ok = [r for r in conceptual if r.get("conceptual_correct")]
    adopted = [r for r in passes if r.get("adopted")]
    layers = {
        "COMPUTE_SUCCESS": len(passes) / max(1, len(invocations)),
        "NUMERICAL_VALIDITY": len(numeric_ok) / max(1, len(numeric_items)),
        "MODEL_ADOPTION": len(adopted) / max(1, len(passes)),
        "SCIENTIFIC_INTERPRETATION":
            len(conceptual_ok) / max(1, len(conceptual)),
    }

    # ---- failure taxonomy (T11.41) over arm-B misses ----
    misses = [r for r in rows_b if not (
        r.get("numeric_correct") or r.get("conceptual_correct")
        or r.get("adversarial_correct"))]
    taxonomy = Counter(classify_miss(r) for r in misses)
    miss_details = [{"eval_id": r["eval_id"], "category": r["category"],
                     "kind": r["kind"],
                     "failure_class": classify_miss(r),
                     "envelope_status": r.get("envelope_status"),
                     "final_answer": r.get("final_answer")}
                    for r in misses]

    out = {
        "suite": "mango-scicomp-eval-v1",
        "arm_a_label": args.arm_a,
        "arm_b_label": args.arm_b,
        "arm_a_summary": summary_a,
        "arm_b_summary": summary_b,
        "deltas": {
            "numeric_accuracy":
                summary_b["numeric_accuracy"] - summary_a["numeric_accuracy"],
            "adversarial_handled_correctly":
                summary_b["adversarial_handled_correctly"]
                - summary_a["adversarial_handled_correctly"],
            "conceptual_discipline":
                summary_b["conceptual_discipline"]
                - summary_a["conceptual_discipline"],
        },
        "four_layer_decomposition_arm_b": layers,
        "failure_taxonomy_arm_b": dict(taxonomy),
        "failure_details": miss_details,
    }
    out_path = ROOT / "evaluations/t11/head_to_head.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "deltas": out["deltas"],
        "layers": layers,
        "taxonomy": dict(taxonomy),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())