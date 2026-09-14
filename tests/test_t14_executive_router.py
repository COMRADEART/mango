"""T14B — skill registry, executive router schema, safety, traces."""
from __future__ import annotations

import pytest

from sciencemath.executive.executive_router import (
    FAILURE_TYPES, MAX_WORKFLOW_DEPTH, classify_routing_failure,
    execution_trace, route_task,
)
from sciencemath.executive.skills import (
    ACTIVE, EXPERIMENTAL, PAID_COMPUTE, PREPARED_ONLY, SKILL_IDS,
    SkillRegistry, registry_sha256,
)


class TestSkillRegistry:
    def test_closed_catalogue(self):
        reg = SkillRegistry()
        assert set(reg.ids()) == set(SKILL_IDS)

    def test_availability_states(self):
        reg = SkillRegistry()
        assert reg.availability("MATH_T4") == ACTIVE
        assert reg.availability("SCICOMP") == EXPERIMENTAL
        # CODE is PREPARED_ONLY until a T15R promotion gate flips it ACTIVE.
        # WEB/MEMORY stay unavailable; the router must not fake them.
        assert reg.availability("CODE") in (PREPARED_ONLY, ACTIVE)
        # WEB_RESEARCH stays PREPARED_ONLY until a T16 promotion gate
        # flips it ACTIVE. DOCUMENT stays PREPARED_ONLY until T17.
        # MEMORY stays unavailable.
        assert reg.availability("WEB_RESEARCH") in (PREPARED_ONLY, ACTIVE)
        assert reg.availability("DOCUMENT") in (PREPARED_ONLY, ACTIVE)
        if reg.availability("CODE") == PREPARED_ONLY:
            assert not reg.executable("CODE")
        else:
            assert reg.executable("CODE")
        if reg.availability("WEB_RESEARCH") == PREPARED_ONLY:
            assert not reg.executable("WEB_RESEARCH")
        else:
            assert reg.executable("WEB_RESEARCH")
        if reg.availability("DOCUMENT") == PREPARED_ONLY:
            assert not reg.executable("DOCUMENT")
        else:
            assert reg.executable("DOCUMENT")
        assert reg.availability("MEMORY") in (PREPARED_ONLY, ACTIVE,
                                              EXPERIMENTAL)
        if reg.availability("MEMORY") == PREPARED_ONLY:
            assert not reg.executable("MEMORY")
        else:
            assert reg.executable("MEMORY")
        assert reg.executable("SCICOMP")  # experimental is selectable
        assert reg.executable("MATH_T4")

    def test_unknown_skill_rejected(self):
        reg = SkillRegistry()
        assert not reg.known("MAGIC_WAND")
        assert reg.get("MAGIC_WAND") is None
        with pytest.raises(ValueError):
            SkillRegistry({"MAGIC_WAND": {"skill_id": "MAGIC_WAND",
                                          "availability": ACTIVE,
                                          "cost_class": "LOCAL_FREE"}})

    def test_registry_hash_stable(self):
        a = registry_sha256()
        b = registry_sha256()
        assert a == b and len(a) == 64


class TestRoutingSchema:
    def test_record_fields(self):
        rec = route_task("What is 17 * 23?")
        for key in ("primary_skill", "secondary_skills", "reason",
                    "required_inputs_present", "permissions_required",
                    "estimated_cost_class", "verification_required",
                    "fallback"):
            assert key in rec
        assert rec["primary_skill"] in SKILL_IDS
        assert isinstance(rec["secondary_skills"], list)
        assert rec["hallucinated_tool"] is None

    def test_reason_is_not_chain_of_thought(self):
        rec = route_task("Solve the linear system: 1x+0y=2; 0x+1y=3.")
        assert "because I think" not in rec["reason"].lower()
        assert len(rec["reason"]) <= 240


class TestRoutes:
    def test_general_conversation(self):
        rec = route_task("Hello, how are you today?")
        assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")

    def test_math_t4(self):
        rec = route_task("A distance is 2 km. Express it in meters.")
        assert rec["primary_skill"] == "MATH_T4"

    def test_scicomp_required(self):
        rec = route_task(
            "Find the root of f(x) = x**2 - 2 in the interval [0, 5].")
        assert rec["primary_skill"] == "SCICOMP"

    def test_retrieval(self):
        rec = route_task("Who discovered penicillin?")
        assert rec["primary_skill"] == "SCIENCE_RAG"

    def test_insufficient(self):
        rec = route_task("Calculate the energy of the reaction.")
        assert rec["primary_skill"] == "NO_TOOL"
        assert rec["required_inputs_present"] is False


