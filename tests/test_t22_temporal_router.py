"""T22 — temporal router runtime tests (preconstruction qualification).

Verifies the remediated candidate against the frozen temporal signal
contract (evaluations/t22/temporal_signal_contract.json) and the temporal
holdout design, on non-blind material only:

- the five frozen temporal intents classify deterministically;
- the no_stale_fallback invariant (contract section 13): a
  current-information requirement with a request date past the frozen
  snapshot never produces an ANSWER from the snapshot;
- the static_query invariant (contract section 14): record-pinned,
  historical, and timeless shapes never route to web research;
- the R17 failure shapes now route (regression: the R17 blind
  explicit-current family, reproduced here as non-blind template cases);
- the post-retrieval metadata rule (carrier B): TIME_SENSITIVE source
  metadata with a stale request date routes, the same query with STATIC
  source metadata answers (protocol section 25 proof);
- the runtime date comes only from the explicit ``now`` input
  (contract section 16): no wall-clock reads, deterministic outputs.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from sciencemath.knowledge.corpus import build_corpus_files, load_corpus
from sciencemath.knowledge.freshness import (
    INTENT_AMBIGUOUS,
    INTENT_CURRENT_REQUIRED,
    INTENT_HISTORICAL,
    INTENT_RECENCY_SENSITIVE,
    INTENT_STATIC,
    classify_query_freshness,
    snapshot_is_current_claim_safe,
)
from sciencemath.knowledge.pipeline import answer_knowledge
from sciencemath.knowledge.routing import (
    ROUTE_WEB_RESEARCH,
    knowledge_eligibility,
)
from sciencemath.knowledge.schema import (
    KnowledgeChunk,
    KnowledgeSourceRecord,
)

SNAPSHOT = "2026-01-31"
REQUEST_DATE = "2026-06-30"


# --------------------------------------------------------------------------
# frozen intent classification (5 intents)
# --------------------------------------------------------------------------
def test_intent_explicit_current_direct_cue() -> None:
    r = classify_query_freshness(
        "What is the current registered value of blind entry c1?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_CURRENT_REQUIRED
    assert r["action"] == "ROUTE_WEB_RESEARCH"
    assert r["snapshot_stale"] is True


def test_intent_lexicon_frame_role() -> None:
    # T21R17 root-cause shape: present-state role lexicon without any
    # explicit current/today/latest token.
    r = classify_query_freshness(
        "Who is the registered officeholder for blind entry c2?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_RECENCY_SENSITIVE
    assert r["action"] == "ROUTE_WEB_RESEARCH"
    assert r["temporal_signals"]


def test_intent_metadata_only_shape_is_static() -> None:
    # The metadata-only sub-shape has NO temporal word: classification is
    # STATIC; routing must come exclusively from source metadata (carrier
    # B), never from gold information.
    r = classify_query_freshness(
        "What registered value is stated for blind entry c3?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_STATIC
    assert r["action"] == "ANSWER"
    assert r["temporal_signals"] == []


def test_intent_historical_as_of_never_routes() -> None:
    r = classify_query_freshness(
        "As of 2019, what registered value is stated for blind entry c5?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_HISTORICAL
    assert r["action"] == "ANSWER"
    assert r["snapshot_stale"] is True  # stale but snapshot-compatible


def test_intent_record_pinned_is_static() -> None:
    r = classify_query_freshness(
        "Within blind record c4, what registered value is stated?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_STATIC
    assert r["frame"] == "record_pinned"
    assert r["action"] == "ANSWER"


def test_intent_past_tense_frame_is_historical() -> None:
    r = classify_query_freshness(
        "What was the registered officeholder for blind entry c6?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_HISTORICAL
    assert r["action"] == "ANSWER"


def test_intent_ambiguous_unscoped_superlative() -> None:
    # T21R17 section-24 fix: "latest" over an unscoped referent is not a
    # determinate current-information requirement.
    r = classify_query_freshness(
        "What is the latest registered value of blind entry c7?")
    assert r["temporal_intent"] == INTENT_AMBIGUOUS
    assert r["action"] == "ANSWER"


def test_intent_superlative_time_scoped_routes() -> None:
    r = classify_query_freshness(
        "What is the latest version of the analysis tool?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_CURRENT_REQUIRED
    assert r["action"] == "ROUTE_WEB_RESEARCH"


def test_intent_inherent_recency_is_current_required() -> None:
    r = classify_query_freshness(
        "What recent registered result is recorded for c9?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_CURRENT_REQUIRED
    assert r["action"] == "ROUTE_WEB_RESEARCH"


def test_intent_static_default() -> None:
    r = classify_query_freshness(
        "What registered value is stated for blind entry c3?",
        now="", snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_STATIC
    assert r["action"] == "ANSWER"


# --------------------------------------------------------------------------
# contract section 13 — no stale fallback for CURRENT_REQUIRED
# --------------------------------------------------------------------------
@pytest.mark.parametrize("now", ["2026-06-30", "2027-01-01", ""])
def test_current_required_with_stale_or_unknown_request_routes(now) -> None:
    r = classify_query_freshness(
        "What is the current registered value of blind entry c1?",
        now=now, snapshot_date=SNAPSHOT)
    assert r["temporal_intent"] == INTENT_CURRENT_REQUIRED
    assert r["action"] == "ROUTE_WEB_RESEARCH"


def test_current_required_within_snapshot_window_answers() -> None:
    # The frozen snapshot is the allowed current path when the request
    # date is inside the snapshot validity window.
    r = classify_query_freshness(
        "What is the current registered value of blind entry c1?",
        now="2026-01-31", snapshot_date=SNAPSHOT)
    assert r["action"] == "ANSWER"
    assert r["snapshot_stale"] is False


# --------------------------------------------------------------------------
# contract section 14 — static shapes never route
# --------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "Within blind record c4, what registered value is stated?",
    "As of 2019, what registered value is stated for blind entry c5?",
    "What registered value is stated for blind entry c3?",
    "What was the registered officeholder for blind entry c6?",
    "What is the latest digit in this sequence 3 1 4 1 5?",
])
def test_static_invariant_no_routing(query) -> None:
    r = classify_query_freshness(query, now=REQUEST_DATE,
                                 snapshot_date=SNAPSHOT)
    assert r["action"] == "ANSWER"
    assert r["temporal_intent"] in (INTENT_STATIC, INTENT_HISTORICAL,
                                    INTENT_AMBIGUOUS)


# --------------------------------------------------------------------------
# section 24 — false-positive fixes (deterministic regressions)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "How does current flow in electrical circuits?",
    "What is the current in electrical engineering?",
    "What is the ocean current near the Benguela system?",
    "Define current in physics terms.",
    "What is the Benguela Current?",
])
def test_physics_and_propernoun_current_is_not_a_cue(query) -> None:
    r = classify_query_freshness(query, now="", snapshot_date=SNAPSHOT)
    assert r["action"] == "ANSWER"
    assert r["temporal_intent"] != INTENT_CURRENT_REQUIRED


# --------------------------------------------------------------------------
# backward-compatible single-arg contract (R17 call sites)
# --------------------------------------------------------------------------
def test_backward_compatible_keys_and_single_arg() -> None:
    r = classify_query_freshness(
        "Within blind record c4, what registered value is stated?")
    for key in ("freshness_requirement", "temporal_signals", "action",
                "reason", "temporal_intent", "request_date",
                "snapshot_date", "snapshot_stale", "frame"):
        assert key in r
    assert r["action"] == "ANSWER"
    assert r["request_date"] == ""
    assert r["snapshot_date"] == SNAPSHOT  # frozen default
    assert r["temporal_intent"] == INTENT_STATIC


def test_no_wall_clock_determinism() -> None:
    # Contract section 16: the runtime date comes from the explicit input
    # only; repeated classification without one is deterministic.
    q = "What is the current registered value of blind entry c1?"
    a = classify_query_freshness(q)
    b = classify_query_freshness(q)
    assert a == b
    assert a["request_date"] == ""
    assert a["snapshot_date"] == SNAPSHOT
    # An unparsed request date is treated as absent (fail-safe route).
    c = classify_query_freshness(q, now="not-a-date")
    assert c["action"] == "ROUTE_WEB_RESEARCH"


def test_snapshot_is_current_claim_safe_uses_suppression() -> None:
    assert snapshot_is_current_claim_safe("the value is 12")
    assert not snapshot_is_current_claim_safe("the value is currently 12")
    # Proper-noun compound remains safe.
    assert snapshot_is_current_claim_safe("the Benguela Current flows north")


# --------------------------------------------------------------------------
# routing passthrough
# --------------------------------------------------------------------------
def test_knowledge_eligibility_carries_temporal_intent() -> None:
    temporal = classify_query_freshness(
        "What is the current registered value of blind entry c1?",
        now=REQUEST_DATE, snapshot_date=SNAPSHOT)
    e = knowledge_eligibility("What is the current registered value of "
                              "blind entry c1?", temporal)
    assert e["eligible"] is False
    assert e["route"] == ROUTE_WEB_RESEARCH
    assert e["temporal_intent"] == INTENT_CURRENT_REQUIRED
    e2 = knowledge_eligibility(
        "Within blind record c4, what registered value is stated?",
        classify_query_freshness(
            "Within blind record c4, what registered value is stated?",
            now=REQUEST_DATE, snapshot_date=SNAPSHOT))
    assert e2["eligible"] is True
    assert e2["temporal_intent"] == INTENT_STATIC


# --------------------------------------------------------------------------
# post-retrieval metadata rule (carrier B / protocol section 25 proof)
# --------------------------------------------------------------------------
def _synthetic_corpus(tmp_path, freshness: str):
    src = KnowledgeSourceRecord(
        source_id="gk-t22fix-0001",
        source_title="T22 preconstruction fixture record",
        source_type="fixture",
        source_uri_or_origin="project://t22/fixtures",
        publisher_or_collection="mango-t22",
        license="CC0",
        revision_or_version="v1",
        retrieved_at_or_snapshot_date=SNAPSHOT,
        language="en",
        authority_class="GENERAL_REFERENCE",
        freshness_class=freshness,
        topic_tags=["cross_domain"],
        content_text="Blind record c-fix states the registered value 41.",
    )
    chunk = KnowledgeChunk(
        chunk_id="gk-t22fix-0001-001", source_id=src.source_id,
        section="main", ordinal=0,
        text="Blind record c-fix states the registered value 41.",
        span=(0, 51))
    build_corpus_files(tmp_path, [src], [chunk],
                       snapshot_date=SNAPSHOT)
    return load_corpus(tmp_path)


def _no_wall_clock_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@pytest.mark.parametrize("freshness,expected_status", [
    ("TIME_SENSITIVE", "ROUTE_WEB_RESEARCH"),
    ("STATIC", "ANSWER"),
])
def test_metadata_only_carrier_rule(tmp_path, freshness,
                                    expected_status) -> None:
    corpus = _synthetic_corpus(tmp_path, freshness)
    query = "What registered value is stated for blind record c-fix?"
    # Deterministic and identical across repeated calls (no wall clock).
    first = answer_knowledge(query, corpus, now=REQUEST_DATE)
    second = answer_knowledge(query, corpus, now=REQUEST_DATE)
    assert first.status == expected_status
    assert _no_wall_clock_hash(json.dumps(first.decision_trace)) == \
        _no_wall_clock_hash(json.dumps(second.decision_trace))
    if expected_status == "ROUTE_WEB_RESEARCH":
        assert "temporal_metadata_route:TIME_SENSITIVE_source_stale_" \
               "snapshot" in first.decision_trace
        assert first.answer == ""
        assert first.eligibility["route"] == ROUTE_WEB_RESEARCH
        assert first.eligibility["temporal_intent"] in (INTENT_STATIC,
                                                        INTENT_AMBIGUOUS)


def test_metadata_rule_exempt_for_record_pinned(tmp_path) -> None:
    corpus = _synthetic_corpus(tmp_path, "TIME_SENSITIVE")
    query = "Within blind record c-fix, what registered value is stated?"
    result = answer_knowledge(query, corpus, now=REQUEST_DATE)
    # Record-pinning makes the question snapshot-internal regardless of
    # source metadata (contract section 8 / static invariant).
    assert result.status != ROUTE_WEB_RESEARCH


def test_metadata_rule_requires_stale_request(tmp_path) -> None:
    corpus = _synthetic_corpus(tmp_path, "TIME_SENSITIVE")
    query = "What registered value is stated for blind record c-fix?"
    result = answer_knowledge(query, corpus, now="2026-01-31")
    # Request date inside the snapshot window: the snapshot is current
    # for this request, so no routing.
    assert result.status != ROUTE_WEB_RESEARCH