"""T20 assignment / locks / handoffs domain tests (deterministic)."""
import dataclasses

import pytest

from sciencemath.orchestration.assignment import (
    agent_for_skill,
    agents_for_role,
    assignable_batch,
    pick_verifier,
    ready_plan_tasks,
    reassignment_target,
    skill_permitted_agent,
    verification_required_for,
    worker_role_for_task,
)
from sciencemath.orchestration.handoffs import (
    MAX_HANDOFF_CYCLE,
    build_handoff,
    handoff_cycle_depth,
    validate_handoff,
)
from sciencemath.orchestration.locks import (
    LockTable,
    find_deadlock,
    resources_for_task,
    wait_for_graph,
)
from sciencemath.orchestration.models import Handoff

NOW = "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def mk_agent(agent_id, role, status="READY", allowed=None, denied=None,
             budget=None, paid=False):
    return {
        "agent_id": agent_id,
        "role": role,
        "status": status,
        "allowed_skills": list(allowed or []),
        "denied_skills": list(denied or []),
        "paid_compute_access": paid,
        "budget": budget if budget is not None
        else {"max_tasks": 3, "max_revisions": 2, "max_messages": 40},
    }


def mk_task(task_id, skill="CODE", status="PENDING", resources=None,
            optional=False, task_type="", criteria=None):
    t = {
        "task_id": task_id,
        "objective": "obj " + task_id,
        "title": "title " + task_id,
        "required_skill": skill,
        "status": status,
        "optional": optional,
        "success_criteria": list(criteria or ["crit-1"]),
    }
    if task_type:
        t["task_type"] = task_type
    if resources is not None:
        t["resources"] = resources
    return t


def mk_plan(tasks, deps=None, constraints=None):
    return {
        "plan_id": "plan_1",
        "plan_version": 1,
        "tasks": tasks,
        "dependencies": list(deps or []),
        "constraints": list(constraints or []),
    }


def mk_run(plan, task_status=None):
    return {
        "run_id": "run_1",
        "plan_id": "plan_1",
        "plan": plan,
        "tasks": dict(task_status or {}),
        "budgets": {"max_cost_class": "FREE", "max_tasks": 30},
        "artifacts": [],
        "handoffs": [],
    }


def default_agents():
    return {
        "ag_code_1": mk_agent("ag_code_1", "CODE_WORKER", allowed=["CODE"]),
        "ag_code_2": mk_agent("ag_code_2", "CODE_WORKER", allowed=["CODE"]),
        "ag_doc_1": mk_agent("ag_doc_1", "DOCUMENT_WORKER",
                             allowed=["DOCUMENT"]),
        "ag_web_1": mk_agent("ag_web_1", "WEB_RESEARCH_WORKER",
                             allowed=["WEB_RESEARCH"]),
        "ag_mem_1": mk_agent("ag_mem_1", "MEMORY_CONTEXT_WORKER",
                             allowed=["MEMORY"]),
        "ag_ver_1": mk_agent("ag_ver_1", "VERIFIER"),
        "ag_ver_2": mk_agent("ag_ver_2", "VERIFIER"),
    }


def deferred_by_task(deferred):
    return {d["task"]["task_id"]: d["reason"] for d in deferred}


# ---------------------------------------------------------------------------
# ready_plan_tasks
# ---------------------------------------------------------------------------
def test_ready_dependency_ordering():
    t1 = mk_task("t1")
    t2 = mk_task("t2")
    t3 = mk_task("t3")
    plan = mk_plan([t1, t2, t3], deps=[{"from": "t1", "to": "t2"}])
    assert [t["task_id"] for t in ready_plan_tasks(plan)] == ["t1", "t3"]
    t1["status"] = "SUCCEEDED"
    assert [t["task_id"] for t in ready_plan_tasks(plan)] == ["t2", "t3"]


def test_ready_excludes_blocked_by_dependency():
    t1 = mk_task("t1")
    t2 = mk_task("t2")
    plan = mk_plan([t1, t2], deps=[{"from": "t1", "to": "t2"}])
    assert [t["task_id"] for t in ready_plan_tasks(plan)] == ["t1"]
    # a FAILED dependency also blocks
    t1["status"] = "FAILED"
    assert ready_plan_tasks(plan) == []


