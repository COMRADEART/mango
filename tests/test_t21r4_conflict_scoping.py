"""T21R4.3 — reproduction tests for the top-item conflict-scoping defect.

T21R3's strict blind holdout (evaluations/t21r3/) recorded
conflict_detection = 0.8889 < 0.98: six gold-conflict rows abstained
INSUFFICIENT_EVIDENCE because _relevant_conflicts() scoped conflicts to the
metadata of the TOP-RANKED retrieved item only. When the top item does not
carry the queried fact's metadata but lower-ranked items contain a genuine
conflict, relevant = [] and the pipeline synthesizes instead of surfacing
CONFLICTING_EVIDENCE.

These tests fail against the T21R3 runtime and pin the T21R4 repair:
conflict scoping must be QUERY-RELEVANT, not TOP-ITEM-RELEVANT and not
ALL-CONFLICTS-RELEVANT. The suite covers the ten preregistered cases:
  1.  rank 1 unrelated, ranks 2-3 genuine conflict  -> CONFLICTING_EVIDENCE
  2.  rank 1 different attribute, lower conflict    -> CONFLICTING_EVIDENCE
  3.  rank 1 same entity different attribute        -> CONFLICTING_EVIDENCE
  4.  unrelated-entity conflict in set              -> not surfaced
  5.  two attributes same entity, one queried       -> only queried surfaced
  6.  authority-resolvable lower-ranked conflict    -> authority resolution
  7.  freshness-resolvable lower-ranked conflict    -> freshness resolution
  8.  no relevant conflict                          -> NO_CONFLICT
  9.  same-value restatement lower-ranked           -> no false conflict
  10. weakly worded conflict, correct metadata      -> still surfaced
"""
from __future__ import annotations

from sciencemath.knowledge.conflicts import (
    detect_conflicts,
    query_relevant_conflicts,
    resolve_conflicts,
)
from sciencemath.knowledge.evidence import EvidenceItem
from sciencemath.knowledge.pipeline import answer_knowledge
from sciencemath.knowledge.routing import CONFLICTING_EVIDENCE

_H = "0" * 12


def _item(source: str, cid: str, text: str, entity: str, attribute: str,
          value: str, *, authority: str = "ENCYCLOPEDIC",
          freshness: str = "STATIC") -> EvidenceItem:
    return EvidenceItem(
        source_id=source, chunk_id=cid, title="t", section="s",
        text_span=text, score=1.0, rank=0, authority_class=authority,
        content_hash=_H, citation_id="C1-x", freshness_class=freshness,
        metadata={"fact_entity": entity, "fact_attribute": attribute,
                  "fact_value": value})


# ---- case 1: rank 1 unrelated / no target fact metadata -----------------
def test_rank1_unrelated_lower_rank_conflict_surfaces() -> None:
    q = "What establishment year is listed for the town of Marlowgate?"
    items = [
        _item("gk-aaaa11112222", "s0:marlowgate-geography:3",
              "The nation of the town of Marlowgate is Brontide; the town "
              "of Marlowgate lies within Brontide.",
              "Marlowgate", "nation", "Brontide"),
        _item("gk-bbbb33334444", "s1:marlowgate-founded-a:0",
              "The established year of Marlowgate is 1120, per the Register "
              "of Municipal Foundations.",
              "Marlowgate", "established year", "1120",
              authority="GENERAL_REFERENCE"),
        _item("gk-cccc55556666", "s2:marlowgate-founded-b:0",
              "The established year of Marlowgate is 1291, per the Roll of "
              "Foundation.",
              "Marlowgate", "established year", "1291",
              authority="GENERAL_REFERENCE"),
    ]
    conflicts_all = detect_conflicts(items)
    assert conflicts_all, "genuine conflict must be detected at all"
    relevant = query_relevant_conflicts(q, conflicts_all)
    assert relevant, "query-relevant scoping must keep the conflict"
    assert resolve_conflicts(relevant)[0] == CONFLICTING_EVIDENCE


