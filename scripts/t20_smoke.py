"""T20.50 real local smoke: create a validated T19 plan, run the
orchestrator create -> step loop deterministically, assert zero-tolerance
counters stay 0 and the plan gate completes."""
import sys

from sciencemath.planning.contract import PLAN_COMPLETE
from sciencemath.planning.pipeline import Planner
from sciencemath.planning.policy import completion_decision
from sciencemath.orchestration.orchestrator import (
    Orchestrator, RunResult, completion_ok,
)

NOW = "2026-01-01T00:00:00Z"


def build_plan(planner):
    res = planner.handle({
        "operation": "PLAN_CREATE",
        "goal": "Compare two fixture datasets and report the numeric difference "
                "and a one-paragraph summary.",
        "now": NOW,
        "required_skills": ["SCICOMP", "DOCUMENT"],
        "success_criteria": [
            "dataset A mean reported",
            "dataset B mean reported",
            "difference reported",
        ],
    })
    assert res.ok, (res.errors, getattr(res, "blocked_reason", ""))
    return res.plan


def main() -> int:
    planner = Planner()
    plan = build_plan(planner)
    orch = Orchestrator(planner=planner)
    created = orch.create({"plan": plan, "now": NOW})
    assert created.ok, created.errors
    run = created.run
    print("agents:", [(a["agent_id"], a["role"]) for a in run.agents])
    for i in range(40):
        res = orch.step({"run": run, "now": NOW, "case": {}})
        run = res.run
        print(f"step {i}: status={run.status} tasks={run.tasks} "
              f"ok={res.ok} blocked={res.blocked_reason} "
              f"blockers={run.blockers[-2:]}")
        if run.status in ("COMPLETE", "BLOCKED", "FAILED", "NEEDS_REPLAN"):
            break
        if run.status == "WAITING" and all(
                s in ("SUCCEEDED", "BLOCKED") for s in run.tasks.values()):
            break
    print("zero-tolerance nonzero:",
          {k: v for k, v in run.counters.items() if v})
    print("replay_ok:", res.replay_ok)
    done, evidence = completion_decision(planner._coerce_plan(run.plan))
    print("plan gate:", done, run.status == "COMPLETE")
    assert res.replay_ok
    assert not {k: v for k, v in run.counters.items() if v}, "zero-tolerance"
    assert run.status == "COMPLETE", run.status
    assert done == PLAN_COMPLETE
    assert completion_ok(run, planner)
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())