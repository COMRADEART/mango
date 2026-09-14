"""T20 domain tests: orchestration contract, models, manifests, and the
executive skill-registry ORCHESTRATION entry.

Deterministic: no network, no inference, fixed timestamps everywhere.
"""
from __future__ import annotations

import pytest

from sciencemath.executive.skills import (
    ACTIVE, DISABLED, EXPERIMENTAL, SKILL_IDS, SkillRegistry,
    default_registry,
)
from sciencemath.orchestration import contract as C
from sciencemath.orchestration.manifests import (
    ROLE_TEMPLATES, SKILL_TO_ROLE, AgentCreationError, build_agent,
    skill_permitted,
)
from sciencemath.orchestration.models import (
    AgentSpec, ArtifactReference, Handoff, Message, OrchestrationRun,
    agent_budget_subset, default_run_budget, new_run_id, run_state_hash,
)

NOW = "2026-01-01T00:00:00Z"
PRE_EXISTING_SKILLS = (
    "GENERAL", "MATH_T4", "SCIENCE_RAG", "SCICOMP", "CODE",
    "WEB_RESEARCH", "DOCUMENT", "MEMORY", "PLANNING", "NO_TOOL",
)


def _run() -> OrchestrationRun:
    return OrchestrationRun(
        run_id="run_test0001", plan_id="plan_test0001", run_version=1,
        status="CREATED", started_at=NOW, updated_at=NOW,
    )


# ---------------------------------------------------------------------------
# Contract constants integrity
# ---------------------------------------------------------------------------

def test_no_external_action_authority_anywhere():
    assert "EXTERNAL_ACTION" not in C.AUTHORITIES
    for role, tpl in ROLE_TEMPLATES.items():
        assert tpl["authority"] != "EXTERNAL_ACTION", role
    # not obtainable as a scope either
    with pytest.raises(AgentCreationError):
        build_agent("ORCHESTRATOR", "orch_x", caller_role="", now=NOW,
                    scope="EXTERNAL_ACTION")


def test_zero_tolerance_keys_shape():
    assert len(C.ZERO_TOLERANCE_KEYS) == 24
    assert len(set(C.ZERO_TOLERANCE_KEYS)) == 24
    for key in C.ZERO_TOLERANCE_KEYS:
        assert isinstance(key, str) and key


def test_new_run_counters_all_zero():
    run = _run()
    assert set(run.counters) == set(C.ZERO_TOLERANCE_KEYS)
    assert all(v == 0 for v in run.counters.values())


def test_run_ops_list():
    assert C.RUN_OPS == (
        "RUN_CREATE", "RUN_STEP", "RUN_STATUS", "RUN_CHECKPOINT",
        "RUN_RESUME", "RUN_BLOCK", "RUN_ABORT", "RUN_REPLAN", "RUN_COMPLETE",
    )


def test_failure_classes_size_12():
    assert len(C.FAILURE_CLASSES) == 12
    for expected in ("TRANSIENT", "PERMANENT", "VERIFICATION_FAIL",
                     "BUDGET_EXCEEDED", "AGENT_CRASH", "UNKNOWN"):
        assert expected in C.FAILURE_CLASSES


def test_bounded_limits_values():
    assert C.MAX_TOTAL_AGENTS == 8
    assert C.MAX_WORKER_AGENTS == 6
    assert C.MAX_CONCURRENT_WORKERS == 3
    assert C.MAX_CONCURRENT_VERIFIERS == 2
    assert C.MAX_SPAWN_DEPTH == 1
    assert C.MAX_REVISIONS_PER_TASK == 2
    assert C.MAX_TOTAL_REVISIONS == 12
    assert C.MAX_HANDOFF_CYCLE == 4


def test_statuses_and_roles():
    assert set(C.RUN_STATUSES) == {
        "CREATED", "RUNNING", "WAITING", "BLOCKED", "NEEDS_REPLAN",
        "COMPLETE", "ABORTED", "FAILED",
    }
    assert len(AGENT_ROLES := C.AGENT_ROLES) == 9
    assert set(C.WORKER_ROLES) <= set(AGENT_ROLES)
    assert "VERIFIER" in AGENT_ROLES and "ORCHESTRATOR" in AGENT_ROLES


# ---------------------------------------------------------------------------
# AgentSpec invariants
# ---------------------------------------------------------------------------

def test_agentspec_post_init_forces_dangerous_flags_false():
    spec = AgentSpec(
        agent_id="a1", role="CODE_WORKER", display_name="a1",
        can_spawn=True, paid_compute_access=True, shell_access=True,
    )
    assert spec.can_spawn is False
    assert spec.paid_compute_access is False
    assert spec.shell_access is False


