"""T21R6 Part B1 — root-cause artifact protection tests.

evaluations/t21r6/t21r5_multihop_root_cause.json records the diagnosis of
the 32 multihop failures exposed by the single official T21R5 exposure
(NON-PROMOTIONAL). These tests pin the artifact to its evidence so the
diagnosis can never silently drift from the raw results it claims to
explain, and pin the repair contract (no per-phrasing regex).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "evaluations" / "t21r6" / "t21r5_multihop_root_cause.json"
RAW = ROOT / "evaluations" / "t21r5" / "raw_results.jsonl"
PIPELINE = ROOT / "src" / "sciencemath" / "knowledge" / "pipeline.py"

FAILED_TRACE = ("attribute_gate:NO_NAMED_ATTRIBUTE_EVIDENCED",)


def _doc() -> dict:
    assert ARTIFACT.exists(), (
        "t21r5_multihop_root_cause.json missing — regenerate via the B1 "
        "diagnosis")
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_artifact_evidence_sha_matches_raw_results():
    doc = _doc()
    assert doc["source"]["file"] == "evaluations/t21r5/raw_results.jsonl"
    assert doc["source"]["sha256"] == \
        hashlib.sha256(RAW.read_bytes()).hexdigest()


def test_artifact_counts_match_reality():
    doc = _doc()
    rows = [json.loads(l) for l in
            RAW.read_text(encoding="utf-8").splitlines() if l.strip()]
    fails = [r for r in rows
             if r.get("suite") == "mango-t21r5-multihop-holdout-v1"
             and r.get("expected_status") == "ANSWER"
             and r.get("status") != "ANSWER"]
    assert doc["scope"]["total_rows"] == len(
        [r for r in rows
         if r.get("suite") == "mango-t21r5-multihop-holdout-v1"])
    assert doc["scope"]["failed_rows"] == len(fails) == 32
    assert len(doc["per_row"]) == 32
    artifact_ids = {r["case_id"] for r in doc["per_row"]}
    assert artifact_ids == {r["case_id"] for r in fails}


def test_every_per_row_record_matches_raw_row():
    doc = _doc()
    rows = {json.loads(l)["case_id"]: json.loads(l)
            for l in RAW.read_text(encoding="utf-8").splitlines()
            if l.strip()}
    for rec in doc["per_row"]:
        raw = rows[rec["case_id"]]
        assert rec["query"] == raw["query"]
        assert rec["observed_status"] == raw["status"]
        assert rec["expected_status"] == raw["expected_status"]
        assert rec["decision_trace"] == raw["decision_trace"]
        assert rec["diagnosis"]


def test_classification_and_mechanism_pinned():
    doc = _doc()
    rc = doc["root_cause"]
    assert rc["classification"] == "INTERROGATIVE_NORMALIZATION_GAP"
    assert rc["stage"] == \
        "wrong-entity gate on the bridge-candidate scan " \
        "(precedes attribute-named selection; no coverage-gate involvement)"
    assert FAILED_TRACE[-1] in rc["failure_trace_shared_by_all_rows"]
    # the distinguishing evidence: all failures sentence-initial "Within",
    # zero passing rows use it
    dist = rc["evidence_phrase_distribution"]
    assert dist["failed_rows_first_word"] == {"Within": 32}
    assert "Within" not in dist["passing_rows_first_word"]


def test_repair_is_generalized_not_per_phrasing():
    doc = _doc()
    repair = doc["root_cause"]["repair"]
    # the repair must be relational vocabulary + attribute-aware hop-2
    # selection, never a hardcoded failed query or phrasing
    assert "_RELATIONAL_PREPOSITIONS" in repair
    assert "_BRIDGE_TARGET_CUES" in repair
    assert "Within which town" not in repair
    src = PIPELINE.read_text(encoding="utf-8")
    assert "_RELATIONAL_PREPOSITIONS" in src
    assert "_BRIDGE_TARGET_CUES" in src
    assert "_QUESTION_FRAME_TOKENS" in src and "_CAP_FRAMEWORDS" in src


def test_repair_reproducibly_fixes_the_failure_shape():
    """The exact failed shape (sentence-initial 'Within' creator-birth
    query) must now bridge and answer on a synthetic world; the trace
    must show the two-hop path, not the old attribute-gate abstention."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from sciencemath.knowledge.corpus import KnowledgeCorpus
    from sciencemath.knowledge.pipeline import answer_knowledge
    from sciencemath.knowledge.schema import (
        KnowledgeChunk,
        KnowledgeSourceRecord,
        make_chunk_id,
    )

    snap = "2026-01-31"
    s1, s2 = "gk-rc-w-000001", "gk-rc-b-000002"
    corpus = KnowledgeCorpus(
        sources=[
            KnowledgeSourceRecord(
                source_id=s1, source_title="W", source_type="reference",
                source_uri_or_origin=f"local://{s1}",
                publisher_or_collection="fx", license="CC0",
                revision_or_version="1",
                retrieved_at_or_snapshot_date=snap, language="en",
                authority_class="ENCYCLOPEDIC", freshness_class="STATIC",
                topic_tags=["literature"]),
            KnowledgeSourceRecord(
                source_id=s2, source_title="B", source_type="reference",
                source_uri_or_origin=f"local://{s2}",
                publisher_or_collection="fx", license="CC0",
                revision_or_version="1",
                retrieved_at_or_snapshot_date=snap, language="en",
                authority_class="ENCYCLOPEDIC", freshness_class="STATIC",
                topic_tags=["biography"]),
        ],
        chunks=[
            KnowledgeChunk(
                chunk_id=make_chunk_id(s1, "book-author", 0), source_id=s1,
                section="book-author", ordinal=0,
                text="The novel Ambregarth Vale was written by Elena "
                     "Tarnwick; the author of Ambregarth Vale is Elena "
                     "Tarnwick.",
                span=(0, 80), metadata={
                    "fact_entity": "Ambregarth Vale",
                    "fact_attribute": "author",
                    "fact_value": "Elena Tarnwick"}),
            KnowledgeChunk(
                chunk_id=make_chunk_id(s2, "tw-birth", 0), source_id=s2,
                section="tw-birth", ordinal=0,
                text="Elena Tarnwick was born in the town of Halemere; the "
                     "birthplace of the writer Elena Tarnwick is Halemere.",
                span=(0, 80), metadata={
                    "fact_entity": "Elena Tarnwick",
                    "fact_attribute": "birthplace",
                    "fact_value": "Halemere"}),
        ],
        manifest={"snapshot_date": snap})
    result = answer_knowledge(
        "Within which town was the author of Ambregarth Vale born?", corpus)
    assert result.status == "ANSWER", result.decision_trace
    assert "Halemere" in result.answer
    assert "multi_hop:2:" in " ".join(result.decision_trace)
    assert FAILED_TRACE[-1] not in result.decision_trace