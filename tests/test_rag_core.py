"""T5 core tests — registry, license gates, schema, cleaning, chunking,
taxonomy, routing, evidence contract, citations, audit, metrics.

Deterministic only: no model, no network, no index.
"""
from __future__ import annotations

import json

import pytest

from sciencemath.rag.citations import (Citation, claim_support_score,
                                       verify_answer_citations,
                                       verify_citation)
from sciencemath.rag.chunking import (ChunkPlan, chunk_document,
                                      chunk_section_text, estimate_tokens)
from sciencemath.rag.cleaning import (BOILERPLATE_SECTIONS, CleanSection,
                                      clean_document, dedupe_sections,
                                      strip_html)
from sciencemath.rag.evidence import (EVIDENCE_STATES, build_contract,
                                      detect_conflicts,
                                      determine_evidence_state)
from sciencemath.rag.metrics import (evaluate_retrieval, mrr, ndcg_at_k,
                                     recall_at_k)
from sciencemath.rag.pipeline import build_prompt
from sciencemath.rag.route import classify_route, prompt_modules_for_route
from sciencemath.rag.schema import SciDocument, chunk_checksum, normalize_record
from sciencemath.rag.source_registry import (LicenseGateError, SourceRegistry,
                                             SourceRegistryError,
                                             default_registry)
from sciencemath.rag.taxonomy import (DOMAINS, SCIENCE_TAXONOMY,
                                      classify_domain, normalize_domain)


# ---------------------------------------------------------------------------
# T5.1 source registry + license gates
# ---------------------------------------------------------------------------

def test_registry_exists_and_denies_by_default():
    reg = default_registry()
    assert reg.source_ids()
    assert reg.allows("wikipedia_en", "local_index") is True
    assert reg.allows("nonexistent_source", "local_index") is False
    assert reg.allows("nonexistent_source", "retrieval") is False
    assert reg.allows("wikipedia_en", "weaponized_use") is False


def test_registry_status_gates():
    reg = default_registry()
    # arxiv: RETRIEVAL_ONLY -> live retrieval ok, durable anything denied
    assert reg.allows("arxiv", "retrieval") is True
    assert reg.allows("arxiv", "local_index") is False
    assert reg.allows("arxiv", "training") is False
    # REVIEW_REQUIRED denied entirely
    assert reg.allows("openstax", "local_index") is False
    assert reg.allows("openstax", "retrieval") is False
    # BLOCKED denied everywhere
    for usage in ("retrieval", "local_index", "redistribution", "training"):
        assert reg.allows("sciencedirect", usage) is False
    # APPROVED but flag explicitly false -> denied
    assert reg.allows("wikipedia_en", "training") is False


def test_registry_require_raises():
    reg = default_registry()
    with pytest.raises(LicenseGateError):
        reg.require("arxiv", "local_index")
    reg.require("wikipedia_en", "local_index")   # must not raise


def test_registry_rejects_malformed_files(tmp_path):
    p = tmp_path / "reg.json"
    dup = {"policy": {"deny_by_default": True},
           "sources": [{"source_id": "a", "status": "APPROVED"},
                       {"source_id": "a", "status": "APPROVED"}]}
    p.write_text(json.dumps(dup), encoding="utf-8")
    with pytest.raises(SourceRegistryError):
        SourceRegistry(p)
    bad_status = {"policy": {"deny_by_default": True},
                  "sources": [{"source_id": "b", "status": "MAYBE"}]}
    p.write_text(json.dumps(bad_status), encoding="utf-8")
    with pytest.raises(SourceRegistryError):
        SourceRegistry(p)
    no_deny = {"policy": {}, "sources": []}
    p.write_text(json.dumps(no_deny), encoding="utf-8")
    with pytest.raises(SourceRegistryError):
        SourceRegistry(p)
    missing = tmp_path / "nope.json"
    with pytest.raises(SourceRegistryError):
        SourceRegistry(missing)


# ---------------------------------------------------------------------------
# T5.3 taxonomy
# ---------------------------------------------------------------------------

