"""T20 orchestrator adversarial / verification path tests.

Covers: transient failure -> bounded replan recovery, completed-work
preservation, adversarial worker claims treated as DATA (never obeyed),
missing-evidence verification failure, bounded revisions (and the revision
budget cap), verifier independence, message-budget exhaustion, identity
spoof rejection, deadlock guard, no-compatible-agent blocking, the
unverified-mandatory-artifact completion gate, self-verification bypass
claims, abort/step-after-terminal, and the zero-tolerance invariant for
well-behaved runs.
Deterministic: fixed NOW everywhere; no network, no sleep, no wall clock.
"""
from __future__ import annotations

import pytest

from sciencemath.orchestration.assignment import verification_required_for
from sciencemath.orchestration.contract import ZERO_TOLERANCE_KEYS
from sciencemath.orchestration.orchestrator import Orchestrator, completion_ok
from sciencemath.planning.pipeline import Planner

NOW = "2026-01-01T00:00:00Z"
TERMINAL = {"COMPLETE", "BLOCKED", "FAILED", "ABORTED", "NEEDS_REPLAN"}

DOC_GOAL = "Summarize the contract terms from the local document"
WEB_GOAL = "Research current api rate limits with citations"
SCI_GOAL = "Compute the numeric integral with SciComp"
MEM_GOAL = "Recall the prior decision from memory"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def make_plan(goal: str, skills: list[str]):
    planner = Planner()
    res = planner.handle({
        "operation": "PLAN_CREATE", "goal": goal, "now": NOW,
        "required_skills": list(skills),
    })
    assert res.ok and res.plan is not None, res.errors
    return planner, res.plan


def make_orch_run(goal: str, skills: list[str], budget: dict | None = None):
    planner, plan = make_plan(goal, skills)
    orch = Orchestrator(planner=planner)
    res = orch.create({"plan": plan, "now": NOW, "budget": dict(budget or {})})
    assert res.ok and res.run is not None, res.errors
    return orch, res.run


def drive(orch: Orchestrator, run, case: dict | None = None, cap: int = 40):
    """Step until a terminal run status (bounded iterations, no sleep)."""
    case = case or {}
    res = None
    for _ in range(cap):
        res = orch.step({"run": run, "now": NOW, "case": case})
        if run.status in TERMINAL:
            return res
    raise AssertionError(f"run did not reach a terminal status: {run.status}")


def events_of_type(run, event_type: str) -> list[dict]:
    return [e for e in run.events if e["event_type"] == event_type]


def plan_task_status(run, task_id: str) -> str:
    return next(t["status"] for t in run.plan["tasks"]
                if t["task_id"] == task_id)


def succeeded_task_ids(plan: dict) -> set[str]:
    return {t["task_id"] for t in plan.get("tasks") or []
            if t.get("status") == "SUCCEEDED"}


# ===========================================================================
# failure + recovery (T20.32/T20.33/T20.46)
# ===========================================================================

def test_transient_failure_requests_bounded_replan():
    orch, run = make_orch_run(DOC_GOAL, ["DOCUMENT"])
    for _ in range(3):   # t01..t03 succeed
        orch.step({"run": run, "now": NOW, "case": {}})
    assert run.status in ("RUNNING", "WAITING")
    assert succeeded_task_ids(run.plan) == {"t01", "t02", "t03"}

    res = orch.step({"run": run, "now": NOW,
                     "case": {"worker_behavior": {"t04": "failure"}}})
    assert run.status == "NEEDS_REPLAN"
    assert run.tasks["t04"] == "FAILED"
    # completed tasks are untouched
    assert succeeded_task_ids(run.plan) == {"t01", "t02", "t03"}
    assert any(e["event_type"] == "AGENT_FAILED" and e["task_id"] == "t04"
               for e in run.events)
    assert any(e["event_type"] == "PLAN_REPLAN_REQUESTED" and
               e["payload"].get("replan_trigger") == "TRANSIENT"
               for e in run.events)
    assert run.counters["unbounded_retry"] == 0
    assert run.replan_state["trigger"] == "TRANSIENT"


def test_replan_after_transient_failure_recovers_and_preserves_work():
    orch, run = make_orch_run(DOC_GOAL, ["DOCUMENT"])
    for _ in range(3):
        orch.step({"run": run, "now": NOW, "case": {}})
    orch.step({"run": run, "now": NOW,
               "case": {"worker_behavior": {"t04": "failure"}}})
    before = succeeded_task_ids(run.plan)

    rp = orch.replan({"run": run, "replan_trigger": "dependency_fail",
                      "now": NOW})
    assert rp.ok
    assert run.budgets["consumed_replans"] == 1
    # replan must not lose unrelated completed work (T20.46)
    assert run.counters["silent_completed_work_loss"] == 0
    assert run.status == "RUNNING"

    drive(orch, run)
    assert run.status == "COMPLETE"
    after = succeeded_task_ids(run.plan)
    assert before <= after, "completed work lost across replan"
    assert run.tasks["t04"] == "SUCCEEDED"
    for k in ZERO_TOLERANCE_KEYS:
        assert run.counters[k] == 0, k


