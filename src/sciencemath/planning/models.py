"""T19.3–T19.4 / T19.14 / T19.16–T19.17 plan, task, budget, observation models."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone

from sciencemath.planning.contract import (
    COST_FREE, SCHEMA_VERSION, SIDE_EFFECT_CLASSES,
)


def utc_now(now: str | None = None) -> str:
    if now:
        return now
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _id(prefix: str, *parts: object) -> str:
    blob = "|".join(str(p) for p in parts)
    return prefix + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def default_budget() -> dict:
    return {
        "max_tasks": 30,
        "max_depth": 8,
        "max_replans": 5,
        "max_attempts_per_task": 3,
        "max_network_reads": 8,
        "max_document_reads": 8,
        "max_code_iterations": 6,
        "max_memory_writes": 2,
        "max_wall_time_class": "SHORT",
        "max_cost_class": COST_FREE,
        "consumed_tasks": 0,
        "consumed_replans": 0,
        "consumed_network_reads": 0,
        "consumed_document_reads": 0,
        "consumed_code_iterations": 0,
        "consumed_memory_writes": 0,
        "non_progress_streak": 0,
    }


@dataclass
class Assumption:
    assumption_id: str
    statement: str
    confidence: str = "MEDIUM"
    validation_task: str | None = None
    status: str = "UNVERIFIED"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Assumption":
        return cls(**{f.name: d[f.name] for f in fields(cls) if f.name in d})


@dataclass
class Observation:
    observation_id: str
    task_id: str
    result_status: str
    facts: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    confidence: str = "HIGH"
    timestamp: str = ""
    failure_class: str | None = None
    instruction_authority: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Observation":
        return cls(**{f.name: d[f.name] for f in fields(cls) if f.name in d})


@dataclass
class Task:
    task_id: str
    title: str
    objective: str
    task_type: str
    required_skill: str
    required_inputs: list = field(default_factory=list)
    expected_outputs: list = field(default_factory=list)
    preconditions: list = field(default_factory=list)
    postconditions: list = field(default_factory=list)
    success_criteria: list = field(default_factory=list)
    failure_conditions: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    status: str = "PENDING"
    attempt_count: int = 0
    max_attempts: int = 3
    estimated_cost_class: str = COST_FREE
    network_required: bool = False
    persistent_write_requested: bool = False
    side_effect_class: str = "NONE"
    observations: list = field(default_factory=list)
    result_reference: str | None = None
    execution_authority: bool = False
    approval_required: bool = False
    approval_reason: str = ""
    optional: bool = False
    parallel_safe: bool = False
    rationale: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.execution_authority = False
        if self.side_effect_class not in SIDE_EFFECT_CLASSES:
            self.side_effect_class = "NONE"
        if self.estimated_cost_class == "PAID":
            self.side_effect_class = "PAID"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["execution_authority"] = False
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        known = {f.name for f in fields(cls)}
        obj = cls(**{k: v for k, v in d.items() if k in known})
        obj.execution_authority = False
        return obj


@dataclass
class Plan:
    plan_id: str
    goal: str
    goal_type: str
    created_at: str
    updated_at: str
    status: str
    constraints: list = field(default_factory=list)
    preferences: list = field(default_factory=list)
    assumptions: list = field(default_factory=list)
    success_criteria: list = field(default_factory=list)
    failure_criteria: list = field(default_factory=list)
    budget: dict = field(default_factory=default_budget)
    tasks: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    checkpoints: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    revisions: list = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    plan_version: int = 1
    plan_hash: str = ""
    schema_version: int = SCHEMA_VERSION
    subgoals: list = field(default_factory=list)
    replan_policy: str = "EVENT_TRIGGERED"
    stop_conditions: list = field(default_factory=list)
    graph_meta: dict = field(default_factory=dict)
    best_verified: dict = field(default_factory=dict)
    blocked_reason: str = ""
    completion_evidence: list = field(default_factory=list)
    decision_metadata: list = field(default_factory=list)
    history: list = field(default_factory=list)

    def task_map(self) -> dict[str, Task]:
        out = {}
        for t in self.tasks:
            if isinstance(t, Task):
                out[t.task_id] = t
            else:
                obj = Task.from_dict(t)
                out[obj.task_id] = obj
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tasks"] = [
            t.to_dict() if isinstance(t, Task) else dict(t)
            for t in self.tasks
        ]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        known = {f.name for f in fields(cls)}
        payload = {k: v for k, v in d.items() if k in known}
        tasks = []
        for t in payload.get("tasks") or []:
            tasks.append(t if isinstance(t, Task) else Task.from_dict(t))
        payload["tasks"] = tasks
        if not payload.get("budget"):
            payload["budget"] = default_budget()
        return cls(**payload)


def new_plan_id(goal: str, created_at: str) -> str:
    return _id("pln_", goal, created_at)


def new_obs_id(task_id: str, ts: str) -> str:
    return _id("obs_", task_id, ts)


def snapshot_best(plan: Plan) -> dict:
    kept = []
    for t in plan.tasks:
        task = t if isinstance(t, Task) else Task.from_dict(t)
        if task.status == "SUCCEEDED" and task.result_reference:
            kept.append({
                "task_id": task.task_id,
                "result_reference": task.result_reference,
                "required_skill": task.required_skill,
                "status": "SUCCEEDED",
            })
    return {
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "completed": kept,
        "status": plan.status,
    }
