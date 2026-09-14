"""T20 recovery / checkpoint / events / serialize domain tests.

Covers: failure classification (12-class taxonomy), recovery actions,
bounded revisions, livelock fingerprints/detection, completed-work
preservation, descendant closure, per-agent failure bound, run
checkpointer roundtrip, resume integrity, crash consistency, the
append-only event log, deterministic reduction / replay equivalence,
and canonical run serialization.
Deterministic: fixed NOW everywhere; no network, no sleep, no wall clock.
"""
from __future__ import annotations

import pytest

from sciencemath.orchestration.contract import FAILURE_CLASSES
from sciencemath.orchestration.recovery import (
    RECOVERY_ACTIONS,
    agent_failed_ok_to_recover,
    bounded_revision_ok,
    classify_failure,
    descendants_of,
    livelock_detected,
    livelock_fingerprint,
    recovery_action,
    unrelated_completed_work_loss,
)
from sciencemath.orchestration.checkpoint import (
    RunCheckpointer,
    crash_consistency_check,
    resume_integrity as ckpt_resume_integrity,
)
from sciencemath.orchestration.events import (
    EventLog,
    log_hash,
    reduce_events,
    replay_equivalent,
)
from sciencemath.orchestration.models import OrchestrationRun
from sciencemath.orchestration.serialize import (
    RunSchemaError,
    dumps,
    loads,
    resume_integrity as ser_resume_integrity,
    run_hash,
)

NOW = "2026-01-01T00:00:00Z"


def make_run(run_id: str = "run_t20domain", **overrides) -> OrchestrationRun:
    base = dict(
        run_id=run_id,
        plan_id="plan_t20domain",
        run_version=1,
        status="RUNNING",
        started_at=NOW,
        updated_at=NOW,
    )
    base.update(overrides)
    return OrchestrationRun(**base)


# ===========================================================================
# classify_failure (T20.32)
# ===========================================================================

@pytest.mark.parametrize(
    "blob,expected",
    [
        ("timeout waiting for worker", "AGENT_CRASH"),
        ("worker crashed mid-task", "AGENT_CRASH"),
        ("verification mismatch on criterion", "VERIFICATION_FAIL"),
        ("policy violation detected", "POLICY_BLOCK"),
        ("budget exhausted for step", "BUDGET_EXCEEDED"),
        ("artifact missing from submission", "MISSING_ARTIFACT"),
        ("conflict on write lock", "RESOURCE_CONFLICT"),
        ("capability not available", "CAPABILITY_MISMATCH"),
        ("skill not permitted", "CAPABILITY_MISMATCH"),
        ("invalid payload shape", "INVALID_INPUT"),
        ("schema validation failed", "INVALID_INPUT"),
    ],
)
def test_classify_failure_keyword_hints(blob, expected):
    assert classify_failure({"errors": [blob]}) == expected


def test_classify_failure_explicit_failure_class_honored():
    res = {"result_status": "FAILED", "failure_class": "PERMANENT"}
    assert classify_failure(res) == "PERMANENT"


def test_classify_failure_context_class_override():
    res = {"result_status": "FAILED", "errors": ["timeout"]}
    # context override wins over error keywords
    assert classify_failure(res, {"class": "DEPENDENCY_FAIL"}) == \
        "DEPENDENCY_FAIL"
    # context class outside the taxonomy falls back safely
    assert classify_failure(res, {"class": "NOT_A_CLASS"}) == "UNKNOWN"


def test_classify_failure_result_status_failed_defaults():
    assert classify_failure({"result_status": "FAILED"}) == "TRANSIENT"
    assert classify_failure(
        {"result_status": "FAILED"}, {"default": "PERMANENT"}) == "PERMANENT"


def test_classify_failure_unknown_when_no_hints():
    assert classify_failure({}) == "UNKNOWN"
    assert classify_failure({"result_status": "OK"}) == "UNKNOWN"


# ===========================================================================
# RECOVERY_ACTIONS (T20.32)
# ===========================================================================

def test_every_failure_class_has_recovery_action():
    for fc in FAILURE_CLASSES:
        assert fc in RECOVERY_ACTIONS, f"missing action for {fc}"
        assert isinstance(recovery_action(fc), str) and recovery_action(fc)


def test_recovery_action_unknown_class_falls_back_safely():
    assert recovery_action("NOT_IN_TAXONOMY") == "block_or_replan"


# ===========================================================================
# bounded_revision_ok (T20.31)
# ===========================================================================

