"""T14.12 — Executive Router.

Selects a bounded skill workflow for a user task. Deterministic.
Never invents tools, permissions, or executions. Unknown/unavailable
fail closed to GENERAL / NO_TOOL / NEEDS_INFORMATION.

This is routing, not autonomous orchestration. Max workflow depth: 3.
"""
from __future__ import annotations

import re
import time
from typing import Any

from sciencemath.executive.skills import (
    PAID_COMPUTE, PREPARED_ONLY, SkillRegistry, default_registry,
)
from sciencemath.scicomp.router import (
    COMPUTE_HELPFUL, COMPUTE_REQUIRED, INSUFFICIENT_INFORMATION,
    NO_COMPUTE, compute_necessity, route_precedence,
)
from sciencemath.tools.router import route_question

MAX_WORKFLOW_DEPTH = 3

FAILURE_TYPES = (
    "MISSED_TOOL", "UNNECESSARY_TOOL", "WRONG_PRIMARY_SKILL",
    "WRONG_SECONDARY_SKILL", "WRONG_ORDER", "UNAVAILABLE_SKILL",
    "INSUFFICIENT_INPUT_NOT_DETECTED", "PERMISSION_ERROR",
    "PAID_COMPUTE_VIOLATION", "ROUTE_CONFLICT", "FALLBACK_FAILURE",
    "OTHER",
)

_CODE_REQUEST = re.compile(
    r"\b(write (a |me )?(python|javascript|rust|code)|run this code|"
    r"execute (this )?(python|script|shell)|implement a function|"
    r"debug this (code|program)|open a shell)\b", re.I)
_WEB_REQUEST = re.compile(
    r"\b(search the web|look up( online)?|browse|latest news|"
    r"what happened( to| with)? .*(today|this week)|google|"
    r"current (ceo|mayor|status|price|version)|"
    r"official (docs|documentation|specification|site)|"
    r"fact[- ]check|compare (these |the )?(three |two )?sources|"
    r"according to (the )?(web|sources|official)|"
    r"as of today|breaking news)\b", re.I)
_DOC_REQUEST = re.compile(
    r"\b(this pdf|this document|spreadsheet|csv file|parse the file)\b", re.I)
_MEM_REQUEST = re.compile(
    r"\b(remember (that|this)|please remember|save this fact|"
    r"store this (fact|in memory)|what did we (discuss|choose|decide)|"
    r"what database did we|from last session|my notes say|"
    r"what do you remember|forget (this )?(session|project)|"
    r"my preferred editor)\b", re.I)
_PLAN_REQUEST = re.compile(
    r"\b(make a plan|plan the steps|break this into steps|"
    r"multi-step plan)\b", re.I)
_PAID_REQUEST = re.compile(
    r"\b(rent (a |an )?(a100|h100|gpu)|launch paid (gpu|compute)|"
    r"buy cloud gpu|spin up a cluster)\b", re.I)


def _reason(text: str) -> str:
    """Concise routing rationale only — never chain-of-thought."""
    return text[:240]