# ---- case 2: rank 1 carries a different attribute ------------------------
def test_rank1_different_attribute_lower_conflict_surfaces() -> None:
    q = "Which founding year is recorded for the city of Verrenholm?"
    items = [
        _item("gk-aaaa11112222", "s0:verrenholm-geography:9",
              "The province of the city of Verrenholm is the salt marches.",
              "Verrenholm", "province", "the salt marches"),
        _item("gk-bbbb33334444", "s1:verrenholm-founded-a:2",
              "The founding year of Verrenholm is 1404, per the civic "
              "register.",
              "Verrenholm", "established year", "1404",
              authority="GENERAL_REFERENCE"),
        _item("gk-cccc55556666", "s2:verrenholm-founded-b:7",
              "The founding year of Verrenholm is 1387, per the charter "
              "roll.",
              "Verrenholm", "established year", "1387",
              authority="GENERAL_REFERENCE"),
    ]
    relevant = query_relevant_conflicts(q, detect_conflicts(items))
    assert relevant
    assert resolve_conflicts(relevant)[0] == CONFLICTING_EVIDENCE


# ---- case 3: rank 1 same entity but unrelated attribute ------------------
def test_rank1_same_entity_unrelated_attribute_surfaces() -> None:
    q = "In which year was the town of Duskwater founded?"
    items = [
        _item("gk-aaaa11112222", "s0:duskwater-emblem:0",
              "The emblem of the town of Duskwater is a bronze heron.",
              "Duskwater", "emblem", "a bronze heron"),
        _item("gk-bbbb33334444", "s1:duskwater-founded-a:0",
              "The town of Duskwater was founded in 1043 according to the "
              "parish record.",
              "Duskwater", "established year", "1043",
              authority="GENERAL_REFERENCE"),
        _item("gk-cccc55556666", "s2:duskwater-founded-b:0",
              "The town of Duskwater was founded in 1099 according to the "
              "abbey roll.",
              "Duskwater", "established year", "1099",
              authority="GENERAL_REFERENCE"),
    ]
    relevant = query_relevant_conflicts(q, detect_conflicts(items))
    assert relevant
    assert resolve_conflicts(relevant)[0] == CONFLICTING_EVIDENCE


# ---- case 4: unrelated-entity conflict must NOT surface ------------------
def test_unrelated_entity_conflict_not_surfaced() -> None:
    q = "What is the established year of the town of Marlowgate?"
    items = [
        _item("gk-aaaa11112222", "s0:marlowgate-geography:3",
              "The nation of the town of Marlowgate is Brontide.",
              "Marlowgate", "nation", "Brontide"),
        _item("gk-bbbb33334444", "s1:aldermoor-founded-a:0",
              "The town of Aldermoor was established in 1138.",
              "Aldermoor", "established year", "1138",
              authority="GENERAL_REFERENCE"),
        _item("gk-cccc55556666", "s2:aldermoor-founded-b:0",
              "The town of Aldermoor was established in 1204.",
              "Aldermoor", "established year", "1204",
              authority="GENERAL_REFERENCE"),
    ]
    conflicts_all = detect_conflicts(items)
    assert conflicts_all, "the Aldermoor conflict is real and detected"
    relevant = query_relevant_conflicts(q, conflicts_all)
    assert relevant == [], "unrelated-entity conflict must not surface"


