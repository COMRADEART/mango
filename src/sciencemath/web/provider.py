"""T16.3 — provider-neutral research interface."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from sciencemath.web.limits import FREE_LOCAL, PAID_NETWORK, paid_gate
from sciencemath.web.source import Source


@runtime_checkable
class ResearchProvider(Protocol):
    provider_name: str
    provider_cost_class: str
    network_required: bool
    live_or_fixture: str

    def search(self, query: str) -> list[Source]: ...
    def fetch(self, url: str) -> Source: ...
    def metadata(self, url: str) -> dict: ...
    def timestamp(self) -> str: ...


def assert_cost_allowed(provider: ResearchProvider) -> dict | None:
    if getattr(provider, "provider_cost_class", None) == PAID_NETWORK:
        return paid_gate(
            provider=getattr(provider, "provider_name", "UNKNOWN"),
            estimated_cost="UNKNOWN",
            reason="T16 permits only FREE_LOCAL and FREE_NETWORK",
            free_alternative="FIXTURE_SEARCH_PROVIDER or Wikipedia REST",
            expected_benefit="none — paid network is forbidden",
        )
    return None


class NullProvider:
    """Parametric baseline: no search, no fetch, no citations."""
    provider_name = "NULL_PROVIDER"
    provider_cost_class = FREE_LOCAL
    network_required = False
    live_or_fixture = "fixture"

    def search(self, query: str) -> list[Source]:
        return []

    def fetch(self, url: str) -> Source:
        return Source(source_id="UNKNOWN", url=url or "UNKNOWN",
                      fetch_status="ERROR")

    def metadata(self, url: str) -> dict:
        return {"url": url or "UNKNOWN", "status": "UNAVAILABLE"}

    def timestamp(self) -> str:
        return "UNKNOWN"
