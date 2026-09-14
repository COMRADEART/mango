"""T20.4/T20.5/T20.23 bounded agent role templates and manifest enforcement.

Only the ORCHESTRATOR instantiates agents (T20.62). Workers operate strictly
within their manifest; attempted out-of-role operations are BLOCK. No agent
receives EXTERNAL_ACTION authority during T20 (T20.10).
"""
from __future__ import annotations

from sciencemath.orchestration.contract import (
    AUTHORITIES, MAX_SPAWN_DEPTH, TASK_SKILLS,
)
from sciencemath.orchestration.models import AgentSpec, agent_budget_subset

# role -> manifest template (T20.4). These are closed templates; arbitrary
# dynamically invented authority-bearing roles are rejected.
ROLE_TEMPLATES: dict[str, dict] = {
    "ORCHESTRATOR": {
        "authority": "COORDINATE",
        "capabilities": ["PLANNING"],
        "allowed_skills": [],
        "denied_skills": ["CODE", "SCICOMP", "WEB_RESEARCH", "DOCUMENT",
                          "MEMORY", "MATH_T4", "SCIENCE_RAG"],
        "memory_access": "NONE",
        "network_access": False,
        "filesystem_access": False,
        "verification_role": False,
        "max_tasks": 0,
    },
    "PLANNER": {
        "authority": "PLAN",
        "capabilities": ["PLANNING"],
        "allowed_skills": ["PLANNING"],
        "denied_skills": ["CODE", "SCICOMP", "WEB_RESEARCH", "DOCUMENT",
                          "MEMORY", "MATH_T4", "SCIENCE_RAG"],
        "memory_access": "NONE",
        "network_access": False,
        "filesystem_access": False,
        "verification_role": False,
        "max_tasks": 0,
    },
    "SCICOMP_WORKER": {
        "authority": "COMPUTE",
        "capabilities": ["SCICOMP", "MATH_T4"],
        "allowed_skills": ["SCICOMP", "MATH_T4"],
        "denied_skills": ["CODE", "WEB_RESEARCH", "DOCUMENT", "MEMORY",
                          "SCIENCE_RAG"],
        "memory_access": "NONE",
        "network_access": False,
        "filesystem_access": False,
        "verification_role": False,
    },
    "CODE_WORKER": {
        "authority": "ANALYZE",
        "capabilities": ["CODE"],
        "allowed_skills": ["CODE"],
        "denied_skills": ["SCICOMP", "WEB_RESEARCH", "DOCUMENT", "MEMORY",
                          "MATH_T4", "SCIENCE_RAG"],
        "memory_access": "NONE",
        "network_access": False,
        "filesystem_access": True,   # sandbox fixture copies only
        "verification_role": False,
    },
    "WEB_RESEARCH_WORKER": {
        "authority": "RESEARCH",
        "capabilities": ["WEB_RESEARCH", "SCIENCE_RAG"],
        "allowed_skills": ["WEB_RESEARCH", "SCIENCE_RAG"],
        "denied_skills": ["CODE", "SCICOMP", "DOCUMENT", "MEMORY", "MATH_T4"],
        "memory_access": "NONE",
        "network_access": False,     # frozen eval: fixture providers only
        "filesystem_access": False,
        "verification_role": False,
    },
    "DOCUMENT_WORKER": {
        "authority": "DOCUMENT_ANALYZE",
        "capabilities": ["DOCUMENT"],
        "allowed_skills": ["DOCUMENT"],
        "denied_skills": ["CODE", "SCICOMP", "WEB_RESEARCH", "MEMORY",
                          "MATH_T4", "SCIENCE_RAG"],
        "memory_access": "NONE",
        "network_access": False,
        "filesystem_access": False,
        "verification_role": False,
    },
    "MEMORY_CONTEXT_WORKER": {
        "authority": "MEMORY_READ",
        "capabilities": ["MEMORY"],
        "allowed_skills": ["MEMORY"],
        "denied_skills": ["CODE", "SCICOMP", "WEB_RESEARCH", "DOCUMENT",
                          "MATH_T4", "SCIENCE_RAG"],
        "memory_access": "READ_ONLY",   # T20.11 default
        "network_access": False,
        "filesystem_access": False,
        "verification_role": False,
    },
    "VERIFIER": {
        "authority": "VERIFY",
        "capabilities": [],
        "allowed_skills": [],
        "denied_skills": ["CODE", "SCICOMP", "WEB_RESEARCH", "DOCUMENT",
                          "MEMORY", "MATH_T4", "SCIENCE_RAG"],
        "memory_access": "NONE",
        "network_access": False,
        "filesystem_access": False,
        "verification_role": True,
        "max_tasks": 0,
    },
    "SYNTHESIS_WORKER": {
        "authority": "SYNTHESIZE",
        "capabilities": ["GENERAL"],
        "allowed_skills": ["GENERAL"],
        "denied_skills": ["CODE", "SCICOMP", "WEB_RESEARCH", "DOCUMENT",
                          "MEMORY", "MATH_T4", "SCIENCE_RAG"],
        "memory_access": "NONE",
        "network_access": False,
        "filesystem_access": False,
        "verification_role": False,
    },
}