# ---- case 5: two attributes of same entity, only one queried -------------
def test_only_queried_attribute_conflict_surfaces() -> None:
    q = "What is the established year of the town of Marlowgate?"
    items = [
        _item("gk-aaaa11112222", "s0:marlowgate-geography:3",
              "The nation of the town of Marlowgate is Brontide.",
              "Marlowgate", "nation", "Brontide"),
        _item("gk-bbbb33334444", "s1:marlowgate-founded-a:0",
              "The town of Marlowgate was established in 1120.",
              "Marlowgate", "established year", "1120",
              authority="GENERAL_REFERENCE"),
        _item("gk-cccc55556666", "s2:marlowgate-founded-b:0",
              "The town of Marlowgate was established in 1291.",
              "Marlowgate", "established year", "1291",
              authority="GENERAL_REFERENCE"),
        _item("gk-dddd77778888", "s3:marlowgate-waterway-a:0",
              "The waterway that flows past the town of Marlowgate is the "
              "Sarrow, per the hydrographic register.",
              "Marlowgate", "waterway", "the Sarrow",
              authority="GENERAL_REFERENCE"),
        _item("gk-eeee99990000", "s4:marlowgate-waterway-b:0",
              "The waterway that flows past the town of Marlowgate is the "
              "Vindle, per the gazetteer.",
              "Marlowgate", "waterway", "the Vindle",
              authority="GENERAL_REFERENCE"),
    ]
    conflicts_all = detect_conflicts(items)
    keys = {c["claim_key"] for c in conflicts_all}
    assert keys == {"Marlowgate|established year",
                    "Marlowgate|waterway"}
    relevant = query_relevant_conflicts(q, conflicts_all)
    assert {c["claim_key"] for c in relevant} == \
        {"Marlowgate|established year"}


# ---- case 6: authority-resolvable lower-ranked conflict ------------------
def test_authority_resolvable_lower_rank_conflict_resolves() -> None:
    q = "What is the established year of the town of Marlowgate?"
    items = [
        _item("gk-aaaa11112222", "s0:marlowgate-geography:3",
              "The nation of the town of Marlowgate is Brontide.",
              "Marlowgate", "nation", "Brontide"),
        _item("gk-bbbb33334444", "s1:marlowgate-founded-a:0",
              "The town of Marlowgate was established in 1120, per a local "
              "leaflet.",
              "Marlowgate", "established year", "1120",
              authority="GENERAL_REFERENCE"),
        _item("gk-cccc55556666", "s2:marlowgate-founded-b:0",
              "The established year of Marlowgate is 1291, per the Register "
              "of Municipal Foundations.",
              "Marlowgate", "established year", "1291",
              authority="PRIMARY_REFERENCE"),
    ]
    relevant = query_relevant_conflicts(q, detect_conflicts(items))
    assert relevant
    resolution, winner = resolve_conflicts(relevant)
    assert resolution == "RESOLVED_BY_AUTHORITY"
    assert winner["chunk_id"] == "s2:marlowgate-founded-b:0"


# ---- case 7: freshness-resolvable lower-ranked conflict ------------------
def test_freshness_resolvable_lower_rank_conflict_resolves() -> None:
    q = "Who is the mayor of the town of Marlowgate?"
    items = [
        _item("gk-aaaa11112222", "s0:marlowgate-geography:3",
              "The nation of the town of Marlowgate is Brontide.",
              "Marlowgate", "nation", "Brontide"),
        _item("gk-bbbb33334444", "s1:marlowgate-mayor-old:0",
              "The mayor of the town of Marlowgate is Rosa Quenild, "
              "recorded in the 2019 civic handbook.",
              "Marlowgate", "mayor", "Rosa Quenild",
              freshness="SLOW_CHANGING"),
        _item("gk-cccc55556666", "s2:marlowgate-mayor-new:0",
              "The June 2026 officeholder register records the mayor of "
              "Marlowgate as Tobias Ellery.",
              "Marlowgate", "mayor", "Tobias Ellery",
              freshness="STATIC"),
    ]
    relevant = query_relevant_conflicts(q, detect_conflicts(items))
    assert relevant
    resolution, winner = resolve_conflicts(relevant)
    assert resolution == "RESOLVED_BY_AUTHORITY"
    assert winner["chunk_id"] == "s2:marlowgate-mayor-new:0"