def test_bounded_revision_two_allowed_third_refused():
    run = {
        "revisions": [{"task_id": "t1"}, {"task_id": "t1"}],
        "budgets": {"consumed_revisions": 2, "max_revisions": 12},
    }
    # 0 used -> allowed; 1 used -> allowed; 2 used -> refused
    assert bounded_revision_ok({"revisions": [], "budgets": run["budgets"]},
                               "t1")
    assert bounded_revision_ok({"revisions": run["revisions"][:1],
                                "budgets": run["budgets"]}, "t1")
    assert not bounded_revision_ok(run, "t1")


def test_bounded_revision_global_budget_cap():
    run = {
        "revisions": [],  # fresh task, nothing used per-task
        "budgets": {"consumed_revisions": 12, "max_revisions": 12},
    }
    assert not bounded_revision_ok(run, "t_fresh")
    run["budgets"]["consumed_revisions"] = 11
    assert bounded_revision_ok(run, "t_fresh")


# ===========================================================================
# livelock fingerprint / detection (T20.29)
# ===========================================================================

def _livelock_run(**overrides) -> dict:
    run = {
        "plan": {
            "plan_version": 3,
            "tasks": [
                {"task_id": "t1", "status": "RUNNING"},
                {"task_id": "t2", "status": "PENDING"},
            ],
        },
        "revisions": [{"task_id": "t1"}],
        "budgets": {"consumed_replans": 1},
        "steps": 17,
    }
    run.update(overrides)
    return run


def test_fingerprint_excludes_steps():
    assert livelock_fingerprint(_livelock_run()) == \
        livelock_fingerprint(_livelock_run(steps=999))


def test_fingerprint_identical_runs_identical():
    assert livelock_fingerprint(_livelock_run()) == \
        livelock_fingerprint(_livelock_run())


def test_fingerprint_changes_on_state_changes():
    base = livelock_fingerprint(_livelock_run())
    # status change
    r = _livelock_run()
    r["plan"]["tasks"][0]["status"] = "SUCCEEDED"
    assert livelock_fingerprint(r) != base
    # plan_version change
    r = _livelock_run()
    r["plan"]["plan_version"] = 4
    assert livelock_fingerprint(r) != base
    # revisions change
    assert livelock_fingerprint(_livelock_run(revisions=[])) != base
    # replans change
    r = _livelock_run()
    r["budgets"]["consumed_replans"] = 2
    assert livelock_fingerprint(r) != base


def test_livelock_detected_three_identical_fingerprints():
    run = _livelock_run()
    fp = livelock_fingerprint(run)
    run["fingerprints"] = [fp, fp]
    assert livelock_detected(run) is True


def test_livelock_detected_false_for_two_or_differing():
    run = _livelock_run()
    fp = livelock_fingerprint(run)
    # only 2 identical in history -> below limit
    run["fingerprints"] = [fp]
    assert livelock_detected(run) is False
    # 3 in tail but one differs
    other_run = _livelock_run()
    other_run["plan"]["plan_version"] = 4
    other = livelock_fingerprint(other_run)
    assert other != fp
    run["fingerprints"] = [fp, other]
    assert livelock_detected(run) is False


# ===========================================================================
# completed-work preservation / descendants / agent failure bound
# ===========================================================================

def _dep_plan(tasks, deps) -> dict:
    return {"tasks": tasks, "dependencies": deps}


def test_descendants_of_transitive_closure():
    plan = _dep_plan(
        [{"task_id": t} for t in ("t1", "t2", "t3", "t4")],
        [{"from": "t1", "to": "t2"}, {"from": "t2", "to": "t3"}],
    )
    assert descendants_of(plan, "t1") == {"t2", "t3"}
    assert descendants_of(plan, "t4") == set()
    assert descendants_of(plan, "t3") == set()


def test_unrelated_completed_work_loss_counts_only_outside_subtree():
    def plan_with(t1, t2, t3):
        return _dep_plan(
            [{"task_id": "t1", "status": t1},
             {"task_id": "t2", "status": t2},
             {"task_id": "t3", "status": t3}],
            [{"from": "t1", "to": "t2"}],
        )

    before = plan_with("SUCCEEDED", "SUCCEEDED", "SUCCEEDED")
    # replan invalidates t1 (and its dependent t2); t3 untouched
    after = plan_with("INVALIDATED", "INVALIDATED", "SUCCEEDED")
    # t1 itself is allowed to change via changed_id, t2 via descendants
    assert unrelated_completed_work_loss(before, after, "t1") == 0
    # a change that also drops unrelated t3 loses exactly that one task
    after_bad = plan_with("INVALIDATED", "INVALIDATED", "FAILED")
    assert unrelated_completed_work_loss(before, after_bad, "t1") == 1