# deterministic skill -> worker-role mapping (T20.24). No free-form role
# guessing when this mapping exists.
SKILL_TO_ROLE = {
    "SCICOMP": "SCICOMP_WORKER",
    "MATH_T4": "SCICOMP_WORKER",
    "CODE": "CODE_WORKER",
    "WEB_RESEARCH": "WEB_RESEARCH_WORKER",
    "SCIENCE_RAG": "WEB_RESEARCH_WORKER",
    "DOCUMENT": "DOCUMENT_WORKER",
    "MEMORY": "MEMORY_CONTEXT_WORKER",
    "GENERAL": "SYNTHESIS_WORKER",
}

ROLE_PREFIX_BY_SKILL = {}


class AgentCreationError(ValueError):
    """Invalid or unauthorized agent instantiation."""


def validate_role(role: str) -> None:
    if role not in ROLE_TEMPLATES:
        raise AgentCreationError(
            f"invented authority-bearing role {role!r} rejected")


def build_agent(role: str, agent_id: str, display_name: str = "",
                caller_role: str = "", now: str = "",
                scope: str = "", memory_access: str | None = None) -> AgentSpec:
    """Instantiate a bounded agent from a closed role template.

    Only the ORCHESTRATOR may call this (T20.62). Workers cannot spawn.
    """
    if caller_role and caller_role != "ORCHESTRATOR":
        raise AgentCreationError(
            f"agent creation attempted by non-orchestrator {caller_role!r}")
    validate_role(role)
    tpl = ROLE_TEMPLATES[role]
    if role == "MEMORY_CONTEXT_WORKER":
        # T20.11: read-only default; the orchestrator cannot convert a
        # read-only memory worker into write-enabled mode.
        mem = "READ_ONLY" if memory_access is None else memory_access
        if mem not in ("NONE", "READ_ONLY"):
            raise AgentCreationError(
                "orchestrator cannot convert memory worker to write-enabled")
    else:
        mem = "NONE"
    agent = AgentSpec(
        agent_id=agent_id,
        role=role,
        display_name=display_name or role.lower(),
        capabilities=list(tpl["capabilities"]),
        allowed_skills=list(tpl["allowed_skills"]),
        denied_skills=list(tpl["denied_skills"]),
        authority=tpl["authority"],
        scope=scope,
        memory_access=mem,
        network_access=bool(tpl["network_access"]),
        filesystem_access=bool(tpl["filesystem_access"]),
        can_spawn=False,
        spawn_depth=MAX_SPAWN_DEPTH if role == "ORCHESTRATOR" else 0,
        verification_role=bool(tpl["verification_role"]),
        status="READY",
        budget=agent_budget_subset(role),
        provenance={"created_by": "ORCHESTRATOR", "created_at": now,
                    "template": role},
    )
    if agent.authority not in AUTHORITIES:
        raise AgentCreationError(f"bad authority {agent.authority!r}")
    if "EXTERNAL_ACTION" in (agent.authority, agent.scope):
        raise AgentCreationError("external action authority is T24, not T20")
    return agent


def skill_permitted(agent: AgentSpec, skill_id: str) -> bool:
    """T20.23 manifest enforcement."""
    if skill_id in agent.denied_skills:
        return False
    if skill_id not in agent.allowed_skills:
        return False
    return True


def authority_permitted(agent: AgentSpec, authority: str) -> bool:
    return agent.authority == authority


def worker_role_for_skill(skill_id: str) -> str | None:
    return SKILL_TO_ROLE.get(skill_id)


def task_skills() -> tuple:
    return TASK_SKILLS