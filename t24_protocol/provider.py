"""T24 production provider: frozen T23 candidate execution with T24 private mounting.

The router and capability dispatch are the frozen T23 production provider. T24
adds: the live-web firewall is mandatory on the web path, the corpus is mounted
from the private store, and gold can never reach the provider.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from sciencemath.executive.router_v2 import route_request
from t23_protocol.provider import ProductionRouterProvider, ProductionDispatchError

from .firewall import FirewallSearchProvider

PROVIDER_ID = "t24_protocol.provider:T24ProductionRouterProvider"


class T24ProductionRouterProvider(ProductionRouterProvider):
    provider_id = PROVIDER_ID
    provider_kind = "REAL_CANDIDATE"
    synthetic = False

    def __init__(self, corpus_dir: Path, *, web_provider: Any = None,
                 general_context: Any = None,
                 specialist_adapters: Mapping[str, Callable[..., Any]] | None = None,
                 document_roots: tuple[Path, ...] = (),
                 workspace_mode: str = "REAL_EXPERIMENT",
                 firewall_mandatory: bool = True) -> None:
        if firewall_mandatory and web_provider is not None \
                and not isinstance(web_provider, FirewallSearchProvider):
            raise ProductionDispatchError(
                "T24 production web path requires the live-web source firewall")
        super().__init__(corpus_dir, web_provider=web_provider, general_context=general_context,
                         specialist_adapters=specialist_adapters,
                         document_roots=document_roots, workspace_mode=workspace_mode)

    def firewall_counters(self) -> dict[str, Any]:
        if isinstance(self.web_provider, FirewallSearchProvider):
            return dict(self.web_provider.firewall.counters)
        return {}

    def generate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Frozen candidate execution; gold exposure raises before any row runs."""
        return super().generate(rows)


def decision_parity(inputs: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Direct route_request parity against the runtime router."""
    mismatches = []
    for row, output in zip(inputs, outputs):
        direct = route_request(row["candidate_input"])
        decision = output["router_decision"]
        differing = {key for key in direct if decision.get(key) != direct[key]}
        if differing:
            mismatches.append({"case_id": row["case_id"], "fields": sorted(differing)})
    return {"status": "PASS" if not mismatches else "FAIL", "rows": len(inputs),
            "parity_mismatches": mismatches}


assert callable(route_request)