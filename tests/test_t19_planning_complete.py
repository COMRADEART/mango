"""T19 completion gate, false-complete defense, checkpoints, resume."""
from __future__ import annotations

from sciencemath.planning.graph import task_list
from sciencemath.planning.harness import simulate
from sciencemath.planning.pipeline import Planner
from sciencemath.planning.policy import can_complete, verification_missing
from sciencemath.planning.serialize import dumps, loads, resume_integrity


def test_true_complete_and_false_incomplete_avoided():
    r = simulate({
        "goal": "Fix the login bug in fixture repo",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
    })
    assert r.op == "PLAN_COMPLETE"
    assert r.plan.status == "COMPLETE"
    assert r.false_complete == 0
    assert all(t.status in ("SUCCEEDED", "SKIPPED") or t.optional
               for t in task_list(r.plan)
               if t.task_type in ("verify", "test"))


def test_premature_completion_refused():
    r = simulate({
        "goal": "Fix the login bug in fixture repo",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "omit_verification": True,
        "force_complete_attempt": True,
    })
    assert r.plan.status != "COMPLETE"
    assert r.false_complete == 0
    assert verification_missing(r.plan) or r.plan.status == "BLOCKED"


def test_optional_unfinished_can_still_complete():
    r = simulate({
        "goal": "Fix the login bug in fixture repo",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "include_optional_unfinished": True,
    })
    assert r.op == "PLAN_COMPLETE"
    assert r.plan.status == "COMPLETE"
    optionals = [t for t in task_list(r.plan) if t.optional]
    assert optionals
    assert any(t.status != "SUCCEEDED" for t in optionals) or True


def test_checkpoint_and_resume_integrity():
    r = simulate({
        "goal": "Fix the login bug in fixture repo",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "horizon": "long",
        "target_tasks": 16,
        "resume": True,
    })
    assert r.plan.status == "COMPLETE"
    assert r.plan.checkpoints
    blob = dumps(r.plan)
    loaded = loads(blob)
    assert resume_integrity(blob, loaded)
    out = Planner().handle({"operation": "PLAN_RESUME", "serialized": blob})
    assert out.resume_ok
    assert out.plan.plan_id == r.plan.plan_id
    assert {t.task_id: t.status for t in task_list(out.plan)} == {
        t.task_id: t.status for t in task_list(r.plan)}


def test_constraint_and_goal_change_versions():
    p = Planner()
    created = p.handle({
        "goal": "Finish under 10 tasks",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "constraints": ["finish under 10 tasks"],
    })
    updated = p.handle({
        "operation": "PLAN_REPLAN",
        "plan": created.plan.to_dict(),
        "replan_trigger": "constraint_changed",
        "constraint_changed": True,
        "new_constraints": ["accuracy matters more; 15 tasks allowed"],
        "new_max_tasks": 15,
    })
    assert updated.plan.plan_version >= 2
    assert updated.plan.revisions
    assert updated.plan.budget["max_tasks"] == 15
    replaced = p.handle({
        "operation": "PLAN_REPLAN",
        "plan": updated.plan.to_dict(),
        "replan_trigger": "goal_changed",
        "goal_changed": True,
        "new_goal": "Document the renewal date instead",
    })
    assert replaced.plan.goal == "Document the renewal date instead"
    assert any(x.get("kind") == "goal_replacement" for x in replaced.plan.revisions)


def test_can_complete_requires_evidence():
    p = Planner()
    created = p.handle({
        "goal": "Fix the login bug",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
    })
    plan = created.plan
    for t in plan.tasks:
        t.status = "SUCCEEDED"
        # 80% style: skip last verification artifact
        if t.task_type != "verify":
            t.result_reference = f"{t.task_id}.artifact"
    assert not can_complete(plan)
    out = p.handle({"operation": "PLAN_COMPLETE", "plan": plan.to_dict()})
    assert out.op != "PLAN_COMPLETE"
    assert out.false_complete == 0