def test_ready_excludes_optional():
    t1 = mk_task("t1")
    topt = mk_task("t_opt", optional=True)
    plan = mk_plan([t1, topt])
    ready = ready_plan_tasks(plan)
    assert [t["task_id"] for t in ready] == ["t1"]


def test_ready_accepts_pending_and_ready_statuses():
    tp = mk_task("t_p", status="PENDING")
    tr = mk_task("t_r", status="READY")
    ta = mk_task("t_a", status="ASSIGNED")
    plan = mk_plan([tp, tr, ta])
    ids = [t["task_id"] for t in ready_plan_tasks(plan)]
    assert ids == ["t_p", "t_r"]


def test_ready_deterministic_order():
    plan = mk_plan([mk_task("t3"), mk_task("t1"), mk_task("t2")])
    ids = [t["task_id"] for t in ready_plan_tasks(plan)]
    assert ids == ["t1", "t2", "t3"]


# ---------------------------------------------------------------------------
# agent selection
# ---------------------------------------------------------------------------
def test_agents_for_role_sorted_and_status_filtered():
    agents = default_agents()
    agents["ag_code_3"] = mk_agent("ag_code_3", "CODE_WORKER",
                                   status="DISABLED", allowed=["CODE"])
    agents["ag_doc_1"]["status"] = "BUSY"
    ids = [a["agent_id"] for a in agents_for_role(agents, "CODE_WORKER")]
    assert ids == ["ag_code_1", "ag_code_2"]
    assert [a["agent_id"] for a in agents_for_role(
        agents, "MEMORY_CONTEXT_WORKER")] == ["ag_mem_1"]
    assert agents_for_role(agents, "NO_SUCH_ROLE") == []


def test_agent_for_skill_deterministic_pick():
    agents = default_agents()
    a = agent_for_skill(agents, "CODE")
    assert a["agent_id"] == "ag_code_1"
    assert agent_for_skill(agents, "DOCUMENT")["agent_id"] == "ag_doc_1"
    assert worker_role_for_task({"required_skill": "CODE"}) == "CODE_WORKER"
    assert worker_role_for_task({"required_skill": "NOPE"}) is None


def test_agent_for_skill_exclude_and_none():
    agents = default_agents()
    assert agent_for_skill(agents, "CODE",
                           exclude={"ag_code_1"})["agent_id"] == "ag_code_2"
    assert agent_for_skill(agents, "CODE",
                           exclude={"ag_code_1", "ag_code_2"}) is None
    assert agent_for_skill(agents, "GENERAL") is None  # no SYNTHESIS worker


def test_agent_for_skill_skips_denied():
    agents = default_agents()
    agents["ag_code_1"]["denied_skills"] = ["CODE"]
    assert agent_for_skill(agents, "CODE")["agent_id"] == "ag_code_2"
    # every role-matched candidate denied -> None
    agents["ag_code_2"]["denied_skills"] = ["CODE"]
    assert agent_for_skill(agents, "CODE") is None


def test_skill_permitted_agent_direct():
    a = mk_agent("x", "CODE_WORKER", allowed=["CODE"], denied=["DOCUMENT"])
    assert skill_permitted_agent(a, "CODE")
    assert not skill_permitted_agent(a, "DOCUMENT")
    assert not skill_permitted_agent(a, "SCICOMP")  # not in allowed list


# ---------------------------------------------------------------------------
# assignable_batch
# ---------------------------------------------------------------------------
def test_batch_concurrency_cap():
    plan = mk_plan([mk_task("t1"), mk_task("t2"), mk_task("t3")])
    run = mk_run(plan)
    batch, deferred = assignable_batch(plan, default_agents(), run, {},
                                       max_concurrent=2)
    assert [b["task"]["task_id"] for b in batch] == ["t1", "t2"]
    assert deferred_by_task(deferred) == {"t3": "concurrency_limit"}


