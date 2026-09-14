"""T20.58/T20.59 baselines: A (T19 sequential) and B (naive dispatcher).

Runs every run-mode FINAL case through three drivers and compares:

- **T20 coordinated**: the orchestration runtime (independent verification,
  bounded recovery, adversarial containment, parallel batching, budgets).
  Reuses the frozen benchmark runner so metrics are apples-to-apples.
- **Baseline A (T19 sequential)**: the T19 planning harness, unchanged.
  One task in flight at a time, T19 PLAN_REPLAN on failure, no independent
  verifier, no agent containment. Worker-behavior directives that only the
  T20 fixture world understands (partial/malicious/missing_evidence/
  self_verify_claim) are translated to the closest T19 modeling; behaviors
  with no T19 modeling are counted as accepted-unverified, which is the
  point of the baseline.
- **Baseline B (naive dispatcher)**: dispatches every task immediately
  (ignores dependencies), accepts worker claims as success without any
  verification, retries a failure once unconditionally, and declares
  completion regardless. No budgets, no containment.

Deterministic fixture world only; no network, no training, no paid compute.
Output: evaluations/t20/results/baselines.json + stdout summary.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import t20_run_eval as R  # noqa: E402

from sciencemath.orchestration.workers import worker_run  # noqa: E402
from sciencemath.planning.harness import simulate  # noqa: E402

SUITES_DIR = ROOT / "evaluations" / "t20" / "suites"
RESULTS_DIR = ROOT / "evaluations" / "t20" / "results"

# behaviors a T19-sequential run cannot detect or contain: the result is
# accepted because the worker said SUCCEEDED and there is no verifier.
UNVERIFIABLE_BEHAVIORS = ("partial", "malicious", "missing_evidence",
                          "self_verify_claim")
FAILING_BEHAVIORS = ("failure", "timeout", "crash", "revision_demand")


def load_run_rows() -> list[tuple[str, dict]]:
    rows = []
    for suite_dir in sorted(SUITES_DIR.iterdir()):
        path = suite_dir / "final.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("mode") == "run":
                rows.append((suite_dir.name, row))
    return rows


# ---------------------------------------------------------------------------
# Baseline A: T19 sequential (planning harness, unchanged)
# ---------------------------------------------------------------------------
def translate_case(row: dict) -> dict:
    """Map a T20 benchmark case onto T19's harness vocabulary."""
    case = dict(row.get("case") or {})
    wb = case.get("worker_behavior") or {}
    t19 = {
        "goal": row["request"].get("goal") or "",
        "required_skills": list(row["request"].get("required_skills") or []),
        "hard_constraints": ["no network", "FREE cost only"],
        "now": "2026-01-01T00:00:00Z",
        "max_sim_steps": int(row["driver"].get("max_steps", 60)) * 2,
    }
    for tid, behavior in wb.items():
        if behavior in FAILING_BEHAVIORS:
            t19.setdefault("events", []).append({
                "task_id": tid,
                "observation": {
                    "task_id": tid,
                    "result_status": "FAILED",
                    "failure_class":
                        "INVALID_INPUT" if behavior == "revision_demand"
                        else "TRANSIENT",
                    "errors": [f"simulated {behavior}"],
                    "facts": [],
                    "artifacts": [],
                },
            })
        elif behavior in UNVERIFIABLE_BEHAVIORS:
            # no independent verifier in T19: the claim is accepted as-is
            t19["accepted_unverified"] = \
                t19.get("accepted_unverified", 0) + 1
    return t19


def baseline_a(row: dict) -> dict:
    t19_case = translate_case(row)
    result = simulate(t19_case)
    plan = result.plan
    status = plan.status if plan is not None else "NO_PLAN"
    completed = plan is not None and plan.status == "COMPLETE"
    return {
        "completed": completed,
        "status": status,
        "worker_runs": -1,          # T19 harness does not expose step counts
        "verification_passes": 0,   # no independent verifier
        "false_complete": 0 if completed else
            len(t19_case.get("events") or []),
        "unverified_accepted": t19_case.get("accepted_unverified", 0),
        "claim_rejections": 0,      # no containment layer
        "parallel_batches": 0,      # strictly sequential
        "replans": 1 if (plan is not None and
                         plan.status == "COMPLETE" and
                         t19_case.get("events")) else 0,
    }


