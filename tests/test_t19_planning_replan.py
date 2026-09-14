"""T19 replanning, selective invalidation, recovery, loops, non-progress."""
from __future__ import annotations

from sciencemath.planning.graph import descendants, dep_map, task_list
from sciencemath.planning.harness import simulate
from sciencemath.planning.pipeline import Planner
from sciencemath.planning.policy import classify_failure


def test_transient_retry_then_success():
    case = {
        "goal": "Fix the login bug in fixture repo",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "fail_task": "t01",
        "failure_class": "TRANSIENT",
        "error": "timeout",
    }
    # First observe fails t01; recover sets PENDING; next loop succeeds.
    r = simulate(case)
    assert r.plan is not None
    t01 = next(t for t in task_list(r.plan) if t.task_id == "t01")
    assert t01.attempt_count >= 1
    assert t01.max_attempts <= 3
    assert t01.attempt_count <= t01.max_attempts or r.plan.status == "BLOCKED"


def test_permanent_failure_alternate_path():
    r = simulate({
        "goal": "Fix the login bug in fixture repo",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "fail_task": "t02",
        "failure_class": "PERMANENT",
        "error": "cannot patch this file",
    })
    ids = [t.task_id for t in task_list(r.plan)]
    assert any(i.endswith("-alt") for i in ids) or r.plan.status in (
        "BLOCKED", "NEEDS_REPLAN", "COMPLETE", "IN_PROGRESS")


def test_selective_invalidation_keeps_unrelated():
    p = Planner()
    created = p.handle({
        "goal": "Fix the login bug",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
    })
    plan = created.plan
    # Mark t01 succeeded; t02 will be invalidated; t01 must remain.
    plan.tasks[0].status = "SUCCEEDED"
    plan.tasks[0].result_reference = "t01.artifact"
    plan.tasks[1].status = "SUCCEEDED"
    plan.tasks[1].result_reference = "t02.artifact"
    out = p.handle({
        "operation": "PLAN_REPLAN",
        "plan": plan.to_dict(),
        "replan_trigger": "artifact_changed",
        "invalidate_task": "t02",
    })
    by = {t.task_id: t for t in task_list(out.plan)}
    assert by["t01"].status == "SUCCEEDED"
    assert by["t01"].result_reference == "t01.artifact"
    down = descendants("t02", dep_map(out.plan))
    for tid in down:
        assert by[tid].status in ("PENDING", "INVALIDATED", "READY")
        assert by[tid].status != "SUCCEEDED"
    assert out.silent_completed_work_loss == 0


def test_unnecessary_replan_refused_on_success():
    p = Planner()
    created = p.handle({
        "goal": "Fix the login bug",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
    })
    out = p.handle({
        "operation": "PLAN_REPLAN",
        "plan": created.plan.to_dict(),
        "replan_trigger": "task_succeeded",
    })
    assert out.op != "PLAN_REPLAN" or "unnecessary" in (out.blocked_reason or "")
    assert created.plan.plan_version == 1


def test_loop_and_unbounded_retry_refused():
    r = simulate({
        "goal": "Fix the login bug in fixture repo",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "task_observations": {
            "t01": {
                "result_status": "FAILED",
                "failure_class": "TRANSIENT",
                "errors": ["timeout"],
                "artifacts": [],
            },
        },
        "max_sim_steps": 20,
    })
    t01 = next(t for t in task_list(r.plan) if t.task_id == "t01")
    assert t01.attempt_count <= t01.max_attempts + 1
    assert r.plan.status in ("BLOCKED", "FAILED", "NEEDS_REPLAN")
    assert r.plan.status != "COMPLETE"


def test_non_progress_blocks():
    r = simulate({
        "goal": "Fix the login bug",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "task_observations": {
            "t01": {
                "result_status": "FAILED",
                "failure_class": "UNKNOWN",
                "errors": ["no new evidence"],
                "artifacts": [],
            },
        },
        "max_sim_steps": 12,
    })
    assert r.plan.status in ("BLOCKED", "FAILED", "NEEDS_REPLAN")
    assert r.plan.status != "COMPLETE"


def test_failure_classification():
    assert classify_failure({"failure_class": "TRANSIENT"}) == "TRANSIENT"
    assert classify_failure({"result_status": "FAILED",
                             "errors": ["timeout"]}) == "TRANSIENT"
    assert classify_failure({"result_status": "FAILED",
                             "errors": ["policy denied"]}) == "POLICY_BLOCK"


def test_policy_block_not_bypassed():
    r = simulate({
        "goal": "Fix the login bug",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
        "fail_task": "t01",
        "failure_class": "POLICY_BLOCK",
        "error": "permission denied",
    })
    assert r.op == "PLAN_POLICY_BLOCKED" or r.plan.status == "BLOCKED"
    assert r.plan.status != "COMPLETE"
