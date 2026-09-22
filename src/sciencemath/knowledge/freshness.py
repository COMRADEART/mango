"""T21.16 / T21.17 — freshness model and temporal language detection.

T22 — temporal signal contract (evaluations/t22/temporal_signal_contract.json):
the corpus is a frozen snapshot. A query whose freshness requirement exceeds
the snapshot must NOT be answered as current: it routes to WEB_RESEARCH (or
abstains with a staleness notice). Static, record-pinned, and historical
"as of" questions are answerable from the frozen corpus.

T22 classification model (deterministic, frozen before blind construction):
every query gets a temporal intent among STATIC, HISTORICAL_AS_OF,
CURRENT_REQUIRED, RECENCY_SENSITIVE, AMBIGUOUS_FRESHNESS, resolved by a
frozen precedence over runtime-visible signal carriers only (query
semantics, source freshness metadata, source as-of dates, the corpus
snapshot date, and the explicit request timestamp). The route decision is a
staleness mapping: with an explicit request date, CURRENT_REQUIRED and
RECENCY_SENSITIVE route to web research exactly when the request date is
past the snapshot; without one, CURRENT_REQUIRED fail-safes to web research
(a stale snapshot is never presented as current) and RECENCY_SENSITIVE
answers from the frozen frame without asserting currency.
"""
from __future__ import annotations

import re

from sciencemath.knowledge.schema import FRESHNESS_CLASSES_SET

# Temporal cue patterns. Order matters for the classification precedence
# (explicit-current > record-pinning > historical-as-of > present-state
# lexicon > unresolved temporal word > static default).
# T21R6 — generalized explicit-current vocabulary: the T21R5 replay proved
# "present-day" (and its family) exceeded the frozen snapshot but was not
# recognized as an explicit-current cue, so the runtime answered stale
# snapshot state as current (4 rows: "Which town is the present-day
# capital of X?"). The additions are the standard current-time phrasing
# family, preregistered before holdout construction. Frozen in the T22
# temporal signal contract (explicit_current_cues).
_EXPLICIT_CURRENT = re.compile(
    r"\b(current|currently|today|now|right now|this (?:week|month|year|"
    r"quarter)|so far|at present|as we speak|live|present[- ]day|"
    r"present day|modern[- ]day|modern day|nowadays|these days|"
    r"as of now|at the moment)\b", re.IGNORECASE)
# T22 — inherent-recency words are always temporal in sense (unlike
# superlatives, whose noun must be time-scoped). Frozen in the temporal
# signal contract (inherent_recency_words).
_INHERENT_RECENCY = re.compile(
    r"\b(recent|recently|last (?:week|month|year)|this year|"
    r"up to date|up-to-date)\b", re.IGNORECASE)
# T22 — superlatives are temporal only over a time-scoped referent
# ("latest version"), never over an arbitrary noun ("latest digit").
# Frozen in the temporal signal contract (superlative_time_scoped_nouns).
_SUPERLATIVE = re.compile(r"\b(latest|newest)\b", re.IGNORECASE)
_TIME_SCOPED_NOUNS = (
    "version", "release", "model", "edition", "update", "report", "news",
    "event", "figure", "estimate", "ranking", "standings", "score", "build",
    "firmware", "patch", "draft", "revision", "announcement", "episode",
    "season", "study", "development",
)
# T22 — present-state fact-class lexicons (frozen in the temporal signal
# contract): a role/value noun in a present-tense frame makes the query
# recency-sensitive even without an explicit current word (T21R17 root
# cause: the lexical cue list alone could not classify present-state
# intent). Populations, capitals, and other slow-changing facts are
# deliberately absent (SLOW_CHANGING semantics).
_ROLE_LEXICON = (
    "president", "vice president", "prime minister", "chancellor",
    "premier", "mayor", "governor", "ceo", "cfo", "coo", "cto", "chief",
    "executive director", "managing director", "chairman", "chairwoman",
    "chairperson", "chair", "secretary", "secretary general",
    "secretary-general", "treasurer", "director", "dean", "principal",
    "rector", "provost", "coach", "captain", "manager", "leader",
    "proprietor", "owner", "editor", "ambassador", "senator", "minister",
    "pope", "monarch", "king", "queen", "emperor", "emir", "sultan",
    "officeholder", "office holder",
)
_VALUE_LEXICON = (
    "price", "cost", "exchange rate", "fare", "fee", "salary", "wage",
    "interest rate", "inflation rate", "unemployment rate", "stock price",
    "share price", "market cap", "version", "balance", "status", "quote",
)
_PRESENT_FRAME = re.compile(
    r"\b(?:who|what|which|where)\s+(?:is|are)\b|\b(?:who's|what's)\b",
    re.IGNORECASE)
