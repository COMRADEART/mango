"""T16.9 — bounded query planning."""
from __future__ import annotations

import re

from sciencemath.web.contract import (
    WEB_COMPARE, WEB_CONTRADICTION_CHECK, WEB_FACT_CHECK,
    WEB_FRESHNESS_CHECK, WEB_SEARCH, classify_request,
)
from sciencemath.web.limits import ResearchLimits

ENTITY_LOOKUP = "ENTITY_LOOKUP"
CURRENT_STATUS = "CURRENT_STATUS"
PRIMARY_SOURCE = "PRIMARY_SOURCE"
CONTRADICTION_SEARCH = "CONTRADICTION_SEARCH"
DATE_VERIFICATION = "DATE_VERIFICATION"
TECHNICAL_DOCUMENTATION = "TECHNICAL_DOCUMENTATION"
SCIENTIFIC_EVIDENCE = "SCIENTIFIC_EVIDENCE"
COUNTER_EVIDENCE = "COUNTER_EVIDENCE"

INTENTS = (
    ENTITY_LOOKUP, CURRENT_STATUS, PRIMARY_SOURCE, CONTRADICTION_SEARCH,
    DATE_VERIFICATION, TECHNICAL_DOCUMENTATION, SCIENTIFIC_EVIDENCE,
    COUNTER_EVIDENCE,
)

_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "for", "in", "on", "is",
    "are", "was", "were", "what", "who", "whom", "which", "this", "that",
    "with", "from", "does", "do", "did", "how", "when", "where", "why",
}


_STRIP_SUFFIX = re.compile(
    r"\s*(Please use official sources\.?|Cite evidence\.?|"
    r"Prefer a primary source\.?|Do not invent a URL\.?)\s*$",
    re.I,
)
_STRIP_PREFIX = re.compile(
    r"^(Look up( official)?|Search the web( for)?:?|"
    r"Fact-check the claim that|"
    r"Is this claim supported by evidence:?|"
    r"Compare what these sources claim about|"
    r"Who is the current|What is the)\s+",
    re.I,
)


def _phrases(question: str) -> list[str]:
    q = re.sub(r"[^\w\s\-/]", " ", question or "")
    words = [w for w in q.split() if w.lower() not in _STOP and len(w) > 1]
    if not words:
        return []
    joined = " ".join(words)
    out = [joined]
    # keep proper-noun runs
    runs = re.findall(r"(?:[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)*)", question or "")
    out.extend(runs)
    return list(dict.fromkeys(x.strip() for x in out if x.strip()))


def topic_claim(question: str, *, drop_years: bool = False) -> str:
    """Entity/topic used for entailment — not the full user utterance."""
    q = _STRIP_SUFFIX.sub("", question or "").strip()
    q = _STRIP_PREFIX.sub("", q).strip()
    if drop_years:
        q = re.sub(r"\b(?:19|20)\d{2}\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip()
    phrases = _phrases(q)
    if phrases:
        return phrases[0]
    return q or (question or "").strip()


def plan_queries(question: str, *, limits: ResearchLimits | None = None,
                 op: str | None = None) -> dict:
    limits = limits or ResearchLimits()
    op = op or classify_request(question)
    phrases = _phrases(question)
    seed = phrases[0] if phrases else (question or "").strip()
    intents: list[str] = [ENTITY_LOOKUP]
    queries = [seed] if seed else []

    if op in (WEB_SEARCH, WEB_FRESHNESS_CHECK) or re.search(
            r"\b(current|today|latest|breaking)\b", question or "", re.I):
        intents.append(CURRENT_STATUS)
        queries.append(f"{seed} current".strip())
        queries.append(f"{seed} official".strip())
    if re.search(r"\b(api|docs|documentation|specification|protocol)\b",
                 question or "", re.I):
        intents.append(TECHNICAL_DOCUMENTATION)
        queries.append(f"{seed} official documentation specification")
        queries.append(f"{seed} API")
    if re.search(r"\b(study|trial|efficacy|paper|journal|nist|constant)\b",
                 question or "", re.I):
        intents.append(SCIENTIFIC_EVIDENCE)
        queries.append(f"{seed} paper trial")
    if op == WEB_COMPARE or op == WEB_CONTRADICTION_CHECK:
        intents.append(CONTRADICTION_SEARCH)
        queries.append(f"{seed} contradiction")
        queries.append(f"{seed} denied")
    if op == WEB_FACT_CHECK:
        intents.append(COUNTER_EVIDENCE)
        queries.append(f"{seed} evidence")
        queries.append(f"{seed} false")
    if re.search(r"\b(year|date|passed in|since|appointed)\b",
                 question or "", re.I):
        intents.append(DATE_VERIFICATION)
        queries.append(f"{seed} date")
    intents.append(PRIMARY_SOURCE)
    if seed:
        queries.append(f"{seed} official")

    # de-dupe, budget
    seen = []
    for q in queries:
        qn = re.sub(r"\s+", " ", q).strip()
        if qn and qn.lower() not in {s.lower() for s in seen}:
            seen.append(qn)
    seen = seen[: limits.max_search_queries]
    intents = list(dict.fromkeys(intents))
    return {
        "intents": intents,
        "queries": seen,
        "budget": limits.max_search_queries,
        "op": op,
    }
