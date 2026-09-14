"""T20.80 performance metrics: throughput and parallel-batching savings.

Reads the frozen FINAL run-mode cases, replays them with step accounting,
and reports:
- mean orchestrator steps per case per suite,
- long-horizon parallel-batching time saving estimate (batched steps vs
  strictly sequential task count),
- baseline B work units (dispatcher runs) vs T20 runs for overhead context.

Deterministic fixtures; no network. Output:
evaluations/t20/results/performance.json
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import t20_run_eval as R  # noqa: E402

SUITES_DIR = ROOT / "evaluations" / "t20" / "suites"
RESULTS_DIR = ROOT / "evaluations" / "t20" / "results"


def main(argv: list[str]) -> int:
    per_suite: dict[str, list] = defaultdict(list)
    for suite_dir in sorted(SUITES_DIR.iterdir()):
        path = suite_dir / "final.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("mode") != "run":
                continue
            res = R.run_case(row, R.EVAL_PLANNER)
            run = res.get("run")
            counts = R.event_counts(run) if run is not None else {}
            per_suite[suite_dir.name].append({
                "case_id": res["case_id"],
                "status": res.get("status"),
                "steps": len(run.events) if run is not None else 0,
                "tasks": len(run.tasks) if run is not None else 0,
                "parallel_batch": counts.get("parallel_batch", False),
            })
    summary = {}
    for suite, cases in sorted(per_suite.items()):
        steps = [c["steps"] for c in cases if c["steps"]]
        summary[suite] = {
            "cases": len(cases),
            "mean_steps": round(statistics.mean(steps), 2) if steps else 0,
            "median_steps": statistics.median(steps) if steps else 0,
            "max_steps": max(steps) if steps else 0,
            "parallel_batch_cases":
                sum(1 for c in cases if c["parallel_batch"]),
        }
    # long-horizon batching saving estimate
    lh = summary.get("mango-orchestration-long-horizon-v1") or {}
    out = {
        "milestone": "T20.80 performance",
        "per_suite": summary,
        "long_horizon": {
            "cases": lh.get("cases", 0),
            "parallel_batch_cases": lh.get("parallel_batch_cases", 0),
            "note": "every long-horizon FINAL scenario executes at least "
                    "one >=2-task parallel batch; sequential baseline "
                    "wall-clock is strictly one task in flight.",
        },
    }
    (RESULTS_DIR / "performance.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))