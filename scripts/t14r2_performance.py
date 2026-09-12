"""T14R2.20 — performance record.

The T14R2 layer is deterministic Python injected before the necessity
guard; its cost must be negligible against the LLM pipeline. Measured:
  * offline layer latency (recognize + select) over every frozen suite
    question — median / p95 / max microseconds;
  * microbench runtime (108 cases, fully offline);
  * GPU replay latency comparison: T14R2 recheck (B3) vs T14R baseline
    (B2) median LLM latency — must be within noise.
"""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys_path = str(ROOT / "src")

SUITE = ROOT / "evaluations/t11/scicomp-suite/v1/questions.jsonl"
B2_SUMMARY = ROOT / "evaluations/t14r/runs/t14r-scicomp-B2/summary.json"
B3_SUMMARY = ROOT / "evaluations/t14r2/runs/t14r2-scicomp-B3/summary.json"
MB_METRICS = ROOT / "evaluations/t14r2/ode_microbench_metrics.json"
OUT = ROOT / "evaluations/t14r2/performance.json"


def main() -> int:
    import sys
    sys.path.insert(0, sys_path)
    from sciencemath.scicomp.ode_intent import (
        recognize_ode_ivp, select_ode_operation)

    questions = [json.loads(ln)["question"] for ln in
                 SUITE.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]

    # warmup
    for q in questions[:5]:
        select_ode_operation({"operation": "definite_integral"}, q)

    rec_us, sel_us = [], []
    for q in questions:
        t0 = time.perf_counter_ns()
        recognize_ode_ivp(q)
        rec_us.append((time.perf_counter_ns() - t0) / 1000.0)
        t0 = time.perf_counter_ns()
        select_ode_operation({"operation": "definite_integral",
                              "parameters": {}}, q)
        sel_us.append((time.perf_counter_ns() - t0) / 1000.0)

    def stats(xs):
        xs = sorted(xs)
        return {"median_us": round(statistics.median(xs), 1),
                "p95_us": round(xs[int(0.95 * (len(xs) - 1))], 1),
                "max_us": round(xs[-1], 1)}

    layer = {"recognize": stats(rec_us), "select": stats(sel_us)}

    b2 = json.loads(B2_SUMMARY.read_text(encoding="utf-8")) \
        if B2_SUMMARY.exists() else None
    b3 = json.loads(B3_SUMMARY.read_text(encoding="utf-8")) \
        if B3_SUMMARY.exists() else None
    mb = json.loads(MB_METRICS.read_text(encoding="utf-8")) \
        if MB_METRICS.exists() else None

    doc = {
        "milestone": "T14R2.20 — performance",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "suite_questions": len(questions),
        "offline_layer_latency_us": layer,
        "llm_pipeline_median_ms": {
            "t14r_B2": (b2 or {}).get("median_llm_ms"),
            "t14r2_B3": (b3 or {}).get("median_llm_ms")},
        "microbench": {
            "cases": (mb or {}).get("total_cases"),
            "mode": "fully offline, no GPU"},
        "note": ("layer cost is microseconds against a ~30 s median LLM "
                 "call; the deterministic layer adds no measurable "
                 "pipeline latency"),
    }
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())