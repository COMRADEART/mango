"""Fresh development reproduction of partial-path answering; no holdout inputs."""
from sciencemath.knowledge.corpus import KnowledgeCorpus
from sciencemath.knowledge.pipeline import answer_knowledge
from sciencemath.knowledge.schema import KnowledgeChunk, KnowledgeSourceRecord


def test_location_country_path_requires_terminal_value_and_both_sources():
    sources = []
    chunks = []
    for index, (entity, relation, value, domain) in enumerate([
        ("Qorzeth Archive", "location", "Ulveniq Borough", "culture"),
        ("Ulveniq Borough", "country", "Mazrulin Federation", "geography"),
    ]):
        sid = f"gk-r8dev-reproduction-{index}"
        sources.append(KnowledgeSourceRecord(
            source_id=sid, source_title=f"Development reference {index}",
            source_type="reference", source_uri_or_origin=f"local://{sid}",
            publisher_or_collection="R8 development", license="CC0",
            revision_or_version="1", retrieved_at_or_snapshot_date="2026-01-31",
            language="en", authority_class="ENCYCLOPEDIC",
            freshness_class="STATIC", topic_tags=[domain],
        ))
        text = f"The {relation} of {entity} is {value}."
        chunks.append(KnowledgeChunk(
            chunk_id=f"{sid}:fact:0", source_id=sid, section="fact",
            text=text, ordinal=0, span=(0, len(text)),
            metadata={"fact_entity": entity, "fact_attribute": relation,
                      "fact_value": value},
        ))
    corpus = KnowledgeCorpus(sources=sources, chunks=chunks,
                             manifest={"snapshot_date": "2026-01-31"})
    result = answer_knowledge(
        "What is the country of the location of Qorzeth Archive?", corpus,
        top_k=1,
    )
    assert result.status == "ANSWER", result.decision_trace
    assert "Mazrulin Federation" in result.answer, (result.answer, result.decision_trace)
    assert {c["source_id"] for c in result.citations} == {s.source_id for s in sources}
    assert result.citation_report["ok"]