def test_replan_budget_cap_blocks_unbounded_retry():
    orch, run = make_orch_run(MEM_GOAL, ["MEMORY"])
    # run budget already spent on replans
    run.budgets["consumed_replans"] = int(run.budgets["max_replans"])
    res = orch.replan({"run": run, "replan_trigger": "goal_changed",
                       "now": NOW})
    assert res.ok is False
    assert run.counters["unbounded_retry"] == 1
    assert run.status == "BLOCKED"
    assert any(e["event_type"] == "BUDGET_EXHAUSTED" and
               e["payload"].get("budget") == "replans" for e in run.events)


# ===========================================================================
# malicious worker claim is DATA, never instruction (T20.40/T20.64)
# ===========================================================================

def test_malicious_claim_recorded_as_data_not_obeyed():
    orch, run = make_orch_run(DOC_GOAL, ["DOCUMENT"])
    n_agents = len(run.agents)
    drive(orch, run, case={"worker_behavior": {"t01": "malicious"}})

    rejected = [e for e in run.events if e["event_type"] == "MESSAGE_REJECTED"
                and e["payload"].get("reason") == "adversarial_claim_as_data"]
    assert rejected, "adversarial claim not recorded as rejected data"
    assert rejected[0]["task_id"] == "t01"
    assert rejected[0]["payload"].get("claim")

    # the claim was not obeyed: no extra agents, no spawn, no injection win
    assert len(run.agents) == n_agents
    assert run.counters["prompt_injection_success"] == 0
    assert run.counters["unbounded_agent_spawn"] == 0
    assert run.counters["unauthorized_external_action"] == 0
    # the verifier still decided on facts: claim is not evidence
    t01_records = [v for v in run.verifications if v["task_id"] == "t01"]
    assert t01_records_fail(t01_records)


def t01_records_fail(records) -> bool:
    return any(v["decision"] == "FAIL" for v in records)


def test_missing_evidence_insufficient_verification_no_false_complete():
    orch, run = make_orch_run(DOC_GOAL, ["DOCUMENT"])
    drive(orch, run, case={"worker_behavior": {"t01": "missing_evidence"}})

    decisions = [v["decision"] for v in run.verifications]
    assert "INSUFFICIENT_EVIDENCE" in decisions
    assert any(e["event_type"] == "VERIFICATION_FAILED" for e in run.events)
    assert run.counters["false_complete"] == 0
    # the insufficient first attempt never completes the task directly: a
    # bounded revision must produce a separately-verified artifact before
    # completion (completion_ok holds only via the revised, verified one)
    if run.status == "COMPLETE":
        assert run.revisions, "completed without a bounded revision"
        assert any(v["decision"] == "PASS" for v in run.verifications)
    else:
        assert run.status in ("NEEDS_REPLAN", "BLOCKED")
    assert completion_ok(run) == (run.status == "COMPLETE")


# ===========================================================================
# bounded revision (T20.31)
# ===========================================================================

def test_partial_task_bounded_revision_recovers():
    orch, run = make_orch_run(WEB_GOAL, ["WEB_RESEARCH"])
    orch.step({"run": run, "now": NOW,
               "case": {"worker_behavior": {"t01": "partial"}}})

    assert len(run.revisions) == 1
    assert run.revisions[0]["task_id"] == "t01"
    assert run.revisions[0]["requested_by"] == "VERIFIER"
    assert run.budgets["consumed_revisions"] == 1
    assert any(e["event_type"] == "REVISION_REQUESTED" and
               e["task_id"] == "t01" for e in run.events)
    # the revision path re-ran the worker (default behavior) and re-verified
    assert run.tasks["t01"] == "SUCCEEDED"
    passed = [a for a in run.artifacts if a["task_id"] == "t01"
              and a["verification_status"] == "PASSED"]
    assert passed, "revised artifact was not re-verified"
    assert run.counters["unbounded_revision"] == 0
    assert run.counters["false_complete"] == 0


def test_revision_cap_per_task_exhausted_requests_replan():
    orch, run = make_orch_run(WEB_GOAL, ["WEB_RESEARCH"])
    # per-task revision bound already consumed (max 2 per task, T20.31)
    run.revisions = [{"task_id": "t01"}, {"task_id": "t01"}]
    run.budgets["consumed_revisions"] = 2

    drive(orch, run, case={"worker_behavior": {"t01": "partial"}})

    assert len(run.revisions) == 2, "revision beyond the per-task cap"
    assert run.budgets["consumed_revisions"] == 2
    assert run.status == "NEEDS_REPLAN"
    assert any(e["event_type"] == "PLAN_REPLAN_REQUESTED" and
               e["task_id"] == "t01" for e in run.events)
    assert run.counters["unbounded_revision"] == 0
    assert run.counters["unbounded_retry"] == 0