# ---------------------------------------------------------------------------
# Baseline B: naive dispatcher (no deps, no verifier, no budgets)
# ---------------------------------------------------------------------------
def baseline_b(row: dict) -> dict:
    planner = R.EVAL_PLANNER
    if row.get("plan"):
        plan_dict = row["plan"]
    else:
        pr = planner.handle({"operation": "PLAN_CREATE",
                             **row["request"],
                             "hard_constraints":
                                 ["no network", "FREE cost only"],
                             "now": R.step_now(0)})
        plan_dict = pr.plan.to_dict()
    tasks = [t for t in plan_dict["tasks"]
             if t.get("status") not in ("SUCCEEDED", "SKIPPED")]
    wb = (row.get("case") or {}).get("worker_behavior") or {}

    workers: dict[str, dict] = {}
    runs = 0
    retries = 0
    unverified_accepted = 0
    false_complete = 0
    unrecovered = 0
    state: dict = {}
    for task in tasks:
        skill = task.get("required_skill") or ""
        agent = workers.setdefault(skill, {
            "agent_id": f"naive-{skill.lower() or 'general'}",
            "role": f"{skill}_WORKER", "allowed_skills": [skill],
            "denied_skills": [], "status": "READY", "budget": {},
        })
        tid = task.get("task_id") or ""
        behavior = wb.get(tid) or wb.get(task.get("task_type")) or "success"
        if behavior == "success":
            runs += 1
            continue
        result = worker_run(task, agent, row.get("case") or {},
                            now=R.step_now(runs), state=state)
        runs += 1
        if result["result_status"] != "SUCCEEDED":
            # unconditional single retry, then accept whatever comes back
            result = worker_run(task, agent, row.get("case") or {},
                                now=R.step_now(runs), state=state)
            runs += 1
            retries += 1
        if result["result_status"] != "SUCCEEDED":
            unrecovered += 1
            false_complete += 1   # declares completion anyway
        elif behavior in UNVERIFIABLE_BEHAVIORS:
            unverified_accepted += 1
            false_complete += 1   # accepted with no verification
    completed_claim = True   # naive dispatcher always claims completion
    return {
        "completed": completed_claim,
        "status": "COMPLETE (claimed, unverified)" if not false_complete
            else "COMPLETE (claimed with defects)",
        "worker_runs": runs,
        "verification_passes": 0,
        "false_complete": false_complete,
        "unverified_accepted": unverified_accepted,
        "claim_rejections": 0,
        "parallel_batches": 0,   # dispatch-all with no coordination gating
        "replans": 0,
        "retries_unconditional": retries,
        "unrecovered_failures": unrecovered,
    }


