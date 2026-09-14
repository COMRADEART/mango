"""T16.2 — typed WEB_RESEARCH skill contract.

Do not treat every question as requiring web research.
"""
from __future__ import annotations

import re

WEB_SEARCH = "WEB_SEARCH"
WEB_FETCH = "WEB_FETCH"
WEB_INSPECT = "WEB_INSPECT"
WEB_EXTRACT = "WEB_EXTRACT"
WEB_VERIFY = "WEB_VERIFY"
WEB_COMPARE = "WEB_COMPARE"
WEB_FACT_CHECK = "WEB_FACT_CHECK"
WEB_FRESHNESS_CHECK = "WEB_FRESHNESS_CHECK"
WEB_CONTRADICTION_CHECK = "WEB_CONTRADICTION_CHECK"
WEB_SYNTHESIZE = "WEB_SYNTHESIZE"
WEB_CITE = "WEB_CITE"
WEB_NO_EVIDENCE = "WEB_NO_EVIDENCE"
WEB_NEEDS_CLARIFICATION = "WEB_NEEDS_CLARIFICATION"
WEB_BLOCKED = "WEB_BLOCKED"

WEB_OPS = (
    WEB_SEARCH, WEB_FETCH, WEB_INSPECT, WEB_EXTRACT, WEB_VERIFY,
    WEB_COMPARE, WEB_FACT_CHECK, WEB_FRESHNESS_CHECK,
    WEB_CONTRADICTION_CHECK, WEB_SYNTHESIZE, WEB_CITE, WEB_NO_EVIDENCE,
    WEB_NEEDS_CLARIFICATION, WEB_BLOCKED,
)

_BLOCKED = re.compile(
    r"\b(download (and )?(run|execute)|curl .*\| *(bash|sh)|"
    r"login to|purchase|buy (a |an )?(report|dataset|api key)|"
    r"paid (search|api)|submit (this )?form|send (an )?email|"
    r"upload (the |this )?(file|secret)|post (this )?comment)\b", re.I)

_MATH = re.compile(
    r"^\s*(what('s| is)|calculate|compute|evaluate)?\s*"
    r"[\d\.\s\+\-\*\/\^\(\)]+\s*\??\s*$", re.I)
_ARITH = re.compile(
    r"\b(what is \d+\s*[\+\-\*\/x×]\s*\d+|square root of \d+|"
    r"convert \d+\s*(km|m|kg|lb|celsius|fahrenheit))\b", re.I)

_COMPARE = re.compile(
    r"\b(compare (what )?(these|the) (three |two |sources|pages)|"
    r"what do (these|the) (three |sources) claim|"
    r"side[- ]by[- ]side)\b", re.I)
_FACT = re.compile(
    r"\b(is this claim|fact[- ]check|supported by evidence|"
    r"does (the )?evidence support|verify (this |the )?claim)\b", re.I)
_FRESH = re.compile(
    r"\b(still (true|current|accurate)|outdated|stale source|"
    r"is this (source|article|page) (still )?(current|valid)|"
    r"as of today is .{0,40} (still|current))\b", re.I)
_CONTRA = re.compile(
    r"\b(disagree|contradict|conflict(ing)? sources|"
    r"sources (differ|conflict))\b", re.I)
_FETCH = re.compile(
    r"\b(fetch|open|retrieve) (this |the )?(url|page|link|source)\b", re.I)
_INSPECT = re.compile(
    r"\b(inspect (this |the )?(page|source|html)|what domain|"
    r"publisher of|metadata (for|of))\b", re.I)
_EXTRACT = re.compile(
    r"\b(extract (the )?(evidence|quote|span)|what does .{0,40} say)\b", re.I)
_CITE = re.compile(r"\b(cite|citation|provenance|source list)\b", re.I)
_VERIFY = re.compile(
    r"\b(does (this|the) source (actually )?support|entailment)\b", re.I)
_WEB = re.compile(
    r"\b(search the web|look up|look it up|browse|latest news|"
    r"what happened( to| with)? .*(today|this week|yesterday)|"
    r"current (ceo|status|price|version|mayor|population)|"
    r"who is the (current )?|"
    r"official (docs|documentation|site|specification|announcement)|"
    r"primary source|according to (the )?(web|sources|news)|"
    r"on the (official|company) (site|website)|"
    r"breaking|as of (today|this (week|month|year)))\b", re.I)
_VAGUE = re.compile(
    r"^\s*(look it up|search( it)?|google it|find out)\s*\.?\s*$", re.I)


def needs_web(text: str) -> bool:
    """True only when the question requires external evidence."""
    op = classify_request(text)
    return op not in (WEB_NO_EVIDENCE, WEB_NEEDS_CLARIFICATION, WEB_BLOCKED)


def classify_request(text: str) -> str:
    """Map a natural-language request to exactly one WEB operation."""
    q = (text or "").strip()
    if not q:
        return WEB_NEEDS_CLARIFICATION
    if _BLOCKED.search(q):
        return WEB_BLOCKED
    if _MATH.match(q) or _ARITH.search(q):
        return WEB_NO_EVIDENCE
    if _VAGUE.search(q):
        return WEB_NEEDS_CLARIFICATION
    if _COMPARE.search(q):
        return WEB_COMPARE
    if _FACT.search(q):
        return WEB_FACT_CHECK
    if _FRESH.search(q):
        return WEB_FRESHNESS_CHECK
    if _CONTRA.search(q):
        return WEB_CONTRADICTION_CHECK
    if _FETCH.search(q):
        return WEB_FETCH
    if _INSPECT.search(q):
        return WEB_INSPECT
    if _EXTRACT.search(q):
        return WEB_EXTRACT
    if _VERIFY.search(q):
        return WEB_VERIFY
    if _CITE.search(q):
        return WEB_CITE
    if _WEB.search(q):
        return WEB_SEARCH
    # Time-insensitive closed questions without a lookup cue do not
    # require the web (T16.2: "What is 2+2?").
    if re.search(r"\b(today|current|latest|breaking|official|"
                 r"according to|look up|search|who is|what happened|"
                 r"fact[- ]check|compare .{0,30}sources)\b", q, re.I):
        return WEB_SEARCH
    return WEB_NO_EVIDENCE