def test_agentspec_spawn_depth_clamped_to_max():
    assert AgentSpec(agent_id="a", role="VERIFIER",
                     display_name="a", spawn_depth=7).spawn_depth == 1
    assert AgentSpec(agent_id="a", role="VERIFIER",
                     display_name="a", spawn_depth=1).spawn_depth == 1
    assert AgentSpec(agent_id="a", role="VERIFIER",
                     display_name="a", spawn_depth=0).spawn_depth == 0


def test_agentspec_roundtrip():
    spec = build_agent("SCICOMP_WORKER", "w1", now=NOW)
    restored = AgentSpec.from_dict(spec.to_dict())
    assert restored == spec
    assert restored.to_dict() == spec.to_dict()


def test_agentspec_from_dict_ignores_unknown_keys():
    d = build_agent("VERIFIER", "v1", now=NOW).to_dict()
    d["injected_field"] = "boom"
    spec = AgentSpec.from_dict(d)
    assert not hasattr(spec, "injected_field")
    assert spec.role == "VERIFIER"


# ---------------------------------------------------------------------------
# build_agent
# ---------------------------------------------------------------------------

def test_build_agent_creates_all_nine_roles():
    for role in C.AGENT_ROLES:
        agent = build_agent(role, f"ag_{role}", caller_role="ORCHESTRATOR",
                            now=NOW)
        assert agent.role == role
        assert agent.status == "READY"
        assert agent.provenance["created_by"] == "ORCHESTRATOR"
        assert agent.provenance["created_at"] == NOW
        assert agent.provenance["template"] == role


def test_build_agent_non_orchestrator_caller_raises():
    for caller in ("CODE_WORKER", "VERIFIER", "PLANNER", "SYNTHESIS_WORKER"):
        with pytest.raises(AgentCreationError):
            build_agent("CODE_WORKER", "w9", caller_role=caller, now=NOW)


def test_build_agent_internal_and_orchestrator_callers_allowed():
    by_orch = build_agent("CODE_WORKER", "w1", caller_role="ORCHESTRATOR",
                          now=NOW)
    internal = build_agent("CODE_WORKER", "w2", caller_role="", now=NOW)
    assert by_orch.role == internal.role == "CODE_WORKER"


def test_build_agent_invented_role_rejected():
    with pytest.raises(AgentCreationError):
        build_agent("SUPER_ADMIN", "x1", caller_role="ORCHESTRATOR", now=NOW)
    with pytest.raises(AgentCreationError):
        build_agent("ORCHESTRATOR_CLONE", "x2", caller_role="", now=NOW)


def test_build_agent_memory_write_enable_refused():
    with pytest.raises(AgentCreationError):
        build_agent("MEMORY_CONTEXT_WORKER", "m1",
                    caller_role="ORCHESTRATOR", now=NOW,
                    memory_access="READ_WRITE")
    ok = build_agent("MEMORY_CONTEXT_WORKER", "m2",
                     caller_role="ORCHESTRATOR", now=NOW,
                     memory_access="READ_ONLY")
    assert ok.memory_access == "READ_ONLY"
    default = build_agent("MEMORY_CONTEXT_WORKER", "m3", now=NOW)
    assert default.memory_access == "READ_ONLY"


def test_build_agent_no_agent_obtains_external_action():
    for role in C.AGENT_ROLES:
        agent = build_agent(role, f"ag_{role}", now=NOW)
        assert agent.authority != "EXTERNAL_ACTION"
        assert agent.scope != "EXTERNAL_ACTION"
        assert agent.authority in C.AUTHORITIES


def test_build_agent_orchestrator_spawn_depth_only():
    assert build_agent("ORCHESTRATOR", "o1", now=NOW).spawn_depth == 1
    for role in C.AGENT_ROLES:
        if role == "ORCHESTRATOR":
            continue
        assert build_agent(role, f"ag_{role}", now=NOW).spawn_depth == 0


# ---------------------------------------------------------------------------
# ROLE_TEMPLATES closure
# ---------------------------------------------------------------------------

def test_role_templates_closed_over_agent_roles():
    assert set(ROLE_TEMPLATES) == set(C.AGENT_ROLES)
    assert len(ROLE_TEMPLATES) == 9


def test_no_template_has_network_access():
    for role, tpl in ROLE_TEMPLATES.items():
        assert tpl["network_access"] is False, role