_PAST_FRAME = re.compile(
    r"\b(?:who|what|which|where)\s+(?:was|were)\b", re.IGNORECASE)
_HISTORICAL_AS_OF = re.compile(
    r"\bas of\s+(?:the\s+)?(?:end of\s+)?(\d{4}|[A-Z][a-z]+ \d{1,2},? "
    r"\d{4}|\w+ \d{4})\b", re.IGNORECASE)
_YEAR_TOKEN = re.compile(r"\b(1[5-9]\d{2}|20[0-4]\d)\b")
# T22 — record-pinning frame: the named record is the evidence universe,
# so the question is snapshot-internal regardless of fact class. Frozen in
# the temporal signal contract (record_pinning_phrases).
_RECORD_PIN = re.compile(
    r"\b(within (?:the |blind )?record|according to (?:the|this) record|"
    r"per the (?:registered )?record|stated in (?:the|this) record|"
    r"the record states|as recorded in|as stated in the record|"
    r"as registered in)\b", re.IGNORECASE)
# T22 — self-contained referents: the fact lives in the query itself
# ("the latest digit in this sequence"), so no external current evidence
# is required. Frozen in the temporal signal contract
# (self_contained_referents).
_SELF_CONTAINED = re.compile(
    r"\b(this sequence|the sequence|the following|the above|this list|"
    r"the list|this puzzle|this pattern)\b", re.IGNORECASE)
# T22 — physics-sense suppression for the noun "current" (frozen in the
# temporal signal contract, physics_sense_suppression): the noun "current"
# in a physics/electrical sense is not a currency cue. Suppressed when
# preceded by a frozen physics modifier ("ocean current", "electrical
# current"), followed by "in <physics domain>" context ("current in
# electrical engineering"), an adjacent physics compound ("current
# density", "current account"), or asked as a definition lookup ("define
# current", "definition of current").
_PHYSICS_PRECEDE = re.compile(
    r"\b(ocean|air|tidal|water|electric|electrical|alternating|direct|"
    r"eddy|convection)\s+(?:surface\s+|deep\s+)?currents?\b", re.IGNORECASE)
_PHYSICS_FOLLOW_IN = re.compile(
    r"\bin\s+(?:the\s+)?(?:electrical|electric|physics|ocean|air|water|"
    r"tidal|circuit|conductor|density|account)\b", re.IGNORECASE)
_PHYSICS_ADJACENT = re.compile(
    r"^\s+(?:density|account)\b", re.IGNORECASE)
_DEFINITION_FRAME = re.compile(
    r"\b(?:define|definition of)\s+(?:the\s+)?current\b", re.IGNORECASE)

# Status vocabulary the freshness gate can recommend.
FRESH_ACTION_ANSWER = "ANSWER"
FRESH_ACTION_ROUTE_WEB = "ROUTE_WEB_RESEARCH"

# T22 — temporal intent vocabulary (frozen signal contract).
INTENT_STATIC = "STATIC"
INTENT_HISTORICAL = "HISTORICAL_AS_OF"
INTENT_CURRENT_REQUIRED = "CURRENT_REQUIRED"
INTENT_RECENCY_SENSITIVE = "RECENCY_SENSITIVE"
INTENT_AMBIGUOUS = "AMBIGUOUS_FRESHNESS"
TEMPORAL_INTENTS = (
    INTENT_STATIC, INTENT_HISTORICAL, INTENT_CURRENT_REQUIRED,
    INTENT_RECENCY_SENSITIVE, INTENT_AMBIGUOUS,
)

_CORPUS_SNAPSHOT = "2026-01-31"
_CORPUS_SNAPSHOT_YEAR = 2026

# T21R5 — proper-noun currency guard. The word "Current" as the second
# element of a proper-noun compound ("Benguela Current", "Kuroshio
# Current") is part of a NAME, not a currency cue: routing such a query to
# WEB_RESEARCH is a false temporal signal (T21R4 replay: two geography
# rows routed instead of answering). A capitalized "Current" counts as
# part of a proper-noun compound only when it is immediately preceded by
# a capitalized non-function word; lowercase "current" ("current mayor")
# and sentence-initial "Current" remain currency cues.
_FUNCTION_WORD_CAPS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "and", "or", "is",
    "was", "its", "his", "her", "their", "this", "that", "as", "for",
    "with", "by", "from", "not", "but",
})
_CAP_PREDECESSOR_RE = re.compile(r"([A-Za-z][\w'-]*)$")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date(value: str) -> tuple[int, int, int] | None:
    """Parse an ISO date (YYYY-MM-DD) into a comparable tuple."""
    if not value or not _DATE_RE.match(value.strip()):
        return None
    year, month, day = (int(part) for part in value.strip().split("-"))
    return (year, month, day)