def test_agent_failed_ok_to_recover_boundary():
    def run_with_fails(agent_id, n):
        return {"assignments": [{"agent_id": agent_id, "status": "FAILED"}
                                for _ in range(n)]}

    assert agent_failed_ok_to_recover(run_with_fails("a1", 0), "a1")
    assert agent_failed_ok_to_recover(run_with_fails("a1", 2), "a1")
    # boundary at max_failed=3: the 3rd failure blocks further recovery
    assert not agent_failed_ok_to_recover(run_with_fails("a1", 3), "a1")
    # other agents' failures do not count
    assert agent_failed_ok_to_recover(run_with_fails("a2", 5), "a1")
    # non-FAILED assignment statuses are not failures
    assert agent_failed_ok_to_recover(
        {"assignments": [{"agent_id": "a1", "status": "SUCCEEDED"}] * 5},
        "a1")


# ===========================================================================
# RunCheckpointer (T20.71)
# ===========================================================================

def _populated_run() -> OrchestrationRun:
    run = make_run()
    run.tasks = {"t1": "SUCCEEDED", "t2": "RUNNING"}
    run.agents = [{"agent_id": "a1", "role": "SCICOMP_WORKER"},
                  {"agent_id": "a2", "role": "VERIFIER"}]
    run.budgets["consumed_messages"] = 7
    run.budgets["consumed_revisions"] = 1
    run.artifacts = [{"artifact_id": "ar1", "task_id": "t1"}]
    run.events = [{"event_id": "ev-000001", "event_type": "TASK_ASSIGNED"},
                  {"event_id": "ev-000002", "event_type": "TASK_COMPLETED"}]
    return run


def test_checkpoint_save_writes_file_and_load_roundtrip(tmp_path):
    ckpt = RunCheckpointer(tmp_path)
    run = _populated_run()
    name = ckpt.save(run, {"locks": {"t1": "a1"}}, reason="step", now=NOW)
    assert name == f"{run.run_id}.ckpt.json"
    assert (tmp_path / name).exists()

    loaded, locks = ckpt.load(run.run_id)
    assert locks == {"locks": {"t1": "a1"}}
    assert loaded.run_id == run.run_id
    assert loaded.plan_id == run.plan_id
    assert loaded.tasks == run.tasks
    assert loaded.agents == run.agents
    assert loaded.artifacts == run.artifacts
    assert loaded.budgets["consumed_messages"] == 7
    assert loaded.budgets["consumed_revisions"] == 1
    assert len(loaded.events) == len(run.events) == 2
    # faithful roundtrip passes resume integrity
    assert ckpt_resume_integrity(run, loaded) == []


def test_checkpoint_load_missing_returns_none(tmp_path):
    assert RunCheckpointer(tmp_path).load("run_never_saved") is None


# ===========================================================================
# resume_integrity (checkpoint.py, T20.72)
# ===========================================================================

def test_resume_integrity_faithful_copy_is_clean():
    saved = _populated_run()
    loaded = OrchestrationRun.from_dict(saved.to_dict())
    assert ckpt_resume_integrity(saved, loaded) == []


@pytest.mark.parametrize(
    "mutation,violation",
    [
        (lambda r: r.tasks.pop("t1"), "lost_completed_tasks"),
        (lambda r: r.budgets.__setitem__("consumed_messages", 0),
         "budget_reset"),
        (lambda r: r.budgets.__setitem__("consumed_revisions", 0),
         "budget_reset"),
        (lambda r: r.events.__setitem__(slice(None), r.events[:1]),
         "event_log_truncated"),
        (lambda r: r.agents.__setitem__(slice(None), []), "ghost_agents"),
        (lambda r: r.__setattr__("run_id", "run_other"), "run_id_changed"),
    ],
)
def test_resume_integrity_detects_mutations(mutation, violation):
    saved = _populated_run()
    loaded = OrchestrationRun.from_dict(saved.to_dict())
    mutation(loaded)
    assert violation in ckpt_resume_integrity(saved, loaded)


# ===========================================================================
# crash_consistency_check (T20.74)
# ===========================================================================

