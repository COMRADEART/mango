"""T20 bounded multi-agent orchestration (EXPERIMENTAL).

Coordination of bounded specialist agents over validated T19 plans.
Authority: COORDINATE_INTERNAL_WORK_ONLY — no external action (T24),
no autonomous workflow engine (T25), no Executive Router promotion.
"""
from sciencemath.orchestration.contract import (
    EVENT_TYPES, FAILURE_CLASSES, RUN_OPS, RUN_STATUSES, SCHEMA_VERSION,
    ZERO_TOLERANCE_KEYS,
)
from sciencemath.orchestration.models import (
    AgentSpec, ArtifactReference, Handoff, Message, OrchestrationRun,
    Verification, default_run_budget,
)
from sciencemath.orchestration.pipeline import (
    OrchestratorFacade, OrchestrationError,
)
from sciencemath.orchestration.orchestrator import (
    Orchestrator, RunResult, completion_ok,
)

__all__ = [
    "EVENT_TYPES", "FAILURE_CLASSES", "RUN_OPS", "RUN_STATUSES",
    "SCHEMA_VERSION", "ZERO_TOLERANCE_KEYS",
    "AgentSpec", "ArtifactReference", "Handoff", "Message",
    "OrchestrationRun", "Verification", "default_run_budget",
    "OrchestratorFacade", "OrchestrationError",
    "Orchestrator", "RunResult", "completion_ok",
]