def test_taxonomy_canonical_domains():
    for d in ("physics", "chemistry", "biology", "astronomy",
              "earth_science", "computer_science", "interdisciplinary"):
        assert d in SCIENCE_TAXONOMY
    for s in ("mechanics", "electromagnetism", "thermodynamics", "optics",
              "quantum", "relativity", "nuclear_particle"):
        assert s in SCIENCE_TAXONOMY["physics"]
    assert "mathematics" in DOMAINS      # kept separate, not a science domain


def test_domain_normalization():
    assert normalize_domain("Earth Science") == "earth_science"
    assert normalize_domain("Chemistry") == "chemistry"
    assert normalize_domain("ribosomes") == "biology"
    assert normalize_domain(None) == "general"
    assert normalize_domain("zzz") == "general"


def test_domain_classification_whole_word():
    # 'enzymes' (biology) and 'reactions' (chemistry) both match; the
    # longest alias wins -> chemistry. Either is a sane science domain.
    assert classify_domain("How do enzymes speed up reactions?") in \
        ("biology", "chemistry")
    assert classify_domain("What do ribosomes do?") == "biology"
    assert classify_domain("What causes ocean tides?") == "earth_science"
    # no prefix false positives: 'sunlight' must not classify as 'sun'
    d = classify_domain("sunlight passes through the canopy")
    assert d in ("astronomy", "general")
    assert classify_domain("Solve 3x + 5 = 20") == "general"


# ---------------------------------------------------------------------------
# T5.4 document schema + provenance
# ---------------------------------------------------------------------------

def _doc(**over) -> SciDocument:
    base = dict(
        document_id="wiki-1", source_id="wikipedia_en",
        source_type="encyclopedia", title="Algebra", section="History",
        domain="mathematics", subject="", text="Algebra studies ...",
        url="https://en.wikipedia.org/wiki/Algebra", revision="123",
        publication_date="", retrieved_at="2026-09-03",
        license="CC BY-SA 4.0", attribution="Text from Wikipedia (en) ...",
        chunk_id="wiki-1:history:0", checksum="")
    base.update(over)
    doc = SciDocument(**base)
    if not doc.checksum:
        doc.checksum = chunk_checksum(doc)
    return doc


def test_schema_accepts_complete_provenance():
    assert normalize_record(_doc().to_dict(),
                            source_ids={"wikipedia_en"}) is not None


def test_schema_rejects_missing_provenance():
    d = _doc()
    d.url = ""
    with pytest.raises(Exception):
        normalize_record(d.to_dict(), source_ids={"wikipedia_en"})


def test_schema_rejects_unregistered_source():
    with pytest.raises(Exception):
        normalize_record(_doc(source_id="mystery_wiki").to_dict(),
                         source_ids={"wikipedia_en"})


def test_schema_never_fabricates_missing_metadata():
    d = _doc(doi=None, authors=None)
    d2 = normalize_record(d.to_dict(), source_ids={"wikipedia_en"})
    assert d2.doi is None and d2.authors is None


def test_schema_rejects_non_canonical_domain():
    with pytest.raises(Exception):
        normalize_record(_doc(domain="sciency_stuff").to_dict(),
                         source_ids={"wikipedia_en"})


def test_schema_rejects_malformed_chunk_id():
    with pytest.raises(Exception):
        normalize_record(_doc(chunk_id="bad id!").to_dict(),
                         source_ids={"wikipedia_en"})


# ---------------------------------------------------------------------------
# T5.5 cleaning
# ---------------------------------------------------------------------------

def test_cleaning_preserves_science_notation():
    body = ("== Chemistry ==\nWater is H₂O and reacts 2H₂ + O₂ → 2H₂O.\n"
            "The pH is 7.0 at 25 °C; energy ΔE = 1.5 eV.")
    cleaned = clean_document("Water", body)
    text = " ".join(s.text for s in cleaned.sections)
    assert "H₂O" in text
    assert "2H₂ + O₂" in text
    assert "25 °C" in text
    assert "ΔE = 1.5 eV" in text


