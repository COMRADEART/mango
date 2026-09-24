"""Registered Mango capability adapters for the T26 internal executor.

All mutable paths are derived from the runner's disposable/private sandbox.
The T25 provider handles its qualified GENERAL, KNOWLEDGE_RAG, DOCUMENT and
WEB_RESEARCH routes. Other skills call their existing public runtime APIs.
No adapter can perform an external action through this registry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import Adapter, ExecutionError, UnavailableError
from t25_protocol.firewall import FirewallSearchProvider
from t25_protocol.provider import T25ProductionRouterProvider
from .firewall import T26LiveWebSourceFirewall

PROVIDER_CAPABILITIES = frozenset({"GENERAL", "KNOWLEDGE_RAG", "DOCUMENT",
                                   "WEB_RESEARCH", "SCIENCE_RAG"})


def _evidence(source: str, context: dict, *, citation: str | None = None) -> list[dict]:
    return [{"source_id": source,
             "chunk_id": f"{context['scenario_id']}:{context['step_id']}",
             "citation": citation or source,
             "classification": context["classification"],
             "freshness": "STATIC"}]


def _result(status: str, value: Any, source: str, context: dict,
            *, evidence: list[dict] | None = None,
            confidence: str = "HIGH") -> dict:
    return {"status": status, "value": value,
            "evidence": evidence if evidence is not None else _evidence(source, context),
            "provenance": {"source_id": source, "instruction_authority": 0,
                           "capability": context["router_decision"]["selected_capability"]},
            "classification": context["classification"],
            "confidence": confidence}


def _sandbox(context: dict, name: str) -> Path:
    root = Path(context["sandbox_root"]).resolve()
    path = (root / name).resolve()
    if root not in path.parents:
        raise ExecutionError("capability sandbox escape")
    return path


def _provider_call(provider: T25ProductionRouterProvider, capability: str,
                   payload: dict, context: dict) -> dict:
    if capability == "WEB_RESEARCH" and not (
            isinstance(provider.web_provider, FirewallSearchProvider) and
            isinstance(provider.web_provider.firewall, T26LiveWebSourceFirewall)):
        raise ExecutionError("T26 additive live-web firewall missing")
    decision = context["router_decision"]
    query = payload.get("query") or context["router_input"]["query"]
    if not isinstance(query, str) or not query.strip():
        raise ExecutionError("capability query missing")
    exec_context = {}
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
    except Exception as exc:
        raise UnavailableError(f"provider capability unavailable: {capability}") from exc
    if raw.get("capability") != capability:
        raise ExecutionError("production capability dispatch mismatch")
    status = raw.get("status")
    if status in {"OK", "ANSWER", "PARTIALLY_SUPPORTED", "DOC_ANSWER"}:
        normalized = "OK"
    elif status in {"CONFLICTING_EVIDENCE"}:
        normalized = "CONFLICTING_EVIDENCE"
    elif status in {"SECURITY_REFUSAL"}:
        normalized = "SECURITY_REFUSAL"
    else:
        normalized = "INSUFFICIENT_EVIDENCE"
    detail = raw.get("evidence") or {}
    citations = detail.get("citations") if isinstance(detail, dict) else None
    evidence = []
    if isinstance(citations, list):
        for i, citation in enumerate(citations):
            if isinstance(citation, dict):
                source = str(citation.get("source_id") or citation.get("url") or "")
                chunk = str(citation.get("chunk_id") or citation.get("evidence_id") or i)
                marker = str(citation.get("citation") or citation.get("url") or source)
                if source and marker:
                    evidence.append({"source_id": source, "chunk_id": chunk,
                                     "citation": marker,
                                     "classification": context["classification"],
                                     "freshness": str(citation.get("freshness") or "UNKNOWN")})
    if not evidence and normalized == "OK" and capability in {"GENERAL", "SCIENCE_RAG"}:
        # General/model output has no source citation; schema verification can
        # accept it, while evidence/citation verification correctly refuses.
        evidence = []
    return _result(normalized, raw.get("answer"),
                   f"t25-provider:{capability}", context,
                   evidence=evidence,
                   confidence="HIGH" if normalized == "OK" else "LOW")


def _math(payload: dict, context: dict) -> dict:
    from sciencemath.tools.calculator import CalculatorTool

    expression = payload.get("expression")
    if expression is None and isinstance(payload.get("previous"), (int, float)) and isinstance(payload.get("delta"), (int, float)):
        expression = f"({payload['previous']})+({payload['delta']})"
    if not isinstance(expression, str):
        raise ExecutionError("math expression missing")
    answer = CalculatorTool().run({"expression": expression})
    if answer.status != "ok":
        return _result("INSUFFICIENT_EVIDENCE", None, "MATH_T4:calculator", context,
                       confidence="LOW")
    return _result("OK", answer.result["value"], "MATH_T4:calculator", context)


def _scicomp(payload: dict, context: dict) -> dict:
    from sciencemath.scicomp.invocation import invoke

    if payload.get("op") == "describe_previous":
        previous, delta = payload.get("previous"), payload.get("delta")
        if type(previous) not in {int, float} or type(delta) not in {int, float}:
            raise ExecutionError("SciComp predecessor value missing")
        request = {"operation": "describe",
                   "inputs": {"values": [previous, previous + 2 * delta]}}
    else:
        request = payload.get("compute_request")
    if not isinstance(request, dict):
        raise ExecutionError("structured SciComp request missing")
    answer = invoke(request, question=str(payload.get("query") or ""))
    if not answer.adopted:
        return _result("INSUFFICIENT_EVIDENCE", None, "SCICOMP", context,
                       confidence="LOW")
    value = answer.envelope.get("result")
    if payload.get("op") == "describe_previous":
        value = value.get("mean") if isinstance(value, dict) else None
    return _result("OK", value, "SCICOMP", context)


def _code(payload: dict, context: dict) -> dict:
    from sciencemath.code.runner import run_coding_task

    root = _sandbox(context, "code-repository")
    if not root.is_dir() or not (root / ".git").exists():
        raise UnavailableError("disposable code repository absent")
    request = payload.get("request")
    if not isinstance(request, str) or not request:
        raise ExecutionError("code request missing")
    answer = run_coding_task(root, request,
                             op=payload.get("op"),
                             network_permitted=False,
                             checkpoint_dir=_sandbox(context, "code-checkpoints"))
    if answer.get("requested_action"):
        return _result("SECURITY_REFUSAL", None, "CODE", context,
                       confidence="LOW")
    status = "OK" if answer.get("status") == "EXECUTED_PASS" else "INSUFFICIENT_EVIDENCE"
    return _result(status, answer.get("answer") or answer.get("detail"),
                   "CODE", context, confidence="HIGH" if status == "OK" else "LOW")


def _memory(payload: dict, context: dict) -> dict:
    from sciencemath.memory.pipeline import handle
    from sciencemath.memory.store import MemoryStore

    root = _sandbox(context, "memory")
    root.mkdir(parents=True, exist_ok=True)
    query = payload.get("query")
    if not isinstance(query, str) or not query:
        raise ExecutionError("memory query missing")
    with MemoryStore(root / "t26-memory.sqlite", allow_fixture=True) as store:
        answer = handle(query, store=store,
                        owner_id=f"t26-{context['scenario_id']}",
                        scope_type="SESSION", scope_id=context["scenario_id"],
                        content=payload.get("content"),
                        user_explicit=bool(payload.get("user_explicit")),
                        write_reason=payload.get("write_reason"),
                        op=payload.get("op"))
    if answer.instruction_authority != 0:
        raise ExecutionError("memory instruction authority escalation")
    status = "OK" if answer.status not in {"MEMORY_NO_MATCH", "MEMORY_EXPIRED",
                                            "MEMORY_BLOCKED_POLICY", "MEMORY_BLOCKED_SECRET"} else "INSUFFICIENT_EVIDENCE"
    return _result(status, answer.answer, "MEMORY:t26-sandbox", context,
                   confidence="HIGH" if status == "OK" else "LOW")


def _planning(payload: dict, context: dict) -> dict:
    from sciencemath.planning.pipeline import Planner

    request = payload.get("request")
    if not isinstance(request, dict):
        raise ExecutionError("planner request missing")
    planner = Planner()
    result = planner.handle(request)
    if result.execution_authority != "PROPOSE_ONLY" or planner.log.total() != 0:
        raise ExecutionError("planner authority escalation")
    return _result("OK" if result.ok else "INSUFFICIENT_EVIDENCE",
                   result.plan.to_dict() if result.plan else None,
                   "PLANNING:T19", context,
                   confidence="HIGH" if result.ok else "LOW")


def _orchestration(payload: dict, context: dict) -> dict:
    from sciencemath.orchestration.pipeline import OrchestratorFacade

    request = payload.get("request")
    if not isinstance(request, dict):
        raise ExecutionError("orchestration request missing")
    result = OrchestratorFacade().handle(request)
    if result.authority != "COORDINATE_INTERNAL_WORK_ONLY":
        raise ExecutionError("orchestrator authority escalation")
    return _result("OK" if result.ok else "INSUFFICIENT_EVIDENCE",
                   result.to_dict() if result.ok else None,
                   "ORCHESTRATION:T20", context,
                   confidence="HIGH" if result.ok else "LOW")


def _no_tool(payload: dict, context: dict) -> dict:
    return _result("INSUFFICIENT_EVIDENCE", None, "NO_TOOL", context,
                   evidence=[], confidence="LOW")


def build_adapters(provider: T25ProductionRouterProvider) -> dict[str, Adapter]:
    """Bind all registered skills to their frozen runtime or safe terminal."""
    if not isinstance(provider, T25ProductionRouterProvider):
        raise ExecutionError("T25-qualified production provider required")
    mapping = {
        "MATH_T4": _math, "SCICOMP": _scicomp, "CODE": _code,
        "MEMORY": _memory, "PLANNING": _planning,
        "ORCHESTRATION": _orchestration, "NO_TOOL": _no_tool,
    }
    for capability in PROVIDER_CAPABILITIES:
        mapping[capability] = (lambda payload, context, cap=capability:
                               _provider_call(provider, cap, payload, context))
    if set(mapping) != set(SKILL_IDS):
        raise ExecutionError("production capability registry incomplete")
    return {cap: Adapter(cap, function) for cap, function in mapping.items()}
