"""T19.52 baseline: existing T7 experimental planner, T19-shaped wrap."""
from __future__ import annotations

from sciencemath.executive.plan import fallback_plan, validate_plan
from sciencemath.planning.contract import PLAN_CREATE
from sciencemath.planning.models import Plan, Task, utc_now
from sciencemath.planning.pipeline import PlanResult


def baseline_plan(goal: str, now: str | None = None) -> Plan:
    raw = fallback_plan(
        {"problem_type": "GENERAL", "resources": "NONE"},
        {"question_target": goal, "expression": ""},
    )
    ts = utc_now(now)
    tasks = []
    for i, step in enumerate(raw.get("steps") or [], start=1):
        action = step.get("action") or "REASON"
        tasks.append(Task(
            task_id=step.get("id") or f"s{i}",
            title=step.get("description") or action,
            objective=step.get("description") or action,
            task_type=str(action).lower(),
            required_skill=str(action),  # T7 actions, not T19 skills
            dependencies=list(step.get("depends_on") or []),
            success_criteria=[],
            execution_authority=False,
            side_effect_class="NONE",
        ))
    plan = Plan(
        plan_id="baseline-t7",
        goal=goal,
        goal_type="T7_EXPERIMENTAL",
        created_at=ts,
        updated_at=ts,
        status="DRAFT",
        tasks=tasks,
        success_criteria=[],
        stop_conditions=[],
        replan_policy="",
    )
    v = validate_plan(raw)
    plan.status = "READY" if v.ok else "FAILED"
    return plan


def baseline_simulate(case: dict) -> PlanResult:
    plan = baseline_plan(case.get("goal") or case.get("question") or "")
    # T7 planner has no completion gate, no T19 skills, no checkpoints.
    return PlanResult(
        op=PLAN_CREATE,
        plan=plan,
        ok=plan.status == "READY",
        errors=["baseline experimental T7 planner"],
    )
