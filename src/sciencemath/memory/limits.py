"""T18 resource limits. Fail closed rather than unbounded."""
from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1
BACKEND = "sqlite"
PARSER_VERSION = "t18-memory-v1"

MAX_CONTENT_CHARS = 4_000
MAX_BATCH_WRITE = 32
MAX_TOP_K = 20
DEFAULT_TOP_K = 5
MAX_CANDIDATES = 100
MAX_DB_RETRY = 8
MAX_CACHE_ENTRIES = 256
BUSY_TIMEOUT_MS = 5_000
CONNECT_TIMEOUT_S = 5.0

PAID_COMPUTE_GATE_REQUIRED = "PAID_COMPUTE_GATE_REQUIRED"


@dataclass(frozen=True)
class MemoryLimits:
    max_content_chars: int = MAX_CONTENT_CHARS
    max_batch_write: int = MAX_BATCH_WRITE
    max_top_k: int = MAX_TOP_K
    default_top_k: int = DEFAULT_TOP_K
    max_candidates: int = MAX_CANDIDATES
    max_db_retry: int = MAX_DB_RETRY
    max_cache_entries: int = MAX_CACHE_ENTRIES
    busy_timeout_ms: int = BUSY_TIMEOUT_MS
    connect_timeout_s: float = CONNECT_TIMEOUT_S


def paid_gate(*, provider: str, estimated_cost: str, reason: str,
              free_alternative: str, expected_benefit: str) -> dict:
    return {
        "status": PAID_COMPUTE_GATE_REQUIRED,
        "provider": provider,
        "estimated_cost": estimated_cost,
        "reason": reason,
        "free_alternative": free_alternative,
        "expected_benefit": expected_benefit,
        "action": "STOP",
    }