def test_batch_no_compatible_agent_deferral():
    plan = mk_plan([mk_task("t1", skill="GENERAL"), mk_task("t2",
                                                            skill="CODE")])
    run = mk_run(plan)
    batch, deferred = assignable_batch(plan, default_agents(), run, {},
                                       max_concurrent=3)
    assert [b["task"]["task_id"] for b in batch] == ["t2"]
    assert deferred_by_task(deferred) == {"t1": "no_compatible_agent"}


def test_batch_already_assigned_deferral():
    plan = mk_plan([mk_task("t1"), mk_task("t2"), mk_task("t3")])
    run = mk_run(plan, task_status={"t1": "ASSIGNED"})
    batch, deferred = assignable_batch(plan, default_agents(), run, {},
                                       max_concurrent=2)
    # t1 already in flight: deferred AND consumes a concurrency slot
    assert [b["task"]["task_id"] for b in batch] == ["t2"]
    assert deferred_by_task(deferred) == {
        "t1": "already_assigned", "t3": "concurrency_limit"}
    # RUNNING counts as in flight too
    run2 = mk_run(plan, task_status={"t1": "RUNNING"})
    batch2, deferred2 = assignable_batch(plan, default_agents(), run2, {},
                                         max_concurrent=1)
    assert batch2 == []
    assert deferred_by_task(deferred2) == {
        "t1": "already_assigned", "t2": "concurrency_limit",
        "t3": "concurrency_limit"}


def test_batch_budget_exhausted_deferral():
    agents = default_agents()
    agents["ag_code_1"]["budget"] = {"max_tasks": 0}
    plan = mk_plan([mk_task("t1")])
    run = mk_run(plan)
    batch, deferred = assignable_batch(plan, agents, run, {},
                                       max_concurrent=3)
    assert batch == []
    assert deferred_by_task(deferred) == {"t1": "agent_budget_exhausted"}


def test_batch_write_conflict_within_batch():
    res = [{"resource_id": "repo:main", "kind": "WRITE"}]
    plan = mk_plan([mk_task("t1", resources=res),
                    mk_task("t2", resources=res)])
    run = mk_run(plan)
    batch, deferred = assignable_batch(plan, default_agents(), run, {},
                                       max_concurrent=3)
    assert [b["task"]["task_id"] for b in batch] == ["t1"]
    # batch-acquired WRITE lands in lock_held, so the conflict is reported
    # against the holder (batch_write_conflict branch is shadowed)
    assert deferred_by_task(deferred) == {
        "t2": "resource_conflict:repo:main:t1"}


# ---------------------------------------------------------------------------
# resource conflicts across batches / lock_held
# ---------------------------------------------------------------------------
def test_batch_read_read_coexist():
    res = [{"resource_id": "repo:main", "kind": "READ"}]
    plan = mk_plan([mk_task("t1", resources=res),
                    mk_task("t2", resources=res)])
    run = mk_run(plan)
    batch, deferred = assignable_batch(plan, default_agents(), run, {},
                                       max_concurrent=3)
    assert [b["task"]["task_id"] for b in batch] == ["t1", "t2"]
    assert deferred == []


def test_batch_read_write_serialize():
    w = [{"resource_id": "repo:main", "kind": "WRITE"}]
    r = [{"resource_id": "repo:main", "kind": "READ"}]
    # WRITE first (sorted task order): READ task deferred in-batch
    plan = mk_plan([mk_task("t1", resources=w), mk_task("t2", resources=r)])
    run = mk_run(plan)
    batch, deferred = assignable_batch(plan, default_agents(), run, {},
                                       max_concurrent=3)
    assert [b["task"]["task_id"] for b in batch] == ["t1"]
    assert list(deferred_by_task(deferred)) == ["t2"]
    # READ first: WRITE task conflicts against the batch-acquired READ lock
    plan2 = mk_plan([mk_task("t1", resources=r), mk_task("t2", resources=w)])
    run2 = mk_run(plan2)
    batch2, deferred2 = assignable_batch(plan2, default_agents(), run2, {},
                                         max_concurrent=3)
    assert [b["task"]["task_id"] for b in batch2] == ["t1"]
    assert list(deferred_by_task(deferred2)) == ["t2"]
    assert deferred2[0]["reason"].startswith("resource_conflict:repo:main:")