def test_cleaning_removes_citation_markers():
    out = clean_document("T", "== X ==\nThe cell divides[1][12] often"
                              "[citation needed] today.")
    text = out.sections[0].text
    assert "[1]" not in text and "[citation needed]" not in text
    assert "cell divides" in text


def test_cleaning_drops_boilerplate_and_empty_sections():
    body = ("== See also ==\nMain article: Water cycle.\n"
            "== References ==\n[1] Some book.\n"
            "== History ==\nWater was studied by early philosophers.\n"
            "== Empty ==\n\n")
    cleaned = clean_document("Water", body)
    assert len(cleaned.sections) == 1
    assert "History" in cleaned.sections[0].heading
    assert cleaned.dropped_sections          # boilerplate recorded, not hidden
    assert set(BOILERPLATE_SECTIONS) >= {"references", "see also"}


def test_cleaning_preserves_heading_hierarchy():
    body = ("== Physics ==\nIntro paragraph.\n"
            "=== Mechanics ===\nMotion is described by kinematics.\n")
    cleaned = clean_document("P", body)
    heads = [s.heading for s in cleaned.sections]
    assert any("Physics" in h and "Mechanics" in h for h in heads)


def test_cleaning_html_removal_keeps_superscript():
    raw = "<p>x<sup>2</sup> + y<sub>1</sub> = 3 &amp; 5 &gt; 2</p>"
    out = strip_html(raw)
    assert "x²" in out and "y₁" in out
    assert "script" not in out


def test_cleaning_duplicate_section_flagged():
    body = "== Properties ==\nA body.\n\n== Properties ==\nOther body.\n"
    cleaned = clean_document("T", body)
    assert len(cleaned.sections) == 2
    assert any("(1)" in s.heading for s in cleaned.sections)


def test_exact_duplicate_sections_collapsed():
    a = CleanSection(heading="X", level=2, text="Identical body text.")
    b = CleanSection(heading="X", level=2, text="Identical body text.")
    c = CleanSection(heading="X", level=2, text="Different body text.")
    assert dedupe_sections([a, b, c]) == [a, c]


# ---------------------------------------------------------------------------
# T5.6 chunking
# ---------------------------------------------------------------------------

def test_chunking_respects_target_and_cap():
    body = "\n\n".join(
        f"Paragraph {i} about kinematics " + "word " * 80
        for i in range(6))
    chunks = chunk_section_text(body, ChunkPlan(650, 80))
    toks = [estimate_tokens(c) for c in chunks]
    assert len(chunks) >= 2
    assert all(t <= 900 for t in toks)          # hard cap
    assert any(t >= 400 for t in toks)          # reaches target scale


def test_chunking_never_splits_mid_paragraph():
    para = "A single compact paragraph about momentum. " * 10
    chunks = chunk_section_text(para, ChunkPlan())
    assert chunks
    for c in chunks:
        last = c.split()[-1]
        assert last.endswith((".", "!", "?", ":", ";")) or last[-1].isalnum()


def test_chunking_overlap_present():
    text = "\n\n".join(
        " ".join(f"Sentence {j} of unit {i} explains something."
                 for j in range(8))
        for i in range(12))
    chunks = chunk_section_text(text, ChunkPlan(650, 80))
    assert len(chunks) >= 2
    tail_words = chunks[0].split()[-6:]
    assert any(w in chunks[1] for w in tail_words[:3])


def test_chunk_document_keeps_provenance_fields():
    body = "== A ==\nSome text here.\n== B ==\nMore text."
    cleaned = clean_document("T", body)
    chunks = chunk_document(cleaned.sections, ChunkPlan())
    assert all({"section", "chunk_index", "text", "token_estimate"} <=
               set(c) for c in chunks)
    assert {c["section"] for c in chunks} >= {"A", "B"}


# ---------------------------------------------------------------------------
# T5.11 routing + T5.22/T5.23 invariants
# ---------------------------------------------------------------------------