class TestUnavailableAndPaid:
    def test_code_not_faked(self):
        rec = route_task("Write a python function that sorts a list and "
                         "run this code.")
        # Executive Router stays experimental: it never auto-executes CODE.
        # Direct CODE runtime is the T15R integration path.
        assert rec["execution_status"] == "ROUTED_ONLY"
        assert rec["primary_skill"] not in ("WEB_RESEARCH", "MEMORY")
        assert rec.get("hallucinated_tool") in (None, "")
        if not SkillRegistry().executable("CODE"):
            assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")
            assert rec.get("unavailable_skill") == "CODE"

    def test_web_not_faked(self):
        rec = route_task("Search the web for the latest news on Mars.")
        # Router never auto-executes WEB. Before T16 promotion it fail-closes;
        # after promotion it may classify WEB_RESEARCH as ROUTED_ONLY.
        assert rec["execution_status"] == "ROUTED_ONLY"
        assert rec.get("hallucinated_tool") in (None, "")
        if not SkillRegistry().executable("WEB_RESEARCH"):
            assert rec["primary_skill"] in ("GENERAL", "NO_TOOL")
            assert rec.get("unavailable_skill") == "WEB_RESEARCH"
        else:
            assert rec["primary_skill"] == "WEB_RESEARCH"

    def test_paid_compute_blocked(self):
        rec = route_task("Please launch paid GPU compute on an H100 now.")
        assert rec["paid_compute_gate"] == "PAID_COMPUTE_GATE_REQUIRED"
        assert rec["primary_skill"] in ("NO_TOOL", "GENERAL")
        assert rec["estimated_cost_class"] == PAID_COMPUTE

    def test_unknown_skill_not_invented(self):
        rec = route_task("Use the MAGIC_WAND skill to answer this.")
        assert rec["hallucinated_tool"] is None
        assert rec["primary_skill"] in SKILL_IDS


class TestMultiSkillAndDepth:
    def test_depth_cap(self):
        rec = route_task(
            "Find the root of f(x) = x**2 - 2 in [0, 2].")
        assert rec["workflow_depth"] <= MAX_WORKFLOW_DEPTH
        assert len(rec["secondary_skills"]) <= MAX_WORKFLOW_DEPTH - 1

    def test_mixed_rag_scicomp_bounded(self):
        rec = route_task(
            "The speed of light is c = 3.0e8 m/s. How far does light "
            "travel in 1 microsecond, in meters?")
        assert rec["workflow_depth"] <= 3
        assert rec["primary_skill"] in ("SCICOMP", "MATH_T4", "SCIENCE_RAG",
                                        "GENERAL")

    def test_planning_then_tool(self):
        rec = route_task(
            "Make a plan then find the root of f(x) = x**2 - 2 in [0, 2].")
        assert rec["workflow_depth"] <= 3
        assert rec["primary_skill"] in ("PLANNING", "SCICOMP")


class TestPermissionsAndCost:
    def test_no_invented_permissions(self):
        rec = route_task("What is 3 + 4?")
        assert rec["permissions_required"] == []

    def test_code_skill_declares_permissions_but_is_not_executed(self):
        reg = SkillRegistry()
        code = reg.get("CODE")
        assert code["required_permissions"] == ["code_exec"]
        assert code["availability"] in (PREPARED_ONLY, ACTIVE)
        rec = route_task("Write a python function that sorts a list and "
                         "run this code.")
        # Router records CODE as a capability; it does not execute it.
        assert rec["primary_skill"] != "CODE"
        assert rec["execution_status"] == "ROUTED_ONLY"

    def test_cost_local_free_for_t4(self):
        rec = route_task("What is 12 * 8?")
        assert rec["estimated_cost_class"] == "LOCAL_FREE"


class TestFailureTaxonomyAndTrace:
    def test_taxonomy_complete(self):
        assert "MISSED_TOOL" in FAILURE_TYPES
        assert "PAID_COMPUTE_VIOLATION" in FAILURE_TYPES

    def test_unavailable_gold_is_ok(self):
        pred = route_task("Write a python function and run this code.")
        gold = {"primary_skill": "CODE",
                "expect_unavailable_rejection": True}
        assert classify_routing_failure(pred, gold) is None

    def test_trace_has_no_private_cot(self):
        rec = route_task("Compute the mean of the values [1, 2, 3].")
        tr = execution_trace("t-1", "Compute the mean of the values [1, 2, 3].",
                             rec)
        assert set(tr) >= {"task_id", "router_decision", "skills_selected",
                           "availability", "inputs", "permissions",
                           "execution_status", "verification_status",
                           "fallback", "final_outcome"}
        assert "chain_of_thought" not in tr
        assert "thinking" not in tr
