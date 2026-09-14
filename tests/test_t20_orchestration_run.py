"""T20 orchestration e2e: happy paths, budgets, and the completion gate.

Domain: orchestrator_run — RUN_CREATE validation and bounded agent
instantiation, step loop to COMPLETE through the T19 planner gate, event
ordering and replay equivalence, structured ASSIGN messages, budget
monotonicity/bounds, facade RUN_STATUS/RUN_COMPLETE, bounded replan and
abort, checkpoint/resume integrity, WAITING, and recovery livelock
detection. Deterministic: fixed NOW everywhere, no network, no LLM, no
sleeps.
"""
import copy

import pytest

from sciencemath.orchestration.checkpoint import (
    RunCheckpointer, resume_integrity,
)
from sciencemath.orchestration.contract import (
    MAX_TOTAL_AGENTS, RUN_STATUSES, ZERO_TOLERANCE_KEYS,
)
from sciencemath.orchestration.events import replay_equivalent
from sciencemath.orchestration.models import OrchestrationRun
from sciencemath.orchestration.orchestrator import Orchestrator, completion_ok
from sciencemath.orchestration.pipeline import OrchestratorFacade
from sciencemath.orchestration.recovery import (
    livelock_detected, livelock_fingerprint,
)
from sciencemath.planning.contract import PLAN_COMPLETE
from sciencemath.planning.pipeline import Planner
from sciencemath.planning.policy import completion_decision

NOW = "2026-01-01T00:00:00Z"
SCICOMP_GOAL = "Run deterministic numeric computation"
SCICOMP_CRITERIA = ["numeric result produced"]
DOC_GOAL = "Summarize the local contract document"
DOC_CRITERIA = ["summary produced"]
TERMINAL = ("COMPLETE", "BLOCKED", "FAILED", "NEEDS_REPLAN")


def make_plan(goal=SCICOMP_GOAL, skills=("SCICOMP",),
              criteria=SCICOMP_CRITERIA):
    planner = Planner()
    res = planner.handle({
        "operation": "PLAN_CREATE", "goal": goal, "now": NOW,
        "required_skills": list(skills),
        "success_criteria": list(criteria),
    })
    assert res.ok, res.errors
    return planner, res.plan


def new_orchestrator(planner=None, checkpointer=None):
    return Orchestrator(planner=planner or Planner(),
                        checkpointer=checkpointer)


def step_to_completion(orch, run, cap=40):
    results = []
    for _ in range(cap):
        r = orch.step({"run": run, "now": NOW, "case": {}})
        results.append(r)
        assert r.replay_ok, f"replay broke at step {len(results)}"
        if run.status in TERMINAL:
            break
    assert run.status in TERMINAL, \
        f"no terminal status after {cap} steps: {run.status}"
    return results


# ---------------------------------------------------------------------------
# RUN_CREATE
# ---------------------------------------------------------------------------

def test_create_rejects_plan_without_tasks():
    orch = new_orchestrator()
    res = orch.create({"plan": {
        "plan_id": "pln_bad", "goal": "g", "goal_type": "MIXED",
        "created_at": NOW, "updated_at": NOW, "status": "READY",
        "tasks": [], "budget": {"max_cost_class": "FREE"},
        "stop_conditions": ["s"], "replan_policy": "EVENT_TRIGGERED",
    }, "now": NOW})
    assert res.ok is False
    assert res.run is None
    assert any("no tasks" in e for e in res.errors)


def test_create_accepts_valid_plan_status_running():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    res = orch.create({"plan": plan, "now": NOW})
    assert res.ok is True
    assert res.op == "RUN_CREATE"
    assert res.authority == "COORDINATE_INTERNAL_WORK_ONLY"
    run = res.run
    assert run.status == "RUNNING"
    assert run.status in RUN_STATUSES
    assert run.plan_id == plan.plan_id


def test_create_agent_complement():
    planner, plan = make_plan(skills=("SCICOMP",))
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    roles = [a["role"] for a in run.agents]
    assert roles.count("ORCHESTRATOR") == 1
    assert roles.count("PLANNER") == 1
    assert roles.count("VERIFIER") == 2
    assert roles.count("SCICOMP_WORKER") == 1
    # workers exist only for needed roles: no CODE/DOCUMENT/WEB/MEMORY
    for unwanted in ("CODE_WORKER", "DOCUMENT_WORKER",
                     "WEB_RESEARCH_WORKER", "MEMORY_CONTEXT_WORKER",
                     "SYNTHESIS_WORKER"):
        assert unwanted not in roles


def test_create_agent_count_bounded():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    assert len(run.agents) <= MAX_TOTAL_AGENTS
    workers = [a for a in run.agents
               if a["role"] not in ("ORCHESTRATOR", "PLANNER", "VERIFIER")]
    assert len(workers) <= run.budgets["max_worker_agents"]