def test_route_pure_math_never_science():
    for q in ("Solve 3x + 5 = 20", "What is 15% of 80?",
              "Find the derivative of x**2", "Convert 5 km to miles"):
        c = classify_route(q)
        assert c["route"] == "MATH", (q, c)


def test_route_pure_science():
    assert classify_route(
        "What is the function of ribosomes?")["route"] == "SCIENCE"
    assert classify_route("Why do earthquakes occur?")["route"] == "SCIENCE"


def test_route_quantitative_science_is_mixed():
    assert classify_route(
        "A 2 kg object accelerates at 4 m/s². What force acts on it?"
    )["route"] == "MIXED"
    assert classify_route(
        "Using F = ma, calculate the acceleration of a 6 kg object "
        "pushed by an 18 N force.")["route"] == "MIXED"


def test_route_general():
    for q in ("What is the capital of France?",
              "Write a haiku about autumn leaves."):
        assert classify_route(q)["route"] == "GENERAL"


def test_t5_23_conditional_prompt_modules():
    assert prompt_modules_for_route("MATH") == ["math_tools"]
    assert prompt_modules_for_route("SCIENCE") == ["science_retrieval"]
    assert set(prompt_modules_for_route("MIXED")) == \
        {"math_tools", "science_retrieval"}
    assert prompt_modules_for_route("GENERAL") == []


def test_t5_23_no_cross_contamination_in_prompts():
    from sciencemath.tools.benchmark import TOOL_PROTOCOL_INSTRUCTION
    # MATH prompt must NOT contain science evidence scaffolding
    p_math = build_prompt("Solve 3x + 5 = 20.", "MATH", None)
    assert TOOL_PROTOCOL_INSTRUCTION in p_math
    assert "No relevant sources" not in p_math
    # SCIENCE prompt must NOT contain tool protocol
    p_sci = build_prompt("What is a ribosome?", "SCIENCE", None)
    assert TOOL_PROTOCOL_INSTRUCTION not in p_sci
    assert "No relevant sources" in p_sci
    # GENERAL prompt: neither subsystem
    p_gen = build_prompt("What is the capital of France?", "GENERAL", None)
    assert TOOL_PROTOCOL_INSTRUCTION not in p_gen
    assert "No relevant sources" not in p_gen
    assert "boxed" in p_gen


# ---------------------------------------------------------------------------
# T5.18 retrieval metrics (deterministic)
# ---------------------------------------------------------------------------

def test_retrieval_metrics_math():
    retrieved = ["a", "b", "c"]
    assert recall_at_k(retrieved, {"a"}, 1) == 1.0
    assert recall_at_k(retrieved, {"b"}, 1) == 0.0
    assert recall_at_k(retrieved, {"b"}, 3) == 1.0
    assert mrr(retrieved, {"c"}) == pytest.approx(1 / 3)
    assert mrr(retrieved, {"z"}) == 0.0
    assert ndcg_at_k(["a", "b"], {"a": 3, "b": 1}, 2) == pytest.approx(1.0)


def test_evaluate_retrieval_aggregates():
    rows = [
        {"retrieved": ["a", "b", "c"], "expected_domain": "physics",
         "predicted_domain": "physics", "relevant": ["a"],
         "graded": {"a": 3}, "irrelevant_ids": ["c"]},
        {"retrieved": ["x", "a"], "expected_domain": "physics",
         "predicted_domain": "chemistry", "relevant": ["a"],
         "graded": {"a": 3}, "irrelevant_ids": []},
    ]
    m = evaluate_retrieval(rows)
    assert m.n_queries == 2
    assert m.recall_at_1 == 0.5
    assert m.recall_at_5 == 1.0
    assert m.mrr == pytest.approx(0.75)
    assert m.domain_routing_accuracy == 0.5
    assert m.irrelevant_chunk_rate == pytest.approx(1 / 10)
    assert m.to_dict()["recall_at_5"] == 1.0


