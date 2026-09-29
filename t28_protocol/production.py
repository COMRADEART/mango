"""T28 production adapter successor with explicit provider normalization."""
from __future__ import annotations

from typing import Any

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import Adapter, ExecutionError, UnavailableError
from t25_protocol.firewall import FirewallSearchProvider
from t25_protocol.provider import T25ProductionRouterProvider
from t26_protocol.firewall import T26LiveWebSourceFirewall
from t26_protocol.production import (
    _code, _evidence, _math, _memory, _no_tool, _orchestration, _planning,
    _result, _sandbox, _scicomp,
)

PROVIDER_CAPABILITIES = frozenset({
    "GENERAL", "KNOWLEDGE_RAG", "DOCUMENT", "WEB_RESEARCH", "SCIENCE_RAG",
})
PROVIDER_STATUS_MAP = {
    "OK": "OK",
    "ANSWER": "OK",
    "DOC_ANSWER": "OK",
    "PARTIALLY_SUPPORTED": "INSUFFICIENT_EVIDENCE",
    "CONFLICTING_EVIDENCE": "CONFLICTING_EVIDENCE",
    "SECURITY_REFUSAL": "SECURITY_REFUSAL",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
    "ROUTER_CONFIGURATION_ERROR": "INSUFFICIENT_EVIDENCE",
}


def normalize_provider_status(status: Any) -> str:
    """Return the frozen T28 status or reject an unknown provider status."""
    if status not in PROVIDER_STATUS_MAP:
        raise ExecutionError("unknown production provider status")
    return PROVIDER_STATUS_MAP[status]


def _provider_call(provider: T25ProductionRouterProvider, capability: str,
                   payload: dict, context: dict) -> dict:
    if capability == "WEB_RESEARCH" and not (
            isinstance(provider.web_provider, FirewallSearchProvider) and
            isinstance(provider.web_provider.firewall, T27LiveWebSourceFirewall)):
        raise ExecutionError("qualified additive live-web firewall missing")
    decision = context["router_decision"]
    query = payload.get("query") or context["router_input"].get("query")
    if not isinstance(query, str) or not query.strip():
        raise ExecutionError("capability query missing")
    exec_context: dict[str, Any] = {}
    if capability == "DOCUMENT":
        files = payload.get("files")
        if not isinstance(files, list) or not files:
            raise ExecutionError("document files missing")
        exec_context["files"] = files
    if "request_date" in context["router_input"]:
        exec_context["request_date"] = context["router_input"]["request_date"]
    try:
        raw = provider._dispatch(decision, query, exec_context,
                                 f"{context['scenario_id']}-{context['step_id']}")
    except (ExecutionError, ValueError):
        raise
    except Exception as exc:
        raise UnavailableError(
            f"provider capability unavailable: {capability}") from exc
    if not isinstance(raw, dict) or raw.get("capability") != capability:
        raise ExecutionError("production capability dispatch mismatch")
    normalized = normalize_provider_status(raw.get("status"))
    detail = raw.get("evidence") or {}
    citations = detail.get("citations") if isinstance(detail, dict) else None
    evidence = []
    if isinstance(citations, list):
        for index, citation in enumerate(citations):
            if not isinstance(citation, dict):
                continue
            source = str(citation.get("source_id") or citation.get("url") or "")
            chunk = str(citation.get("chunk_id") or
                        citation.get("evidence_id") or index)
            marker = str(citation.get("citation") or citation.get("url") or source)
            if source and marker:
                evidence.append({
                    "source_id": source, "chunk_id": chunk, "citation": marker,
                    "classification": context["classification"],
                    "freshness": str(citation.get("freshness") or "UNKNOWN"),
                })
    return _result(normalized, raw.get("answer"),
                   f"t25-provider:{capability}", context, evidence=evidence,
                   confidence="HIGH" if normalized == "OK" else "LOW")


def build_adapters(provider: T25ProductionRouterProvider) -> dict[str, Adapter]:
    """Bind the qualified runtimes while replacing only status normalization."""
    if not isinstance(provider, T25ProductionRouterProvider):
        raise ExecutionError("T25-qualified production provider required")
    mapping = {
        "MATH_T4": _math, "SCICOMP": _scicomp, "CODE": _code,
        "MEMORY": _memory, "PLANNING": _planning,
        "ORCHESTRATION": _orchestration, "NO_TOOL": _no_tool,
    }
    for capability in PROVIDER_CAPABILITIES:
        mapping[capability] = (
            lambda payload, context, cap=capability:
            _provider_call(provider, cap, payload, context))
    if set(mapping) != set(SKILL_IDS):
        raise ExecutionError("production capability registry incomplete")
    return {capability: Adapter(capability, function)
            for capability, function in mapping.items()}


__all__ = [
    "PROVIDER_CAPABILITIES", "PROVIDER_STATUS_MAP", "build_adapters",
    "normalize_provider_status", "_provider_call", "_sandbox", "_evidence",
]
