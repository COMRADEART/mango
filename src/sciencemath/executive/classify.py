"""T7.3 — Problem classification (deterministic-first).

Extends the T5R deterministic router (mango F1 0.94 measured) with
complexity and resource-requirement classification. The model is never
asked to classify; deterministic rules only, so routing metrics are
reproducible and the classifier is a fixed function of the question.
"""
from __future__ import annotations

import re

from sciencemath.rag.route import classify_route as _rag_classify_route

PROBLEM_TYPES = ("MATH", "SCIENCE", "MIXED", "GENERAL")
COMPLEXITIES = ("SIMPLE", "MULTI_STEP", "OPEN_ENDED")
RESOURCES = ("NONE", "MATH_TOOL", "RETRIEVAL", "BOTH", "UNKNOWN")

# multi-step cues: explicit sequencing, chained quantities, "then",
# per-unit rates, derived quantities
_MULTI_STEP_PAT = re.compile(
    r"\b(then|next|after that|first .* then|step|in order|following)\b"
    r"|\b(each|per)\s+(day|hour|minute|second|month|year|student|item"
    r"|unit|kg|m|s|litre|liter)\b"
    r"|\b(how much|how many|what is the total|calculate|compute)\b.*\b"
    r"(total|combined|together|altogether|remaining|left)\b"
    r"|\b(total|sum|combined|altogether)\b"
    r"|\b(percentage|percent|fraction|ratio|average|speed|velocity"
    r"|acceleration|energy|momentum|force|molar|concentration|rate)\b",
    re.IGNORECASE,
)
# open-ended cues: no single numeric/exact answer expected
_OPEN_ENDED_PAT = re.compile(
    r"\b(explain|describe|why|how does|discuss|compare|what role"
    r"|what happens|elaborate|in your own words|justify|evaluate)\b",
    re.IGNORECASE,
)

_TOOL_CUES = re.compile(
    r"\b(calculate|compute|convert|solve|evaluate|how many|how much"
    r"|derivative|integral|square root|log|sin|cos|tan|percent(age)?"
    r"|sum|average|area|volume|perimeter)\b"
    r"|[\d]+\s*[\+\-\*\/\^×÷]\s*[\d]",
    re.IGNORECASE,
)
_RETRIEVAL_CUES = re.compile(
    r"\b(who|when|where|which scientist|which element|discovered"
    r"|defined|law|theory|named after|first proposed|what is the "
    r"(name|chemical symbol|atomic number)|fact)\b",
    re.IGNORECASE,
)


def classify_complexity(question: str) -> str:
    """SIMPLE / MULTI_STEP / OPEN_ENDED — deterministic heuristics."""
    q = question.strip()
    if _OPEN_ENDED_PAT.search(q) and not re.search(
            r"calculate|compute|how many|how much", q, re.IGNORECASE):
        return "OPEN_ENDED"
    if _MULTI_STEP_PAT.search(q):
        return "MULTI_STEP"
    # single numeric relation, one operator, or direct lookup
    if re.search(r"[\d]+\s*[\+\-\*\/\^×÷]\s*[\d]", q) or len(q) < 120:
        return "SIMPLE"
    return "MULTI_STEP"


def classify_resources(question: str) -> str:
    """NONE / MATH_TOOL / RETRIEVAL / BOTH / UNKNOWN (T7.3 axis)."""
    tool = bool(_TOOL_CUES.search(question))
    retrieval = bool(_RETRIEVAL_CUES.search(question))
    if tool and retrieval:
        return "BOTH"
    if tool:
        return "MATH_TOOL"
    if retrieval:
        return "RETRIEVAL"
    # numbers present but no operator: ambiguous -> UNKNOWN
    if re.search(r"\d", question) and len(question) > 200:
        return "UNKNOWN"
    return "NONE"


def classify_problem(question: str) -> dict:
    """Full classification dict (type from T5R router, complexity and
    resources from this module). Deterministic: same input -> same dict."""
    rag = _rag_classify_route(question)
    ptype = rag.get("route", "GENERAL")
    if ptype not in PROBLEM_TYPES:
        ptype = "GENERAL"
    return {
        "problem_type": ptype,
        "complexity": classify_complexity(question),
        "resources": classify_resources(question),
        "tools": rag.get("tools", []),
        "domain": rag.get("domain", "general"),
    }


def fast_path_eligible(cls: dict) -> bool:
    """T7.22 — simple-question bypass: SIMPLE + no resources + not MIXED
    goes straight to the baseline answer path (no plan, no executive
    overhead). Measured as unnecessary-executive-invocation when wrong."""
    return (cls["complexity"] == "SIMPLE"
            and cls["resources"] == "NONE"
            and cls["problem_type"] in ("MATH", "GENERAL"))