def test_verifier_template_is_the_only_verification_role():
    for role, tpl in ROLE_TEMPLATES.items():
        if role == "VERIFIER":
            assert tpl["verification_role"] is True
        else:
            assert tpl["verification_role"] is False, role


def test_skill_to_role_covers_all_task_skills():
    assert set(SKILL_TO_ROLE) == set(C.TASK_SKILLS)
    executor_roles = set(C.AGENT_ROLES) - {"ORCHESTRATOR", "PLANNER",
                                           "VERIFIER"}
    for skill, role in SKILL_TO_ROLE.items():
        assert role in executor_roles, (skill, role)


# ---------------------------------------------------------------------------
# skill_permitted
# ---------------------------------------------------------------------------

def test_skill_permitted_worker_denies_out_of_role_skill():
    scicomp = build_agent("SCICOMP_WORKER", "w1", now=NOW)
    assert skill_permitted(scicomp, "SCICOMP") is True
    assert skill_permitted(scicomp, "MATH_T4") is True
    assert skill_permitted(scicomp, "CODE") is False
    assert skill_permitted(scicomp, "WEB_RESEARCH") is False
    assert skill_permitted(scicomp, "DOCUMENT") is False
    assert skill_permitted(scicomp, "MEMORY") is False


def test_skill_permitted_orchestrator_denied_all_worker_skills():
    orch = build_agent("ORCHESTRATOR", "o1", now=NOW)
    for skill in C.TASK_SKILLS:
        assert skill_permitted(orch, skill) is False, skill


def test_skill_permitted_verifier_denied_all_worker_skills():
    ver = build_agent("VERIFIER", "v1", now=NOW)
    for skill in C.TASK_SKILLS:
        assert skill_permitted(ver, skill) is False, skill


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def test_default_budget_network_frozen_and_free():
    budget = default_run_budget()
    assert budget["max_network_reads"] == 0
    assert budget["max_cost_class"] == "FREE"
    assert budget["max_agents"] == C.MAX_TOTAL_AGENTS
    assert budget["max_worker_agents"] == C.MAX_WORKER_AGENTS
    assert budget["max_concurrent_workers"] == C.MAX_CONCURRENT_WORKERS
    assert budget["max_revisions"] == C.MAX_TOTAL_REVISIONS


def test_agent_budget_subset_verifier_cannot_revise():
    budget = agent_budget_subset("VERIFIER")
    assert budget["max_revisions"] == 0
    assert budget["max_tasks"] > 0


def test_agent_budget_subset_orchestrator_no_network_keys():
    budget = agent_budget_subset("ORCHESTRATOR")
    assert "max_network_reads" not in budget
    assert "max_network_reads" not in agent_budget_subset("PLANNER")


def test_agent_budget_subset_worker_default_shape():
    for role in C.WORKER_ROLES + ("SYNTHESIS_WORKER",):
        budget = agent_budget_subset(role)
        assert budget["max_revisions"] == C.MAX_REVISIONS_PER_TASK, role
        assert budget["max_replans"] == 0, role
        assert budget["max_tasks"] > 0


def test_build_agent_wires_budget_subset():
    orch = build_agent("ORCHESTRATOR", "o1", now=NOW)
    ver = build_agent("VERIFIER", "v1", now=NOW)
    worker = build_agent("SCICOMP_WORKER", "w1", now=NOW)
    assert orch.budget == agent_budget_subset("ORCHESTRATOR")
    assert ver.budget == agent_budget_subset("VERIFIER")
    assert worker.budget == agent_budget_subset("SCICOMP_WORKER")


# ---------------------------------------------------------------------------
# Executive skill registry
# ---------------------------------------------------------------------------

def test_registry_has_orchestration_entry():
    reg = default_registry()
    assert "ORCHESTRATION" in reg
    rec = reg["ORCHESTRATION"]
    assert rec["skill_id"] == "ORCHESTRATION"
    assert rec["availability"] == ACTIVE
    assert rec["executable"] is True
    assert rec["cost_class"] == "LOCAL_EXPENSIVE"
    assert rec["offline"] is True
    assert rec["online"] is False
    assert rec["deterministic"] is True
    assert rec["verification_method"] == "orchestration_run_audit"
    assert rec["fallback_behavior"] == "PLANNING"


def test_registry_pre_existing_skills_unchanged_active():
    reg = default_registry()
    for skill_id in PRE_EXISTING_SKILLS:
        assert reg[skill_id]["availability"] == ACTIVE, skill_id
    counts = SkillRegistry().counts()
    assert counts.get(ACTIVE) == 11
    assert counts.get(EXPERIMENTAL, 0) == 0