def _explicit_current_cues(text: str) -> list[re.Match]:
    """Real currency-cue matches in text, excluding proper-noun
    compounds ("Benguela Current") and physics-sense noun uses ("current
    in electrical engineering", "the ocean current", "define current")."""
    cues = []
    for m in _EXPLICIT_CURRENT.finditer(text):
        if m.group(0).lower() != "current":
            cues.append(m)
            continue
        prefix = text[:m.start()].rstrip(" \t\"'(")
        prev = _CAP_PREDECESSOR_RE.search(prefix)
        if prev and prev.group(1)[:1].isupper() and \
                prev.group(1).lower() not in _FUNCTION_WORD_CAPS:
            continue  # proper-noun compound, not a currency cue
        if _PHYSICS_PRECEDE.search(text[:m.end()]):
            continue  # "ocean/electrical current": physics noun
        if _PHYSICS_FOLLOW_IN.search(text[m.end():m.end() + 24]):
            continue  # "current (flow) in <physics domain>": physics noun
        if _PHYSICS_ADJACENT.search(text[m.end():m.end() + 12]):
            continue  # "current density/account": physics compound
        if _DEFINITION_FRAME.search(text):
            continue  # definition lookup of the noun, not currency
        cues.append(m)
    return cues


def _historical_year(query: str) -> int | None:
    m = _HISTORICAL_AS_OF.search(query)
    if m:
        digits = re.findall(r"\d{4}", m.group(1))
        if digits:
            return int(digits[0])
    return None


def _lexicon_hits(query: str) -> list[str]:
    """Present-state role/value lexicon terms present in the query."""
    lowered = query.lower()
    hits = []
    for term in (*_ROLE_LEXICON, *_VALUE_LEXICON):
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            hits.append(term)
    return hits


def _record_pinned(query: str) -> bool:
    return _RECORD_PIN.search(query) is not None


def _classify_intent(query: str) -> tuple[str, list[str], str | None]:
    """Frozen precedence (temporal signal contract, router_precedence).

    Returns (intent, matched signals, frame) where frame is
    "record_pinned", "historical", or None.
    """
    signals: list[str] = []
    current_cues = _explicit_current_cues(query)
    pinned = _record_pinned(query)
    as_of_year = _historical_year(query)
    frame_present = _PRESENT_FRAME.search(query)
    frame_past = _PAST_FRAME.search(query)
    lexicon = _lexicon_hits(query)
    self_contained = _SELF_CONTAINED.search(query)

    if current_cues:
        signals.extend(m.group(0).lower() for m in current_cues)
        return INTENT_CURRENT_REQUIRED, signals, None
    if pinned:
        signals.append("record_pinned")
        return INTENT_STATIC, signals, "record_pinned"
    if as_of_year is not None:
        m = _HISTORICAL_AS_OF.search(query)
        signals.append(query[m.start():m.end()].lower())
        return INTENT_HISTORICAL, signals, "historical"
    if frame_past and lexicon:
        signals.append(f"past_frame:{lexicon[0]}")
        return INTENT_HISTORICAL, signals, "historical"
    if recency_match := _INHERENT_RECENCY.search(query):
        signals.append(recency_match.group(0).lower())
        return INTENT_CURRENT_REQUIRED, signals, None
    if superlative := _SUPERLATIVE.search(query):
        tail = query[superlative.end():superlative.end() + 32].lower()
        scoped = any(
            re.search(rf"\b{re.escape(noun)}\b", tail)
            for noun in _TIME_SCOPED_NOUNS
        )
        if scoped:
            signals.append(f"{superlative.group(0).lower()}+time_scoped")
            return INTENT_CURRENT_REQUIRED, signals, None
        if self_contained:
            signals.append(f"{superlative.group(0).lower()}:self_contained")
            return INTENT_STATIC, signals, None
        signals.append(f"{superlative.group(0).lower()}:unscoped")
        return INTENT_AMBIGUOUS, signals, None
    if frame_present and lexicon:
        signals.append(f"present_state:{lexicon[0]}")
        return INTENT_RECENCY_SENSITIVE, signals, None
    return INTENT_STATIC, signals, None


