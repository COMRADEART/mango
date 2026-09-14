"""T18.8–T18.9 — persistent writes must be intentional."""
from __future__ import annotations

from sciencemath.memory.contract import is_explicit_write
from sciencemath.memory.models import WRITE_REASONS

ALLOWED = set(WRITE_REASONS)


def write_allowed(*, question: str = "", write_reason: str | None,
                  user_explicit: bool = False, durable_memory: bool = False,
                  project_state: bool = False) -> tuple[bool, str | None]:
    """Return (ok, reason). No valid write reason => do not persist."""
    reason = (write_reason or "").strip()
    explicit = bool(user_explicit or is_explicit_write(question))
    if reason and reason not in ALLOWED:
        return False, None
    if explicit:
        return True, reason or "USER_EXPLICIT_SAVE"
    if durable_memory:
        return True, reason or "WORKFLOW_DURABLE"
    if project_state:
        return True, reason or "PROJECT_STATE_COMMIT"
    if reason == "TOOL_VERIFIED_RESULT" and durable_memory:
        return True, reason
    if reason == "TOOL_VERIFIED_RESULT":
        # tool results persist only when the workflow marks them durable
        return False, None
    return False, None


def confidence_for(*, memory_type: str, source_type: str,
                   verified: bool = False, has_provenance: bool = True,
                   user_confirmed: bool = False,
                   conflicted: bool = False) -> str:
    if conflicted:
        return "MEDIUM"
    if memory_type == "INFERENCE" or source_type == "DERIVED":
        return "LOW" if not user_confirmed else "MEDIUM"
    if verified and source_type in ("SCICOMP", "CODE", "SYSTEM_EVENT"):
        return "VERIFIED"
    if source_type == "USER" and user_confirmed:
        if memory_type == "USER_PREFERENCE":
            return "HIGH"
        return "HIGH"
    if not has_provenance:
        return "UNKNOWN"
    if source_type in ("WEB", "DOCUMENT"):
        return "MEDIUM"
    return "MEDIUM"
