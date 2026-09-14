"""T21.7 (eligibility) / T21.28–T21.31 — knowledge-domain eligibility and
cross-skill boundary routing.

KNOWLEDGE_RAG handles broad stable general knowledge. Out-of-scope
intents route deterministically to the owning skill:

  scientific explanation / method / mechanism  -> SCIENCE_RAG
  computation on given parameters               -> SCICOMP (or MATH_T4)
  user-provided document/file content           -> DOCUMENT
  personal/user-specific facts                  -> MEMORY
  fresh/live/open-web evidence                  -> WEB_RESEARCH
  everything else stable and factual            -> answer locally

The Executive Router is NOT modified by T21: this module is the
KNOWLEDGE_RAG runtime's own eligibility gate, used when the runtime is
invoked directly.
"""
from __future__ import annotations

import re

ANSWER_STATUS = "ANSWER"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
ROUTE_WEB_RESEARCH = "ROUTE_WEB_RESEARCH"
ROUTE_SCIENCE_RAG = "ROUTE_SCIENCE_RAG"
ROUTE_DOCUMENT = "ROUTE_DOCUMENT"
ROUTE_MEMORY = "ROUTE_MEMORY"
OUT_OF_SCOPE = "OUT_OF_SCOPE"

ANSWER_STATUSES = (
    ANSWER_STATUS, INSUFFICIENT_EVIDENCE, CONFLICTING_EVIDENCE,
    ROUTE_WEB_RESEARCH, ROUTE_SCIENCE_RAG, ROUTE_DOCUMENT, ROUTE_MEMORY,
    OUT_OF_SCOPE,
)

_SCIENCE_CUES = re.compile(
    r"\bmitochondria\b|photosynthesis|\benzyme\b|\batp\b|\borbital\b|"
    r"\breaction rate\b|kinetics|thermodynamic|\bmolecule\b|"
    r"\bphysics problem\b|\bentropy\b|\bacid-base\b|\bprotein fold\b|"
    r"\bdna\b|\bgene expression\b", re.IGNORECASE)
_COMPUTE_CUES = re.compile(
    r"\bcalculate|compute|solve for|evaluate\b.*\b(?:given|parameters)\b|"
    r"\bnumerically|integral|derivative|matrix|eigenvalue", re.IGNORECASE)
_DOCUMENT_CUES = re.compile(
    r"\b(this|the|my) (?:pdf|file|document|spreadsheet|docx|attachment|"
    r"table)\b|\bsummarize this\b|\bin the file\b|\bfrom the document\b",
    re.IGNORECASE)
_MEMORY_CUES = re.compile(
    r"\b(?:what did i|i told you|my project|my notes|i said|i mentioned|"
    r"remember when i)\b", re.IGNORECASE)
_WEB_CUES = re.compile(
    r"\b(?:reported|published) (?:today|yesterday|this week)|breaking news|"
    r"\bcurrent (?:price|stock|score|weather|standings|release)\b|"
    r"\blive (?:score|coverage|update|event|stream|feed|match)\b",
    re.IGNORECASE)

# Stable general-knowledge domain vocabulary (T21 corpus domains).
KNOWLEDGE_DOMAINS = (
    "history", "geography", "government_civics", "economics", "computing",
    "technology_history", "literature", "arts", "culture", "natural_world",
    "education_reference", "biography", "cross_domain",
)


def classify_boundary(query: str) -> dict:
    """Deterministic boundary check (T21.28 examples are pinned by tests)."""
    if _DOCUMENT_CUES.search(query):
        return {"status": ROUTE_DOCUMENT,
                "reason": "user-provided document content is DOCUMENT scope"}
    if _MEMORY_CUES.search(query):
        return {"status": ROUTE_MEMORY,
                "reason": "personal/user-specific facts are MEMORY scope"}
    if _COMPUTE_CUES.search(query):
        return {"status": ROUTE_SCIENCE_RAG,
                "reason": "computation on parameters is the scientific/"
                          "math-tool path, not knowledge retrieval"}
    if _SCIENCE_CUES.search(query):
        return {"status": ROUTE_SCIENCE_RAG,
                "reason": "scientific mechanism/evidence question is "
                          "SCIENCE_RAG scope"}
    if _WEB_CUES.search(query):
        return {"status": ROUTE_WEB_RESEARCH,
                "reason": "live/open-web evidence requirement"}
    return {"status": ANSWER_STATUS,
            "reason": "stable general knowledge; local retrieval applies"}


def knowledge_eligibility(query: str, temporal: dict) -> dict:
    """Combined eligibility decision for the knowledge pipeline.

    Precedence: boundary routing > freshness routing > eligible.
    """
    boundary = classify_boundary(query)
    if boundary["status"] != ANSWER_STATUS:
        return {"eligible": False, "route": boundary["status"],
                "reason": boundary["reason"], "boundary": boundary}
    if temporal.get("action") == "ROUTE_WEB_RESEARCH":
        return {"eligible": False, "route": ROUTE_WEB_RESEARCH,
                "reason": temporal.get("reason", "freshness exceeds snapshot"),
                "boundary": boundary,
                "temporal_signals": temporal.get("temporal_signals", [])}
    return {"eligible": True, "route": ANSWER_STATUS,
            "reason": boundary["reason"], "boundary": boundary}