def classify_query_freshness(query: str, now: str = "",
                             snapshot_date: str | None = None) -> dict:
    """Classify a query's freshness requirement (T22 temporal signal
    contract).

    ``now`` is the explicit runtime request date (signal-carrier E); the
    pipeline never reads the wall clock. ``snapshot_date`` defaults to the
    frozen corpus snapshot. Returns a dict with the carried-forward keys
    (freshness_requirement, temporal_signals, action, reason) plus the T22
    keys temporal_intent, request_date, snapshot_date, snapshot_stale,
    and frame.
    """
    snapshot = snapshot_date or CORPUS_SNAPSHOT_DATE
    request_date = _parse_date(now) if now else None
    snapshot_parsed = _parse_date(snapshot)
    stale = (
        request_date is not None and snapshot_parsed is not None
        and request_date > snapshot_parsed
    )
    intent, signals, frame = _classify_intent(query)
    as_of_year = _historical_year(query)

    if intent == INTENT_CURRENT_REQUIRED:
        # Fail-safe: without a request date the runtime cannot establish
        # that the frozen snapshot is current, so an explicit
        # current-information requirement routes to web research
        # (no_stale_fallback, temporal signal contract section 11).
        route = stale or request_date is None
        return {
            "freshness_requirement": "TIME_SENSITIVE",
            "temporal_signals": signals,
            "action": FRESH_ACTION_ROUTE_WEB if route
            else FRESH_ACTION_ANSWER,
            "reason": (
                "explicit current/now/today phrasing exceeds the frozen "
                "corpus snapshot" if stale else
                "explicit current/now/today phrasing; the request date is "
                "unknown, so the runtime cannot establish that the frozen "
                "snapshot is current and routes to web research"
                if request_date is None else
                f"current phrasing within the snapshot validity window "
                f"({snapshot}): the frozen snapshot is the allowed current "
                "path for this request date"
            ),
            "temporal_intent": intent,
            "request_date": now,
            "snapshot_date": snapshot,
            "snapshot_stale": stale,
            "frame": frame,
        }
    if intent == INTENT_RECENCY_SENSITIVE:
        if stale:
            return {
                "freshness_requirement": "TIME_SENSITIVE",
                "temporal_signals": signals,
                "action": FRESH_ACTION_ROUTE_WEB,
                "reason": (
                    "present-state fact class with the request date beyond "
                    "the frozen corpus snapshot"
                ),
                "temporal_intent": intent,
                "request_date": now,
                "snapshot_date": snapshot,
                "snapshot_stale": stale,
                "frame": frame,
            }
        return {
            "freshness_requirement": "STATIC",
            "temporal_signals": signals,
            "action": FRESH_ACTION_ANSWER,
            "reason": (
                "present-state fact class but the snapshot covers the "
                "request date; answered from the frozen frame without "
                "asserting currency"
            ),
            "temporal_intent": intent,
            "request_date": now,
            "snapshot_date": snapshot,
            "snapshot_stale": stale,
            "frame": frame,
        }
    if intent == INTENT_AMBIGUOUS:
        return {
            "freshness_requirement": "STATIC",
            "temporal_signals": signals,
            "action": FRESH_ACTION_ANSWER,
            "reason": (
                "temporal word with an unresolved scope; the deterministic "
                "ambiguity policy answers locally unless runtime-visible "
                "source metadata establishes a present-state requirement"
            ),
            "temporal_intent": intent,
            "request_date": now,
            "snapshot_date": snapshot,
            "snapshot_stale": stale,
            "frame": frame,
        }
    if intent == INTENT_HISTORICAL:
        return {
            "freshness_requirement": "STATIC",
            "temporal_signals": signals,
            "action": FRESH_ACTION_ANSWER,
            "reason": (
                f"historical 'as of {as_of_year}' frame is frozen-snapshot "
                "compatible"
                if as_of_year is not None else
                "past-tense frame asks for a past state; frozen-snapshot "
                "compatible"
            ),
            "temporal_intent": intent,
            "request_date": now,
            "snapshot_date": snapshot,
            "snapshot_stale": stale,
            "frame": frame,
        }
    return {
        "freshness_requirement": "STATIC",
        "temporal_signals": signals,
        "action": FRESH_ACTION_ANSWER,
        "reason": "no temporal cue requiring evidence newer than snapshot",
        "temporal_intent": intent,
        "request_date": now,
        "snapshot_date": snapshot,
        "snapshot_stale": stale,
        "frame": frame,
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
    # The cue regex is case-insensitive, so the ORIGINAL text is scanned:
    # lowercasing here would erase the proper-noun capitalization that
    # distinguishes "Benguela Current" (a name) from "current" (a cue).
    return not _explicit_current_cues(text)


CORPUS_SNAPSHOT_DATE = _CORPUS_SNAPSHOT