def test_crash_consistency_duplicate_completion_detected():
    after = {"completed_events": ["t1", "t1", "t2"],
             "budgets": {"consumed_messages": 3}}
    errs = crash_consistency_check({}, after)
    assert errs == ["duplicate_task_completion:t1"]


def test_crash_consistency_clean_and_corrupt_budget():
    clean = crash_consistency_check(
        {}, {"completed_events": ["t1", "t2"],
             "budgets": {"consumed_messages": 2}})
    assert clean == []
    corrupt = crash_consistency_check(
        {}, {"completed_events": [], "budgets": {"consumed_messages": None}})
    assert "corrupted_budget" in corrupt


# ===========================================================================
# EventLog (T20.17/T20.18)
# ===========================================================================

def test_event_log_deterministic_event_ids():
    log_a, log_b = EventLog(), EventLog()
    run_a, run_b = make_run(), make_run()
    for log, run in ((log_a, run_a), (log_b, run_b)):
        log.append(run, "orchestrator", "AGENT_CREATED",
                   payload={"agent_id": "a1"}, now=NOW)
        log.append(run, "orchestrator", "TASK_ASSIGNED", task_id="t1",
                   payload={"agent_id": "a1"}, now=NOW)
    ids_a = [e["event_id"] for e in log_a.events]
    ids_b = [e["event_id"] for e in log_b.events]
    assert ids_a == ids_b == [
        f"ev-{run_a.run_id[:16]}-000001",
        f"ev-{run_a.run_id[:16]}-000002",
    ]


def test_event_log_unknown_type_raises_and_appends_to_run():
    run = make_run()
    log = EventLog()
    with pytest.raises(ValueError):
        log.append(run, "orchestrator", "NOT_AN_EVENT", now=NOW)
    ev = log.append(run, "orchestrator", "TASK_ASSIGNED", task_id="t1",
                    payload={"agent_id": "a1"}, now=NOW)
    assert run.events == [ev]
    assert run.event_seq == 1
    assert log.event_ids_unique() is True


def test_log_hash_stable_and_changes_with_events():
    run_a, run_b = make_run(), make_run()
    log_a, log_b = EventLog(), EventLog()
    for log, run in ((log_a, run_a), (log_b, run_b)):
        log.append(run, "orchestrator", "AGENT_CREATED",
                   payload={"agent_id": "a1"}, now=NOW)
    assert log_hash(run_a) == log_hash(run_b)
    log_b.append(run_b, "orchestrator", "TASK_ASSIGNED", task_id="t1",
                 now=NOW)
    assert log_hash(run_b) != log_hash(run_a)


# ===========================================================================
# reduce_events (T20.19)
# ===========================================================================

RID = "run_reduce"


def _ev(event_type, task_id="", **payload) -> dict:
    return {"run_id": RID, "event_type": event_type,
            "task_id": task_id, "payload": payload,
            "timestamp": NOW, "actor_id": "orchestrator",
            "event_id": f"ev-{len(payload)}"}


def test_reduce_events_reconstructs_full_state():
    events = [
        _ev("AGENT_CREATED", agent_id="a1"),
        _ev("TASK_ASSIGNED", "t1", agent_id="a1"),
        _ev("TASK_STARTED", "t1"),
        _ev("ARTIFACT_REGISTERED", "t1", artifact_id="ar1",
            verification_status="REGISTERED"),
        _ev("VERIFICATION_PASSED", "t1", verification_id="v1",
            artifact_id="ar1"),
        _ev("TASK_COMPLETED", "t1"),
    ]
    state = reduce_events(RID, events)
    assert state["run_id"] == RID
    assert state["agents"] == {"a1": "READY"}
    assert state["tasks"] == {"t1": "SUCCEEDED"}
    assert state["assignments"] == {"t1": "a1"}
    assert state["artifacts"] == {"ar1": "PASSED"}
    assert state["verifications"] == {"v1": "PASSED"}
    assert state["steps"] == len(events)
    # events for a different run_id are ignored
    foreign = reduce_events("run_other", events)
    assert foreign["tasks"] == {} and foreign["steps"] == 0


def test_reduce_events_reassign_revision_and_terminal_events():
    events = [
        _ev("TASK_ASSIGNED", "t1", agent_id="a1"),
        _ev("TASK_REASSIGNED", "t1", to_agent="a2"),
        _ev("REVISION_REQUESTED", "t1"),
        _ev("REVISION_REQUESTED", "t1"),
        _ev("TASK_BLOCKED", "t2"),
        _ev("RUN_COMPLETED"),
    ]
    state = reduce_events(RID, events)
    assert state["assignments"] == {"t1": "a2"}
    assert state["tasks"]["t1"] == "REVISION_REQUESTED"
    assert state["revisions"] == 2
    assert state["blockers"] == ["t2"]
    assert state["status"] == "COMPLETE"


