"""T19 unit tests: schema, graph, goals, skills, budget, invariants."""
from __future__ import annotations

import pytest

from sciencemath.planning.contract import (
    PLAN_ADD_DEPENDENCY, PLAN_BUDGET_EXCEEDED, PLAN_CREATE,
    PLAN_INSUFFICIENT_CAPABILITY, PLAN_NEEDS_CLARIFICATION, SCHEMA_VERSION,
)
from sciencemath.planning.graph import add_dependency, cycles, dep_map, validate_graph
from sciencemath.planning.models import Plan, Task
from sciencemath.planning.pipeline import Planner
from sciencemath.planning.serialize import PlanSchemaError, dumps, loads


def _create(**kw):
    p = Planner()
    req = {"allow_unspecified_repo": True, "goal": kw.pop("goal", "Fix the login bug")}
    req.update(kw)
    return p.handle(req)


def test_plan_and_task_schema_fields():
    r = _create(goal_type="CODE_BUGFIX")
    assert r.ok and r.plan is not None
    d = r.plan.to_dict()
    for k in ("plan_id", "goal", "goal_type", "created_at", "updated_at",
              "status", "constraints", "assumptions", "success_criteria",
              "failure_criteria", "budget", "tasks", "dependencies",
              "checkpoints", "observations", "revisions", "provenance",
              "plan_version", "plan_hash"):
        assert k in d
    t = r.plan.tasks[0].to_dict()
    for k in ("task_id", "title", "objective", "task_type", "required_skill",
              "required_inputs", "expected_outputs", "preconditions",
              "postconditions", "success_criteria", "failure_conditions",
              "dependencies", "status", "attempt_count", "max_attempts",
              "estimated_cost_class", "network_required",
              "persistent_write_requested", "side_effect_class",
              "observations", "result_reference", "execution_authority"):
        assert k in t
    assert t["execution_authority"] is False
    assert r.plan.schema_version == SCHEMA_VERSION


def test_goal_constraint_preference_split():
    r = _create(
        goal="Ship the fix. Prefer prettier logs.",
        constraints=["must remain offline"],
        preferences=["prefer shorter plan"],
        assumptions=["tests already exist"],
        goal_type="CODE_BUGFIX",
    )
    assert r.plan.goal.startswith("Ship the fix")
    assert any("offline" in c.lower() for c in r.plan.constraints)
    assert r.plan.preferences
    assert "prefer shorter plan" in r.plan.preferences
    assert "prefer shorter plan" not in r.plan.constraints
    assert r.plan.assumptions


def test_decomposition_is_actionable():
    r = _create(goal_type="CODE_BUGFIX")
    types = [t.task_type for t in r.plan.tasks]
    assert types != ["solve", "verify", "finish"]
    assert "inspect" in types and "test" in types and "verify" in types
    assert all(t.success_criteria for t in r.plan.tasks)
    assert all(t.required_skill == "CODE" for t in r.plan.tasks)


def test_skill_selection_per_capability():
    cases = [
        ("WEB_RESEARCH", "WEB_RESEARCH"),
        ("DOCUMENT_ANALYSIS", "DOCUMENT"),
        ("SCICOMP", "SCICOMP"),
        ("MEMORY_RECALL", "MEMORY"),
        ("CODE_BUGFIX", "CODE"),
    ]
    for gtype, skill in cases:
        r = _create(goal_type=gtype, goal=f"Handle a {gtype} task")
        assert r.ok, r.errors
        assert skill in {t.required_skill for t in r.plan.tasks}


def test_cycle_and_unknown_dependency_rejected():
    r = _create(goal_type="CODE_BUGFIX")
    plan = r.plan
    err = add_dependency(plan, plan.tasks[0].task_id, plan.tasks[0].task_id)
    assert err and "self-dependency" in err[0]
    p = Planner()
    bad = p.handle({
        "operation": PLAN_ADD_DEPENDENCY,
        "plan": r.plan.to_dict(),
        "from": "t99",
        "to": "t01",
    })
    assert not bad.ok
    # Force a cycle via two edges
    plan2 = Planner().handle({
        "goal": "Fix login", "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
    }).plan
    t1, t2 = plan2.tasks[0], plan2.tasks[1]
    t2.dependencies = [t1.task_id]
    t1.dependencies = [t2.task_id]
    plan2.tasks = [t1, t2] + plan2.tasks[2:]
    assert validate_graph(plan2)
    assert cycles(dep_map(plan2))
    out = Planner().handle({"operation": "PLAN_VALIDATE", "plan": plan2.to_dict()})
    assert not out.ok
    assert out.cycle_accepted == 0


def test_budget_and_paid_and_missing_capability():
    r = _create(goal_type="CODE_BUGFIX", horizon="long", target_tasks=20,
                max_tasks=5)
    assert r.op == PLAN_BUDGET_EXCEEDED
    paid = _create(goal="spend money on H100 cloud GPU")
    assert paid.op == "PLAN_POLICY_BLOCKED"
    cap = _create(goal="use magic orchestrator",
                  required_skills=["ORCHESTRATE_CLOUD"])
    assert cap.op == PLAN_INSUFFICIENT_CAPABILITY


def test_clarification_contradiction_and_format():
    r = _create(goal="must use no network and retrieve today's live stock price")
    assert r.op == PLAN_NEEDS_CLARIFICATION
    r2 = _create(goal="export the report", unknown_output_format=True)
    assert r2.op == PLAN_NEEDS_CLARIFICATION


def test_serialization_fail_closed_and_roundtrip():
    r = _create(goal_type="CODE_BUGFIX")
    blob = dumps(r.plan)
    loaded = loads(blob)
    assert loaded.plan_id == r.plan.plan_id
    assert loaded.schema_version == SCHEMA_VERSION
    with pytest.raises(PlanSchemaError):
        loads('{"schema_version": 99, "plan_id": "x"}')
    with pytest.raises(PlanSchemaError):
        loads("not-json")
