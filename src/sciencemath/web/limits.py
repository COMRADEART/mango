"""T16.27 / T16.51 — cost classes and resource limits."""
from __future__ import annotations

from dataclasses import dataclass

FREE_LOCAL = "FREE_LOCAL"
FREE_NETWORK = "FREE_NETWORK"
PAID_NETWORK = "PAID_NETWORK"
COST_CLASSES = (FREE_LOCAL, FREE_NETWORK, PAID_NETWORK)

PAID_COMPUTE_GATE_REQUIRED = "PAID_COMPUTE_GATE_REQUIRED"

MAX_SEARCH_QUERIES = 6
MAX_FETCHED_SOURCES = 12
MAX_EVIDENCE_SPANS_PER_SOURCE = 8
MAX_RESEARCH_DEPTH = 3
MAX_REDIRECTS = 5
MAX_FETCHED_TEXT_CHARS = 20_000
MAX_RETRY_COUNT = 2
MAX_QUOTE_CHARS = 280


@dataclass(frozen=True)
class ResearchLimits:
    max_search_queries: int = MAX_SEARCH_QUERIES
    max_fetched_sources: int = MAX_FETCHED_SOURCES
    max_evidence_spans_per_source: int = MAX_EVIDENCE_SPANS_PER_SOURCE
    max_research_depth: int = MAX_RESEARCH_DEPTH
    max_redirects: int = MAX_REDIRECTS
    max_fetched_text_chars: int = MAX_FETCHED_TEXT_CHARS
    max_retry_count: int = MAX_RETRY_COUNT
    max_quote_chars: int = MAX_QUOTE_CHARS


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