def route_task(question: str, *,
               registry: SkillRegistry | None = None) -> dict:
    """Produce a T14.12 executive route record for one task."""
    start = time.perf_counter()
    reg = registry or SkillRegistry()
    if not isinstance(question, str) or not question.strip():
        rec = _closed("NO_TOOL", "empty or invalid input",
                      registry=reg, extra={"required_inputs_present": False,
                                           "fallback": "GENERAL"})
        rec["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
        return rec

    nec = compute_necessity(question)
    prec = route_precedence(question)
    t4 = route_question(question)
    asked = _requested_capabilities(question)

    # Paid compute is never launched (T14.15).
    if asked["paid_compute"] or _PAID_REQUEST.search(question):
        rec = _closed(
            "NO_TOOL", "PAID_COMPUTE_GATE_REQUIRED — paid compute blocked",
            registry=reg,
            extra={"estimated_cost_class": PAID_COMPUTE,
                   "paid_compute_gate": "PAID_COMPUTE_GATE_REQUIRED",
                   "permissions_required": ["paid_compute"],
                   "fallback": "GENERAL"})
        rec["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
        return rec

    primary, secondary, reason = _select(question, nec, prec, t4, asked, reg)
    # Depth cap: primary + secondaries <= 3 stages.
    if len(secondary) > MAX_WORKFLOW_DEPTH - 1:
        secondary = secondary[:MAX_WORKFLOW_DEPTH - 1]
        reason = _reason(reason + "; depth capped at 3")

    stages = [primary, *secondary]
    for sid in stages:
        if not reg.known(sid):
            rec = _closed("GENERAL", "unknown skill rejected",
                          registry=reg, extra={"fallback": "NO_TOOL"})
            rec["hallucinated_tool"] = sid
            rec["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
            return rec
        if not reg.executable(sid) and sid not in ("GENERAL", "NO_TOOL"):
            # Do not present unavailable skills as the executed primary.
            rec = _closed(
                "GENERAL",
                f"skill {sid} availability={reg.availability(sid)} "
                "is not executable; fail closed",
                registry=reg,
                extra={"unavailable_skill": sid,
                       "fallback": reg.get(sid)["fallback_behavior"]
                       if reg.get(sid) else "GENERAL"})
            rec["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
            return rec

    cost = _cost_class(stages, reg)
    if cost == PAID_COMPUTE:
        rec = _closed("NO_TOOL", "PAID_COMPUTE_GATE_REQUIRED",
                      registry=reg,
                      extra={"estimated_cost_class": PAID_COMPUTE,
                             "paid_compute_gate": "PAID_COMPUTE_GATE_REQUIRED",
                             "fallback": "GENERAL"})
        rec["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
        return rec

    perms: list[str] = []
    for sid in stages:
        perms.extend(reg.get(sid)["required_permissions"])
    # Never invent permissions.
    perms = sorted(set(perms))

    verification = any(
        (reg.get(sid) or {}).get("verification_method") not in (None, "none")
        for sid in stages)

    rec = {
        "primary_skill": primary,
        "secondary_skills": secondary,
        "reason": _reason(reason),
        "required_inputs_present": nec["necessity"] != INSUFFICIENT_INFORMATION,
        "permissions_required": perms,
        "estimated_cost_class": cost,
        "verification_required": verification,
        "fallback": (reg.get(primary) or {}).get("fallback_behavior", "GENERAL"),
        "necessity": nec["necessity"],
        "availability": {sid: reg.availability(sid) for sid in stages},
        "workflow_depth": len(stages),
        "paid_compute_gate": None,
        "hallucinated_tool": None,
        "execution_status": "ROUTED_ONLY",
        "verification_status": "NOT_RUN",
        "skills_selected": stages,
        "unavailable_skill": None,
    }
    for cap, skill in (("code", "CODE"), ("web", "WEB_RESEARCH"),
                       ("document", "DOCUMENT"), ("memory", "MEMORY")):
        if asked[cap] and not reg.executable(skill):
            rec["unavailable_skill"] = skill
            break
    rec["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
    return rec


def _select(question: str, nec: dict, prec: dict, t4: dict,
            asked: dict, reg: SkillRegistry) -> tuple[str, list[str], str]:
    """Deterministic precedence (T14.4) plus T14B skill mapping."""
    secondary: list[str] = []

    # Unavailable capability requests fail closed (do not fake execution).
    for cap, skill in (("code", "CODE"), ("web", "WEB_RESEARCH"),
                       ("document", "DOCUMENT"), ("memory", "MEMORY")):
        if asked[cap] and not reg.executable(skill):
            return "GENERAL", [], (
                f"{skill} requested but availability="
                f"{reg.availability(skill)}; not executed")

    # T16 availability integration only: WEB_RESEARCH when executable.
    if asked["web"] and reg.executable("WEB_RESEARCH"):
        follow: list[str] = []
        if nec["necessity"] == COMPUTE_REQUIRED and reg.executable("SCICOMP"):
            follow = ["SCICOMP"]
        elif asked["code"] and reg.executable("CODE"):
            follow = ["CODE"]
        return "WEB_RESEARCH", follow, "web research; evidence then tools"

    # T17 availability integration only: DOCUMENT when executable.
    if asked["document"] and reg.executable("DOCUMENT"):
        follow_d: list[str] = []
        if nec["necessity"] == COMPUTE_REQUIRED and reg.executable("SCICOMP"):
            follow_d = ["SCICOMP"]
        elif asked["code"] and reg.executable("CODE"):
            follow_d = ["CODE"]
        return "DOCUMENT", follow_d, "document intelligence; evidence then tools"

    # T18 availability integration only: MEMORY when executable.
    if asked["memory"] and reg.executable("MEMORY"):
        follow_m: list[str] = []
        if nec["necessity"] == COMPUTE_REQUIRED and reg.executable("SCICOMP"):
            follow_m = ["SCICOMP"]
        elif asked["code"] and reg.executable("CODE"):
            follow_m = ["CODE"]
        return "MEMORY", follow_m, "persistent memory; data not policy"

    if nec["necessity"] == INSUFFICIENT_INFORMATION:
        return "NO_TOOL", [], "insufficient information; do not invent inputs"

    if asked["planning"] and reg.executable("PLANNING"):
        # Planning may precede another executable skill, depth-capped.
        follow = None
        if nec["necessity"] == COMPUTE_REQUIRED and reg.executable("SCICOMP"):
            follow = "SCICOMP"
        elif t4.get("primary") and reg.executable("MATH_T4"):
            follow = "MATH_T4"
        if follow:
            return "PLANNING", [follow], "planning then bounded tool stage"
        return "PLANNING", [], "bounded planning request"

    if nec["necessity"] == NO_COMPUTE:
        if asked["retrieval"] or prec["primary"] == "SCIENCE_RAG":
            if reg.executable("SCIENCE_RAG"):
                return "SCIENCE_RAG", [], "retrieval-only science fact"
        return "GENERAL", [], "no tool required"

    if prec["primary"] == "MATH_T4" or (
            nec["necessity"] == COMPUTE_HELPFUL and t4.get("primary")):
        # Named scientific constants already in-prompt may still justify a
        # bounded RAG secondary (DEV mixed-skill items); never a 2nd compute.
        if nec.get("features", {}).get("retrieval_named_constant") and (
                reg.executable("SCIENCE_RAG")):
            return ("MATH_T4", ["SCIENCE_RAG"],
                    "T4 math primary; RAG secondary for named constant")
        return "MATH_T4", [], "T4 deterministic math is sufficient"

    if prec["primary"] == "MIXED_RAG_SCICOMP":
        if nec["necessity"] == COMPUTE_REQUIRED and reg.executable("SCICOMP"):
            secondary = ["SCIENCE_RAG"] if reg.executable("SCIENCE_RAG") else []
            return "SCICOMP", secondary, "SciComp required; RAG secondary"
        if t4.get("primary"):
            secondary = ["SCIENCE_RAG"] if reg.executable("SCIENCE_RAG") else []
            return "MATH_T4", secondary, "mixed fact+arithmetic; T4 primary"
        if reg.executable("SCIENCE_RAG"):
            return "SCIENCE_RAG", [], "mixed request without local compute"

    if nec["necessity"] == COMPUTE_REQUIRED and reg.executable("SCICOMP"):
        return "SCICOMP", [], "SciComp required for determined computation"

    if t4.get("primary") and reg.executable("MATH_T4"):
        return "MATH_T4", [], "T4 math tools recommended"

    if prec["primary"] == "SCIENCE_RAG" and reg.executable("SCIENCE_RAG"):
        return "SCIENCE_RAG", [], "science retrieval"

    if nec["necessity"] == COMPUTE_HELPFUL:
        if reg.executable("MATH_T4"):
            return "MATH_T4", [], "compute helpful; T4 is the conservative tool"
        return "GENERAL", [], "compute helpful but no executable tool selected"

    return "GENERAL", [], "default general explanation"


def _requested_capabilities(question: str) -> dict[str, bool]:
    q = question or ""
    return {
        "code": bool(_CODE_REQUEST.search(q)),
        "web": bool(_WEB_REQUEST.search(q)),
        "document": bool(_DOC_REQUEST.search(q)),
        "memory": bool(_MEM_REQUEST.search(q)),
        "planning": bool(_PLAN_REQUEST.search(q)),
        "paid_compute": bool(_PAID_REQUEST.search(q)),
        "retrieval": bool(re.search(
            r"\b(who discovered|chemical symbol|atomic number|"
            r"in what year)\b", q, re.I)),
    }


def _cost_class(stages: list[str], reg: SkillRegistry) -> str:
    order = ["PAID_COMPUTE", "ONLINE_METERED", "ONLINE_FREE",
             "LOCAL_EXPENSIVE", "LOCAL_FREE"]
    classes = [(reg.get(s) or {}).get("cost_class", "LOCAL_FREE")
               for s in stages]
    for c in order:
        if c in classes:
            return c
    return "LOCAL_FREE"


def _closed(primary: str, reason: str, *, registry: SkillRegistry,
            extra: dict | None = None) -> dict:
    rec = {
        "primary_skill": primary,
        "secondary_skills": [],
        "reason": _reason(reason),
        "required_inputs_present": extra.get("required_inputs_present", True)
        if extra else True,
        "permissions_required": extra.get("permissions_required", [])
        if extra else [],
        "estimated_cost_class": extra.get("estimated_cost_class", "LOCAL_FREE")
        if extra else "LOCAL_FREE",
        "verification_required": False,
        "fallback": extra.get("fallback", "GENERAL") if extra else "GENERAL",
        "necessity": None,
        "availability": {primary: registry.availability(primary)},
        "workflow_depth": 1,
        "paid_compute_gate": (extra or {}).get("paid_compute_gate"),
        "hallucinated_tool": None,
        "execution_status": "ROUTED_ONLY",
        "verification_status": "NOT_RUN",
        "skills_selected": [primary],
        "unavailable_skill": (extra or {}).get("unavailable_skill"),
    }
    return rec


def classify_routing_failure(predicted: dict, gold: dict) -> str | None:
    """T14.20 failure taxonomy. None if the route matches gold."""
    if predicted.get("hallucinated_tool"):
        return "OTHER"
    if predicted.get("paid_compute_gate") == "PAID_COMPUTE_GATE_REQUIRED" \
            and gold.get("primary_skill") not in ("NO_TOOL", "GENERAL"):
        # Blocking paid compute is success when gold says block.
        pass
    if predicted.get("unavailable_skill") or (
            predicted.get("primary_skill") == "GENERAL"
            and gold.get("primary_skill") in (
                "CODE", "WEB_RESEARCH", "DOCUMENT", "MEMORY")):
        if gold.get("expect_unavailable_rejection"):
            return None
        return "UNAVAILABLE_SKILL"
    p, g = predicted.get("primary_skill"), gold.get("primary_skill")
    # DOCUMENT/MEMORY may be executed when the registry marks them
    # executable (T17/T18). CODE/WEB already follow that rule.
    if gold.get("expect_unavailable_rejection") and p in ("GENERAL", "NO_TOOL"):
        return None
    if predicted.get("workflow_depth", 1) > MAX_WORKFLOW_DEPTH:
        return "OTHER"
    if gold.get("gold_necessity") == INSUFFICIENT_INFORMATION \
            and predicted.get("necessity") != INSUFFICIENT_INFORMATION \
            and predicted.get("primary_skill") not in ("NO_TOOL", "GENERAL"):
        return "INSUFFICIENT_INPUT_NOT_DETECTED"
    toolish = {"MATH_T4", "SCICOMP", "SCIENCE_RAG", "PLANNING"}
    if g in toolish and p in ("GENERAL", "NO_TOOL"):
        return "MISSED_TOOL"
    if g in ("GENERAL", "NO_TOOL") and p in toolish:
        return "UNNECESSARY_TOOL"
    if p != g:
        return "WRONG_PRIMARY_SKILL"
    gs = gold.get("secondary_skills") or []
    ps = predicted.get("secondary_skills") or []
    if gs and ps and gs != ps:
        if set(gs) == set(ps):
            return "WRONG_ORDER"
        return "WRONG_SECONDARY_SKILL"
    if gold.get("max_depth") and predicted.get("workflow_depth", 1) > gold["max_depth"]:
        return "OTHER"
    return None


def execution_trace(task_id: str, question: str, decision: dict,
                    *, inputs: Any = None,
                    final_outcome: str = "ROUTED_ONLY") -> dict:
    """T14.19 audit trace — no private chain-of-thought."""
    return {
        "task_id": task_id,
        "router_decision": {
            "primary_skill": decision.get("primary_skill"),
            "secondary_skills": decision.get("secondary_skills"),
            "reason": decision.get("reason"),
        },
        "skills_selected": decision.get("skills_selected"),
        "availability": decision.get("availability"),
        "inputs": inputs if inputs is not None else {"question": question[:240]},
        "permissions": decision.get("permissions_required"),
        "execution_status": decision.get("execution_status", "ROUTED_ONLY"),
        "verification_status": decision.get("verification_status", "NOT_RUN"),
        "fallback": decision.get("fallback"),
        "final_outcome": final_outcome,
        "paid_compute_gate": decision.get("paid_compute_gate"),
        "hallucinated_tool": decision.get("hallucinated_tool"),
    }
