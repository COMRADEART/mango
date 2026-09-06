"""route — top-level question routing (T5.11).

Extends the T4 tool router with a ROUTE decision — MATH | SCIENCE |
MIXED | GENERAL — without touching tools.router.route_question (its
behavior is frozen by the T4 regression suite).

  MATH     pure mathematics            -> deterministic tools, NO retrieval
  SCIENCE  pure factual science        -> retrieval, no tool protocol
  MIXED    quantitative/mixed science  -> retrieval + math tools as needed
  GENERAL  neither                     -> model reasoning only

Critical T5.22 invariant: "Solve 3x + 5 = 20" is MATH and must never
invoke scientific retrieval.

Prompt-injection design (T5.23): each route injects ONLY its own
subsystem instructions — math-tool protocol text never reaches science
questions and vice versa (regression-tested).
"""
from __future__ import annotations

import re

from sciencemath.rag.taxonomy import classify_domain
from sciencemath.tools.router import route_question

ROUTES = ("MATH", "SCIENCE", "MIXED", "GENERAL")

# quantitative-science signal: a number glued to a scientific unit
_QUANTITY_UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:kg|g|km|cm|mm|m|s|ms|hours?|hrs?|min(?:ute)?s?|"
    r"N|J|kJ|cal|kcal|Pa|kPa|atm|mol|K|°C|°F|eV|MeV|km/h|mph|m/s(?:²)?|"
    r"L|mL|Hz|W|kW|V|A|Ω)\b", re.IGNORECASE)
# physics/math symbols used in equations (F = ma, v = d/t, ...)
_EQUATION_SYMBOL_RE = re.compile(
    r"\b[a-zA-Z]\s*(?:=|≈)\s*[^=]{1,40}\b[a-zA-Z0-9]", re.IGNORECASE)

_SCIENCE_VERB_RE = re.compile(
    r"\b(function|role|process|cause|occur|occurs|happen|structure|"
    r"property|properties|type|types|difference|similar|characteristic|"
    r"feature|features|principle|law|organelle|organism|reaction|"
    r"element|compound|molecule|species|planet|star|cell|gene|"
    r"atmosphere|orbit|orbitals?|bond|bonds|charge|field|force|"
    r"energy|temperature|pressure|velocity|acceleration|mass|"
    r"wavelength|frequency|current|voltage)\b", re.IGNORECASE)


def classify_route(question: str) -> dict:
    """Rule-based route decision. Returns:
    {"route": str, "tools": [names...], "domain": str, "reason": str}

    Deterministic; never executes anything."""
    if not isinstance(question, str) or not question.strip():
        return {"route": "GENERAL", "tools": [], "domain": "general",
                "reason": "empty question"}
    routing = route_question(question)
    tools = routing["tools"]
    domain = classify_domain(question)
    has_science = domain != "general"
    quantitative = bool(_QUANTITY_UNIT_RE.search(question))
    equationish = bool(_EQUATION_SYMBOL_RE.search(question))

    if tools and has_science:
        reason = (f"math tool requested ({tools[0]}) alongside "
                  f"{domain} content")
        return {"route": "MIXED", "tools": tools, "domain": domain,
                "reason": reason}
    if tools and not has_science:
        # tool requested without science context — pure math UNLESS the
        # question still reads as a science explanation request
        if _SCIENCE_VERB_RE.search(question) and quantitative:
            return {"route": "MIXED", "tools": tools, "domain": domain,
                    "reason": "quantity+unit with science vocabulary"}
        return {"route": "MATH", "tools": tools, "domain": domain,
                "reason": f"math tool requested ({tools[0]}), no science context"}
    if has_science:
        if quantitative or equationish:
            return {"route": "MIXED", "tools": tools, "domain": domain,
                    "reason": f"{domain} content with quantities"}
        return {"route": "SCIENCE", "tools": [], "domain": domain,
                "reason": f"science question ({domain}), no computation"}
    if quantitative and _SCIENCE_VERB_RE.search(question):
        return {"route": "MIXED", "tools": tools, "domain": domain,
                "reason": "quantity+unit with science vocabulary"}
    return {"route": "GENERAL", "tools": [], "domain": "general",
            "reason": "neither math nor science signals"}


def prompt_modules_for_route(route: str) -> list[str]:
    """Which instruction modules apply to this route (T5.23). Each route
    gets ONLY its own modules — the regression suite asserts unrelated
    subsystem text is absent."""
    return {
        "MATH": ["math_tools"],
        "SCIENCE": ["science_retrieval"],
        "MIXED": ["math_tools", "science_retrieval"],
        "GENERAL": [],
    }.get(route, [])


# ---------------------------------------------------------------------------
# T5R.1 sub-routes + T5R.6 retrieval eligibility
# ---------------------------------------------------------------------------