def test_skill_registry_accepts_default_registry():
    registry = SkillRegistry(default_registry())
    assert "ORCHESTRATION" in registry.ids()
    assert registry.known("ORCHESTRATION")
    assert registry.availability("ORCHESTRATION") == ACTIVE
    assert registry.executable("ORCHESTRATION") is True
    assert "ORCHESTRATION" in SKILL_IDS


def test_registry_orchestration_not_paid():
    registry = SkillRegistry()
    rec = registry.get("ORCHESTRATION")
    assert rec["cost_class"] != "PAID_COMPUTE"
    # deepcopy isolation: mutating a fetched record does not corrupt registry
    rec["availability"] = DISABLED
    assert registry.availability("ORCHESTRATION") == ACTIVE


# ---------------------------------------------------------------------------
# OrchestrationRun roundtrip and hashing
# ---------------------------------------------------------------------------

def test_run_roundtrip_preserves_tasks_counters_budgets():
    run = _run()
    run.tasks = {"t1": "SUCCEEDED", "t2": "PENDING"}
    run.agents = [build_agent("SCICOMP_WORKER", "w1", now=NOW).to_dict()]
    run.status = "RUNNING"
    d = run.to_dict()
    restored = OrchestrationRun.from_dict(d)
    assert restored.tasks == run.tasks
    assert restored.agents == run.agents
    assert restored.counters == run.counters
    assert set(restored.counters) == set(C.ZERO_TOLERANCE_KEYS)
    assert all(v == 0 for v in restored.counters.values())
    assert restored.budgets == run.budgets
    assert restored.status == "RUNNING"
    assert restored.to_dict() == d


def test_run_from_dict_keeps_explicit_counters():
    run = _run()
    run.counters = {k: 0 for k in C.ZERO_TOLERANCE_KEYS}
    run.counters["prompt_injection_success"] = 1
    restored = OrchestrationRun.from_dict(run.to_dict())
    assert restored.counters["prompt_injection_success"] == 1


def test_run_state_hash_stable_and_sensitive_to_tasks():
    run = _run()
    run.tasks = {"t1": "PENDING"}
    h1 = run_state_hash(run)
    h2 = run_state_hash(run)
    assert h1 == h2 and len(h1) == 64
    run.tasks["t1"] = "SUCCEEDED"
    assert run_state_hash(run) != h1
    # run_hash itself excluded from the state hash
    run.run_hash = "whatever"
    assert run_state_hash(run) == run_state_hash(
        OrchestrationRun.from_dict(
            {**run.to_dict(), "run_hash": "different"}))


def test_new_run_id_deterministic():
    a = new_run_id("plan_fixed", NOW)
    b = new_run_id("plan_fixed", NOW)
    c = new_run_id("plan_other", NOW)
    assert a == b
    assert a != c
    assert a.startswith("run_")


# ---------------------------------------------------------------------------
# Model serialization roundtrips
# ---------------------------------------------------------------------------

def test_artifact_reference_roundtrip():
    art = ArtifactReference(
        artifact_id="art_1", producer_agent_id="w1", task_id="t1",
        artifact_type="result", content_reference="mem://art/1",
        content_hash="deadbeef", provenance={"run": "r1"},
        created_at=NOW, verification_required=True, verification_status="PENDING",
    )
    assert ArtifactReference.from_dict(art.to_dict()) == art


def test_handoff_roundtrip():
    h = Handoff(
        handoff_id="h1", from_agent="o1", to_agent="w1", task_id="t1",
        objective="do the thing", inputs=["in1"],
        artifact_refs=["art_1"], constraints=["bounded"],
        success_criteria=["c1"], remaining_budget={"max_tasks": 6},
        expected_output_schema={"type": "object"}, provenance={"k": "v"},
    )
    assert Handoff.from_dict(h.to_dict()) == h


def test_message_roundtrip():
    m = Message(
        message_id="m1", run_id="run_test0001", sender="o1", recipient="w1",
        task_id="t1", message_type="ASSIGN", payload={"objective": "x"},
        artifact_refs=[], constraints=["c"], budget={"max_tasks": 6},
        timestamp=NOW,
    )
    assert Message.from_dict(m.to_dict()) == m


def test_run_schema_version_pinned():
    run = _run()
    assert run.schema_version == C.SCHEMA_VERSION == 1
    restored = OrchestrationRun.from_dict(run.to_dict())
    assert restored.schema_version == 1