# ---------------------------------------------------------------------------
# T5.13/T5.14 evidence contract + insufficient evidence
# ---------------------------------------------------------------------------

def test_evidence_insufficient_without_chunks():
    state, sources, reason = determine_evidence_state([])
    assert state == "INSUFFICIENT_EVIDENCE"
    assert sources == [] and reason


def test_evidence_insufficient_with_weak_scores():
    chunks = [{"chunk_id": "c1", "source_id": "wikipedia_en",
               "title": "T", "text": "unrelated text", "score": 0.05}]
    state, sources, _ = determine_evidence_state(chunks)
    assert state == "INSUFFICIENT_EVIDENCE"


def test_evidence_supported_with_reference_answer():
    fact = ("Ribosomes are the molecular machines that carry out protein "
            "synthesis by translating messenger RNA.")
    chunks = [{"chunk_id": "c1", "source_id": "wikipedia_en",
               "title": "Ribosome", "text": fact + " They read mRNA.",
               "score": 0.7}]
    state, sources, _ = determine_evidence_state(
        chunks, reference_answer=fact)
    assert state == "SUPPORTED"
    assert sources[0].chunk_id == "c1"


def test_evidence_never_auto_promotes_ambiguity():
    fact = ("Mitochondria generate ATP through cellular respiration and "
            "contain their own DNA separate from nuclear DNA.")
    chunks = [{"chunk_id": "c1", "source_id": "wikipedia_en", "title": "T",
               "text": "Mitochondria produce ATP in the cell.",
               "score": 0.6}]
    state, _s, _r = determine_evidence_state(chunks, reference_answer=fact)
    assert state in ("PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE")


def test_evidence_states_enum():
    assert set(EVIDENCE_STATES) == {"SUPPORTED", "PARTIALLY_SUPPORTED",
                                    "INSUFFICIENT_EVIDENCE",
                                    "CONFLICTING_EVIDENCE"}


def test_contract_visible_text_reports_sources():
    chunks = [{"chunk_id": "c1", "source_id": "wikipedia_en",
               "title": "Mitochondrion", "text": "Mitochondria produce ATP.",
               "score": 0.6}]
    c = build_contract("They produce ATP.", chunks=chunks,
                       reference_answer="Mitochondria produce ATP.")
    vis = c.visible_text()
    assert "Mitochondrion" in vis
    assert c.used_retrieval is True
    assert c.evidence_state == "SUPPORTED"


# ---------------------------------------------------------------------------
# T5.15 conflicting evidence
# ---------------------------------------------------------------------------

def test_conflicting_evidence_detected_and_preserved():
    chunks = [
        {"chunk_id": "a", "source_id": "wikipedia_en", "title": "A",
         "text": "Glass is an amorphous solid; glass does not flow at "
                 "room temperature because its atoms are rigidly fixed, "
                 "so liquid behavior is impossible.",
         "score": 0.6, "source_type": "encyclopedia",
         "publication_date": "2024-01-01"},
        {"chunk_id": "b", "source_id": "wikipedia_en", "title": "B",
         "text": "Glass is a liquid that flows slowly downward over "
                 "years at room temperature.",
         "score": 0.55, "source_type": "encyclopedia",
         "publication_date": "2001-01-01"},
    ]
    pairs = detect_conflicts(chunks)
    assert ("a", "b") in pairs
    contract = build_contract("Glass flows.", chunks=chunks)
    assert contract.evidence_state == "CONFLICTING_EVIDENCE"
    # both sides preserved, ranked by authority/date (newer chunk first)
    ids = [s.chunk_id for s in contract.sources]
    assert set(ids) == {"a", "b"}
    assert ids[0] == "a"
    assert contract.confidence == "low"


def test_no_artificial_consensus_from_conflict():
    chunks = [
        {"chunk_id": "a", "source_id": "s", "title": "A",
         "text": "The medicine is not effective for this condition.",
         "score": 0.5},
        {"chunk_id": "b", "source_id": "s", "title": "B",
         "text": "Clinical trials show the medicine is effective for this "
                 "condition across many patients studied.",
         "score": 0.5},
    ]
    contract = build_contract("It is effective.", chunks=chunks)
    assert contract.evidence_state == "CONFLICTING_EVIDENCE"
    assert contract.confidence == "low"
    assert contract.uncertainty_reason