def test_zero_revision_allowance_is_honored():
    orch, run = make_orch_run(WEB_GOAL, ["WEB_RESEARCH"],
                              budget={"max_revisions": 0})
    drive(orch, run, case={"worker_behavior": {"t01": "partial"}})
    assert run.revisions == []
    assert run.budgets["consumed_revisions"] == 0
    assert run.status == "NEEDS_REPLAN"


def test_run_completes_after_successful_bounded_revision():
    orch, run = make_orch_run(WEB_GOAL, ["WEB_RESEARCH"])
    drive(orch, run, case={"worker_behavior": {"t01": "partial"}})
    assert run.tasks["t01"] == "SUCCEEDED"
    assert len(run.revisions) == 1
    drive(orch, run)
    assert run.status == "COMPLETE"
    assert completion_ok(run) is True
    assert run.counters["false_complete"] == 0


# ===========================================================================
# verifier independence (T20.9/T20.42)
# ===========================================================================

def test_verifier_independence_producer_never_verifies_own_artifact():
    orch, run = make_orch_run(SCI_GOAL, ["SCICOMP"])
    res = drive(orch, run)
    assert run.status == "COMPLETE"
    assert res.replay_ok is True
    roles = {a["agent_id"]: a["role"] for a in run.agents}
    assert run.verifications, "expected verified artifacts"
    for v in run.verifications:
        assert v["verifier_agent_id"] != v["producer_agent_id"]
        assert roles[v["verifier_agent_id"]] == "VERIFIER"


def test_mandatory_verification_flags_for_document_tasks():
    orch, run = make_orch_run(DOC_GOAL, ["DOCUMENT"])
    tasks = {t["task_id"]: t for t in run.plan["tasks"]}
    for t in tasks.values():
        assert verification_required_for(t) is True


# ===========================================================================
# budget exhaustion (T20.35)
# ===========================================================================

def test_message_budget_exhaustion_is_bounded_not_crashing():
    orch, run = make_orch_run(DOC_GOAL, ["DOCUMENT"],
                              budget={"max_messages": 3})
    res = drive(orch, run)

    assert any(e["event_type"] == "BUDGET_EXHAUSTED" and
               e["payload"].get("budget") == "messages" for e in run.events)
    assert run.budgets["consumed_messages"] == 3
    assert run.budgets["consumed_messages"] <= \
        run.budgets["max_messages"]
    assert len(run.messages) == 3
    # run still terminates cleanly; budgets were never reset
    assert run.status == "COMPLETE"
    assert run.counters["silent_budget_reset"] == 0
    assert res.replay_ok is True


# ===========================================================================
# identity spoof rejection (T20.37/T20.38)
# ===========================================================================

def test_identity_spoof_rejected_no_message_appended():
    orch, run = make_orch_run(MEM_GOAL, ["MEMORY"])
    worker = next(a for a in run.agents
                  if a["role"] == "MEMORY_CONTEXT_WORKER")
    n_msgs = len(run.messages)
    n_events = len(run.events)

    orch._message(run, "not-an-agent", worker["agent_id"], "ASSIGN", now=NOW)
    orch._message(run, "ghost", "also-ghost", "ASSIGN", now=NOW)

    assert run.counters["identity_spoof_acceptance"] == 2
    rejected = events_of_type(run, "MESSAGE_REJECTED")
    assert len(rejected) == 2
    assert rejected[0]["payload"]["sender"] == "not-an-agent"
    assert rejected[0]["payload"]["recipient"] == worker["agent_id"]
    assert len(run.messages) == n_msgs
    assert run.budgets["consumed_messages"] == 0
    assert len(run.events) == n_events + 2


# ===========================================================================
# deadlock guard (T20.28)
# ===========================================================================

def test_wait_cycle_blocks_run_with_deadlock():
    orch, run = make_orch_run(SCI_GOAL, ["SCICOMP"])
    run.locks = {"held": {"r1": {"t2": "WRITE"}, "r2": {"t1": "WRITE"}},
                 "waiting": {"t1": ["r1"], "t2": ["r2"]}}

    res = orch.step({"run": run, "now": NOW, "case": {}})

    assert res.blocked_reason == "deadlock"
    assert res.ok is False
    assert run.status == "BLOCKED"
    assert run.counters["accepted_deadlock"] == 1
    assert events_of_type(run, "DEADLOCK_DETECTED")
    assert events_of_type(run, "RUN_BLOCKED")
    # no task was executed under the cyclic lock state
    assert set(run.tasks.values()) == {"PENDING"}
    # any further step is refused on the now-terminal run
    res2 = orch.step({"run": run, "now": NOW, "case": {}})
    assert res2.ok is False
    assert res2.blocked_reason == "run already BLOCKED"