def test_batch_lock_held_updated_and_cross_batch_conflict():
    res = [{"resource_id": "repo:main", "kind": "WRITE"}]
    plan = mk_plan([mk_task("t1", resources=res)])
    run = mk_run(plan)
    lock_held = {}
    batch, _ = assignable_batch(plan, default_agents(), run, lock_held,
                                max_concurrent=3)
    assert len(batch) == 1
    assert lock_held["repo:main"] == {"t1": "WRITE"}
    # a later batch on the same resource must conflict with the held WRITE
    plan2 = mk_plan([mk_task("t9", resources=res)])
    run2 = mk_run(plan2)
    batch2, deferred2 = assignable_batch(plan2, default_agents(), run2,
                                         lock_held, max_concurrent=3)
    assert batch2 == []
    assert deferred_by_task(deferred2) == {
        "t9": "resource_conflict:repo:main:t1"}


# ---------------------------------------------------------------------------
# resources_for_task
# ---------------------------------------------------------------------------
def test_resources_explicit_win():
    t = mk_task("t1", skill="CODE",
                resources=[{"resource_id": "custom:1", "kind": "WRITE"}])
    assert resources_for_task(t) == [{"resource_id": "custom:1",
                                      "kind": "WRITE"}]


def test_resources_skill_fallback_scopes():
    assert resources_for_task(mk_task("t1", skill="CODE")) == [
        {"resource_id": "repository_fixture:t1", "kind": "READ"}]
    assert resources_for_task(mk_task("t2", skill="DOCUMENT")) == [
        {"resource_id": "document_fixture:t2", "kind": "READ"}]
    assert resources_for_task(mk_task("t3", skill="MEMORY")) == [
        {"resource_id": "memory_scope:t3", "kind": "READ"}]
    assert resources_for_task(mk_task("t4", skill="SCICOMP")) == [
        {"resource_id": "artifact:t4", "kind": "READ"}]


def test_resources_string_entry_becomes_write():
    t = mk_task("t1", resources=["db:main"])
    assert resources_for_task(t) == [{"resource_id": "db:main",
                                      "kind": "WRITE"}]


# ---------------------------------------------------------------------------
# LockTable
# ---------------------------------------------------------------------------
def test_lock_write_write_conflict():
    table = LockTable()
    res = [{"resource_id": "repo:main", "kind": "WRITE"}]
    assert table.acquire("t1", res) == ""
    assert table.acquire("t2", res) == "resource_conflict:repo:main:t1"


def test_lock_read_write_conflict_and_read_read_ok():
    table = LockTable()
    read = [{"resource_id": "repo:main", "kind": "READ"}]
    write = [{"resource_id": "repo:main", "kind": "WRITE"}]
    # READ + READ coexist
    assert table.acquire("t1", read) == ""
    assert table.acquire("t2", read) == ""
    # READ holder blocks a WRITE
    assert table.acquire("t3", write) == "resource_conflict:repo:main:t1"
    # fresh table: WRITE holder blocks a READ too
    table2 = LockTable()
    assert table2.acquire("t1", write) == ""
    assert table2.acquire("t2", read) == "resource_conflict:repo:main:t1"


def test_lock_reacquire_same_task_and_release():
    table = LockTable()
    res = [{"resource_id": "repo:main", "kind": "WRITE"}]
    assert table.acquire("t1", res) == ""
    assert table.acquire("t1", res) == ""   # same task may re-acquire
    table.release("t1", res)
    assert table.held == {}
    assert table.acquire("t2", res) == ""
    # release_all clears everything for the task (and its waiting entry)
    table.mark_waiting("t2", [{"resource_id": "other:x"}])
    table.release_all("t2")
    assert table.held == {}
    assert table.waiting == {}


def test_lock_invalid_kind():
    table = LockTable()
    bad = [{"resource_id": "repo:main", "kind": "EXEC"}]
    assert table.acquire("t1", bad) == "invalid lock kind 'EXEC'"
    assert table.held == {}