def test_conflicting_units_in_chunks_flagged():
    chunks = [
        {"chunk_id": "a", "source_id": "s", "title": "A",
         "text": "The melting point of the alloy is 660 degrees celsius "
                 "measured carefully in lab conditions today.",
         "score": 0.5},
        {"chunk_id": "b", "source_id": "s", "title": "B",
         "text": "The melting point is not 660 degrees; it is far lower "
                 "at ambient pressure measured in field conditions.",
         "score": 0.5},
    ]
    assert ("a", "b") in detect_conflicts(chunks)


# ---------------------------------------------------------------------------
# T5.20 citation verification
# ---------------------------------------------------------------------------

def _retrieved() -> dict[str, dict]:
    return {
        "c1": {"chunk_id": "c1", "source_id": "wikipedia_en",
               "title": "Ribosome",
               "url": "https://en.wikipedia.org/wiki/Ribosome",
               "text": "Ribosomes carry out protein synthesis by "
                       "translating messenger RNA into polypeptide chains.",
               "score": 0.8},
        "c2": {"chunk_id": "c2", "source_id": "wikipedia_en",
               "title": "Newton's laws",
               "url": "https://en.wikipedia.org/wiki/Newton's_laws",
               "text": "Newton's second law: F = ma relates force, mass, "
                       "acceleration.",
               "score": 0.7},
    }


def test_valid_citation_passes():
    c = Citation(chunk_id="c1", source_id="wikipedia_en", title="Ribosome",
                 url="https://en.wikipedia.org/wiki/Ribosome",
                 support="ribosomes carry out protein synthesis translating")
    verify_citation(c, _retrieved())
    assert c.valid and not c.invalid_reason


def test_fabricated_source_fails():
    c = Citation(chunk_id="fabricated-chunk-id", source_id="wikipedia_en",
                 title="Whatever", url="", support="anything at all")
    verify_citation(c, _retrieved())
    assert not c.valid
    assert "fabricated" in c.invalid_reason


def test_wrong_source_id_fails():
    c = Citation(chunk_id="c1", source_id="openstax", title="Ribosome",
                 url="", support="ribosomes carry out protein synthesis")
    verify_citation(c, _retrieved())
    assert not c.valid and "source id" in c.invalid_reason


def test_citation_after_source_filtered_out_fails():
    # the model 'cites' a chunk that was retrieved then filtered OUT —
    # it is not in the supplied context, so it fails provenance closed
    supplied = {k: v for k, v in _retrieved().items() if k != "c2"}
    c = Citation(chunk_id="c2", source_id="wikipedia_en", title="X", url="",
                 support="F = ma relates force mass acceleration")
    verify_citation(c, supplied)
    assert not c.valid and "fabricated" in c.invalid_reason


def test_correct_source_but_unsupported_claim_fails():
    c = Citation(chunk_id="c2", source_id="wikipedia_en",
                 title="Newton's laws", url="",
                 support="the mitochondria produce ATP in cells")
    verify_citation(c, _retrieved())
    assert not c.valid
    assert "unsupported" in c.invalid_reason


def test_irrelevant_chunk_citation_fails():
    c = Citation(chunk_id="c1", source_id="wikipedia_en", title="Ribosome",
                 url="", support="F = ma relates force mass acceleration")
    verify_citation(c, _retrieved())
    assert not c.valid


def test_claim_support_numbers_must_match():
    s1 = claim_support_score("the object has mass 8 kg",
                             "the object has a mass of 8 kg measured")
    s2 = claim_support_score("the object has mass 8 kg",
                             "the object has a mass of 9 kg measured")
    assert s1 >= 0.5
    assert s2 < s1      # numeric mismatch penalized


