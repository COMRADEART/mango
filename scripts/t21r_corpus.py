"""T21R.4 — build the completely fresh holdout corpus at
rag/gk_holdout_t21r/ (sources.jsonl, chunks.jsonl, corpus_manifest.json).

Composition mirrors the proven T21 corpus shape but with entirely new
project-owned fixture material (scripts/t21r_fixtures.py):

  - new curated stable real-world facts
  - a new fixture world (towns, scholars, works, artworks, institutions,
    technologies) with multi-hop creator chains
  - same-entity/other-attribute distractors, near-miss abstention traps
  - equal-authority conflict pairs (-> CONFLICTING_EVIDENCE),
    authority-resolvable and freshness-resolvable conflict pairs
  - prompt-injection passages with NEW directive phrasings (data, never
    obeyed; they match the frozen runtime's preregistered patterns so
    containment is exercised)

Mechanical disjointness assertions at build time (the holdout must not
reuse T21 material):
  - every source_id is new (no gk- id from rag/gk_corpus)
  - no entity name from the T21 fixture world is reused
  - no T21R fact value string equals a T21 fact value string
  - no chunk text equals a T21 chunk text

Usage: python scripts/t21r_corpus.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge import fixtures as T21F  # noqa: E402  (T21 world)
sys.path.insert(0, str(ROOT / "scripts"))

from sciencemath.knowledge.corpus import build_corpus_files  # noqa: E402
from sciencemath.knowledge.schema import (  # noqa: E402
    KnowledgeChunk,
    KnowledgeSourceRecord,
    make_chunk_id,
    make_source_id,
)
import t21r_fixtures as F  # noqa: E402

SNAPSHOT = F.SNAPSHOT_DATE
LICENSE_NOTE = ("CC0-1.0 (project fixture; T21R fresh holdout corpus; "
                "evaluation only, not training material)")

# ---------------------------------------------------------------------------
# Source plans: (title, publisher, authority, freshness, source_type, tags)
# All titles and publishers are new; source ids are re-derived from identity.
# ---------------------------------------------------------------------------
SOURCES: dict[str, tuple[str, str, str, str, str, list[str]]] = {
    "coastal_gazetteer": (
        "Gazetteer of Coastal and Inland Towns", "Coastal Survey Press",
        "ENCYCLOPEDIC", "SLOW_CHANGING", "reference_work", ["geography"]),
    "continental_atlas": (
        "Continental Atlas of the Four Realms",
        "Continental Reference Union", "INSTITUTIONAL", "SLOW_CHANGING",
        "reference_work", ["geography"]),
    "civic_compendium": (
        "Compendium of Civic Structures", "Office of Civic Records",
        "GOVERNMENT_PUBLICATION", "SLOW_CHANGING", "government_publication",
        ["government_civics"]),
    "founding_ledger": (
        "Ledger of Municipal Foundations", "National Academy Editions",
        "ENCYCLOPEDIC", "STATIC", "reference_work", ["history", "geography"]),
    "towns_annals": (
        "Annals of Small Towns", "National Academy Editions",
        "ENCYCLOPEDIC", "STATIC", "academic_reference",
        ["history", "geography"]),
    "history_compendium": (
        "Compendium of Recorded History", "National Academy Editions",
        "ENCYCLOPEDIC", "STATIC", "reference_work", ["history"]),
    "arts_review": (
        "Review of the Applied Arts", "Continental Reference Union",
        "ENCYCLOPEDIC", "STATIC", "reference_work", ["arts", "culture"]),
    "literature_register": (
        "Register of Printed Literature", "Continental Reference Union",
        "ENCYCLOPEDIC", "STATIC", "reference_work", ["literature"]),
    "economics_notes": (
        "Working Notes on Economic Terms", "National Academy Editions",
        "ACADEMIC_REFERENCE", "STATIC", "academic_reference", ["economics"]),
    "computing_handbook": (
        "Handbook of Computing Methods", "National Academy Editions",
        "ACADEMIC_REFERENCE", "STATIC", "academic_reference", ["computing"]),
    "tech_survey": (
        "Survey of Landmark Technical Systems", "National Academy Editions",
        "ACADEMIC_REFERENCE", "STATIC", "academic_reference",
        ["technology_history"]),
    "officeholder_roll": (
        "Roll of Municipal Officeholders", "Office of Civic Records",
        "INSTITUTIONAL", "TIME_SENSITIVE", "government_register",
        ["government_civics", "biography"]),
    "scholars_dir": (
        "Directory of Scholars and Their Fields",
        "Continental Reference Union", "ENCYCLOPEDIC", "STATIC",
        "academic_reference", ["biography"]),
    "works_list": (
        "List of Regional Works", "Coastal Survey Press",
        "ENCYCLOPEDIC", "STATIC", "reference_work", ["literature"]),
    "gallery_catalog": (
        "Catalogue of Painted Studies", "Coastal Survey Press",
        "ENCYCLOPEDIC", "STATIC", "reference_work", ["arts"]),
    "institutions_dir": (
        "Directory of Learned Coastal Institutions",
        "Continental Reference Union", "ENCYCLOPEDIC", "STATIC",
        "reference_work", ["education_reference"]),
    "tech_registry": (
        "Registry of Inventors and Systems", "Coastal Survey Press",
        "ENCYCLOPEDIC", "STATIC", "reference_work", ["technology_history"]),
    "misc_notes": (
        "Miscellaneous Historical Notes", "Continental Reference Union",
        "GENERAL_REFERENCE", "STATIC", "reference_work", ["history"]),
    "tech_annals_draft": (
        "Draft Annals of Technical Change", "National Academy Editions",
        "ENCYCLOPEDIC", "SLOW_CHANGING", "academic_reference",
        ["technology_history"]),
}

CURATED_SOURCE = {
    "the Sistine Chapel ceiling": "arts_review",
    "Jane Eyre": "literature_register",
    "the Antikythera mechanism": "history_compendium",
    "the cotton gin": "tech_survey",
    "the Voyager 1 probe": "tech_survey",
    "Brazil": "continental_atlas",
    "Kilimanjaro": "continental_atlas",
    "the Nile": "continental_atlas",
    "the United States Bill of Rights": "civic_compendium",
    "the United States House of Representatives": "civic_compendium",
    "gross national income": "economics_notes",
    "a tariff": "economics_notes",
    "a web browser": "computing_handbook",
    "a hash table": "computing_handbook",
    "the steam turbine": "tech_survey",
    "the Treaty of Rome": "history_compendium",
}

# ---------------------------------------------------------------------------
# Sentence templates (new phrasings; each embeds the attribute noun and the
# value so the frozen coverage/entity/synthesis gates are exercisable)
# ---------------------------------------------------------------------------
CITY_ATTR_SECTION = {
    "country": ("Geography",
                "The best-known map of {e} places it in the country of {v}."),
    "founding year": ("History",
                      "The founding year of {e} is {v}; the town of {e} "
                      "was founded then."),
    "river": ("Geography",
              "The river that flows through the town of {e} is {v}."),
    "mayor": ("Government",
              "The March 2026 officeholder register snapshot records the "
              "mayor of {e} as {v}."),
    "landmark": ("Culture",
                 "The best-known landmark of {e} is {v}."),
    "region": ("Geography",
               "The region of {e} is {v}; {e} lies within {v}."),
}

PEOPLE_ATTR_SENTENCE = {
    "field of study": "The field of study of the scholar {e} was {v}.",
    "birth year": "The birth year of {e} is {v}.",
    "birthplace": "{e} was born in the town of {v}; the birthplace of "
                  "{e} is {v}.",
    "notable work": "The notable work of {e} is {v}.",
}

WORK_ATTR_SENTENCE = {
    "genre": "The genre of {e} is {v}; {e} is classified as a {v}.",
    "publication year": "{e} was published in {v}; the publication year "
                        "of {e} is {v}.",
    "subject": "The subject of {e} is {v}.",
}

ART_ATTR_SENTENCE = {
    "painter": "{e} was painted by {v}; the painter of {e} is {v}.",
    "creation year": "{e} was created in {v}; the creation year of "
                     "{e} is {v}.",
    "medium": "The medium of {e} is {v}.",
}

INST_ATTR_SENTENCE = {
    "founding year": "The founding year of the {e} is {v}.",
    "location": "The location of the {e} is the town of {v}.",
}

TECH_ATTR_SENTENCE = {
    "inventor": "The {e} was invented by {v}; the inventor of the {e} "
                "is {v}.",
    "introduction year": "The {e} was introduced in {v}; the introduction "
                         "year of the {e} is {v}.",
    "property": "The {e} is known for {v}.",
}


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


CURATED_SENTENCE = {
    ("the Sistine Chapel ceiling", "painter"):
        "Michelangelo painted the Sistine Chapel ceiling; the painter of "
        "the Sistine Chapel ceiling is Michelangelo.",
    ("Jane Eyre", "author"):
        "The author of Jane Eyre is Charlotte Bronte.",
    ("the Antikythera mechanism", "discovery year"):
        "The discovery year of the Antikythera mechanism is 1901.",
    ("the cotton gin", "invention year"):
        "The cotton gin was invented in 1793; the invention year of the "
        "cotton gin is 1793.",
    ("the Voyager 1 probe", "launch year"):
        "The launch year of the Voyager 1 probe is 1977.",
    ("Brazil", "capital"):
        "The capital of Brazil is Brasilia.",
    ("Kilimanjaro", "country"):
        "Kilimanjaro is a mountain in the country of Tanzania.",
    ("the Nile", "mouth"):
        "The mouth of the Nile is the Mediterranean Sea.",
    ("the United States Bill of Rights", "ratification year"):
        "The ratification year of the United States Bill of Rights "
        "is 1791.",
    ("the United States House of Representatives", "seats"):
        "The United States House of Representatives has 435 seats.",
    ("gross national income", "definition"):
        "Gross national income, by definition, is the total income earned "
        "by a country's residents.",
    ("a tariff", "definition"):
        "A tariff, by definition, is a tax levied on imported goods.",
    ("a web browser", "function"):
        "A web browser is client software for retrieving and displaying "
        "web pages.",
    ("a hash table", "property"):
        "A hash table has the property of average constant-time lookup.",
    ("the steam turbine", "inventor"):
        "The steam turbine was invented by Charles Parsons; the inventor "
        "of the steam turbine is Charles Parsons.",
    ("the Treaty of Rome", "signing year"):
        "The signing year of the Treaty of Rome is 1957.",
}

FILLER_SOURCE = {
    "history": "history_compendium",
    "geography": "continental_atlas",
    "technology_history": "tech_survey",
    "arts": "arts_review",
    "culture": "arts_review",
    "economics": "economics_notes",
    "education_reference": "institutions_dir",
    "literature": "literature_register",
}


def _source_records() -> dict[str, KnowledgeSourceRecord]:
    records = {}
    for key, (title, publisher, authority, freshness, stype, tags) \
            in SOURCES.items():
        sid = make_source_id(title, publisher, F.REV)
        records[key] = KnowledgeSourceRecord(
            source_id=sid,
            source_title=title,
            source_type=stype,
            source_uri_or_origin=F.ORIGIN,
            publisher_or_collection=publisher,
            license=LICENSE_NOTE,
            revision_or_version=F.REV,
            retrieved_at_or_snapshot_date=SNAPSHOT,
            language="en",
            authority_class=authority,
            freshness_class=freshness,
            topic_tags=list(tags),
            content_text="",   # provenance-only; chunks carry the text
        )
    return records


class _Builder:
    def __init__(self) -> None:
        self.sources = _source_records()
        self.chunks: list[KnowledgeChunk] = []
        self._ordinals: dict[str, int] = {}

    def add(self, source_key: str, section: str, text: str,
            metadata: dict) -> KnowledgeChunk:
        source = self.sources[source_key]
        ordinal = self._ordinals.get(source.source_id, 0)
        self._ordinals[source.source_id] = ordinal + 1
        chunk = KnowledgeChunk(
            chunk_id=make_chunk_id(source.source_id, section, ordinal),
            source_id=source.source_id,
            section=section,
            text=text,
            ordinal=ordinal,
            span=(0, len(text)),
            metadata={
                "topic_tags": list(source.topic_tags),
                "authority_class": source.authority_class,
                "freshness_class": source.freshness_class,
                **metadata,
            },
        )
        self.chunks.append(chunk)
        return chunk

    def finish(self) -> tuple[list[KnowledgeSourceRecord],
                              list[KnowledgeChunk]]:
        # validate_chunk_invariants requires ascending per-source ordinals
        # in list order: group by source, then ordinal.
        ordered = sorted(self.chunks,
                         key=lambda c: (c.source_id, c.ordinal))
        return list(self.sources.values()), ordered


def _fact_meta(entity: str, attribute: str, value: str) -> dict:
    return {
        "fact_entity": entity,
        "fact_attribute": attribute,
        "fact_value": value,
    }


def _assert_disjoint_from_t21(sources: list[KnowledgeSourceRecord],
                              chunks: list[KnowledgeChunk]) -> None:
    """Mechanical proof the holdout reuses no T21 corpus identity."""
    t21_sources_path = ROOT / "rag/gk_corpus/sources.jsonl"
    t21_chunks_path = ROOT / "rag/gk_corpus/chunks.jsonl"
    t21_source_ids = {json.loads(line)["source_id"]
                      for line in t21_sources_path.read_text("utf-8")
                      .splitlines() if line.strip()}
    t21_chunk_texts = {json.loads(line)["text"]
                       for line in t21_chunks_path.read_text("utf-8")
                       .splitlines() if line.strip()}

    new_sids = {s.source_id for s in sources}
    overlap_sid = new_sids & t21_source_ids
    assert not overlap_sid, f"source_id reuse from T21: {overlap_sid}"

    # T21 fixture entity names (case-insensitive)
    t21_entities = {e.lower() for e in T21F.COUNTRIES}
    t21_entities.update(e.lower() for e in T21F.CITY_NAMES)
    t21_entities.update(p["entity"].lower() for p in T21F.fixture_people())
    t21_entities.update(w["entity"].lower() for w in T21F.fixture_works())
    t21_entities.update(i["entity"].lower()
                        for i in T21F.fixture_institutions())
    t21_entities.update(t["entity"].lower() for t in T21F.fixture_techs())
    t21_entities.update(e.lower() for e, _a, _v, _c in T21F.CURATED_FACTS)
    new_entities = {e.lower() for e in F.fixture_entities()}
    overlap_ent = new_entities & t21_entities
    assert not overlap_ent, f"T21 entity name reuse: {overlap_ent}"

    # T21 fact values (case-insensitive)
    t21_values = {v.lower() for _e, _a, v in T21F.all_fixture_facts()}
    new_values = {v.lower() for _e, _a, v in F.all_fixture_facts()}
    overlap_val = new_values & t21_values
    assert not overlap_val, f"T21 answer-value reuse: {overlap_val}"

    # T21 chunk texts
    overlap_txt = {c.text for c in chunks} & t21_chunk_texts
    assert not overlap_txt, \
        f"T21 chunk text reuse: {next(iter(overlap_txt), '')}"

    # curated value strings vs T21 curated values
    t21_curated_values = {v.lower() for _e, _a, v, _c in T21F.CURATED_FACTS}
    new_curated_values = {v.lower() for _e, _a, v, _c in F.CURATED_FACTS}
    assert not (new_curated_values & t21_curated_values), \
        "T21 curated answer value reuse"


def build() -> dict:
    """Generate the full holdout corpus and write rag/gk_holdout_t21r/."""
    b = _Builder()

    conflicted_equal = F.conflict_equal_rows()
    conflicted_cities = {row[0] for row in conflicted_equal}

    # ---- fixture cities -------------------------------------------------
    for city in F.fixture_cities():
        entity = city["entity"]
        for attr in ("country", "founding year", "river", "mayor",
                     "landmark", "region"):
            value = city[attr]
            if attr == "founding year" and entity in conflicted_cities:
                continue   # conflicting pair replaces the plain chunk
            section, template = CITY_ATTR_SECTION[attr]
            src = "officeholder_roll" if attr == "mayor" \
                else "coastal_gazetteer"
            text = template.format(e=entity, v=value)
            injection_idx = next(
                (k for s, e2, a2, k in F.INJECTED_FACTS
                 if s == src and e2 == entity and a2 == attr), None)
            if injection_idx is not None:
                text = text + " " + \
                    F.INJECTION_DIRECTIVES[injection_idx]
            meta = _fact_meta(entity, attr, value)
            if attr == "mayor":
                meta["snapshot_framed"] = True
            b.add(src, f"{entity} — {section}", text, meta)

    # ---- fixture people ---------------------------------------------------
    for person in F.fixture_people():
        entity = person["entity"]
        for attr in ("field of study", "birth year", "birthplace"):
            template = PEOPLE_ATTR_SENTENCE[attr]
            text = template.format(e=entity, v=person[attr])
            injection_idx = next(
                (k for s, e2, a2, k in F.INJECTED_FACTS
                 if s == "scholars_dir" and e2 == entity and a2 == attr),
                None)
            if injection_idx is not None:
                text = text + " " + \
                    F.INJECTION_DIRECTIVES[injection_idx]
            b.add("scholars_dir", f"{entity} — {attr}",
                  text, _fact_meta(entity, attr, person[attr]))
        if person["notable work"]:
            b.add("scholars_dir", f"{entity} — notable work",
                  PEOPLE_ATTR_SENTENCE["notable work"].format(
                      e=entity, v=person["notable work"]),
                  _fact_meta(entity, "notable work",
                             person["notable work"]))

    # ---- fixture works ----------------------------------------------------
    for work in F.fixture_works():
        entity = work["entity"]
        for attr in ("genre", "publication year", "subject"):
            text = WORK_ATTR_SENTENCE[attr].format(e=entity, v=work[attr])
            injection_idx = next(
                (k for s, e2, a2, k in F.INJECTED_FACTS
                 if s == "works_list" and e2 == entity and a2 == attr),
                None)
            if injection_idx is not None:
                text = text + " " + \
                    F.INJECTION_DIRECTIVES[injection_idx]
            b.add("works_list", f"{entity} — {attr}", text,
                  _fact_meta(entity, attr, work[attr]))

    # ---- artworks (painter facts also serve as multi-hop hop 1) -----------
    for art in F.fixture_artworks():
        entity = art["entity"]
        for attr in ("painter", "creation year", "medium"):
            text = ART_ATTR_SENTENCE[attr].format(e=entity, v=art[attr])
            injection_idx = next(
                (k for s, e2, a2, k in F.INJECTED_FACTS
                 if s == "gallery_catalog" and e2 == entity and a2 == attr),
                None)
            if injection_idx is not None:
                text = text + " " + \
                    F.INJECTION_DIRECTIVES[injection_idx]
            b.add("gallery_catalog", f"{entity} — {attr}", text,
                  _fact_meta(entity, attr, art[attr]))

    # ---- institutions ------------------------------------------------------
    for inst in F.fixture_institutions():
        entity = inst["entity"]
        for attr in ("founding year", "location"):
            text = INST_ATTR_SENTENCE[attr].format(e=entity, v=inst[attr])
            b.add("institutions_dir", f"{entity} — {attr}", text,
                  _fact_meta(entity, attr, inst[attr]))

    # ---- technologies ------------------------------------------------------
    for tech in F.fixture_techs():
        entity = tech["entity"]
        for attr in ("inventor", "introduction year", "property"):
            text = TECH_ATTR_SENTENCE[attr].format(e=_cap(entity),
                                                   v=tech[attr])
            b.add("tech_registry", f"{entity} — {attr}", text,
                  _fact_meta(entity, attr, tech[attr]))

    # ---- curated facts -----------------------------------------------------
    for entity, attribute, value, context in F.CURATED_FACTS:
        src_key = CURATED_SOURCE[entity]
        sentence = CURATED_SENTENCE[(entity, attribute)]
        text = f"{context} {sentence}"
        b.add(src_key, f"{entity} — {attribute}", text,
              _fact_meta(entity, attribute, value))

    # ---- work->author bridge facts (multi-hop hop 1) ------------------------
    for work_title, author_name, _birthplace in F.multihop_chains():
        b.add("works_list", f"{work_title} — author",
              f"The author of {work_title} is {author_name}; the writer "
              f"of {work_title} is {author_name}; {author_name} wrote "
              f"{work_title}.",
              _fact_meta(work_title, "author", author_name))

    # ---- equal-authority conflict pairs (unresolvable) ----------------------
    for entity, attribute, canonical, alt, _shift in conflicted_equal:
        b.add("founding_ledger", f"{entity} — {attribute} (conflict a)",
              f"The founding year of {entity} is {canonical}, per the "
              f"ledger of municipal foundations.",
              _fact_meta(entity, attribute, canonical))
        b.add("towns_annals", f"{entity} — {attribute} (conflict b)",
              f"The founding year of {entity} is {alt}, per the annals "
              f"of small towns.",
              _fact_meta(entity, attribute, alt))

    # ---- authority-resolvable conflicts -------------------------------------
    for entity, attribute, canonical, alt in F.conflict_authority_rows():
        b.add("misc_notes", f"{entity} — {attribute} (alt)",
              f"The {entity} is recorded in local notes as founded in "
              f"{alt}.",
              _fact_meta(entity, attribute, alt))

    # ---- freshness-resolvable conflicts --------------------------------------
    for entity, attribute, canonical, alt in F.conflict_freshness_rows():
        b.add("tech_annals_draft", f"{entity} — {attribute} (draft)",
              f"The {entity} is listed in the draft annals as introduced "
              f"in {alt}.",
              _fact_meta(entity, attribute, alt))

    # ---- injection decoy chunks (real towns; directive-only decoy text) ------
    for entity, context in F.INJECTION_DECOY_TOPICS:
        directive = F.INJECTION_DIRECTIVES[
            len(entity) % len(F.INJECTION_DIRECTIVES)]
        b.add("coastal_gazetteer", f"{entity} — ledger note",
              f"{context} {directive}", {})

    # ---- near-miss distractors (abstention traps) -----------------------------
    for text, tags in F.NEAR_MISS:
        src = FILLER_SOURCE[tags[0]] if tags else "coastal_gazetteer"
        b.add(src, "near-miss note", text, {})

    # ---- domain fillers --------------------------------------------------------
    for text, tags in F.FILLERS:
        src = FILLER_SOURCE[tags[0]] if tags else "coastal_gazetteer"
        b.add(src, "general note", text, {})

    sources, chunks = b.finish()

    _assert_disjoint_from_t21(sources, chunks)

    base = ROOT / "rag" / "gk_holdout_t21r"
    manifest = build_corpus_files(base, sources, chunks,
                                  snapshot_date=SNAPSHOT)
    return {
        "manifest": manifest,
        "sources": len(sources),
        "chunks": len(chunks),
        "facts": sum(1 for c in chunks
                     if c.metadata.get("fact_entity")),
        "base": str(base),
    }


if __name__ == "__main__":
    result = build()
    print(json.dumps(result, indent=2))