def test_create_initializes_tasks_pending():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    expected_ids = {t.task_id for t in plan.tasks if not t.optional}
    assert set(run.tasks) == expected_ids
    assert all(st == "PENDING" for st in run.tasks.values())


def test_create_provenance_plan_hash_and_authority():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    assert run.provenance["plan_hash"] == plan.plan_hash
    assert run.provenance["authority"] == "COORDINATE_INTERNAL_WORK_ONLY"
    assert run.provenance["plan_id"] == plan.plan_id


def test_create_zero_tolerance_all_zero():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    res = orch.create({"plan": plan, "now": NOW})
    run = res.run
    assert set(run.counters) == set(ZERO_TOLERANCE_KEYS)
    assert all(v == 0 for v in run.counters.values())
    assert all(v == 0 for v in res.zero_tolerance.values())


def test_create_budget_override_known_keys_only():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW,
                       "budget": {"max_messages": 77,
                                  "bogus_unknown_key": 99}}).run
    assert run.budgets["max_messages"] == 77
    assert "bogus_unknown_key" not in run.budgets


def test_create_run_id_deterministic():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    a = orch.create({"plan": plan, "now": NOW}).run
    b = orch.create({"plan": plan, "now": NOW}).run
    assert a.run_id == b.run_id


# ---------------------------------------------------------------------------
# step loop to completion (T20.48 completion gate)
# ---------------------------------------------------------------------------

def test_step_loop_reaches_complete_all_tasks_succeeded():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    results = step_to_completion(orch, run)
    assert run.status == "COMPLETE"
    assert all(st == "SUCCEEDED" for st in run.tasks.values())
    assert run.blockers == []
    assert results[-1].ok is True
    assert all(v == 0 for v in results[-1].zero_tolerance.values())


def test_complete_gate_t19_completion_decision():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    step_to_completion(orch, run)
    done, evidence = completion_decision(planner._coerce_plan(run.plan))
    assert done == PLAN_COMPLETE
    assert evidence  # measurable evidence retained by the T19 gate
    assert completion_ok(run, planner) is True


def test_document_run_has_verified_mandatory_artifacts():
    planner, plan = make_plan(goal=DOC_GOAL, skills=("DOCUMENT",),
                              criteria=DOC_CRITERIA)
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    step_to_completion(orch, run)
    assert run.status == "COMPLETE"
    # every DOCUMENT artifact is mandatory-verification and PASSED
    assert run.artifacts
    assert all(a["verification_required"] for a in run.artifacts)
    assert all(a["verification_status"] == "PASSED"
               for a in run.artifacts)
    assert run.verifications
    for v in run.verifications:
        assert v["verifier_agent_id"] != v["producer_agent_id"]


def test_scicomp_mandatory_artifact_verification_statuses():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    step_to_completion(orch, run)
    for a in run.artifacts:
        if a["verification_required"]:
            assert a["verification_status"] in ("PASSED", "NOT_REQUIRED")
    assert run.blockers == []


# ---------------------------------------------------------------------------
# events + replay
# ---------------------------------------------------------------------------

def test_event_types_present_in_order():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    step_to_completion(orch, run)
    types = [e["event_type"] for e in run.events]
    for expected in ("RUN_CREATED", "AGENT_CREATED", "TASK_ASSIGNED",
                     "TASK_STARTED", "TASK_RESULT_SUBMITTED",
                     "ARTIFACT_REGISTERED", "TASK_COMPLETED",
                     "RUN_COMPLETED"):
        assert expected in types, expected
    idx = [types.index(t) for t in ("RUN_CREATED", "AGENT_CREATED",
                                    "TASK_ASSIGNED", "TASK_STARTED",
                                    "TASK_RESULT_SUBMITTED",
                                    "ARTIFACT_REGISTERED", "TASK_COMPLETED",
                                    "RUN_COMPLETED")]
    assert idx == sorted(idx)
    assert types[-1] == "RUN_COMPLETED"
    assert types.count("RUN_COMPLETED") == 1
    assert types.count("AGENT_CREATED") == len(run.agents)


def test_event_ids_unique():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    step_to_completion(orch, run)
    ids = [e["event_id"] for e in run.events]
    assert len(ids) == len(set(ids))


def test_replay_equivalent_each_step():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    assert replay_equivalent(run)
    results = step_to_completion(orch, run)
    assert all(r.replay_ok for r in results)
    assert replay_equivalent(run)


# ---------------------------------------------------------------------------
# messages + budgets
# ---------------------------------------------------------------------------