def test_verify_answer_citations_report():
    good = Citation(chunk_id="c1", source_id="wikipedia_en",
                    title="Ribosome", url="",
                    support="ribosomes carry out protein synthesis translating")
    bad = Citation(chunk_id="ghost", source_id="wikipedia_en", title="X",
                   url="", support="whatever")
    rep = verify_answer_citations("answer", [good, bad], _retrieved())
    assert len(rep.valid) == 1 and len(rep.fabricated) == 1
    assert rep.all_valid is False


# ---------------------------------------------------------------------------
# T5.21 adversarial distractors (deterministic layer)
# ---------------------------------------------------------------------------

def test_semantically_similar_but_wrong_chunk_not_promoted():
    fact = "Ribosomes translate messenger RNA into proteins."
    near_miss = ("Mitochondria translate energy from food into ATP; "
                 "messenger RNA is read inside the cell machinery.")
    # the near-miss must NOT score as full support for the ribosome claim
    assert claim_support_score(fact, near_miss) < 1.0
    assert claim_support_score(
        fact, "Ribosomes translate messenger RNA into proteins in cells."
    ) > claim_support_score(fact, near_miss)


def test_numerical_distractor_rejected_by_support():
    fact = "water boils at 100 degrees celsius"
    wrong_number = "water boils at 0 degrees celsius"
    right_number = "water boils at 100 degrees celsius at standard pressure"
    assert claim_support_score(fact, wrong_number) < \
        claim_support_score(fact, right_number)


# ---------------------------------------------------------------------------
# T5.24 audit logging
# ---------------------------------------------------------------------------

def test_audit_logger_records_fields(tmp_path):
    from sciencemath.rag.audit import RetrievalAuditLogger
    p = tmp_path / "audit.jsonl"
    lg = RetrievalAuditLogger(p)
    lg.log_answer_attempt(
        question_id="q1", question="What is a ribosome?",
        route={"route": "SCIENCE"}, retrieval_used=True,
        embedding_model="intfloat/e5-small-v2",
        retrieved_chunk_ids=["c1"], retrieval_scores={"c1": 0.8},
        rerank_scores={"c1": 0.7}, selected_ids=["c1"],
        rejected=[{"chunk_id": "c9", "why": "threshold"}],
        tool_calls=[], final_source_ids=["wikipedia_en"],
        latency_s=0.5, evidence_state="SUPPORTED")
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    assert rec["event"] == "rag_answer"
    assert rec["retrieval_used"] is True
    assert rec["retrieved_chunk_ids"] == ["c1"]
    assert rec["retrieval_scores"] == {"c1": 0.8}
    assert rec["rerank_scores"] == {"c1": 0.7}
    assert rec["selected_context_ids"] == ["c1"]
    assert rec["rejected_context"] == [{"chunk_id": "c9",
                                        "why": "threshold"}]
    assert rec["evidence_state"] == "SUPPORTED"
    assert "ts" in rec


def test_audit_logger_redacts_secrets(tmp_path):
    from sciencemath.rag.audit import RetrievalAuditLogger
    p = tmp_path / "audit.jsonl"
    lg = RetrievalAuditLogger(p)
    lg.log({"event": "x",
            "note": "authorization: Bearer sk-abc123 api_key=zzz "
                    "password=hunter2"})
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    for secret in ("sk-abc123", "zzz", "hunter2"):
        assert secret not in rec["note"]
    assert "<redacted>" in rec["note"]

# ---------------------------------------------------------------------------
# T5.2 corpus ingestion dedupe (near-duplicate detection)
# ---------------------------------------------------------------------------

def test_ingest_dedupe_normalization():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from ingest_wikipedia import jaccard, normalize_text
    a = "The cell divides quickly."
    assert normalize_text("The cell divides quickly!") == \
        normalize_text(a)            # punctuation-stripped normalization
    assert jaccard(a, "The cell divides quickly!") >= 0.9
    assert jaccard(a, "Completely unrelated vocabulary words appear here") \
        < 0.3