# ===========================================================================
# no compatible worker -> task blocked (T20.24/T20.26)
# ===========================================================================

def test_no_compatible_agent_defers_then_blocks_task():
    orch, run = make_orch_run(DOC_GOAL, ["DOCUMENT"])
    run.agents = [a for a in run.agents if a["role"] != "DOCUMENT_WORKER"]

    res = orch.step({"run": run, "now": NOW, "case": {}})

    assert run.tasks["t01"] == "BLOCKED"
    blocked = [e for e in run.events if e["event_type"] == "TASK_BLOCKED"
               and e["task_id"] == "t01"
               and e["payload"].get("reason") == "no_compatible_agent"]
    assert blocked, "TASK_BLOCKED event for no_compatible_agent missing"
    assert run.status == "BLOCKED"
    assert res.blocked_reason == "no_compatible_agent"


# ===========================================================================
# false-complete prevention (T20.48)
# ===========================================================================

def test_gate_blocks_unverified_mandatory_artifact():
    orch, run = make_orch_run(SCI_GOAL, ["SCICOMP"])
    drive(orch, run)
    assert run.status == "COMPLETE"
    assert completion_ok(run) is True

    # tamper: one mandatory verified artifact is back to PENDING
    run.status = "RUNNING"
    target = next(a for a in run.artifacts if a["verification_required"])
    target["verification_status"] = "PENDING"

    res = orch.step({"run": run, "now": NOW, "case": {}})

    assert run.status == "BLOCKED"
    assert res.blocked_reason == "unverified_mandatory_artifact"
    assert run.counters["self_verified_mandatory_acceptance"] == 1
    assert events_of_type(run, "RUN_BLOCKED")
    assert completion_ok(run) is False


# ===========================================================================
# abort + step-after-terminal (T20.55-adjacent guards)
# ===========================================================================

def test_abort_marks_run_and_further_steps_refused():
    orch, run = make_orch_run(MEM_GOAL, ["MEMORY"])
    res = orch.abort({"run": run, "now": NOW})
    assert res.run.status == "ABORTED"
    assert events_of_type(run, "RUN_ABORTED")

    res2 = orch.step({"run": run, "now": NOW, "case": {}})
    assert res2.ok is False
    assert res2.blocked_reason == "run already ABORTED"
    assert run.status == "ABORTED"


def test_step_after_complete_refused():
    orch, run = make_orch_run(MEM_GOAL, ["MEMORY"])
    drive(orch, run)
    assert run.status == "COMPLETE"
    res = orch.step({"run": run, "now": NOW, "case": {}})
    assert res.ok is False
    assert res.blocked_reason == "run already COMPLETE"


# ===========================================================================
# self-verification bypass claim (T20.68)
# ===========================================================================

def test_self_verify_claim_does_not_waive_verification():
    orch, run = make_orch_run(SCI_GOAL, ["SCICOMP"])
    # t03 has task_type "verify" -> mandatory verification
    drive(orch, run, case={"worker_behavior": {"t03": "self_verify_claim"}})

    rejected = [e for e in run.events if e["event_type"] == "MESSAGE_REJECTED"
                and "skip verifier" in str(e["payload"].get("claim", ""))
                and e["task_id"] == "t03"]
    assert rejected, "bypass claim not recorded as rejected data"
    # verification still ran independently and passed on facts
    t03_records = [v for v in run.verifications if v["task_id"] == "t03"]
    assert t03_records and all(v["decision"] == "PASS"
                               for v in t03_records)
    assert all(v["verifier_agent_id"] != v["producer_agent_id"]
               for v in run.verifications)
    assert run.status == "COMPLETE"
    assert run.counters["prompt_injection_success"] == 0


# ===========================================================================
# zero-tolerance invariant (T20.61)
# ===========================================================================

@pytest.mark.parametrize("goal,skills", [
    (SCI_GOAL, ["SCICOMP"]),
    (MEM_GOAL, ["MEMORY"]),
    (DOC_GOAL, ["DOCUMENT"]),
])
def test_well_behaved_runs_end_with_all_zero_tolerance_counters_zero(
        goal, skills):
    orch, run = make_orch_run(goal, skills)
    res = drive(orch, run)
    assert run.status == "COMPLETE"
    assert res.replay_ok is True
    assert res.ok is True
    for k in ZERO_TOLERANCE_KEYS:
        assert run.counters[k] == 0, f"zero-tolerance counter {k} != 0"
    assert completion_ok(run) is True