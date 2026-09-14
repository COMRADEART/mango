"""T19 multi-skill planning, memory/document/web/code/SciComp, approval."""
from __future__ import annotations

from sciencemath.planning.graph import task_list
from sciencemath.planning.harness import simulate
from sciencemath.planning.pipeline import Planner


def test_code_plan_includes_inspect_change_test_verify():
    r = Planner().handle({
        "goal": "Fix repository bug in fixture repo",
        "goal_type": "CODE_BUGFIX",
        "allow_unspecified_repo": True,
    })
    types = [t.task_type for t in task_list(r.plan)]
    for need in ("inspect", "diagnose", "change", "test", "verify"):
        assert need in types


def test_web_plan_has_freshness_and_evidence():
    r = Planner().handle({
        "goal": "Research current API behavior",
        "goal_type": "WEB_RESEARCH",
    })
    assert any(t.required_skill == "WEB_RESEARCH" for t in r.plan.tasks)
    assert any("freshness" in " ".join(t.success_criteria).lower()
               for t in r.plan.tasks)


def test_document_plan_expects_cited_field():
    r = Planner().handle({
        "goal": "Analyze the contract and extract the cited renewal date",
        "goal_type": "DOCUMENT_ANALYSIS",
    })
    blob = " ".join(" ".join(t.success_criteria) for t in r.plan.tasks).lower()
    assert "renewal" in blob
    assert any(t.required_skill == "DOCUMENT" for t in r.plan.tasks)


def test_scicomp_not_freeform_arithmetic():
    r = Planner().handle({
        "goal": "Compute the definite integral numerically",
        "goal_type": "SCICOMP",
    })
    assert all(t.required_skill == "SCICOMP" for t in r.plan.tasks)
    assert any(t.task_type == "compute" for t in r.plan.tasks)


def test_memory_write_only_when_explicit():
    implicit = Planner().handle({
        "goal": "What was the prior architecture decision?",
        "goal_type": "MEMORY_RECALL",
    })
    assert not any(t.persistent_write_requested for t in implicit.plan.tasks)
    explicit = Planner().handle({
        "goal": "Remember that the architecture is hexagonal",
        "goal_type": "MEMORY_WRITE",
        "user_explicit_memory_write": True,
    })
    assert any(t.persistent_write_requested for t in explicit.plan.tasks)
    assert all(t.execution_authority is False for t in explicit.plan.tasks)


def test_mixed_web_then_code():
    r = Planner().handle({
        "goal": "Research current API then patch the client in fixture repo",
        "required_skills": ["WEB_RESEARCH", "CODE"],
        "allow_unspecified_repo": True,
    })
    skills = [t.required_skill for t in r.plan.tasks]
    assert "WEB_RESEARCH" in skills and "CODE" in skills


def test_scientific_analysis_document_then_scicomp():
    r = Planner().handle({
        "goal": "Analyze local dataset then compute the mean",
        "goal_type": "SCIENTIFIC_ANALYSIS",
    })
    skills = {t.required_skill for t in r.plan.tasks}
    assert "DOCUMENT" in skills and "SCICOMP" in skills


def test_simulate_mixed_completes_without_execution():
    r = simulate({
        "goal": "Research current API then patch the client",
        "required_skills": ["WEB_RESEARCH", "CODE"],
        "allow_unspecified_repo": True,
    })
    assert r.op == "PLAN_COMPLETE"
    assert r.side_effects["network_requests"] == 0
    assert r.side_effects["filesystem_mutations"] == 0
