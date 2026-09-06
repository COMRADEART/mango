"""Mango T7 executive layer.

A bounded, deterministic plan -> execute -> observe -> verify ->
re-plan loop around Mango-v0.1. No weight changes, no new external
dependencies; the model proposes content, deterministic rules drive
control flow. See research/t7_github_architecture_review.md for the
adopted patterns (A1-A14).
"""
from sciencemath.executive.state import (
    STATES, TERMINAL_STATES, STATE_TRANSITIONS, STOP_REASONS,
    REASON_TO_STATE, EVIDENCE_STATUSES, TransitionError,
    validate_transition, transition, RunState, new_run, SCHEMA_VERSION,
)
from sciencemath.executive.budgets import Budgets, default_usage, exceeded
from sciencemath.executive.classify import (
    classify_problem, classify_complexity, classify_resources,
    fast_path_eligible, PROBLEM_TYPES, COMPLEXITIES, RESOURCES,
)
from sciencemath.executive.plan import (
    ACTIONS, PLAN_SCHEMA_DOC, validate_plan, parse_model_plan,
    fallback_plan, plan_fingerprint, PlanValidation,
)
from sciencemath.executive.runner import (
    ExecContext, DEFAULT_FEATURES, run_executive,
)

__all__ = [
    "STATES", "TERMINAL_STATES", "STATE_TRANSITIONS", "STOP_REASONS",
    "REASON_TO_STATE", "EVIDENCE_STATUSES", "TransitionError",
    "validate_transition", "transition", "RunState", "new_run",
    "SCHEMA_VERSION", "Budgets", "default_usage", "exceeded",
    "classify_problem", "classify_complexity", "classify_resources",
    "fast_path_eligible", "PROBLEM_TYPES", "COMPLEXITIES", "RESOURCES",
    "ACTIONS", "PLAN_SCHEMA_DOC", "validate_plan", "parse_model_plan",
    "fallback_plan", "plan_fingerprint", "PlanValidation",
    "ExecContext", "DEFAULT_FEATURES", "run_executive",
]