def test_lock_snapshot_roundtrip():
    table = LockTable()
    table.acquire("t1", [{"resource_id": "repo:main", "kind": "WRITE"}])
    table.mark_waiting("t2", [{"resource_id": "doc:1"}])
    snap = table.snapshot()
    table2 = LockTable()
    table2.load_snapshot(snap)
    assert table2.snapshot() == snap
    assert table2.held["repo:main"] == {"t1": "WRITE"}
    assert table2.waiting["t2"] == ["doc:1"]
    # loading an empty snapshot clears state
    table2.load_snapshot({})
    assert table2.held == {} and table2.waiting == {}


# ---------------------------------------------------------------------------
# deadlock detection
# ---------------------------------------------------------------------------
def test_find_deadlock_two_cycle():
    edges = {"tA": {"tB"}, "tB": {"tA"}}
    cycle = find_deadlock(edges)
    assert cycle is not None
    assert set(cycle) == {"tA", "tB"}


def test_find_deadlock_chain_no_cycle():
    assert find_deadlock({"tA": {"tB"}, "tB": set()}) is None
    assert find_deadlock({}) is None


def test_wait_for_graph_and_deadlock_via_locktable():
    table = LockTable()
    table.acquire("t1", [{"resource_id": "doc:1", "kind": "WRITE"}])
    table.acquire("t2", [{"resource_id": "repo:main", "kind": "WRITE"}])
    # each task now waits on the resource the other holds
    table.mark_waiting("t1", [{"resource_id": "repo:main"}])
    table.mark_waiting("t2", [{"resource_id": "doc:1"}])
    edges = wait_for_graph(table)
    assert edges == {"t2": {"t1"}, "t1": {"t2"}}
    cycle = find_deadlock(edges)
    assert cycle is not None and set(cycle) == {"t1", "t2"}
    # chain without cycle -> no deadlock
    table3 = LockTable()
    table3.acquire("t1", [{"resource_id": "r:1", "kind": "WRITE"}])
    table3.mark_waiting("t2", [{"resource_id": "r:1"}])
    assert find_deadlock(wait_for_graph(table3)) is None


# ---------------------------------------------------------------------------
# verification_required_for / pick_verifier / reassignment_target
# ---------------------------------------------------------------------------
def test_verification_required_for_mandatory_skills():
    for skill in ("CODE", "WEB_RESEARCH", "DOCUMENT"):
        assert verification_required_for({"required_skill": skill}) is True
    for skill in ("SCICOMP", "MEMORY", "GENERAL", "MATH_T4"):
        assert verification_required_for(
            {"required_skill": skill}) is False


def test_verification_required_for_task_types_override():
    for ttype in ("code", "verify", "synthesis", "test", "freshness"):
        assert verification_required_for(
            {"required_skill": "SCICOMP", "task_type": ttype}) is True
    # exempt skill + no task_type stays False
    assert verification_required_for(
        {"required_skill": "MEMORY", "task_type": ""}) is False


def test_pick_verifier_never_producer_and_cap():
    agents = default_agents()
    v = pick_verifier(agents, "ag_code_1", [])
    assert v["agent_id"] == "ag_ver_1"
    v2 = pick_verifier(agents, "ag_code_1", ["ag_ver_1"])
    assert v2["agent_id"] == "ag_ver_2"
    # cap MAX_CONCURRENT_VERIFIERS = 2
    assert pick_verifier(agents, "ag_code_1",
                         ["ag_ver_1", "ag_ver_2"]) is None
    # a VERIFIER producer is never handed its own artifact
    v3 = pick_verifier(agents, "ag_ver_1", [])
    assert v3["agent_id"] == "ag_ver_2"


def test_pick_verifier_excludes_non_ready():
    agents = default_agents()
    agents["ag_ver_1"]["status"] = "BUSY"
    agents["ag_ver_2"]["status"] = "FAILED"
    assert pick_verifier(agents, "ag_code_1", []) is None


def test_reassignment_target_same_role_and_exclude():
    agents = default_agents()
    agents["ag_code_1"]["status"] = "FAILED"
    t = reassignment_target(agents, "CODE", {"ag_code_1"})
    assert t["agent_id"] == "ag_code_2"
    # no alternative -> None; a different-role agent is never chosen
    assert reassignment_target(
        agents, "CODE", {"ag_code_1", "ag_code_2"}) is None
    # BUSY alternative is not eligible
    agents2 = default_agents()
    agents2["ag_code_1"]["status"] = "FAILED"
    agents2["ag_code_2"]["status"] = "BUSY"
    assert reassignment_target(agents2, "CODE", {"ag_code_1"}) is None


