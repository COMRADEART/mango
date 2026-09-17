"""End-to-end T21R8 development matrix, using only fresh fictional records."""
import json
from collections import Counter
import pytest

from sciencemath.knowledge.pipeline import answer_knowledge
from sciencemath.knowledge.relations import canonical_relation
from sciencemath.knowledge.citations import extract_citation_ids
from t21r8_development_rows import CHAINS, COUNTS, ROWS


def test_development_matrix_exact_counts_and_independent_namespaces():
    assert COUNTS == {"multihop": 120, "crossdomain": 100, "completeness": 80,
                      "provenance": 80, "injection": 80, "singlehop": 80}
    assert len(ROWS) == 540
    assert len({r.case_id for r in ROWS}) == len(ROWS)
    assert len({r.start for r in ROWS}) == len(ROWS)
    assert len(set(CHAINS)) == 12
    assert Counter(r.relations for r in ROWS if r.category == "multihop") == {
        chain: 10 for chain in CHAINS}
    for category in COUNTS:
        statuses = {r.status for r in ROWS if r.category == category}
        assert "ANSWER" in statuses
        assert "INSUFFICIENT_EVIDENCE" in statuses
    assert all(r.start.startswith("Ulvexa ") for r in ROWS)


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r.case_id)
def test_fresh_development_answer_citations_paths_and_traces(row):
    corpus, fact_chunks = row.corpus()
    result = answer_knowledge(row.query, corpus=corpus, top_k=row.top_k)
    data = result.to_dict()
    context = json.dumps({"row": row.case_id, "status": result.status,
                          "answer": result.answer, "trace": result.decision_trace,
                          "path_trace": data.get("evidence_path_trace")}, indent=2)
    assert result.status == row.status, context
    assert result.zero_tolerance and not any(result.zero_tolerance.values()), context
    assert result.eligibility["eligible"], context
    assert data["evidence_paths"] == [
        path.to_dict() if hasattr(path, "to_dict") else path
        for path in result.evidence_paths]
    trace = data["evidence_path_trace"]
    assert trace, context
    assert trace.get("status"), context
    assert trace.get("reason"), context
    assert trace.get("validation_trace"), context
    assert set(trace["requested_relations"]) == {
        str(canonical_relation(relation)) for relation in row.relations}, context
    assert trace["first_retrieval"], context
    for forbidden in row.forbidden:
        assert forbidden not in result.answer, context
    if row.status != "ANSWER":
        assert result.answer == "", context
        assert result.citations == [], context
        assert data["evidence_paths"] == [], context
        if row.status == "CONFLICTING_EVIDENCE":
            assert result.evidence_pack["conflicts"], context
        return

    assert row.final in result.answer, context
    assert result.citation_report["ok"], context
    assert result.claim_review["all_claims_supported"], context
    assert "citation_gate:OK" in result.decision_trace, context
    assert "claim_gate:OK" in result.decision_trace, context
    assert trace["start_entity"] == row.start, context
    assert len(data["evidence_paths"]) == 1, context
    path = data["evidence_paths"][0]
    assert path["hop_count"] == len(row.relations), context
    assert path["final_value"] == row.final, context
    assert path["validation_trace"], context
    edges = path["edges"]
    assert len(edges) == len(row.relations), context
    assert [e["relation"] for e in edges] == [
        str(canonical_relation(relation)) for relation in row.relations], context
    assert edges[0]["subject_entity"] == row.start, context
    assert edges[-1]["object_value"] == row.final, context
    if len(edges) == 2:
        assert edges[0]["object_value"] == edges[1]["subject_entity"] == row.bridge, context
        assert any(t.startswith("multi_hop:2:") for t in result.decision_trace), context
        assert trace["second_retrieval"], context

    cited = {c["citation_id"]: c for c in result.citations}
    evidence = {it["citation_id"]: it for it in result.evidence_pack["evidence_items"]}
    assert set(extract_citation_ids(result.answer)) == set(cited), context
    expected_chunks = {fact_chunks[i] for i in row.edge_indices}
    # Corroborators may be tied primary witnesses, but cannot replace a hop.
    for edge in edges:
        citation = cited[edge["citation_id"]]
        item = evidence[edge["citation_id"]]
        chunk = corpus.chunk(edge["chunk_id"])
        source = corpus.source(edge["source_id"])
        assert chunk is not None and source is not None, context
        assert citation["chunk_id"] == chunk.chunk_id == item["chunk_id"], context
        assert citation["source_id"] == chunk.source_id == source.source_id, context
        assert item["source_id"] == source.source_id, context
        assert edge["subject_entity"] == chunk.metadata["fact_entity"], context
        assert edge["object_value"] == chunk.metadata["fact_value"], context
        assert edge["relation"] == str(canonical_relation(chunk.metadata["fact_attribute"])), context
        assert edge["authority_class"] == source.authority_class, context
        assert edge["freshness_class"] == source.freshness_class, context
        assert set(edge["topic_tags"]) == set(source.topic_tags), context
        assert edge["proposition"] and edge["object_value"] in edge["proposition"], context
        assert edge["proposition"].rstrip(".;") in chunk.text, context
        if row.mode != "corroboration":
            assert chunk.chunk_id in expected_chunks, context
    assert set(path["source_ids"]) == {e["source_id"] for e in edges}, context
    assert path["citation_ids"] == list(dict.fromkeys(e["citation_id"] for e in edges)), context
    assert set(path["domain_tags"]) == {tag for e in edges for tag in e["topic_tags"]}, context
    assert "uncited-domain" not in path["domain_tags"], context
    if row.mode == "same_source":
        assert len(path["source_ids"]) == 1 and len(path["citation_ids"]) == 2, context
    if row.mode == "corroboration":
        assert data["corroborating_evidence"], context
        assert len(result.citations) > len(edges), context
        assert {c["chunk_id"] for c in data["corroborating_evidence"]}.isdisjoint(
            {e["chunk_id"] for e in edges}), context
    if row.flagged:
        assert result.source_injection["n_items_flagged"] >= 1, context
        assert result.source_injection["instruction_authority"] == 0, context
        assert result.source_injection["acted_on"] is False, context
    elif row.category == "injection":
        assert result.source_injection["n_items_flagged"] == 0, context
