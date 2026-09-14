"""T21.16 / T21.17 — freshness model and temporal language detection.

The corpus is a frozen snapshot. A query whose freshness requirement
exceeds the snapshot must NOT be answered as current: it routes to
WEB_RESEARCH (or abstains). Static and historical "as of" questions are
answerable from the frozen corpus.
"""
from __future__ import annotations

import re

from sciencemath.knowledge.schema import FRESHNESS_CLASSES_SET

# Temporal cue patterns. Order matters for the classification precedence
# (explicit-current > historical-as-of > latest/newest > static default).
_EXPLICIT_CURRENT = re.compile(
    r"\b(current|currently|today|now|right now|this (?:week|month|year|"
    r"quarter)|so far|at present|as we speak|live)\b", re.IGNORECASE)
_LATEST_RECENT = re.compile(
    r"\b(latest|newest|recent|recently|this year|last (?:week|month|year)|"
    r"up to date|up-to-date)\b", re.IGNORECASE)
_HISTORICAL_AS_OF = re.compile(
    r"\bas of\s+(?:the\s+)?(?:end of\s+)?(\d{4}|[A-Z][a-z]+ \d{1,2},? "
    r"\d{4}|\w+ \d{4})\b", re.IGNORECASE)
_YEAR_TOKEN = re.compile(r"\b(1[5-9]\d{2}|20[0-4]\d)\b")

# Status vocabulary the freshness gate can recommend.
FRESH_ACTION_ANSWER = "ANSWER"
FRESH_ACTION_ROUTE_WEB = "ROUTE_WEB_RESEARCH"

_CORPUS_SNAPSHOT = "2026-01-31"
_CORPUS_SNAPSHOT_YEAR = 2026


def _historical_year(query: str) -> int | None:
    m = _HISTORICAL_AS_OF.search(query)
    if m:
        digits = re.findall(r"\d{4}", m.group(1))
        if digits:
            return int(digits[0])
    return None


def classify_query_freshness(query: str) -> dict:
    """Classify a query's freshness requirement.

    Returns a dict with:
      freshness_requirement: STATIC | SLOW_CHANGING | TIME_SENSITIVE
      temporal_signals: matched phrases
      action: FRESH_ACTION_* — what the pipeline should do
      reason: short deterministic explanation
    """
    signals: list[str] = []
    as_of_year = _historical_year(query)
    current_hit = _EXPLICIT_CURRENT.search(query)
    latest_hit = _LATEST_RECENT.search(query)

    if current_hit:
        signals.append(current_hit.group(0).lower())
    if latest_hit:
        signals.append(latest_hit.group(0).lower())
    if as_of_year is not None:
        signals.append(query[_HISTORICAL_AS_OF.search(query).start():
                             _HISTORICAL_AS_OF.search(query).end()].lower())

    # Explicit current-tense overrides a bare historical year: "current
    # capital as of 1990" still asks for present state.
    if current_hit:
        return {
            "freshness_requirement": "TIME_SENSITIVE",
            "temporal_signals": signals,
            "action": FRESH_ACTION_ROUTE_WEB,
            "reason": "explicit current/now/today phrasing exceeds the "
                      "frozen corpus snapshot",
        }
    if as_of_year is not None and as_of_year <= _CORPUS_SNAPSHOT_YEAR:
        return {
            "freshness_requirement": "STATIC",
            "temporal_signals": signals,
            "action": FRESH_ACTION_ANSWER,
            "reason": f"historical 'as of {as_of_year}' is frozen-snapshot "
                      "compatible",
        }
    if latest_hit:
        return {
            "freshness_requirement": "TIME_SENSITIVE",
            "temporal_signals": signals,
            "action": FRESH_ACTION_ROUTE_WEB,
            "reason": "latest/recent phrasing requires evidence newer than "
                      "the frozen corpus snapshot",
        }
    return {
        "freshness_requirement": "STATIC",
        "temporal_signals": signals,
        "action": FRESH_ACTION_ANSWER,
        "reason": "no temporal cue requiring evidence newer than snapshot",
    }


def source_meets_requirement(source_freshness: str,
                             requirement: str) -> bool:
    """Can a source of this freshness class satisfy this query requirement?

    A frozen snapshot never satisfies TIME_SENSITIVE queries: even a
    SLOW_CHANGING source only holds snapshot-time state, never current
    state. STATIC requirements are satisfiable by any source class.
    """
    if source_freshness not in FRESHNESS_CLASSES_SET:
        return False
    if requirement == "TIME_SENSITIVE":
        return False
    if requirement == "SLOW_CHANGING":
        return source_freshness in ("SLOW_CHANGING", "STATIC")
    return True


def snapshot_is_current_claim_safe(text: str) -> bool:
    """True if an answer text does not present snapshot facts as current.

    Guards the stale-snapshot zero-tolerance gate: any answer containing
    snapshot-sourced facts must not assert present-tense currency
    ("currently", "as of today") unless the query itself was historical
    'as of' phrasing answered with the frozen frame made explicit.
    """
    lowered = text.lower()
    return not _EXPLICIT_CURRENT.search(lowered)


CORPUS_SNAPSHOT_DATE = _CORPUS_SNAPSHOT