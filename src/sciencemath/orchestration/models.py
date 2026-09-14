"""T20.3/T20.20/T20.21/T20.35–T20.36 typed orchestration models.

AgentSpec, ArtifactReference, Handoff, Message, Verification, Event,
budgets, and the shared OrchestrationRun state. Only the ORCHESTRATOR
commits authoritative transitions (T20.17); workers submit events.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, fields

from sciencemath.orchestration.contract import (
    FAILURE_CLASSES, MAX_CONCURRENT_WORKERS, MAX_MESSAGES_PER_AGENT,
    MAX_REVISIONS_PER_TASK, MAX_SPAWN_DEPTH, MAX_TOTAL_AGENTS,
    MAX_TOTAL_MESSAGES, MAX_TOTAL_REVISIONS, MAX_WORKER_AGENTS,
    SCHEMA_VERSION, ZERO_TOLERANCE_KEYS,
)
from sciencemath.planning.models import utc_now


def _id(prefix: str, *parts: object) -> str:
    blob = "|".join(str(p) for p in parts)
    return prefix + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def deterministic_id(prefix: str, *parts: object) -> str:
    return _id(prefix, *parts)


# ---------------------------------------------------------------------------
# AgentSpec (T20.3)
# ---------------------------------------------------------------------------
@dataclass
class AgentSpec:
    agent_id: str
    role: str
    display_name: str
    capabilities: list = field(default_factory=list)   # skill ids
    allowed_skills: list = field(default_factory=list)
    denied_skills: list = field(default_factory=list)
    authority: str = "ANALYZE"
    scope: str = ""
    concurrency_limit: int = 1
    max_tasks: int = 3
    max_revisions: int = MAX_REVISIONS_PER_TASK
    max_handoffs: int = 6
    memory_access: str = "NONE"
    network_access: bool = False
    filesystem_access: bool = False
    shell_access: bool = False
    paid_compute_access: bool = False
    can_spawn: bool = False
    spawn_depth: int = 0
    verification_role: bool = False
    status: str = "READY"
    budget: dict = field(default_factory=dict)   # per-agent budget subset
    provenance: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # T20.62: only ORCHESTRATOR spawns; nobody gets external action,
        # paid compute, or a shell.
        self.can_spawn = False
        self.paid_compute_access = False
        self.shell_access = False
        if self.spawn_depth > MAX_SPAWN_DEPTH:
            self.spawn_depth = MAX_SPAWN_DEPTH

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentSpec":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# ArtifactReference (T20.20)
# ---------------------------------------------------------------------------
@dataclass
class ArtifactReference:
    artifact_id: str
    producer_agent_id: str
    task_id: str
    artifact_type: str
    content_reference: str
    content_hash: str
    provenance: dict = field(default_factory=dict)
    created_at: str = ""
    status: str = "REGISTERED"
    verification_required: bool = False
    verification_status: str = "PENDING"   # PENDING/PASSED/FAILED/NOT_REQUIRED
    sensitivity: str = "NORMAL"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ArtifactReference":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Handoff contract (T20.21)
# ---------------------------------------------------------------------------
@dataclass
class Handoff:
    handoff_id: str
    from_agent: str
    to_agent: str
    task_id: str
    objective: str
    inputs: list = field(default_factory=list)
    artifact_refs: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    success_criteria: list = field(default_factory=list)
    remaining_budget: dict = field(default_factory=dict)
    expected_output_schema: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Handoff":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Message contract (T20.37)
# ---------------------------------------------------------------------------
@dataclass
class Message:
    message_id: str
    run_id: str
    sender: str
    recipient: str
    task_id: str = ""
    message_type: str = "RESULT"
    payload: dict = field(default_factory=dict)
    artifact_refs: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Verification (T20.8/T20.42)
# ---------------------------------------------------------------------------
@dataclass
class Verification:
    verification_id: str
    task_id: str
    artifact_id: str
    verifier_agent_id: str
    producer_agent_id: str
    objective: str = ""
    success_criteria: list = field(default_factory=list)
    allowed_checks: list = field(default_factory=list)
    decision: str = ""          # VERIFIER_DECISIONS
    reasons: list = field(default_factory=list)
    disputed_criterion: str = ""
    escalation: str = ""        # "" | "deterministic_check" | "blocked"
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Event (T20.18)
# ---------------------------------------------------------------------------
@dataclass
class Event:
    event_id: str
    run_id: str
    timestamp: str
    actor_id: str
    task_id: str
    event_type: str
    payload: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Budgets (T20.35/T20.36)
# ---------------------------------------------------------------------------
def default_run_budget() -> dict:
    return {
        "max_agents": MAX_TOTAL_AGENTS,
        "max_worker_agents": MAX_WORKER_AGENTS,
        "max_tasks": 30,
        "max_concurrent_workers": MAX_CONCURRENT_WORKERS,
        "max_concurrent_verifiers": 2,
        "max_messages": MAX_TOTAL_MESSAGES,
        "max_handoffs": 60,
        "max_revisions": MAX_TOTAL_REVISIONS,
        "max_replans": 5,
        "max_artifacts": 120,
        "max_memory_reads": 16,
        "max_memory_writes": 2,
        "max_network_reads": 0,   # frozen eval: network off
        "max_code_iterations": 6,
        "max_runtime_class": "SHORT",
        "max_cost_class": "FREE",
        "consumed_messages": 0,
        "consumed_handoffs": 0,
        "consumed_revisions": 0,
        "consumed_replans": 0,
        "consumed_artifacts": 0,
        "consumed_memory_reads": 0,
        "consumed_memory_writes": 0,
        "consumed_network_reads": 0,
        "consumed_code_iterations": 0,
        "non_progress_streak": 0,
    }


def agent_budget_subset(role: str) -> dict:
    """Per-agent budget subset (T20.36). Workers cannot raise these."""
    if role == "ORCHESTRATOR":
        return {"max_tasks": 30, "max_messages": MAX_TOTAL_MESSAGES,
                "max_handoffs": 60, "max_revisions": MAX_TOTAL_REVISIONS}
    if role == "VERIFIER":
        return {"max_tasks": 12, "max_messages": MAX_MESSAGES_PER_AGENT,
                "max_revisions": 0}
    if role == "PLANNER":
        return {"max_tasks": 0, "max_messages": MAX_MESSAGES_PER_AGENT,
                "max_revisions": 0, "max_replans": 5}
    return {"max_tasks": 6, "max_messages": MAX_MESSAGES_PER_AGENT,
            "max_revisions": MAX_REVISIONS_PER_TASK, "max_replans": 0}


# ---------------------------------------------------------------------------
# OrchestrationRun (T20.16)
# ---------------------------------------------------------------------------
@dataclass
class OrchestrationRun:
    run_id: str
    plan_id: str
    run_version: int
    status: str
    started_at: str
    updated_at: str
    agents: list = field(default_factory=list)          # AgentSpec dicts
    tasks: dict = field(default_factory=dict)           # task_id -> status
    assignments: list = field(default_factory=list)     # task_id -> agent_id
    artifacts: list = field(default_factory=list)       # ArtifactReference dicts
    observations: list = field(default_factory=list)
    verifications: list = field(default_factory=list)
    handoffs: list = field(default_factory=list)
    budgets: dict = field(default_factory=default_run_budget)
    agent_budgets: dict = field(default_factory=dict)   # agent_id -> budget
    checkpoints: list = field(default_factory=list)
    events: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    revisions: list = field(default_factory=list)
    completion_state: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    run_hash: str = ""
    counters: dict = field(default_factory=dict)        # zero-tolerance
    messages: list = field(default_factory=list)
    locks: dict = field(default_factory=dict)
    fingerprints: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)            # authoritative T19 plan
    replan_state: dict = field(default_factory=dict)
    event_seq: int = 0
    steps: int = 0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.counters:
            self.counters = {k: 0 for k in ZERO_TOLERANCE_KEYS}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OrchestrationRun":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


def new_run_id(plan_id: str, started_at: str) -> str:
    return _id("run_", plan_id, started_at)


def run_state_hash(run: OrchestrationRun) -> str:
    import json
    blob = json.dumps(canonical_run(run), sort_keys=True,
                      ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def canonical_run(run: OrchestrationRun) -> dict:
    d = run.to_dict()
    d.pop("run_hash", None)
    return d