SUBROUTES = ("FACTUAL_SCIENCE", "MULTI_HOP_SCIENCE", "MIXED_MATH_SCIENCE",
             "INSUFFICIENT_EVIDENCE", "GENERAL", "MATH")

# multi-hop shape: a premise statement followed by a dependent question,
# or two linked interrogatives ("... , and ... ?")
_MULTI_HOP_RE = re.compile(
    r"[.!?]\s+[^.!?]{10,}\?|\b(?:and|then)\s+(?:how|why|what|which)\b|"
    r"\?\s*,?\s*(?:and|then|why|how)\b|\b(?:using|from|given)\s+this\b",
    re.IGNORECASE)
# contested knowledge requirement (conflict / freshness probes). Bare
# 'current'/'still' match physics senses (electric current, ocean
# currents, still liquid) — only contested-knowledge phrasings count
_CONTESTED_RE = re.compile(
    r"\b(?:as of|latest|nowadays|no longer)\b|"
    r"\bcurrent(?:ly)?\s+(?:best|state|consensus|scientific|estimates?|"
    r"sources|thinking|understanding|theory|theories|view)\b|"
    r"\bstill\s+(?:true|valid|accepted|considered|held|accurate|correct|"
    r"believed)\b|"
    r"\baccording to\b|\bdo (?:some|many) (?:sources|claims|people)\b|"
    r"\bwhy do some sources\b|\bas some (?:old )?claims\b", re.IGNORECASE)
# constants/formulas already supplied in the question (retrieval adds
# nothing the user did not provide — T5R.6 skip signal). Requires an
# assignment (=/:) or an explicit convert-unit shape; bare unit tokens
# (°C, m/s, ...) also appear in ordinary question givens
_SUPPLIED_CONSTANTS_RE = re.compile(
    r"\b(?:specific heat|density|speed of light|gravity|constant)\b[^.!?\n]*"
    r"[=:]\s*[-\d]|"
    r"\bconvert(?:s|ed|ing)?\b\s*[-\d]|"
    r"\d(?:[\d.,]*)?\s*(?:°C|°F|K|km|mi|ft|kg|lb|J)\b[^.!?\n]{0,30}"
    r"\b(?:to|into)\b\s*(?:°C|°F|K|km|mi|ft|kg|lb|J)\b", re.IGNORECASE)
_CITATION_REQUEST_RE = re.compile(
    r"\b(?:cite|citation|source|sources|reference)\b", re.IGNORECASE)


def classify_subroute(question: str) -> dict:
    """Sub-route decision INSIDE a science-capable route (T5R.1).

    Returns {"subroute": str, "signals": [str,...]}. Purely textual —
    evaluation labels are never read. MATH stays MATH."""
    route = classify_route(question)
    r = route["route"]
    if r == "MATH":
        return {"subroute": "MATH", "signals": ["tool_route"]}
    if r == "GENERAL":
        return {"subroute": "GENERAL", "signals": ["no_domain"]}

    signals = []
    if r == "MIXED":
        sub = "MIXED_MATH_SCIENCE"
        signals.append("quantity+science")
    else:
        sub = "FACTUAL_SCIENCE"
    if _MULTI_HOP_RE.search(question):
        sub = "MULTI_HOP_SCIENCE"
        signals.append("premise+dependent question")
    if _CONTESTED_RE.search(question):
        sub = "INSUFFICIENT_EVIDENCE" if sub != "MIXED_MATH_SCIENCE" else sub
        signals.append("contested/current")
    if _CITATION_REQUEST_RE.search(question):
        signals.append("citation requested")
    return {"subroute": sub, "signals": signals}


def retrieval_eligible(question: str, route: str) -> tuple[bool, list[str]]:
    """T5R.6: should retrieval run for this question at all?

    Retrieve when evidence plausibly improves the answer — factual
    scientific claims, named entities/definitions, contested or current
    facts, citation requests, and GENERAL-routed questions that still
    carry scientific vocabulary. Skip for pure math, deterministic
    calculation whose constants are already supplied in the question,
    and tool-only operations. Returns (eligible, signals)."""
    if route == "MATH":
        return False, ["pure math — never retrieve (T5.22)"]
    if route == "SCIENCE":
        return True, ["science route"]
    if route == "MIXED":
        # constants supplied inline ("specific heat ... = 4180",
        # "convert", unit ratios): the computation is self-contained;
        # retrieved prose only distracts (T5R.6)
        if _SUPPLIED_CONSTANTS_RE.search(question) and \
                not _MULTI_HOP_RE.search(question):
            return False, ["constants supplied inline — computation only"]
        return True, ["mixed route"]
    # GENERAL: retrieve only with real scientific vocabulary
    if _SCIENCE_VERB_RE.search(question) or \
            classify_domain(question) != "general":
        return True, ["science vocabulary in GENERAL route"]
    return False, ["no scientific content"]