# ---------------------------------------------------------------------------
# build_handoff / validate_handoff / handoff_cycle_depth
# ---------------------------------------------------------------------------
def test_build_handoff_carries_full_contract():
    plan = mk_plan([mk_task("t1", skill="CODE",
                            criteria=["crit-a", "crit-b"])],
                   constraints=["no_network", "free_tier"])
    run = mk_run(plan)
    run["plan_id"] = "plan_9"
    run["plan"]["plan_version"] = 3
    run["budgets"] = {"max_cost_class": "FREE", "max_tasks": 30}
    from_a = {"agent_id": "ag_code_1", "role": "CODE_WORKER"}
    to_a = {"agent_id": "ag_code_2", "role": "CODE_WORKER",
            "budget": {"max_tasks": 6, "max_revisions": 2,
                       "max_messages": 40}}
    h = build_handoff(run, plan["tasks"][0], from_a, to_a, now=NOW)
    assert isinstance(h, Handoff)
    assert h.from_agent == "ag_code_1" and h.to_agent == "ag_code_2"
    assert h.task_id == "t1"
    assert h.objective == "obj t1"
    assert h.constraints == ["no_network", "free_tier"]
    assert h.success_criteria == ["crit-a", "crit-b"]
    assert h.remaining_budget["max_cost_class"] == "FREE"
    assert h.remaining_budget["agent"] == {"max_tasks": 6,
                                           "max_revisions": 2,
                                           "max_messages": 40}
    assert h.provenance["plan_id"] == "plan_9"
    assert h.provenance["plan_version"] == 3
    assert h.provenance["from_role"] == "CODE_WORKER"
    assert h.provenance["to_role"] == "CODE_WORKER"
    assert h.provenance["assigned_at"] == NOW
    # deterministic id: same inputs -> same id; different now -> different
    h2 = build_handoff(run, plan["tasks"][0], from_a, to_a, now=NOW)
    assert h2.handoff_id == h.handoff_id
    h3 = build_handoff(run, plan["tasks"][0], from_a, to_a,
                       now="2026-01-02T00:00:00Z")
    assert h3.handoff_id != h.handoff_id


def _valid_handoff_setup():
    plan = mk_plan([mk_task("t1", skill="CODE", criteria=["crit-1"])],
                   constraints=["c1"])
    run = mk_run(plan)
    run["budgets"] = {"max_cost_class": "FREE"}
    task = plan["tasks"][0]
    from_a = {"agent_id": "ag_code_1", "role": "CODE_WORKER"}
    to_a = mk_agent("ag_code_2", "CODE_WORKER", allowed=["CODE"])
    agents = {"ag_code_1": from_a, "ag_code_2": to_a}
    h = build_handoff(run, task, from_a, to_a, now=NOW)
    return run, task, h, agents


def test_validate_handoff_happy_path():
    run, task, h, agents = _valid_handoff_setup()
    assert validate_handoff(run, h, task, agents) == []


def test_validate_handoff_unknown_and_lacks_skill():
    run, task, h, agents = _valid_handoff_setup()
    ghost = dataclasses.replace(h, to_agent="ghost")
    assert validate_handoff(run, ghost, task, agents) == \
        ["unknown_target_agent"]
    doc_target = mk_agent("ag_doc_1", "DOCUMENT_WORKER", allowed=["DOCUMENT"])
    agents2 = dict(agents)
    agents2["ag_doc_1"] = doc_target
    wrong_skill = dataclasses.replace(h, to_agent="ag_doc_1")
    errs = validate_handoff(run, wrong_skill, task, agents2)
    assert "target_lacks_skill:CODE" in errs


def test_validate_handoff_task_status_and_paid_target():
    run, task, h, agents = _valid_handoff_setup()
    run_succeeded = dict(run, tasks={"t1": "SUCCEEDED"})
    errs = validate_handoff(run_succeeded, h, task, agents)
    assert "task_already_succeeded" in errs
    paid = mk_agent("ag_paid", "CODE_WORKER", allowed=["CODE"], paid=True)
    agents_p = dict(agents)
    agents_p["ag_paid"] = paid
    errs2 = validate_handoff(run, dataclasses.replace(h, to_agent="ag_paid"),
                             task, agents_p)
    assert "target_paid_access_forbidden" in errs2