def test_assign_messages_from_orchestrator_to_workers():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    orch_id = next(a["agent_id"] for a in run.agents
                   if a["role"] == "ORCHESTRATOR")
    step_to_completion(orch, run)
    assigns = [m for m in run.messages if m["message_type"] == "ASSIGN"]
    assert len(assigns) == len(run.tasks)
    worker_ids = {a["agent_id"] for a in run.agents
                  if a["role"] not in ("ORCHESTRATOR", "PLANNER", "VERIFIER")}
    for m in assigns:
        assert m["sender"] == orch_id
        assert m["recipient"] in worker_ids
        assert m["task_id"] in run.tasks
    assert run.budgets["consumed_messages"] == len(run.messages)


def test_budget_counters_monotonic_and_bounded():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    seen = []
    for _ in range(40):
        r = orch.step({"run": run, "now": NOW, "case": {}})
        seen.append((run.budgets["consumed_handoffs"],
                     run.budgets["consumed_artifacts"],
                     run.budgets["consumed_messages"],
                     run.steps))
        assert run.budgets["consumed_handoffs"] <= \
            run.budgets["max_handoffs"]
        assert run.budgets["consumed_artifacts"] <= \
            run.budgets["max_artifacts"]
        assert run.budgets["consumed_messages"] <= \
            run.budgets["max_messages"]
        if run.status in TERMINAL:
            break
    for i in range(1, len(seen)):
        for j in range(4):
            assert seen[i][j] >= seen[i - 1][j]
    assert run.steps == len(seen)


def test_run_steps_increments_from_zero():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    assert run.steps == 0
    step_to_completion(orch, run)
    assert run.steps > 0


# ---------------------------------------------------------------------------
# facade RUN_STATUS / RUN_COMPLETE
# ---------------------------------------------------------------------------

def test_facade_run_create_then_status():
    _, plan = make_plan()
    fac = OrchestratorFacade(new_orchestrator())
    res = fac.handle({"op": "RUN_CREATE", "plan": plan, "now": NOW})
    assert res.ok is True
    status = fac.handle({"op": "RUN_STATUS", "run_id": res.run.run_id})
    assert status.ok is True
    assert status.run.run_id == res.run.run_id
    assert status.run is res.run
    assert status.metrics["tasks_total"] == len(res.run.tasks)


def test_facade_status_unknown_run():
    fac = OrchestratorFacade(new_orchestrator())
    res = fac.handle({"op": "RUN_STATUS", "run_id": "no_such_run"})
    assert res.ok is False
    assert "run_not_found" in res.errors


def test_facade_run_complete_refused_on_incomplete_run():
    _, plan = make_plan()
    fac = OrchestratorFacade(new_orchestrator())
    res = fac.handle({"op": "RUN_CREATE", "plan": plan, "now": NOW})
    done = fac.handle({"op": "RUN_COMPLETE", "run_id": res.run.run_id})
    assert done.ok is False


def test_facade_run_complete_on_completed_run():
    _, plan = make_plan()
    fac = OrchestratorFacade(new_orchestrator())
    res = fac.handle({"op": "RUN_CREATE", "plan": plan, "now": NOW})
    run = res.run
    for _ in range(40):
        fac.handle({"op": "RUN_STEP", "run": run, "now": NOW, "case": {}})
        if run.status in TERMINAL:
            break
    assert run.status == "COMPLETE"
    done = fac.handle({"op": "RUN_COMPLETE", "run_id": run.run_id})
    assert done.ok is True


# ---------------------------------------------------------------------------
# replan + abort
# ---------------------------------------------------------------------------

def test_replan_preserves_completed_work():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    orch.step({"run": run, "now": NOW, "case": {}})
    succeeded_before = {tid for tid, st in run.tasks.items()
                        if st == "SUCCEEDED"}
    res = orch.replan({"run": run, "replan_trigger": "TRANSIENT",
                       "now": NOW})
    assert res.ok is True
    assert run.status == "RUNNING"
    assert run.counters["silent_completed_work_loss"] == 0
    assert run.budgets["consumed_replans"] == 1
    succeeded_after = {tid for tid, st in run.tasks.items()
                       if st == "SUCCEEDED"}
    assert succeeded_before <= succeeded_after


def test_replan_budget_exhaustion():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    run.budgets["consumed_replans"] = run.budgets["max_replans"]
    res = orch.replan({"run": run, "replan_trigger": "TRANSIENT",
                       "now": NOW})
    assert res.ok is False
    assert any("budget" in e for e in res.errors)
    assert run.counters["unbounded_retry"] == 1


def test_abort_then_step_refused():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    res = orch.abort({"run": run, "now": NOW})
    assert res.ok is True
    assert run.status == "ABORTED"
    after = orch.step({"run": run, "now": NOW, "case": {}})
    assert after.ok is False
    assert "run already ABORTED" in after.blocked_reason