def test_reduce_events_other_terminal_statuses():
    assert reduce_events(RID, [_ev("RUN_BLOCKED")])["status"] == "BLOCKED"
    assert reduce_events(RID, [_ev("RUN_ABORTED")])["status"] == "ABORTED"
    assert reduce_events(RID, [_ev("RUN_FAILED")])["status"] == "FAILED"
    assert reduce_events(
        RID, [_ev("CHECKPOINT_SAVED"), _ev("PLAN_REVISED")]) == dict(
        reduce_events(RID, []), checkpoints=1, replans=1, steps=2)


# ===========================================================================
# replay_equivalent (T20.73)
# ===========================================================================

def test_replay_equivalent_true_for_matching_run():
    run = make_run(run_id=RID)
    run.tasks = {"t1": "SUCCEEDED"}
    run.artifacts = [{"artifact_id": "ar1", "task_id": "t1",
                      "verification_status": "PASSED",
                      "verification_required": True}]
    events = [
        _ev("TASK_ASSIGNED", "t1", agent_id="a1"),
        _ev("ARTIFACT_REGISTERED", "t1", artifact_id="ar1",
            verification_status="PASSED"),
        _ev("TASK_COMPLETED", "t1"),
    ]
    assert replay_equivalent(run, events) is True


def test_replay_equivalent_false_on_perturbed_status():
    events = [
        _ev("TASK_ASSIGNED", "t1", agent_id="a1"),
        _ev("TASK_COMPLETED", "t1"),
    ]
    run = make_run(run_id=RID)
    run.tasks = {"t1": "SUCCEEDED"}
    assert replay_equivalent(run, events) is True
    # a status in the compared set that replay does not reproduce -> False
    run.tasks = {"t1": "RUNNING"}
    assert replay_equivalent(run, events) is False


# ===========================================================================
# serialize.py (T20.71)
# ===========================================================================

def test_run_hash_dict_vs_object_consistent_and_sensitive():
    run = _populated_run()
    d = run.to_dict()
    assert run_hash(run) == run_hash(d)
    # run_hash field itself is excluded from the identity hash
    d["run_hash"] = "tampered"
    assert run_hash(d) == run_hash(run)
    # any other content change changes the hash
    d2 = run.to_dict()
    d2["status"] = "COMPLETE"
    assert run_hash(d2) != run_hash(run)


def test_dumps_loads_roundtrip():
    run = _populated_run()
    loaded = loads(dumps(run))
    assert loaded.run_id == run.run_id
    assert loaded.plan_id == run.plan_id
    assert loaded.tasks == run.tasks
    assert loaded.agents == run.agents
    assert loaded.budgets["consumed_messages"] == 7
    assert len(loaded.events) == 2
    assert run_hash(loaded) == run_hash(run)


def test_loads_rejects_garbage_and_missing_ids():
    with pytest.raises(RunSchemaError):
        loads("this is {not json")
    with pytest.raises(RunSchemaError):
        loads('{"something": 1}')          # missing run_id/plan_id
    with pytest.raises(RunSchemaError):
        loads('["a", "list"]')             # not an object


def test_serialize_resume_integrity_checks():
    saved = _populated_run()
    saved.steps = 5
    saved.budgets["consumed_revisions"] = 2

    # faithful copy -> clean
    loaded = OrchestrationRun.from_dict(saved.to_dict())
    assert ser_resume_integrity(saved, loaded) == []

    # budget reset (same step count, so no regression error)
    regressed = OrchestrationRun.from_dict(saved.to_dict())
    regressed.budgets["consumed_revisions"] = 1
    assert ser_resume_integrity(saved, regressed) == ["budget_reset"]

    # event log truncation (same step count, so no regression error)
    truncated = OrchestrationRun.from_dict(saved.to_dict())
    truncated.events = truncated.events[:1]
    assert ser_resume_integrity(saved, truncated) == ["event_log_truncated"]

    # run state regression: different state AND fewer steps
    older = OrchestrationRun.from_dict(saved.to_dict())
    older.steps = 2
    older.tasks = {"t1": "RUNNING"}
    assert ser_resume_integrity(saved, older) == ["run_state_regressed"]