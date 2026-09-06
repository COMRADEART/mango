"""T7.1/T7.2 — Executive state machine.

A strict, typed state model. Every run moves through explicit states;
invalid transitions raise. The model never drives control flow: the
runner computes transitions deterministically from observations and
verification results (research pattern A2/A1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0.0"

# -- states -----------------------------------------------------------------
RECEIVED = "RECEIVED"
CLASSIFYING = "CLASSIFYING"
PLANNING = "PLANNING"
EXECUTING = "EXECUTING"
OBSERVING = "OBSERVING"
VERIFYING = "VERIFYING"
REPLANNING = "REPLANNING"
SYNTHESIZING = "SYNTHESIZING"
COMPLETE = "COMPLETE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
FAILED = "FAILED"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
STALLED = "STALLED"

STATES = frozenset({
    RECEIVED, CLASSIFYING, PLANNING, EXECUTING, OBSERVING, VERIFYING,
    REPLANNING, SYNTHESIZING, COMPLETE, INSUFFICIENT_EVIDENCE, FAILED,
    BUDGET_EXHAUSTED, STALLED,
})

TERMINAL_STATES = frozenset({
    COMPLETE, INSUFFICIENT_EVIDENCE, FAILED, BUDGET_EXHAUSTED, STALLED,
})

# legal transitions: from -> allowed next states
STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    RECEIVED: frozenset({CLASSIFYING}),
    CLASSIFYING: frozenset({PLANNING, COMPLETE, INSUFFICIENT_EVIDENCE,
                            FAILED}),
    PLANNING: frozenset({EXECUTING, SYNTHESIZING, INSUFFICIENT_EVIDENCE,
                         FAILED}),
    EXECUTING: frozenset({OBSERVING, FAILED, BUDGET_EXHAUSTED}),
    OBSERVING: frozenset({VERIFYING, REPLANNING}),
    VERIFYING: frozenset({EXECUTING, REPLANNING, SYNTHESIZING, FAILED,
                          INSUFFICIENT_EVIDENCE}),
    REPLANNING: frozenset({EXECUTING, STALLED, BUDGET_EXHAUSTED, FAILED,
                           INSUFFICIENT_EVIDENCE}),
    SYNTHESIZING: frozenset({COMPLETE, FAILED, INSUFFICIENT_EVIDENCE}),
    COMPLETE: frozenset(),
    INSUFFICIENT_EVIDENCE: frozenset(),
    FAILED: frozenset(),
    BUDGET_EXHAUSTED: frozenset(),
    STALLED: frozenset(),
}


def validate_transition(current: str, next_state: str) -> list[str]:
    """Return error strings (empty = transition is legal)."""
    errors = []
    if current not in STATES:
        errors.append(f"unknown state {current!r}")
    if next_state not in STATES:
        errors.append(f"unknown state {next_state!r}")
        return errors
    if current in STATES and next_state not in STATE_TRANSITIONS.get(
            current, frozenset()):
        errors.append(f"illegal transition {current} -> {next_state}")
    return errors


class TransitionError(ValueError):
    """Raised when a state transition is illegal (fail closed)."""


def transition(state: dict, next_state: str) -> dict:
    """Apply a validated state transition to a run-state dict. Fail
    closed: a malformed state dict (missing 'status') is an error, not
    an implicit RECEIVED."""
    if state.get("status") is None:
        raise TransitionError("state dict is malformed: missing 'status'")
    errors = validate_transition(state["status"], next_state)
    if errors:
        raise TransitionError("; ".join(errors))
    state["status"] = next_state
    state["transitions"].append(next_state)
    return state


# -- termination reasons (T7.14) --------------------------------------------
STOP_REASONS = (
    "SOLVED_VERIFIED", "SOLVED_SUPPORTED", "SOLVED_UNVERIFIED",
    "INSUFFICIENT_INFORMATION", "CONFLICTING_EVIDENCE", "MAX_STEPS",
    "MAX_REPLANS", "INVALID_PLAN", "STALLED", "TOOL_FAILURE",
    "SYSTEM_ERROR", "BUDGET_EXHAUSTED",
)

REASON_TO_STATE = {
    "SOLVED_VERIFIED": COMPLETE,
    "SOLVED_SUPPORTED": COMPLETE,
    "SOLVED_UNVERIFIED": COMPLETE,
    "INSUFFICIENT_INFORMATION": INSUFFICIENT_EVIDENCE,
    "CONFLICTING_EVIDENCE": INSUFFICIENT_EVIDENCE,
    "MAX_STEPS": FAILED,
    "MAX_REPLANS": FAILED,
    "INVALID_PLAN": FAILED,
    "STALLED": STALLED,
    "TOOL_FAILURE": FAILED,
    "SYSTEM_ERROR": FAILED,
    "BUDGET_EXHAUSTED": BUDGET_EXHAUSTED,
}

# T7.15 — categorical epistemic statuses (never a bare confidence number)
EVIDENCE_STATUSES = (
    "VERIFIED", "STRONGLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNCERTAIN",
    "INSUFFICIENT_INFORMATION", "CONFLICTING_EVIDENCE",
)


# -- run state ---------------------------------------------------------------
@dataclass
class RunState:
    """Full executive state (T7.2). Compact active context is derived,
    never the whole transcript (T7.22-style context management)."""
    run_id: str
    problem: str
    goal: str = ""
    problem_type: str = "UNKNOWN"          # MATH/SCIENCE/MIXED/GENERAL
    complexity: str = "UNKNOWN"            # SIMPLE/MULTI_STEP/OPEN_ENDED
    resources: str = "UNKNOWN"             # NONE/MATH_TOOL/RETRIEVAL/BOTH/UNKNOWN
    status: str = RECEIVED
    knowns: list = field(default_factory=list)
    unknowns: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    distractors: list = field(default_factory=list)
    missing_information: list = field(default_factory=list)
    plan: dict | None = None
    plan_version: int = 0
    completed_steps: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    verification: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    retrieval_calls: list = field(default_factory=list)
    replans: int = 0
    plan_attempts: int = 0
    failure_fingerprints: list = field(default_factory=list)
    termination_reason: str | None = None
    evidence_status: str | None = None
    final_answer: str | None = None
    transitions: list = field(default_factory=lambda: [RECEIVED])
    budget_usage: dict = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RunState":
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"incompatible executive state schema_version "
                f"{d.get('schema_version')!r} (expected {SCHEMA_VERSION!r}); "
                "no silent migration is performed")
        known = {f for f in cls.__dataclass_fields__}
        obj = cls.__new__(cls)
        for k, v in d.items():
            if k in known:
                setattr(obj, k, v)
        return obj


def new_run(run_id: str, problem: str) -> RunState:
    return RunState(run_id=run_id, problem=problem)