def test_step_on_complete_run_refused():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    run = orch.create({"plan": plan, "now": NOW}).run
    step_to_completion(orch, run)
    after = orch.step({"run": run, "now": NOW, "case": {}})
    assert after.ok is False
    assert "run already COMPLETE" in after.blocked_reason


# ---------------------------------------------------------------------------
# checkpoint + resume
# ---------------------------------------------------------------------------

def test_checkpoint_and_resume_preserves_state(tmp_path):
    planner, plan = make_plan()
    orch = new_orchestrator(planner,
                            checkpointer=RunCheckpointer(tmp_path))
    run = orch.create({"plan": plan, "now": NOW}).run
    orch.step({"run": run, "now": NOW, "case": {}})
    saved_dict = copy.deepcopy(run.to_dict())
    saved_run = OrchestrationRun.from_dict(saved_dict)
    ck = orch.checkpoint({"run": run, "now": NOW, "reason": "manual"})
    assert ck.ok is True
    step_to_completion(orch, run)
    res = orch.resume({"run_id": run.run_id})
    assert res.ok is True
    assert res.resume_ok is True
    loaded = res.run
    assert loaded.run_id == run.run_id
    assert loaded.plan_id == run.plan_id
    done_saved = {t for t, s in saved_run.tasks.items() if s == "SUCCEEDED"}
    done_loaded = {t for t, s in loaded.tasks.items() if s == "SUCCEEDED"}
    assert done_saved <= done_loaded
    assert loaded.budgets["consumed_handoffs"] >= \
        saved_run.budgets["consumed_handoffs"]
    assert loaded.budgets["consumed_replans"] == \
        saved_run.budgets["consumed_replans"]


def test_resume_integrity_clean(tmp_path):
    planner, plan = make_plan()
    orch = new_orchestrator(planner,
                            checkpointer=RunCheckpointer(tmp_path))
    run = orch.create({"plan": plan, "now": NOW}).run
    orch.step({"run": run, "now": NOW, "case": {}})
    saved_run = OrchestrationRun.from_dict(copy.deepcopy(run.to_dict()))
    orch.checkpoint({"run": run, "now": NOW, "reason": "manual"})
    step_to_completion(orch, run)
    loaded = orch.resume({"run_id": run.run_id}).run
    assert resume_integrity(saved_run, loaded) == []


def test_checkpoint_without_checkpointer_fails():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)   # no checkpointer
    run = orch.create({"plan": plan, "now": NOW}).run
    res = orch.checkpoint({"run": run, "now": NOW})
    assert res.ok is False
    assert any("no checkpointer" in e for e in res.errors)


def test_resume_missing_checkpoint(tmp_path):
    planner, plan = make_plan()
    orch = new_orchestrator(planner,
                            checkpointer=RunCheckpointer(tmp_path))
    res = orch.resume({"run_id": "ghost_run"})
    assert res.ok is False
    assert "checkpoint_missing" in res.errors


# ---------------------------------------------------------------------------
# WAITING + livelock (recovery)
# ---------------------------------------------------------------------------

def test_waiting_when_no_ready_task():
    planner, plan = make_plan()
    orch = new_orchestrator(planner)
    plan_dict = plan.to_dict()
    plan_dict["tasks"] = [dict(plan_dict["tasks"][0], status="BLOCKED")]
    plan_dict["dependencies"] = []
    run = OrchestrationRun(
        run_id="run_wait_fixture", plan_id=plan.plan_id, run_version=1,
        status="RUNNING", started_at=NOW, updated_at=NOW,
        plan=plan_dict)
    run.tasks = {plan_dict["tasks"][0]["task_id"]: "PENDING"}
    res = orch.step({"run": run, "now": NOW, "case": {}})
    assert res.ok is True
    assert run.status == "WAITING"
    assert run.status in RUN_STATUSES


def test_livelock_detected_via_recovery():
    planner, plan = make_plan()
    run_dict = {
        "plan": plan.to_dict(), "revisions": [],
        "budgets": {"consumed_replans": 0}, "fingerprints": [],
    }
    assert livelock_detected(run_dict) is False
    fp = livelock_fingerprint(run_dict)
    # one prior identical fingerprint + the current one = 2 < limit 3
    run_dict["fingerprints"] = [fp]
    assert livelock_detected(run_dict) is False
    # two prior identical + current = 3 identical -> livelock
    run_dict["fingerprints"] = [fp, fp]
    assert livelock_detected(run_dict) is True
    # a distinct history entry breaks the streak
    other_dict = dict(run_dict, budgets={"consumed_replans": 1})
    run_dict["fingerprints"] = [fp, livelock_fingerprint(other_dict)]
    assert livelock_detected(run_dict) is False