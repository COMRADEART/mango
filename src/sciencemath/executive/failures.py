"""T7.31 — Executive failure taxonomy (17 categories, closed set).

Every non-success run termination is tagged with exactly one category.
Unknown causes fall back to SYSTEM_ERROR — never unclassified.
"""
from __future__ import annotations

FAILURE_CATEGORIES = (
    "CLASSIFICATION_FAILED",
    "PLAN_INVALID",
    "PLAN_FALLBACK_USED",
    "MODEL_CALL_FAILED",
    "MODEL_EMPTY_OUTPUT",
    "MODEL_UNPARSEABLE_OUTPUT",
    "TOOL_UNKNOWN",
    "TOOL_ARGUMENT_INVALID",
    "TOOL_RUNTIME_ERROR",
    "RETRIEVAL_EMPTY",
    "RETRIEVAL_ERROR",
    "VERIFICATION_FAILED",
    "CONTRADICTION_DETECTED",
    "BUDGET_EXHAUSTED",
    "LOOP_STALLED",
    "CORRECTION_REJECTED",
    "SYSTEM_ERROR",
)


def classify_exception(exc: Exception) -> str:
    """Map an exception to the taxonomy conservatively."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return "MODEL_CALL_FAILED"
    if "transition" in msg or "state" in msg:
        return "SYSTEM_ERROR"
    if "json" in msg or "parse" in msg:
        return "MODEL_UNPARSEABLE_OUTPUT"
    if "tool" in msg and "unknown" in msg:
        return "TOOL_UNKNOWN"
    return "SYSTEM_ERROR"