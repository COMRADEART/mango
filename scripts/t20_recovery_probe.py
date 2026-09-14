"""Quick e2e probe: one-off worker failure -> replan -> recovery -> COMPLETE."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sciencemath.orchestration.orchestrator import Orchestrator
from sciencemath.planning.pipeline import Planner

planner = Planner()
pr = planner.handle({
    "operation": "PLAN_CREATE",
    "request": {"goal": "Recover after transient failure",
                "required_skills": ["CODE"],
                "success_criteria": ["recovery achieved"],
                "constraints": ["no network"]},
})
plan = pr.plan
orch = Orchestrator(planner=planner)
rr = orch.create({"plan": plan.to_dict(), "authority":
                  "COORDINATE_INTERNAL_WORK_ONLY"})
run = rr.run
case = {"worker_behavior": {"t01": "failure"}}
replans = 0
for i in range(60):
    res = orch.step({"run": run, "now": "2026-01-01T00:00:0%dZ" % (i % 10),
                     "case": case})
    run = res.run
    if run.status == "NEEDS_REPLAN":
        replans += 1
        res = orch.replan({"run": run, "replan_trigger":
                           run.replan_state.get("trigger"),
                           "now": "2026-01-01T00:00:0%dZ" % (i % 10)})
        run = res.run
    if run.status in ("COMPLETE", "BLOCKED", "FAILED"):
        break
nz = {k: v for k, v in run.counters.items() if v}
print("status:", run.status)
print("replans:", replans, "consumed:", run.budgets["consumed_replans"])
print("revisions:", len(run.revisions))
print("nonzero counters:", nz)
print("replay_ok:", res.replay_ok)
tasks = {t.get("task_id"): t.get("status")
         for t in (run.plan.get("tasks") or [])}
print("plan tasks:", tasks)
assert run.status == "COMPLETE", run.status
assert replans >= 1
assert not nz
print("RECOVERY PROBE OK")