"""T16.43 — auditable research trace. Observable actions only."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResearchTrace:
    queries_issued: list[str] = field(default_factory=list)
    results_considered: list[str] = field(default_factory=list)
    sources_fetched: list[str] = field(default_factory=list)
    sources_rejected: list[dict] = field(default_factory=list)
    claims_created: list[str] = field(default_factory=list)
    evidence_links: list[dict] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    final_citations: list[dict] = field(default_factory=list)
    injection_events: list[dict] = field(default_factory=list)
    network_actions: list[str] = field(default_factory=list)
    paid_gate: dict | None = None

    def to_dict(self) -> dict:
        return {
            "queries_issued": list(self.queries_issued),
            "results_considered": list(self.results_considered),
            "sources_fetched": list(self.sources_fetched),
            "sources_rejected": list(self.sources_rejected),
            "claims_created": list(self.claims_created),
            "evidence_links": list(self.evidence_links),
            "contradictions": list(self.contradictions),
            "final_citations": list(self.final_citations),
            "injection_events": list(self.injection_events),
            "network_actions": list(self.network_actions),
            "paid_gate": self.paid_gate,
        }