# ---------------------------------------------------------------------------
# driver comparison
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    limit = int(argv[0]) if argv else 0
    rows = load_run_rows()
    if limit:
        rows = rows[:limit]
    per_suite: dict[str, dict] = defaultdict(lambda: {
        "cases": 0, "gold_expect_complete": 0,
        "t20": {"passed": 0, "completed": 0, "verification": 0,
                "false_complete": 0, "batches": 0, "containment": 0},
        "baseline_a": {"completed": 0, "spurious_complete": 0,
                       "false_complete": 0, "unverified_accepted": 0},
        "baseline_b": {"completed": 0, "spurious_complete": 0,
                       "false_complete": 0, "unverified_accepted": 0},
        "adversarial_cases": 0, "adversarial_contained": 0,
    })
    all_t20_replays_ok = True
    for suite, row in rows:
        agg = per_suite[suite]
        gold = row["gold"]
        agg["cases"] += 1
        # gold-expect-COMPLETE cases are the fair recovery-throughput
        # comparison set (expect-BLOCKED cases are containment cases).
        expect_complete = gold.get("expect_status") == "COMPLETE"
        agg["gold_expect_complete"] += int(bool(expect_complete))
        is_adversarial = bool(
            (gold.get("require") or {}).get("claim_rejected_min", 0) > 0)
        if is_adversarial:
            agg["adversarial_cases"] += 1

        t20 = R.run_case(row, R.EVAL_PLANNER)
        run = t20.get("run")
        counts = R.event_counts(run) if run is not None else {}
        status = t20.get("status")
        gate = run is not None and status == "COMPLETE"
        if gate:
            from sciencemath.orchestration.orchestrator import completion_ok
            gate = completion_ok(run, R.EVAL_PLANNER)
        if t20.get("replay_ok") is False:
            all_t20_replays_ok = False
        agg["t20"]["passed"] += int(bool(t20.get("ok")))
        if expect_complete:
            agg["t20"]["completed"] += int(bool(gate))
        agg["t20"]["verification"] += counts.get("verification_passed", 0)
        agg["t20"]["false_complete"] += int(
            (run.counters.get("false_complete", 0) if run else 0) > 0)
        agg["t20"]["batches"] += int(counts.get("parallel_batch", False))
        agg["t20"]["containment"] += counts.get("claim_rejections", 0)
        if is_adversarial and counts.get("claim_rejections", 0) > 0:
            agg["adversarial_contained"] += 1

        a = baseline_a(row)
        if expect_complete:
            agg["baseline_a"]["completed"] += int(a["completed"])
        elif a["completed"]:
            # baseline claims completion where the contract requires blocking
            agg["baseline_a"]["spurious_complete"] += 1
        agg["baseline_a"]["false_complete"] += a["false_complete"]
        agg["baseline_a"]["unverified_accepted"] += a["unverified_accepted"]

        b = baseline_b(row)
        if expect_complete:
            agg["baseline_b"]["completed"] += int(b["completed"])
        elif b["completed"]:
            agg["baseline_b"]["spurious_complete"] += 1
        agg["baseline_b"]["false_complete"] += b["false_complete"]
        agg["baseline_b"]["unverified_accepted"] += b["unverified_accepted"]

    summary = {}
    for suite, agg in sorted(per_suite.items()):
        n = agg["cases"]
        gc = max(1, agg["gold_expect_complete"])
        summary[suite] = {
            "cases": n,
            "gold_expect_complete_cases": agg["gold_expect_complete"],
            "t20_pass_rate": agg["t20"]["passed"] / n,
            "t20_complete_rate_on_gold_complete":
                agg["t20"]["completed"] / gc,
            "baseline_a_complete_rate":
                agg["baseline_a"]["completed"] / gc,
            "baseline_b_complete_rate":
                agg["baseline_b"]["completed"] / gc,
            "t20_verification_passes": agg["t20"]["verification"],
            "t20_parallel_batch_cases": agg["t20"]["batches"],
            "t20_claim_rejections": agg["t20"]["containment"],
            "t20_false_complete_cases": agg["t20"]["false_complete"],
            "adversarial_cases": agg["adversarial_cases"],
            "adversarial_contained": agg["adversarial_contained"],
            "baseline_a_false_complete": agg["baseline_a"]["false_complete"],
            "baseline_b_false_complete": agg["baseline_b"]["false_complete"],
            "baseline_a_spurious_complete":
                agg["baseline_a"]["spurious_complete"],
            "baseline_b_spurious_complete":
                agg["baseline_b"]["spurious_complete"],
            "baseline_a_unverified_accepted":
                agg["baseline_a"]["unverified_accepted"],
            "baseline_b_unverified_accepted":
                agg["baseline_b"]["unverified_accepted"],
        }
    out = {
        "suites": summary,
        "t20_replay_all_ok": all_t20_replays_ok,
    }
    out_path = RESULTS_DIR / "baselines.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))