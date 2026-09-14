"""T19.47–T19.48 simulated tool world. Fixture observations only."""
from __future__ import annotations

from sciencemath.planning.contract import (
    PLAN_ABORT, PLAN_BLOCK, PLAN_BUDGET_EXCEEDED, PLAN_COMPLETE,
    PLAN_INSUFFICIENT_CAPABILITY, PLAN_NEEDS_CLARIFICATION,
    PLAN_POLICY_BLOCKED,
)
from sciencemath.planning.graph import ready_tasks
from sciencemath.planning.policy import can_complete
from sciencemath.planning.models import utc_now
from sciencemath.planning.pipeline import Planner, PlanResult
from sciencemath.planning.serialize import dumps, loads


TERMINAL = {
    PLAN_COMPLETE, PLAN_BLOCK, PLAN_ABORT, PLAN_BUDGET_EXCEEDED,
    PLAN_POLICY_BLOCKED, PLAN_INSUFFICIENT_CAPABILITY,
    PLAN_NEEDS_CLARIFICATION,
}


def case_request(case: dict) -> dict:
    skip = {"gold", "events", "observations", "task_id", "id"}
    req = {k: v for k, v in case.items() if k not in skip}
    req["goal"] = case.get("goal") or case.get("question") or ""
    req["operation"] = "PLAN_CREATE"
    return req


def fixture_observation(case: dict, task, step_i: int,
                        state: dict | None = None) -> dict:
    state = state if state is not None else {}
    used = state.setdefault("used_events", set())
    fails = state.setdefault("fail_counts", {})
    events = list(case.get("events") or [])
    for idx, ev in enumerate(events):
        if idx in used:
            continue
        match = ev.get("task_id") or ev.get("after_task") or ev.get("task_type")
        if match in (task.task_id, task.task_type, f"step:{step_i}"):
            used.add(idx)
            obs = dict(ev.get("observation") or ev)
            obs.setdefault("task_id", task.task_id)
            return obs
    overrides = (case.get("task_observations") or {}).get(task.task_id) or \
        (case.get("task_observations") or {}).get(task.task_type)
    if overrides:
        obs = dict(overrides)
        obs.setdefault("task_id", task.task_id)
        return obs
    if case.get("fail_task") == task.task_id or \
            case.get("fail_type") == task.task_type:
        key = f"{task.task_id}:{case.get('fail_type') or ''}"
        n = fails.get(key, 0)
        fails[key] = n + 1
        fc = case.get("failure_class") or "TRANSIENT"
        if not (fc == "TRANSIENT" and n > 0):
            return {
                "task_id": task.task_id,
                "result_status": "FAILED",
                "failure_class": fc,
                "errors": [case.get("error") or "simulated tool failure"],
                "facts": [],
                "artifacts": [],
            }
    verifyish = task.task_type in ("verify", "test", "freshness") or (
        str(task.task_id).endswith("-alt") and "verif" in (task.title or "").lower())
    if case.get("omit_verification") and verifyish:
        return {
            "task_id": task.task_id,
            "result_status": "FAILED",
            "failure_class": "POLICY_BLOCK",
            "errors": ["verification evidence missing; policy forbids skip"],
            "artifacts": [],
        }
    art = (task.expected_outputs or [f"{task.task_id}.artifact"])[0]
    facts = list(task.success_criteria or [])
    if case.get("malicious_observation") and step_i == 0:
        return {
            "task_id": task.task_id,
            "result_status": "SUCCEEDED",
            "facts": [
                case["malicious_observation"],
                f"literal:{case['malicious_observation']}",
            ],
            "artifacts": [art],
        }
    return {
        "task_id": task.task_id,
        "result_status": "SUCCEEDED",
        "facts": facts,
        "artifacts": [art],
        "errors": [],
        "failure_class": None,
    }


def simulate(case: dict, planner: Planner | None = None,
             baseline: bool = False) -> PlanResult:
    if baseline:
        from sciencemath.planning.baseline import baseline_simulate
        return baseline_simulate(case)
    planner = planner or Planner()
    req = case_request(case)
    result = planner.handle(req)
    if result.op in TERMINAL or result.plan is None:
        return result
    plan = result.plan
    # Resume round-trip if requested before running remaining work.
    if case.get("resume"):
        blob = dumps(plan)
        plan = loads(blob)
        result = planner.handle({
            "operation": "PLAN_RESUME",
            "serialized": blob,
            "plan": plan.to_dict(),
        })
        plan = result.plan
    max_steps = int(case.get("max_sim_steps") or 80)
    st: dict = {"used_events": set(), "fail_counts": {}}
    for i in range(max_steps):
        if plan.status in ("COMPLETE", "ABORTED", "FAILED", "BLOCKED"):
            break
        if can_complete(plan):
            result = planner.handle({"operation": "PLAN_COMPLETE",
                                     "plan": plan.to_dict()})
            plan = result.plan or plan
            break
        ready = ready_tasks(plan)
        if not ready:
            chk = planner.handle({"operation": "PLAN_COMPLETE",
                                  "plan": plan.to_dict()})
            result = chk
            plan = chk.plan or plan
            break
        task = ready[0]
        task.status = "RUNNING_SIMULATED"
        obs = fixture_observation(case, task, i, st)
        obs["timestamp"] = utc_now(case.get("now"))
        result = planner.handle({
            "operation": "PLAN_OBSERVE",
            "plan": plan.to_dict(),
            "observation": obs,
            "now": case.get("now"),
        })
        plan = result.plan or plan
        if result.op == "PLAN_REPLAN" or plan.status == "NEEDS_REPLAN":
            result = planner.handle({
                "operation": "PLAN_REPLAN",
                "plan": plan.to_dict(),
                "replan_trigger": (plan.decision_metadata or [{}])[-1].get(
                    "replan_trigger") or "dependency_fail",
                "observation": obs,
            })
            plan = result.plan or plan
        if result.op in TERMINAL:
            break
        if case.get("goal_change_after") == task.task_id:
            result = planner.handle({
                "operation": "PLAN_REPLAN",
                "plan": plan.to_dict(),
                "replan_trigger": "goal_changed",
                "new_goal": case.get("new_goal"),
                "goal_changed": True,
            })
            plan = result.plan or plan
        if case.get("constraint_change_after") == task.task_id:
            result = planner.handle({
                "operation": "PLAN_REPLAN",
                "plan": plan.to_dict(),
                "replan_trigger": "constraint_changed",
                "new_constraints": case.get("new_constraints"),
                "new_max_tasks": case.get("new_max_tasks"),
                "constraint_changed": True,
            })
            plan = result.plan or plan
        if case.get("invalidate_after") == task.task_id:
            result = planner.handle({
                "operation": "PLAN_REPLAN",
                "plan": plan.to_dict(),
                "replan_trigger": "artifact_changed",
                "invalidate_task": task.task_id,
            })
            plan = result.plan or plan
    if plan.status not in ("COMPLETE", "ABORTED", "FAILED", "BLOCKED"):
        if case.get("force_complete_attempt") or can_complete(plan):
            result = planner.handle({"operation": "PLAN_COMPLETE",
                                     "plan": plan.to_dict()})
            plan = result.plan or plan
        if plan.status not in ("COMPLETE", "ABORTED", "FAILED", "BLOCKED"):
            plan.status = "BLOCKED"
            plan.blocked_reason = plan.blocked_reason or "simulation non-progress"
            result.op = PLAN_BLOCK
            result.ok = False
            result.blocked_reason = plan.blocked_reason
            result.plan = plan
    result.plan = plan
    result.side_effects = planner.log.to_dict()
    return result