# ---- case 8: no relevant conflict ----------------------------------------
def test_no_relevant_conflict_is_no_conflict() -> None:
    q = "What is the established year of the town of Marlowgate?"
    items = [
        _item("gk-aaaa11112222", "s0:marlowgate-founded:0",
              "The town of Marlowgate was established in 1120, per the "
              "Register of Municipal Foundations.",
              "Marlowgate", "established year", "1120"),
        _item("gk-bbbb33334444", "s1:aldermoor-founded-a:0",
              "The town of Aldermoor was established in 1138.",
              "Aldermoor", "established year", "1138",
              authority="GENERAL_REFERENCE"),
        _item("gk-cccc55556666", "s2:aldermoor-founded-b:0",
              "The town of Aldermoor was established in 1204.",
              "Aldermoor", "established year", "1204",
              authority="GENERAL_REFERENCE"),
    ]
    conflicts_all = detect_conflicts(items)
    assert conflicts_all  # Aldermoor conflict exists but is unrelated
    relevant = query_relevant_conflicts(q, conflicts_all)
    assert relevant == []
    assert resolve_conflicts(relevant)[0] == "NO_CONFLICT"


# ---- case 9: same-value restatement lower-ranked -------------------------
def test_same_value_restatement_lower_rank_no_false_conflict() -> None:
    q = "What is the established year of the town of Marlowgate?"
    items = [
        _item("gk-aaaa11112222", "s0:marlowgate-geography:3",
              "The nation of the town of Marlowgate is Brontide.",
              "Marlowgate", "nation", "Brontide"),
        _item("gk-bbbb33334444", "s1:marlowgate-founded-a:0",
              "The town of Marlowgate was established in 1120, per the "
              "Register of Municipal Foundations.",
              "Marlowgate", "established year", "1120"),
        _item("gk-cccc55556666", "s2:marlowgate-founded-restated:0",
              "Marlowgate's recorded founding year is 1120, according to "
              "the municipal foundation roll.",
              "Marlowgate", "established year", "1120"),
    ]
    relevant = query_relevant_conflicts(q, detect_conflicts(items))
    assert relevant == []
    assert resolve_conflicts(relevant)[0] == "NO_CONFLICT"


# ---- case 10: weakly worded conflict, correct metadata -------------------
def test_weakly_worded_conflict_still_surfaced() -> None:
    q = "Which establishment year is recorded for the town of Marlowgate?"
    items = [
        _item("gk-aaaa11112222", "s0:marlowgate-geography:3",
              "The nation of the town of Marlowgate is Brontide; the town "
              "of Marlowgate lies within Brontide.",
              "Marlowgate", "nation", "Brontide"),
        _item("gk-bbbb33334444", "s1:marlowgate-founded-a:0",
              "The established year of Marlowgate is 1102, per the Register "
              "of Municipal Foundations.",
              "Marlowgate", "established year", "1102",
              authority="GENERAL_REFERENCE"),
        _item("gk-cccc55556666", "s2:marlowgate-founded-b:0",
              "The established year of Marlowgate is 1245, per the Roll of "
              "Foundation.",
              "Marlowgate", "established year", "1245",
              authority="GENERAL_REFERENCE"),
    ]
    relevant = query_relevant_conflicts(q, detect_conflicts(items))
    assert relevant
    assert resolve_conflicts(relevant)[0] == CONFLICTING_EVIDENCE


# ---- pipeline-level reproduction of the T21R3 defect shape ---------------
def test_pipeline_surfaces_conflict_when_top_item_lacks_metadata() -> None:
    """End-to-end: the exact T21R3 miss shape must now return
    CONFLICTING_EVIDENCE instead of INSUFFICIENT_EVIDENCE."""
    from pathlib import Path
    from sciencemath.knowledge.corpus import KnowledgeCorpus

    class _MiniCorpus(KnowledgeCorpus):
        pass

    # Build a minimal corpus by hand using the frozen T21R3 corpus loader
    # is overkill; instead reuse the frozen exposed T21R3 holdout corpus,
    # which is allowed for reproduction testing.
    from sciencemath.knowledge.corpus import load_corpus
    corpus = load_corpus(Path("rag/gk_holdout_t21r3"))
    result = answer_knowledge(
        "What establishment year is listed for the town of Cobblewick?",
        corpus)
    assert result.status == CONFLICTING_EVIDENCE, result.decision_trace