def test_validate_handoff_budget_and_artifacts():
    run, task, h, agents = _valid_handoff_setup()
    # non-FREE remaining budget -> budget_invalid
    run_std = dict(run, budgets={"max_cost_class": "STD"})
    from_a = {"agent_id": "ag_code_1", "role": "CODE_WORKER"}
    h_std = build_handoff(run_std, task, from_a,
                          agents["ag_code_2"], now=NOW)
    assert "budget_invalid" in validate_handoff(run_std, h_std, task, agents)
    # unknown artifact ref
    h_art = dataclasses.replace(h, artifact_refs=["art_ghost"])
    errs = validate_handoff(run, h_art, task, agents)
    assert "required_artifact_missing:art_ghost" in errs
    # known artifact ref is accepted
    run_art = dict(run, artifacts=[{"artifact_id": "art_x",
                                    "task_id": "t0"}])
    h_art2 = dataclasses.replace(h, artifact_refs=["art_x"])
    assert "required_artifact_missing:art_x" not in validate_handoff(
        run_art, h_art2, task, agents)


def test_validate_handoff_dropped_fields_and_provenance():
    run, task, h, agents = _valid_handoff_setup()
    bare = Handoff(
        handoff_id="hnd_x", from_agent="ag_code_1", to_agent="ag_code_2",
        task_id="t1", objective="obj t1", inputs=[], artifact_refs=[],
        constraints=[], success_criteria=[], remaining_budget={},
        provenance={})
    errs = validate_handoff(run, bare, task, agents)
    assert "constraint_set_incomplete" in errs
    assert "success_criteria_incomplete" in errs
    assert "provenance_incomplete" in errs
    # restoring the dropped fields (provenance excepted) clears those errors
    h2 = dataclasses.replace(bare, constraints=["c1"],
                             success_criteria=["crit-1"])
    errs2 = validate_handoff(run, h2, task, agents)
    assert "constraint_set_incomplete" not in errs2
    assert "success_criteria_incomplete" not in errs2
    assert errs2 == ["provenance_incomplete"]


def test_handoff_cycle_depth_bounded_and_validate_rejects():
    chain = [{"from_agent": "a1", "to_agent": "a2"},
             {"from_agent": "a2", "to_agent": "a3"},
             {"from_agent": "a3", "to_agent": "a4"},
             {"from_agent": "a4", "to_agent": "a5"}]
    run = {"handoffs": chain, "tasks": {}, "plan": {},
           "artifacts": [], "budgets": {}, "plan_id": "p1"}
    # forward walk from the named agent: a1 hands off through a chain of 4
    assert handoff_cycle_depth(run, "a1") == 4
    assert handoff_cycle_depth(run, "a5") == 0
    # an acyclic chain stays within MAX_HANDOFF_CYCLE
    assert handoff_cycle_depth(run, "a2") == 3
    # a cycle pushes depth beyond MAX_HANDOFF_CYCLE -> validate rejects
    cyclic = chain + [{"from_agent": "a5", "to_agent": "a1"}]
    run_c = dict(run, handoffs=cyclic)
    depth = handoff_cycle_depth(run_c, "a5")
    assert depth > MAX_HANDOFF_CYCLE
    plan = mk_plan([mk_task("t1", skill="CODE", criteria=["crit-1"])],
                   constraints=["c1"])
    task = plan["tasks"][0]
    from_a = {"agent_id": "a1", "role": "CODE_WORKER"}
    to_a = mk_agent("a5", "CODE_WORKER", allowed=["CODE"])
    run_v = dict(run_c, plan=plan, plan_id="p1")
    h = build_handoff(run_v, task, from_a, to_a, now=NOW)
    agents = {"a1": from_a, "a5": to_a}
    errs = validate_handoff(run_v, h, task, agents)
    assert "handoff_cycle_exceeds_limit" in errs