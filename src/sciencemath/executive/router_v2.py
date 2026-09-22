"""T23 Executive Router preconstruction candidate.

This module is the deterministic top-level decision layer over Mango's
registered capabilities.  It deliberately does *routing only*: it cannot
rewrite answers, alter evaluator semantics, grant permissions, or turn a
missing evidence state into a confident answer.

The T22 Knowledge/RAG runtime is an immutable dependency.  Temporal intent
classification is delegated to its frozen ``classify_query_freshness``
function so T23 does not create a second, divergent freshness policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re
from typing import Any, Mapping

from sciencemath.executive.skills import SkillRegistry
from sciencemath.knowledge.freshness import (
    INTENT_HISTORICAL,
    INTENT_RECENCY_SENSITIVE,
    classify_query_freshness,
)


ANSWER_LOCAL = "ANSWER_LOCAL"
KNOWLEDGE_RAG = "KNOWLEDGE_RAG"
ROUTE_WEB_RESEARCH = "ROUTE_WEB_RESEARCH"
HISTORICAL_AS_OF = "HISTORICAL_AS_OF"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CONFLICT_HANDLING = "CONFLICT_HANDLING"
SECURITY_REFUSAL = "SECURITY_REFUSAL"
TOOL_OR_SPECIALIST_ROUTE = "TOOL_OR_SPECIALIST_ROUTE"
ROUTER_CONFIGURATION_ERROR = "ROUTER_CONFIGURATION_ERROR"

ROUTE_IDS = (
    SECURITY_REFUSAL,
    ROUTE_WEB_RESEARCH,
    HISTORICAL_AS_OF,
    CONFLICT_HANDLING,
    INSUFFICIENT_EVIDENCE,
    TOOL_OR_SPECIALIST_ROUTE,
    KNOWLEDGE_RAG,
    ANSWER_LOCAL,
    ROUTER_CONFIGURATION_ERROR,
)

FORBIDDEN_GOLD_FIELDS = frozenset({
    "construction_tag", "expected_route", "floor_id", "test_family",
    "expected_status", "blind_label", "gold_route", "gold_status",
})

INPUT_FIELDS = (
    "query",
    "request_date",
    "snapshot_date",
    "evidence_state",
    "requested_capability",
    "available_capabilities",
    "permission_grants",
    "security_state",
    "source_freshness",
    "citation_required",
)

EVIDENCE_STATES = frozenset({
    "NOT_EVALUATED", "SUFFICIENT", "INSUFFICIENT", "CONFLICTING",
})
SECURITY_STATES = frozenset({"ALLOW", "BLOCK"})
SOURCE_FRESHNESS_STATES = frozenset({
    "UNKNOWN", "STATIC", "SLOW_CHANGING", "TIME_SENSITIVE",
})

# Every entry is a real router outcome with an existing Mango consumer.
# "terminal" means the router has made its one final selection; consumers
# can still execute their own bounded runtime after that selection.
ROUTE_REGISTRY: dict[str, dict[str, Any]] = {
    SECURITY_REFUSAL: {
        "producer": "ExecutiveRouterV2.security_gate",
        "consumer": "NO_TOOL/policy response",
        "allowed_inputs": ["query", "security_state"],
        "preconditions": ["security_state=BLOCK or unsafe action semantics"],
        "terminal": True,
        "fallback_policy": "none; security restrictions are never downgraded",
        "required_capability": "NO_TOOL",
    },
    ROUTE_WEB_RESEARCH: {
        "producer": "ExecutiveRouterV2.temporal_or_explicit_web_gate",
        "consumer": "WEB_RESEARCH",
        "allowed_inputs": [
            "query", "request_date", "snapshot_date", "source_freshness",
            "available_capabilities", "permission_grants",
        ],
        "preconditions": [
            "current/open-web evidence required", "WEB_RESEARCH executable",
            "network permission present",
        ],
        "terminal": True,
        "fallback_policy": "INSUFFICIENT_EVIDENCE; never stale local answer",
        "required_capability": "WEB_RESEARCH",
    },
    HISTORICAL_AS_OF: {
        "producer": "ExecutiveRouterV2.temporal_gate",
        "consumer": "KNOWLEDGE_RAG historical mode",
        "allowed_inputs": [
            "query", "request_date", "snapshot_date", "available_capabilities",
        ],
        "preconditions": ["T22 temporal intent=HISTORICAL_AS_OF"],
        "terminal": True,
        "fallback_policy": "INSUFFICIENT_EVIDENCE when Knowledge/RAG unavailable",
        "required_capability": "KNOWLEDGE_RAG",
    },
    CONFLICT_HANDLING: {
        "producer": "ExecutiveRouterV2.evidence_gate",
        "consumer": "KNOWLEDGE_RAG conflict handling",
        "allowed_inputs": ["evidence_state", "available_capabilities"],
        "preconditions": ["evidence_state=CONFLICTING"],
        "terminal": True,
        "fallback_policy": "INSUFFICIENT_EVIDENCE; never confident resolution",
        "required_capability": "KNOWLEDGE_RAG",
    },
    INSUFFICIENT_EVIDENCE: {
        "producer": "ExecutiveRouterV2.fail_closed_gate",
        "consumer": "NO_TOOL/abstention response",
        "allowed_inputs": [
            "evidence_state", "requested_capability", "available_capabilities",
            "permission_grants",
        ],
        "preconditions": [
            "evidence insufficient or required route unavailable/unauthorized",
        ],
        "terminal": True,
        "fallback_policy": "none; abstention is terminal",
        "required_capability": "NO_TOOL",
    },
    TOOL_OR_SPECIALIST_ROUTE: {
        "producer": "ExecutiveRouterV2.specialist_gate",
        "consumer": "registered SkillRegistry capability",
        "allowed_inputs": [
            "query", "requested_capability", "available_capabilities",
            "permission_grants",
        ],
        "preconditions": [
            "specialist required", "capability executable", "permissions present",
        ],
        "terminal": True,
        "fallback_policy": "INSUFFICIENT_EVIDENCE on unsupported/unavailable route",
        "required_capability": "DYNAMIC_REGISTERED_SPECIALIST",
    },
    KNOWLEDGE_RAG: {
        "producer": "ExecutiveRouterV2.local_knowledge_gate",
        "consumer": "KNOWLEDGE_RAG",
        "allowed_inputs": [
            "query", "evidence_state", "citation_required",
            "available_capabilities",
        ],
        "preconditions": ["stable factual/citation-grounded local request"],
        "terminal": True,
        "fallback_policy": "INSUFFICIENT_EVIDENCE when Knowledge/RAG unavailable",
        "required_capability": "KNOWLEDGE_RAG",
    },
    ANSWER_LOCAL: {
        "producer": "ExecutiveRouterV2.local_answer_gate",
        "consumer": "GENERAL",
        "allowed_inputs": ["query"],
        "preconditions": ["no higher-precedence route applies"],
        "terminal": True,
        "fallback_policy": "INSUFFICIENT_EVIDENCE if downstream lacks support",
        "required_capability": "GENERAL",
    },
    ROUTER_CONFIGURATION_ERROR: {
        "producer": "ExecutiveRouterV2.input_validator",
        "consumer": "NO_TOOL/configuration error response",
        "allowed_inputs": list(INPUT_FIELDS),
        "preconditions": ["unknown field, malformed value, or invalid registry state"],
        "terminal": True,
        "fallback_policy": "none; fail closed and emit no answer/tool route",
        "required_capability": "NO_TOOL",
    },
}

REASON_ROUTE_MAP: dict[str, tuple[str, ...]] = {
    "SECURITY_POLICY": (SECURITY_REFUSAL,),
    "CURRENT_REQUIRED": (ROUTE_WEB_RESEARCH,),
    "RECENCY_SENSITIVE_STALE": (ROUTE_WEB_RESEARCH,),
    "TIME_SENSITIVE_SOURCE_STALE": (ROUTE_WEB_RESEARCH,),
    "EXPLICIT_WEB_REQUIRED": (ROUTE_WEB_RESEARCH,),
    "HISTORICAL_AS_OF": (HISTORICAL_AS_OF,),
    "CONFLICTING_EVIDENCE": (CONFLICT_HANDLING,),
    "INSUFFICIENT_EVIDENCE": (INSUFFICIENT_EVIDENCE,),
    "TOOL_UNAVAILABLE": (INSUFFICIENT_EVIDENCE,),
    "TOOL_PERMISSION_REQUIRED": (INSUFFICIENT_EVIDENCE,),
    "UNSUPPORTED_TOOL": (INSUFFICIENT_EVIDENCE,),
    "CURRENT_ROUTE_UNAVAILABLE": (INSUFFICIENT_EVIDENCE,),
    "HISTORICAL_ROUTE_UNAVAILABLE": (INSUFFICIENT_EVIDENCE,),
    "CONFLICT_ROUTE_UNAVAILABLE": (INSUFFICIENT_EVIDENCE,),
    "KNOWLEDGE_ROUTE_UNAVAILABLE": (INSUFFICIENT_EVIDENCE,),
    "TOOL_REQUIRED": (TOOL_OR_SPECIALIST_ROUTE,),
    "CITATION_GROUNDED_LOCAL": (KNOWLEDGE_RAG,),
    "STATIC_LOCAL_ELIGIBLE": (KNOWLEDGE_RAG,),
    "LOCAL_RESPONSE_SUFFICIENT": (ANSWER_LOCAL,),
    "ROUTER_CONFIGURATION_ERROR": (ROUTER_CONFIGURATION_ERROR,),
}

PRECEDENCE = (
    "INPUT_VALIDATION",
    "SECURITY_POLICY",
    "CURRENT_OR_LIVE_REQUIREMENT",
    "HISTORICAL_AS_OF",
    "CONFLICT_OR_INSUFFICIENT_EVIDENCE",
    "SPECIALIST_OR_TOOL_REQUIREMENT",
    "QUALIFIED_LOCAL_KNOWLEDGE_RAG",
    "LOCAL_RESPONSE",
)

AUTHORITY_BOUNDARIES = (
    "select exactly one registered route",
    "emit a structured reason code and bounded decision trace",
    "never rewrite candidate answers",
    "never rewrite metric semantics or evaluator gold",
    "never override security restrictions or grant permissions",
    "never invent tool availability or capability identifiers",
    "never convert missing/conflicting evidence into confident evidence",
    "never downgrade a stale CURRENT_REQUIRED request to a local answer",
)


class RouterInputError(ValueError):
    """Malformed or unregistered router state; always fails closed."""


def _valid_iso_date(value: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))


@dataclass(frozen=True)
class RouterInput:
    query: str
    request_date: str = ""
    snapshot_date: str = "2026-01-31"
    evidence_state: str = "NOT_EVALUATED"
    requested_capability: str | None = None
    available_capabilities: tuple[str, ...] | None = None
    permission_grants: tuple[str, ...] = ()
    security_state: str = "ALLOW"
    source_freshness: str = "UNKNOWN"
    citation_required: bool = False

    @classmethod
    def parse(cls, payload: Mapping[str, Any], registry: SkillRegistry) -> "RouterInput":
        if not isinstance(payload, Mapping):
            raise RouterInputError("router input must be an object")
        keys = set(payload)
        leaked = sorted(keys & FORBIDDEN_GOLD_FIELDS)
        if leaked:
            raise RouterInputError(f"gold-only fields are forbidden: {leaked}")
        unknown = sorted(keys - set(INPUT_FIELDS))
        if unknown:
            raise RouterInputError(f"implicit/unregistered fields: {unknown}")

        query = payload.get("query")
        if not isinstance(query, str) or not query.strip():
            raise RouterInputError("query must be a non-empty string")
        request_date = payload.get("request_date", "")
        snapshot_date = payload.get("snapshot_date", "2026-01-31")
        if request_date and not _valid_iso_date(request_date):
            raise RouterInputError("request_date must be empty or ISO YYYY-MM-DD")
        if not _valid_iso_date(snapshot_date):
            raise RouterInputError("snapshot_date must be ISO YYYY-MM-DD")

        evidence = payload.get("evidence_state", "NOT_EVALUATED")
        security = payload.get("security_state", "ALLOW")
        freshness = payload.get("source_freshness", "UNKNOWN")
        if evidence not in EVIDENCE_STATES:
            raise RouterInputError(f"unknown evidence_state {evidence!r}")
        if security not in SECURITY_STATES:
            raise RouterInputError(f"unknown security_state {security!r}")
        if freshness not in SOURCE_FRESHNESS_STATES:
            raise RouterInputError(f"unknown source_freshness {freshness!r}")

        requested = payload.get("requested_capability")
        if requested is not None and (
                not isinstance(requested, str) or not requested.strip()):
            raise RouterInputError("requested_capability must be null or a string")

        raw_available = payload.get("available_capabilities")
        available: tuple[str, ...] | None
        if raw_available is None:
            available = None
        else:
            if not isinstance(raw_available, (list, tuple)) or not all(
                    isinstance(item, str) for item in raw_available):
                raise RouterInputError("available_capabilities must be a string list")
            if len(set(raw_available)) != len(raw_available):
                raise RouterInputError("duplicate capability IDs")
            dangling = sorted(set(raw_available) - set(registry.ids()))
            if dangling:
                raise RouterInputError(f"unknown capability references: {dangling}")
            available = tuple(sorted(raw_available))

        raw_grants = payload.get("permission_grants", [])
        if not isinstance(raw_grants, (list, tuple)) or not all(
                isinstance(item, str) for item in raw_grants):
            raise RouterInputError("permission_grants must be a string list")
        if len(set(raw_grants)) != len(raw_grants):
            raise RouterInputError("duplicate permission grants")
        citation = payload.get("citation_required", False)
        if not isinstance(citation, bool):
            raise RouterInputError("citation_required must be boolean")

        return cls(
            query=query.strip(), request_date=request_date,
            snapshot_date=snapshot_date, evidence_state=evidence,
            requested_capability=requested.strip() if requested else None,
            available_capabilities=available,
            permission_grants=tuple(sorted(raw_grants)),
            security_state=security, source_freshness=freshness,
            citation_required=citation,
        )


_ROUTE_OVERRIDE = re.compile(
    r"\b(?:ignore (?:the )?router|use web anyway|never use web|"
    r"pretend (?:the )?tool exists|answer even without evidence)\b"
    r"[\s,;:!.-]*", re.IGNORECASE)
_UNSAFE = re.compile(
    r"\b(?:exfiltrat(?:e|ion)|reveal (?:the )?(?:secret|password|token)|"
    r"steal credentials|bypass (?:the )?(?:security|permission)|"
    r"disable (?:the )?(?:security|safety)|delete all (?:files|tests)|"
    r"force-push|rm\s+-rf|launch paid compute)\b", re.IGNORECASE)
_EXPLICIT_WEB = re.compile(
    r"\b(?:search the web|browse (?:the )?web|look up online|"
    r"use web research|check official online sources)\b", re.IGNORECASE)
_FACTUAL = re.compile(
    r"\b(?:who|when|where|which|what (?:is|was|year|date|capital|language)|"
    r"name the|according to|cite|citation|invented|founded|located|"
    r"registered value|record states)\b", re.IGNORECASE)
_SPECIALISTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CODE", re.compile(
        r"\b(?:write|debug|run|execute|implement|refactor)\b.{0,32}"
        r"\b(?:code|python|javascript|script|program|function)\b", re.I)),
    ("DOCUMENT", re.compile(
        r"\b(?:this|the|my)\s+(?:pdf|document|spreadsheet|csv|file)\b|"
        r"\bparse the (?:file|document)\b", re.I)),
    ("MEMORY", re.compile(
        r"\b(?:remember (?:this|that)|save this fact|what did i tell you|"
        r"from last session)\b", re.I)),
    ("PLANNING", re.compile(
        r"\b(?:make a plan|plan the steps|break this into steps|"
        r"multi-step plan)\b", re.I)),
    ("ORCHESTRATION", re.compile(
        r"\b(?:coordinate|orchestrate)\b.{0,40}\b(?:agents|specialists)\b", re.I)),
    ("SCICOMP", re.compile(
        r"\b(?:simulate|solve numerically|ode|pde|finite element|monte carlo)\b", re.I)),
    ("MATH_T4", re.compile(
        r"\b(?:calculate|compute|convert|solve for|derivative|integral)\b|"
        r"\d+\s*[+*/^-]\s*\d+", re.I)),
    ("SCIENCE_RAG", re.compile(
        r"\b(?:scientific mechanism|experimental evidence|explain why)\b", re.I)),
)


def _effective_query(query: str) -> tuple[str, bool]:
    scrubbed, count = _ROUTE_OVERRIDE.subn("", query)
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip(" ,.;:-")
    return (scrubbed or query), bool(count)


def _detect_specialist(query: str) -> str | None:
    if _EXPLICIT_WEB.search(query):
        return "WEB_RESEARCH"
    for capability, pattern in _SPECIALISTS:
        if pattern.search(query):
            return capability
    return None


def _available(state: RouterInput, registry: SkillRegistry) -> frozenset[str]:
    actual = {sid for sid in registry.ids() if registry.executable(sid)}
    if state.available_capabilities is None:
        return frozenset(actual)
    # Runtime availability metadata can only narrow the actual registry.
    return frozenset(actual & set(state.available_capabilities))


def _can_dispatch(capability: str, state: RouterInput,
                  registry: SkillRegistry, available: frozenset[str]) -> tuple[bool, str]:
    if not registry.known(capability):
        return False, "UNSUPPORTED_TOOL"
    if capability not in available or not registry.executable(capability):
        return False, "TOOL_UNAVAILABLE"
    rec = registry.get(capability) or {}
    missing = set(rec.get("required_permissions", [])) - set(state.permission_grants)
    if missing:
        return False, "TOOL_PERMISSION_REQUIRED"
    return True, ""


def _input_digest(state: RouterInput) -> str:
    blob = json.dumps({
        name: getattr(state, name) for name in INPUT_FIELDS
    }, sort_keys=True, default=list, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _decision(route_id: str, reason_code: str, state: RouterInput | None,
              *, selected_capability: str | None = None,
              priority: str, detail: str,
              override_ignored: bool = False,
              temporal: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if route_id not in ROUTE_REGISTRY:
        raise AssertionError(f"unregistered route {route_id}")
    if route_id not in REASON_ROUTE_MAP.get(reason_code, ()):
        raise AssertionError(f"reason/route contradiction: {reason_code}/{route_id}")
    route = ROUTE_REGISTRY[route_id]
    return {
        "schema_version": "t23-executive-router-decision-v1",
        "route_id": route_id,
        "reason_code": reason_code,
        "reason_detail": detail[:240],
        "priority_resolution": priority,
        "selected_capability": selected_capability or route["required_capability"],
        "consumer": route["consumer"],
        "terminal_router_decision": True,
        "eligible_terminal_routes": [route_id],
        "fallback": route["fallback_policy"],
        "authority": "ROUTE_SELECTION_ONLY",
        "override_instruction_ignored": override_ignored,
        "temporal_intent": (temporal or {}).get("temporal_intent"),
        "temporal_action": (temporal or {}).get("action"),
        "input_sha256": _input_digest(state) if state else None,
    }


def _configuration_error(detail: str) -> dict[str, Any]:
    return _decision(
        ROUTER_CONFIGURATION_ERROR, "ROUTER_CONFIGURATION_ERROR", None,
        selected_capability="NO_TOOL", priority="INPUT_VALIDATION",
        detail=detail,
    )


def route_request(payload: Mapping[str, Any], *,
                  registry: SkillRegistry | None = None) -> dict[str, Any]:
    """Select exactly one deterministic Executive Router outcome.

    The return value is structured provenance, not hidden reasoning.  Any
    unknown field/state, including leaked evaluator gold, fails closed as
    ``ROUTER_CONFIGURATION_ERROR``.
    """
    reg = registry or SkillRegistry()
    try:
        state = RouterInput.parse(payload, reg)
    except (RouterInputError, TypeError, ValueError) as exc:
        return _configuration_error(str(exc))

    available = _available(state, reg)
    query, override_ignored = _effective_query(state.query)

    # 1. Security always dominates every routing pressure.
    if state.security_state == "BLOCK" or _UNSAFE.search(query):
        return _decision(
            SECURITY_REFUSAL, "SECURITY_POLICY", state,
            selected_capability="NO_TOOL", priority="SECURITY_POLICY",
            detail="security policy blocks the requested action",
            override_ignored=override_ignored,
        )

    # 2/3. T22 temporal policy is reused byte-for-byte.
    temporal = classify_query_freshness(
        query, now=state.request_date, snapshot_date=state.snapshot_date)
    current_route = temporal["action"] == ROUTE_WEB_RESEARCH
    if (state.source_freshness == "TIME_SENSITIVE"
            and temporal["temporal_intent"] != INTENT_HISTORICAL
            and state.request_date > state.snapshot_date):
        current_route = True
        temporal = dict(temporal, action=ROUTE_WEB_RESEARCH)
        temporal_reason = "TIME_SENSITIVE_SOURCE_STALE"
    elif temporal["temporal_intent"] == INTENT_RECENCY_SENSITIVE:
        temporal_reason = "RECENCY_SENSITIVE_STALE"
    else:
        temporal_reason = "CURRENT_REQUIRED"

    if current_route:
        ok, _ = _can_dispatch("WEB_RESEARCH", state, reg, available)
        if not ok:
            return _decision(
                INSUFFICIENT_EVIDENCE, "CURRENT_ROUTE_UNAVAILABLE", state,
                selected_capability="NO_TOOL",
                priority="CURRENT_OR_LIVE_REQUIREMENT",
                detail="current evidence is required but the authorized web route is unavailable",
                override_ignored=override_ignored, temporal=temporal,
            )
        return _decision(
            ROUTE_WEB_RESEARCH, temporal_reason, state,
            selected_capability="WEB_RESEARCH",
            priority="CURRENT_OR_LIVE_REQUIREMENT",
            detail=temporal.get("reason", "current evidence required"),
            override_ignored=override_ignored, temporal=temporal,
        )

    if temporal["temporal_intent"] == INTENT_HISTORICAL:
        ok, _ = _can_dispatch("KNOWLEDGE_RAG", state, reg, available)
        if not ok:
            return _decision(
                INSUFFICIENT_EVIDENCE, "HISTORICAL_ROUTE_UNAVAILABLE", state,
                selected_capability="NO_TOOL", priority="HISTORICAL_AS_OF",
                detail="historical evidence route is unavailable",
                override_ignored=override_ignored, temporal=temporal,
            )
        return _decision(
            HISTORICAL_AS_OF, "HISTORICAL_AS_OF", state,
            selected_capability="KNOWLEDGE_RAG", priority="HISTORICAL_AS_OF",
            detail=temporal.get("reason", "historical frame"),
            override_ignored=override_ignored, temporal=temporal,
        )

    # 4. Evidence failure states dominate tools and ordinary local paths.
    if state.evidence_state == "CONFLICTING":
        ok, _ = _can_dispatch("KNOWLEDGE_RAG", state, reg, available)
        if not ok:
            return _decision(
                INSUFFICIENT_EVIDENCE, "CONFLICT_ROUTE_UNAVAILABLE", state,
                selected_capability="NO_TOOL",
                priority="CONFLICT_OR_INSUFFICIENT_EVIDENCE",
                detail="conflict handling is unavailable; fail closed",
                override_ignored=override_ignored, temporal=temporal,
            )
        return _decision(
            CONFLICT_HANDLING, "CONFLICTING_EVIDENCE", state,
            selected_capability="KNOWLEDGE_RAG",
            priority="CONFLICT_OR_INSUFFICIENT_EVIDENCE",
            detail="runtime evidence sources conflict",
            override_ignored=override_ignored, temporal=temporal,
        )
    if state.evidence_state == "INSUFFICIENT":
        return _decision(
            INSUFFICIENT_EVIDENCE, "INSUFFICIENT_EVIDENCE", state,
            selected_capability="NO_TOOL",
            priority="CONFLICT_OR_INSUFFICIENT_EVIDENCE",
            detail="runtime evidence is insufficient for a confident answer",
            override_ignored=override_ignored, temporal=temporal,
        )

    # 5. Specialist/tool requirements use the actual SkillRegistry.
    specialist = state.requested_capability or _detect_specialist(query)
    if specialist:
        ok, failure_reason = _can_dispatch(specialist, state, reg, available)
        if not ok:
            return _decision(
                INSUFFICIENT_EVIDENCE, failure_reason, state,
                selected_capability="NO_TOOL",
                priority="SPECIALIST_OR_TOOL_REQUIREMENT",
                detail=f"requested capability {specialist!r} cannot be dispatched",
                override_ignored=override_ignored, temporal=temporal,
            )
        if specialist == "WEB_RESEARCH":
            return _decision(
                ROUTE_WEB_RESEARCH, "EXPLICIT_WEB_REQUIRED", state,
                selected_capability=specialist,
                priority="SPECIALIST_OR_TOOL_REQUIREMENT",
                detail="explicit open-web evidence request",
                override_ignored=override_ignored, temporal=temporal,
            )
        return _decision(
            TOOL_OR_SPECIALIST_ROUTE, "TOOL_REQUIRED", state,
            selected_capability=specialist,
            priority="SPECIALIST_OR_TOOL_REQUIREMENT",
            detail=f"registered specialist {specialist} is required and authorized",
            override_ignored=override_ignored, temporal=temporal,
        )

    # 6/7. Qualified local knowledge, then the deterministic local response.
    factual = bool(_FACTUAL.search(query))
    if state.citation_required or factual:
        ok, _ = _can_dispatch("KNOWLEDGE_RAG", state, reg, available)
        if not ok:
            return _decision(
                INSUFFICIENT_EVIDENCE, "KNOWLEDGE_ROUTE_UNAVAILABLE", state,
                selected_capability="NO_TOOL",
                priority="QUALIFIED_LOCAL_KNOWLEDGE_RAG",
                detail="qualified local Knowledge/RAG is unavailable",
                override_ignored=override_ignored, temporal=temporal,
            )
        reason = "CITATION_GROUNDED_LOCAL" if state.citation_required \
            else "STATIC_LOCAL_ELIGIBLE"
        return _decision(
            KNOWLEDGE_RAG, reason, state,
            selected_capability="KNOWLEDGE_RAG",
            priority="QUALIFIED_LOCAL_KNOWLEDGE_RAG",
            detail="stable local evidence path is eligible",
            override_ignored=override_ignored, temporal=temporal,
        )

    return _decision(
        ANSWER_LOCAL, "LOCAL_RESPONSE_SUFFICIENT", state,
        selected_capability="GENERAL", priority="LOCAL_RESPONSE",
        detail="no higher-precedence route is required",
        override_ignored=override_ignored, temporal=temporal,
    )


def route_registry_snapshot() -> dict[str, Any]:
    """Public-safe route inventory used by the T23 freeze generator."""
    return {
        "schema_version": "t23-route-registry-v1",
        "routes": {route_id: dict(record, route_id=route_id)
                   for route_id, record in ROUTE_REGISTRY.items()},
        "precedence": list(PRECEDENCE),
        "authority_boundaries": list(AUTHORITY_BOUNDARIES),
    }


def validate_router_contract() -> dict[str, Any]:
    """Return machine-checkable registry/contract integrity evidence."""
    registry_routes = set(ROUTE_REGISTRY)
    reason_routes = {route for routes in REASON_ROUTE_MAP.values() for route in routes}
    dangling_reason_routes = sorted(reason_routes - registry_routes)
    unreachable = sorted(registry_routes - reason_routes)
    duplicate_ids = len(ROUTE_IDS) - len(set(ROUTE_IDS))
    return {
        "registered_routes": len(registry_routes),
        "duplicate_route_ids": duplicate_ids,
        "dangling_reason_routes": dangling_reason_routes,
        "unreachable_registered_routes": unreachable,
        "reason_route_contradictions": 0,
        "status": "PASS" if not (
            duplicate_ids or dangling_reason_routes or unreachable
        ) else "FAIL",
    }
