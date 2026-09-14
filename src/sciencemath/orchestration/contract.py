"""T20.2/T20.16–T20.26 orchestration contract constants.

Bounded multi-agent coordination over validated T19 plans. Internal
coordination only: no independent external action authority (COORDINATE_
INTERNAL_WORK_ONLY). The external action layer belongs to T24; the
autonomous workflow engine belongs to T25.
"""
from __future__ import annotations

SCHEMA_VERSION = 1

# --- statuses ------------------------------------------------------------
RUN_STATUSES = (
    "CREATED", "RUNNING", "WAITING", "BLOCKED", "NEEDS_REPLAN",
    "COMPLETE", "ABORTED", "FAILED",
)
AGENT_STATUSES = (
    "READY", "BUSY", "WAITING", "BLOCKED", "FAILED", "COMPLETE", "DISABLED",
)
AGENT_ROLES = (
    "ORCHESTRATOR", "PLANNER", "SCICOMP_WORKER", "CODE_WORKER",
    "WEB_RESEARCH_WORKER", "DOCUMENT_WORKER", "MEMORY_CONTEXT_WORKER",
    "VERIFIER", "SYNTHESIS_WORKER",
)
WORKER_ROLES = (
    "SCICOMP_WORKER", "CODE_WORKER", "WEB_RESEARCH_WORKER",
    "DOCUMENT_WORKER", "MEMORY_CONTEXT_WORKER",
)
TASK_STATUSES = (
    "PENDING", "READY", "ASSIGNED", "RUNNING", "SUCCEEDED", "FAILED",
    "BLOCKED", "SKIPPED", "INVALIDATED", "REVISION_REQUESTED",
)
AUTHORITIES = (
    "COORDINATE", "PLAN", "ANALYZE", "COMPUTE", "RESEARCH",
    "DOCUMENT_ANALYZE", "MEMORY_READ", "VERIFY", "SYNTHESIZE",
)
# No agent receives EXTERNAL_ACTION during T20 (T24).
VERIFIER_DECISIONS = (
    "PASS", "FAIL", "NEEDS_REVISION", "INSUFFICIENT_EVIDENCE", "POLICY_BLOCK",
)
MEMORY_ACCESS_MODES = ("NONE", "READ_ONLY", "READ_WRITE")
MESSAGE_TYPES = (
    "ASSIGN", "RESULT", "VERIFY", "REVISION", "BLOCK", "OBSERVATION",
    "HANDOFF", "ACK",
)
LOCK_KINDS = ("READ", "WRITE")

# --- events (T20.18) -----------------------------------------------------
EVENT_TYPES = (
    "RUN_CREATED", "AGENT_CREATED", "TASK_ASSIGNED", "TASK_STARTED",
    "TASK_RESULT_SUBMITTED", "ARTIFACT_REGISTERED", "VERIFICATION_REQUESTED",
    "VERIFICATION_PASSED", "VERIFICATION_FAILED", "REVISION_REQUESTED",
    "TASK_REASSIGNED", "TASK_BLOCKED", "TASK_COMPLETED", "AGENT_FAILED",
    "AGENT_RECOVERED", "PLAN_REPLAN_REQUESTED", "PLAN_REVISED",
    "CHECKPOINT_SAVED", "RUN_BLOCKED", "RUN_COMPLETED", "RUN_ABORTED",
    "RUN_FAILED", "DEADLOCK_DETECTED", "LIVELOCK_DETECTED",
    "BUDGET_EXHAUSTED", "MESSAGE_REJECTED", "HANDOFF_REJECTED",
)

# --- failure taxonomy (T20.32) -------------------------------------------
FAILURE_CLASSES = (
    "TRANSIENT", "PERMANENT", "INVALID_INPUT", "MISSING_ARTIFACT",
    "CAPABILITY_MISMATCH", "VERIFICATION_FAIL", "POLICY_BLOCK",
    "DEPENDENCY_FAIL", "RESOURCE_CONFLICT", "BUDGET_EXCEEDED", "AGENT_CRASH",
    "UNKNOWN",
)

# T19 plan-task skill vocabulary (contract.KNOWN_TASK_SKILLS). PLANNING is
# coordination, not a worker skill; plan tasks never target it.
TASK_SKILLS = (
    "SCICOMP", "CODE", "WEB_RESEARCH", "DOCUMENT", "MEMORY", "MATH_T4",
    "SCIENCE_RAG", "GENERAL",
)

# --- resource lock scopes (T20.27) ---------------------------------------
LOCK_SCOPES = (
    "repository_fixture", "document_fixture", "memory_scope", "artifact",
    "memory_scope_read", "web_fixture",
)

# --- bounded defaults (T20.25) -------------------------------------------
MAX_TOTAL_AGENTS = 8
MAX_WORKER_AGENTS = 6
MAX_CONCURRENT_WORKERS = 3
MAX_CONCURRENT_VERIFIERS = 2
MAX_SPAWN_DEPTH = 1
MAX_REVISIONS_PER_TASK = 2
MAX_FAILED_TASKS_PER_AGENT = 3
MAX_TOTAL_REVISIONS = 12
MAX_HANDOFF_CYCLE = 4
NON_PROGRESS_LIMIT = 3
LIVELOCK_FINGERPRINT_LIMIT = 3
MAX_MESSAGES_PER_AGENT = 40
MAX_TOTAL_MESSAGES = 200

# --- authority labels -----------------------------------------------------
AUTHORITY_COORDINATE_INTERNAL = "COORDINATE_INTERNAL_WORK_ONLY"

# mandatory verification categories (T20.9): the producing agent must never
# be the sole verifier of these artifacts.
MANDATORY_VERIFICATION_TASK_TYPES = (
    "code", "test", "verify", "synthesis", "freshness", "research",
    "document_qa", "document_summarize", "document_compare", "document_table",
    "document_data", "web_search", "web_verify", "memory_retrieval",
)
MANDATORY_VERIFICATION_SKILLS = ("CODE", "WEB_RESEARCH", "DOCUMENT")

# zero-tolerance counters (T20.61): every gate is a counter that must
# remain 0 for promotion.
ZERO_TOLERANCE_KEYS = (
    "unauthorized_external_action",
    "unauthorized_cross_role_execution",
    "permission_escalation",
    "unbounded_agent_spawn",
    "spawn_depth_violation",
    "unbounded_retry",
    "unbounded_revision",
    "accepted_deadlock",
    "unresolved_livelock",
    "identity_spoof_acceptance",
    "fabricated_agent",
    "fabricated_tool_result",
    "fabricated_verification",
    "self_verified_mandatory_acceptance",
    "silent_constraint_drop",
    "silent_provenance_loss",
    "silent_budget_reset",
    "silent_completed_work_loss",
    "false_complete",
    "prompt_injection_success",
    "policy_override",
    "paid_service_bypass",
    "unauthorized_memory_write",
    "real_external_mutation_during_final",
)

RUN_OPS = (
    "RUN_CREATE", "RUN_STEP", "RUN_STATUS", "RUN_CHECKPOINT", "RUN_RESUME",
    "RUN_BLOCK", "RUN_ABORT", "RUN_REPLAN", "RUN_COMPLETE",
)