"""T21R3.7 — render the blind holdout corpus at rag/gk_holdout_t21r3/.

Consumes the structured world (rag/gk_holdout_t21r3/world.jsonl, built by
scripts/t21r3_world.py) and renders it into the exact runtime corpus
schema: sources.jsonl, chunks.jsonl, corpus_manifest.json.

BLIND-CONSTRUCTION RULE: this script does NOT import any
sciencemath.knowledge module. The runtime schema (source ids, chunk ids,
checksums, manifest format) is reimplemented here as pure data functions
and cross-checked against the frozen runtime schema by the static audit
and by tests/test_t21r3_blind_holdout_contract.py. The renderer may know
facts, entities, conflicts, sources, and sentence templates; it must not
execute, import, or probe the Mango runtime.

Sentence templates are written so that every fact chunk embeds the
attribute noun and the value, mirroring the vocabulary the gold queries
use (verified statically by scripts/t21r3_static_gold_audit.py against a
local reimplementation of the tokenizer's coverage arithmetic).

Usage: python scripts/t21r3_render_corpus.py
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import t21r3_world as W

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "rag" / "gk_holdout_t21r3"

LICENSE = "CC0-1.0 (project fixture; T21R3 blind holdout corpus; " \
          "evaluation only, not training material)"

# ---------------------------------------------------------------------------
# Local reimplementation of the frozen runtime schema (NO runtime import).
# Must stay byte-compatible with src/sciencemath/knowledge/schema.py and
# corpus.py; tests/test_t21r3_blind_holdout_contract.py cross-checks the
# hash functions against the runtime definitions on T21 fixture data.
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")
    return slug or "section"


def make_source_id(title: str, publisher: str, revision: str) -> str:
    key = f"{title}|{publisher}|{revision}"
    return "gk-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def make_chunk_id(source_id: str, section: str, ordinal: int) -> str:
    return f"{source_id}:{_slug(section)}:{ordinal}"


def _source_record_hash(row: dict) -> str:
    blob = json.dumps({
        "source_id": row["source_id"],
        "source_title": row["source_title"],
        "publisher_or_collection": row["publisher_or_collection"],
        "revision_or_version": row["revision_or_version"],
        "text": row.get("content_text", ""),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _sha256_lf(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()

# ---------------------------------------------------------------------------


def _source_records() -> dict[str, dict]:
    rows = {}
    for key, (title, publisher, authority, freshness, stype, tags) \
            in W.SOURCES.items():
        row = {
            "source_id": make_source_id(title, publisher, W.REV),
            "source_title": title,
            "source_type": stype,
            "source_uri_or_origin": W.ORIGIN,
            "publisher_or_collection": publisher,
            "license": LICENSE,
            "revision_or_version": W.REV,
            "retrieved_at_or_snapshot_date": W.SNAPSHOT_DATE,
            "language": "en",
            "authority_class": authority,
            "freshness_class": freshness,
            "topic_tags": list(tags),
            "content_hash": "",
            "document_hash": "",
        }
        # provenance-only source rows: chunks carry the text (content_text
        # stays empty, exactly as in the T21/T21R corpora)
        row["content_hash"] = _source_record_hash(row)
        row["document_hash"] = row["content_hash"]
        rows[key] = row
    return rows


class _Builder:
    """Ordered per-source chunk accumulator (asc ordinals in list order)."""

    def __init__(self, sources: dict[str, dict]) -> None:
        self.sources = sources
        self.chunks: list[dict] = []
        self._ordinals: dict[str, int] = {}

    def add(self, source_key: str, section: str, text: str,
            metadata: dict) -> dict:
        source = self.sources[source_key]
        ordinal = self._ordinals.get(source["source_id"], 0)
        self._ordinals[source["source_id"]] = ordinal + 1
        self.chunks.append({
            "chunk_id": make_chunk_id(source["source_id"], section, ordinal),
            "source_id": source["source_id"],
            "section": section,
            "text": text,
            "ordinal": ordinal,
            "span": [0, len(text)],
            "metadata": {
                "topic_tags": list(source["topic_tags"]),
                "authority_class": source["authority_class"],
                "freshness_class": source["freshness_class"],
                **metadata,
            },
            "content_hash": _sha256(text),
        })
        return self.chunks[-1]

    def finish(self) -> tuple[list[dict], list[dict]]:
        ordered = sorted(self.chunks,
                         key=lambda c: (c["source_id"], c["ordinal"]))
        return list(self.sources.values()), ordered


def _fact_meta(entity: str, attribute: str, value: str) -> dict:
    return {"fact_entity": entity, "fact_attribute": attribute,
            "fact_value": value}


# ---------------------------------------------------------------------------
# Chunk sentence templates (NEW phrasings, vocabulary-mirrored)
# ---------------------------------------------------------------------------

TOWN_ATTR_SECTION = {
    "nation": ("Geography",
               "The nation of the town of {e} is {v}; {e} lies within {v}."),
    "waterway": ("Geography",
                 "The waterway that flows past the town of {e} is {v}; "
                 "{e} stands on {v}."),
    "mayor": ("Government",
              "The June 2026 officeholder register records the mayor of "
              "{e} as {v}."),
    "emblem": ("Culture",
               "The emblem of the town of {e} is {v}."),
    "province": ("Geography",
                 "The province of the town of {e} is {v}; {e} lies in {v}."),
    "established year": ("History",
                         "The town of {e} was established in {v}; the "
                         "established year of {e} is {v}."),
}

TOWN_ATTR_SOURCE = {
    "nation": "realms_gazetteer",
    "waterway": "realms_gazetteer",
    "mayor": "officeholders_register",
    "emblem": "realms_gazetteer",
    "province": "realms_gazetteer",
    "established year": "establishments_register",
}

PEOPLE_ATTR_SENTENCE = {
    "field of study":
        "The field of study of the scholar {e} was {v}.",
    "birth year":
        "The birth year of the scholar {e} is {v}; {e} was born in {v}.",
    "birthplace":
        "The scholar {e} was born in the town of {v}; the birthplace of "
        "{e} is {v}.",
}

WORK_ATTR_SENTENCE = {
    "genre":
        "The genre of the work {e} is {v}; {e} is classified as a {v}.",
    "publication year":
        "The work {e} was published in {v}; the publication year of "
        "{e} is {v}.",
    "subject":
        "The subject of the work {e} is {v}.",
}

AUTHOR_SENTENCE = ("The author of the work {e} is {v}; the writer of "
                   "{e} is {v}; {v} wrote {e}.")

ART_ATTR_SENTENCE = {
    "painter":
        "The painter of the painting {e} is {v}; {e} was painted by {v}.",
    "creation year":
        "The painting {e} was created in {v}; the creation year of "
        "{e} is {v}.",
    "medium":
        "The medium of the painting {e} is {v}.",
}

INST_ATTR_SENTENCE = {
    "established year":
        "The institution {e} was established in {v}; the established "
        "year of the institution {e} is {v}.",
    "location":
        "The institution {e} is located in the town of {v}; the location "
        "of {e} is {v}.",
}

TECH_ATTR_SENTENCE = {
    "inventor":
        "{E} was invented by {v}; the inventor of {e} is {v}.",
    "introduction year":
        "{E} was introduced in {v}; the introduction year of "
        "{e} is {v}.",
    "property":
        "{E} is known for {v}; the notable property of {e} is {v}.",
}

CAPITAL_SENTENCE = ("The capital of {n} is the town of {t}; the town of "
                    "{t} serves as the capital of {n}.")

# Curated fact sentences: (entity, predicate) -> sentence.
CURATED_SENTENCE = {
    ("the Erie Canal", "opening year"):
        "The opening year of the Erie Canal is 1825; the Erie Canal "
        "opened in 1825.",
    ("the Colosseum", "location"):
        "The Colosseum stands at the location of Rome; the location of "
        "the Colosseum is Rome.",
    ("the Chrysler Building", "location"):
        "The Chrysler Building stands at the location of New York City; "
        "the location of the Chrysler Building is New York City.",
    ("Petra", "country"):
        "Petra is in the country of Jordan; the country of Petra is "
        "Jordan.",
    ("the Murray River", "mouth"):
        "The mouth of the Murray River is the Southern Ocean.",
    ("the Hagia Sophia", "location"):
        "The Hagia Sophia stands at the location of Istanbul; the "
        "location of the Hagia Sophia is Istanbul.",
    ("the Wright Flyer", "maker"):
        "The maker of the Wright Flyer is the Wright brothers.",
    ("the telegraph", "inventor"):
        "The inventor of the telegraph is Samuel Morse; the telegraph "
        "was invented by Samuel Morse.",
    ("the Kremlin", "location"):
        "The Kremlin stands at the location of Moscow; the location of "
        "the Kremlin is Moscow.",
    ("the Gobi Desert", "continent"):
        "The Gobi Desert is a desert on the continent of Asia; the "
        "continent of the Gobi Desert is Asia.",
    ("the Mississippi River", "mouth"):
        "The mouth of the Mississippi River is the Gulf of Mexico.",
    ("a trade deficit", "definition"):
        "A trade deficit, by definition, is the amount by which a "
        "country's imports exceed its exports.",
    ("an operating system", "function"):
        "An operating system has the function of managing hardware and "
        "software resources.",
    ("a statute", "purpose"):
        "A statute has the purpose of being a written law passed by a "
        "legislature.",
    ("condensation", "definition"):
        "Condensation, by definition, is the change of a vapor into a "
        "liquid.",
    ("the imperial system", "property"):
        "The imperial system has the property of customary units not "
        "built on powers of ten.",
}

SLOW_GEO_SENTENCE = {
    ("Mount Fuji", "country"):
        "Mount Fuji is a mountain in the country of Japan; the country "
        "of Mount Fuji is Japan.",
    ("the Mekong", "mouth"):
        "The mouth of the Mekong is the South China Sea.",
    ("the Rockies", "continent"):
        "The Rockies are a mountain range on the continent of North "
        "America.",
    ("the Seine", "mouth"):
        "The mouth of the Seine is the English Channel.",
    ("the Himalayas", "continent"):
        "The Himalayas are a mountain range on the continent of Asia.",
    ("the Niger River", "mouth"):
        "The mouth of the Niger River is the Gulf of Guinea.",
}


def _cap_words(text: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in text.split())


# Near-duplicate false-conflict pairs: the SAME fact restated almost
# verbatim in a second source. Values are identical, so the conflict
# detector must not fire; the deduplicator merges the near-identical
# chunks and the answer proceeds normally.
NEAR_DUP_PAIRS = [
    ("realms_gazetteer", "traditions_annals", "emblem",
     ["Ambervale", "Kingsmoss", "Elderbrook", "Nettleford"]),
    ("realms_gazetteer", "traditions_annals", "province",
     ["Barrowfen", "Mistelbrook", "Marblethorpe", "Umbermill"]),
    ("works_register", "traditions_annals", "genre",
     ["The Bergamot and the Illwater", "The Mirlow of the Cassia",
      "The Dromond and the Kittiwake", "The Loamshire of the Elmbright"]),
    ("paintings_catalogue", "traditions_annals", "medium",
     ["Portrait of Dilys", "Portrait of Fennimore", "Portrait of Grosvenor",
      "Portrait of Halyard"]),
    # T21R3 restatement extension: same entity + same attribute + same
    # normalized fact_value, different wording, across >= 8 domains.
    ("realms_gazetteer", "realms_atlas", "waterway",
     ["Ambervale", "Duskmoor", "Fernhollow", "Nimblewick"]),
    ("officeholders_register", "traditions_annals", "mayor",
     ["Emberlane", "Grimswell", "Pennyford", "Wispford"]),
    ("establishments_register", "antiquarian_notes", "established year",
     ["Cloverfield", "Dockwell", "Ospreymoor", "Aldermoor"]),
    ("scholars_directory", "traditions_annals", "field of study",
     ["Aldous Abernathy", "Damaris Ravenhurst", "Fenella Blackbriar",
      "Hyacinth Oakeshott"]),
    ("scholars_directory", "antiquarian_notes", "birthplace",
     ["Corwin Abernathy", "Eldric Ravenhurst", "Fenella Fairweather",
      "Sibella Falworth"]),
    ("works_register", "antiquarian_notes", "publication year",
     ["The Fandangle and the Mizzle", "The Nimbus of the Galewood",
      "The Hartshorn and the Murnby", "The Pennant of the Illwater"]),
    ("paintings_catalogue", "antiquarian_notes", "painter",
     ["Portrait of Imbrex", "Portrait of Jasmine", "Portrait of Kenilworth",
      "Portrait of Lumley"]),
    ("institutions_directory", "stable_reference_compendium", "location",
     ["Bergamot Lyceum", "Elmbright Athenaeum", "Hartshorn Conservatoire",
      "Kittiwake Observatory"]),
    ("inventions_registry", "technical_draft_register", "property",
     ["the Vantrell orrery", "the Quinmark theodolite",
      "the Ostrellan planimeter", "the Hexbridge dynamo"]),
]

NEAR_DUP_TEMPLATE = {
    "emblem": "The emblem of the town of {e} is {v}.",
    "province": "The province of the town of {e} is {v}; {e} lies in {v}.",
    "genre": "The genre of the work {e} is {v}.",
    "medium": "The medium of the painting {e} is {v}.",
    "waterway": "The waterway of the town of {e} is {v}.",
    "mayor": "The mayor of the town of {e} is {v}.",
    "established year": "The town of {e} was established in {v}.",
    "field of study": "The field of study of the scholar {e} is {v}.",
    "birthplace": "The birthplace of the scholar {e} is {v}.",
    "publication year": "The work {e} was published in {v}.",
    "painter": "The painting {e} was painted by {v}.",
    "location": "The institution {e} is located in the town of {v}.",
    "property": "The device {e} is known for {v}.",
}

# Same-name-family non-conflict distractor notes (never conflicting values).
NAME_FAMILY_NOTES = [
    "The scholars of the Abernathy family appear in several town registers "
    "of the Nine Wolds.",
    "The scholars of the Ravenhurst family appear in several town registers "
    "of the Nine Wolds.",
    "The register lists several scholars who share the first name Fenella.",
    "The register lists several scholars who share the first name Aldous.",
]


def build() -> dict:
    W.assert_disjoint()
    b = _Builder(_source_records())

    conflicted_equal = {r["entity"]: r for r in W.CONFLICTS
                        if r["class"] == "EQUAL_AUTHORITY_UNRESOLVED"}
    conflict_alt_sources = {r["alt_source"] for r in W.CONFLICTS}

    # ---- towns -----------------------------------------------------------
    town_fact = {}
    for fact in _world_facts().values():
        town_fact[(fact["subject"], fact["predicate"])] = fact
    for i, town in enumerate(W.TOWNS):
        for attr, (section, template) in TOWN_ATTR_SECTION.items():
            if attr == "established year" and town in conflicted_equal:
                continue   # conflict pair replaces the plain chunk
            fact = town_fact.get((town, attr))
            if fact is None:
                continue
            value = fact["object"]
            src = TOWN_ATTR_SOURCE[attr]
            text = template.format(e=town, v=value)
            text = _with_injection(src, town, attr, text)
            meta = _fact_meta(town, attr, value)
            if attr == "mayor":
                meta["snapshot_framed"] = True
            b.add(src, f"{town} — {section}", text, meta)

    # ---- nation capitals --------------------------------------------------
    for k, idx in enumerate(W.CAPITAL_TOWN_INDICES):
        nation = W.NATIONS[k]
        town = W.TOWNS[idx]
        b.add("nations_capitals_atlas", f"{nation} — capital",
              CAPITAL_SENTENCE.format(n=nation, t=town),
              _fact_meta(nation, "capital", town))

    # ---- people -----------------------------------------------------------
    for person in W.PEOPLE:
        for attr, template in PEOPLE_ATTR_SENTENCE.items():
            text = template.format(e=person["entity"], v=person[attr])
            text = _with_injection("scholars_directory",
                                   person["entity"], attr, text)
            b.add("scholars_directory", f"{person['entity']} — {attr}",
                  text, _fact_meta(person["entity"], attr, person[attr]))

    # ---- works (facts + author relations) ------------------------------------
    for work in W.WORKS:
        title = work["entity"]
        register = work["register"]
        for attr, template in WORK_ATTR_SENTENCE.items():
            text = template.format(e=title, v=work[attr])
            src = register
            text = _with_injection(src, title, attr, text)
            b.add(src, f"{title} — {attr}", text,
                  _fact_meta(title, attr, work[attr]))
    for title, author in W.author_pairs():
        register = W.work_register(title)
        b.add(register, f"{title} — author",
              AUTHOR_SENTENCE.format(e=title, v=author),
              _fact_meta(title, "author", author))

    # ---- artworks ----------------------------------------------------------
    for art in W.ARTWORKS:
        for attr, template in ART_ATTR_SENTENCE.items():
            text = template.format(e=art["entity"], v=art[attr])
            text = _with_injection("paintings_catalogue",
                                   art["entity"], attr, text)
            b.add("paintings_catalogue", f"{art['entity']} — {attr}",
                  text, _fact_meta(art["entity"], attr, art[attr]))

    # ---- institutions (facts + authority-conflict alts) ----------------------
    for inst in W.INSTITUTIONS:
        for attr, template in INST_ATTR_SENTENCE.items():
            b.add("institutions_directory", f"{inst['entity']} — {attr}",
                  template.format(e=inst["entity"], v=inst[attr]),
                  _fact_meta(inst["entity"], attr, inst[attr]))

    # ---- technologies (facts + freshness-conflict alts) ------------------------
    for tech in W.TECHS:
        for attr, template in TECH_ATTR_SENTENCE.items():
            text = template.format(e=tech["entity"], v=tech[attr],
                                   E=_cap_words(tech["entity"]))
            text = _with_injection("inventions_registry",
                                   tech["entity"], attr, text)
            b.add("inventions_registry", f"{tech['entity']} — {attr}",
                  text, _fact_meta(tech["entity"], attr, tech[attr]))

    # ---- curated facts ------------------------------------------------------
    for entity, predicate, value, desc, domain, tag in W.CURATED_FACTS:
        sentence = CURATED_SENTENCE[(entity, predicate)]
        text = f"{desc} {sentence}"
        b.add("stable_reference_compendium", f"{entity} — {predicate}",
              text, _fact_meta(entity, predicate, value))

    # ---- slow-changing reference facts ------------------------------------------
    for entity, predicate, value, desc, domain in W.SLOW_GEOGRAPHY_FACTS:
        sentence = SLOW_GEO_SENTENCE[(entity, predicate)]
        text = f"{desc} {sentence}"
        b.add("nations_capitals_atlas", f"{entity} — {predicate}",
              text, _fact_meta(entity, predicate, value))

    # ---- conflicts -------------------------------------------------------------
    for conflict in W.CONFLICTS:
        entity = conflict["entity"]
        attr = conflict["predicate"]
        if conflict["class"] == "EQUAL_AUTHORITY_UNRESOLVED":
            canon = conflicted_equal[entity]
            canon_text = _with_injection(
                canon["canonical_source"], entity, attr,
                f"The established year of {entity} is "
                f"{canon['canonical_value']}, per the Register of "
                f"Municipal Establishments.")
            b.add(canon["canonical_source"],
                  f"{entity} — {attr} (conflict a)",
                  canon_text,
                  _fact_meta(entity, attr, canon["canonical_value"]))
            b.add(canon["alt_source"], f"{entity} — {attr} (conflict b)",
                  f"The established year of {entity} is "
                  f"{canon['alt_value']}, per the Roll of Foundation "
                  f"Records.",
                  _fact_meta(entity, attr, canon["alt_value"]))
        elif conflict["class"] == "AUTHORITY_RESOLVABLE":
            b.add(conflict["alt_source"], f"{entity} — {attr} (alt)",
                  f"The {entity} is recorded in the local antiquarian "
                  f"notes as established in {conflict['alt_value']}.",
                  _fact_meta(entity, attr, conflict["alt_value"]))
        elif conflict["class"] == "FRESHNESS_RESOLVABLE":
            b.add(conflict["alt_source"], f"{entity} — {attr} (draft)",
                  f"The draft register of technical change lists "
                  f"{entity} as introduced in "
                  f"{conflict['alt_value']}.",
                  _fact_meta(entity, attr, conflict["alt_value"]))

    # ---- near-duplicate false-conflict pairs --------------------------------
    for src_a, src_b, attr, entities in NEAR_DUP_PAIRS:
        for entity in entities:
            fact = _world_facts().get((entity, attr))
            value = fact["object"] if fact else None
            if value is None:
                raise SystemExit(f"near-dup fact missing: {entity} {attr}")
            template = NEAR_DUP_TEMPLATE[attr]
            base = template.format(e=entity, v=value)
            b.add(src_a, f"{entity} — {attr} (record)",
                  base, _fact_meta(entity, attr, value))
            restated = _restate(attr, template.format(e=entity, v=value))
            b.add(src_b, f"{entity} — {attr} (restated)",
                  restated, _fact_meta(entity, attr, value))

    # ---- injection decoy chunks -------------------------------------------------
    for entity, context in W.INJECTION_DECOY_TOPICS:
        directive = W.INJECTION_DIRECTIVES[
            len(entity) % len(W.INJECTION_DIRECTIVES)]
        b.add("realms_gazetteer", f"{entity} — ledger note",
              f"{context} {directive}", {})

    # ---- near-miss distractors (abstention traps) ---------------------------------
    for text in W.NEAR_MISS_CHUNKS:
        b.add("traditions_annals", "near-miss note", text, {})

    # ---- name-family non-conflict notes -------------------------------------------
    for text in NAME_FAMILY_NOTES:
        b.add("scholars_directory", "register note", text, {})

    # ---- domain fillers -------------------------------------------------------------
    filler_source = {
        "history": "traditions_annals",
        "geography": "realms_atlas",
        "technology_history": "inventions_registry",
        "arts": "paintings_catalogue",
        "culture": "realms_gazetteer",
        "economics": "stable_reference_compendium",
        "education_reference": "institutions_directory",
        "literature": "works_register",
    }
    for text, tags in W.FILLERS:
        b.add(filler_source[tags[0]], "general note", text, {})

    sources, chunks = b.finish()

    _assert_disjoint(sources, chunks)
    _validate_invariants(sources, chunks)

    _write_corpus(BASE, sources, chunks, W.SNAPSHOT_DATE)
    return {
        "sources": len(sources),
        "chunks": len(chunks),
        "facts": sum(1 for c in chunks
                     if c["metadata"].get("fact_entity")),
        "conflict_chunks": sum(
            1 for c in chunks
            if any(m in c["section"]
                   for m in ("(conflict a)", "(conflict b)", "(alt)",
                             "(draft)"))),
    }


def _with_injection(source_key: str, entity: str, attr: str,
                    text: str) -> str:
    idx = next((k for s, e2, a2, k in W.INJECTED_FACTS
                if s == source_key and e2 == entity and a2 == attr), None)
    if idx is not None:
        text = text + " " + W.INJECTION_DIRECTIVES[idx]
    return text


def _restate(attr: str, sentence: str) -> str:
    """A near-verbatim restatement (4-gram Jaccard above the dedup floor)."""
    swaps = {
        "emblem": ("The emblem of the town of", "The town emblem of"),
        "province": ("The province of the town of", "The town province of"),
        "genre": ("The genre of the work", "The work genre of"),
        "medium": ("The medium of the painting", "The painting medium of"),
        "waterway": ("The waterway of the town of", "The town waterway of"),
        "mayor": ("The mayor of the town of", "The town mayor of"),
        "established year": ("was established in", "was founded in"),
        "field of study": ("The field of study of the scholar",
                           "The scholarly field of"),
        "birthplace": ("The birthplace of the scholar",
                       "The scholar birthplace of"),
        "publication year": ("was published in", "appeared in print in"),
        "painter": ("was painted by", "is by"),
        "location": ("is located in the town of", "is situated in"),
        "property": ("is known for", "is noted for"),
    }
    old, new = swaps[attr]
    restated = sentence.replace(old, new, 1)
    assert restated != sentence
    return restated


_WORLD_FACT_INDEX: dict[tuple[str, str], dict] | None = None


def _world_facts() -> dict[tuple[str, str], dict]:
    global _WORLD_FACT_INDEX
    if _WORLD_FACT_INDEX is None:
        _WORLD_FACT_INDEX = {}
        for line in (BASE / "world.jsonl").read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec["type"] == "WorldFact":
                _WORLD_FACT_INDEX[(rec["subject"], rec["predicate"])] = rec
    return _WORLD_FACT_INDEX


def _lookup_fact(entity: str, attr: str) -> dict | None:
    return _world_facts().get((entity, attr))


# ---------------------------------------------------------------------------
# Mechanical disjointness + structural invariants (data only)
# ---------------------------------------------------------------------------


def _assert_disjoint(sources: list[dict], chunks: list[dict]) -> None:
    old_source_ids: set[str] = set()
    old_chunk_texts: set[str] = set()
    for rel in ("rag/gk_corpus", "rag/gk_holdout_t21r"):
        base = ROOT / rel
        for line in (base / "sources.jsonl").read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                old_source_ids.add(json.loads(line)["source_id"])
        for line in (base / "chunks.jsonl").read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                old_chunk_texts.add(json.loads(line)["text"])
    overlap_sid = {s["source_id"] for s in sources} & old_source_ids
    assert not overlap_sid, f"source_id reuse: {overlap_sid}"
    overlap_txt = {c["text"] for c in chunks} & old_chunk_texts
    assert not overlap_txt, f"chunk text reuse: {len(overlap_txt)} rows"


def _validate_invariants(sources: list[dict], chunks: list[dict]) -> None:
    seen: set[str] = set()
    per_source: dict[str, list[int]] = {}
    for c in chunks:
        assert c["chunk_id"] not in seen, f"duplicate chunk_id {c['chunk_id']}"
        seen.add(c["chunk_id"])
        assert _sha256(c["text"]) == c["content_hash"], c["chunk_id"]
        per_source.setdefault(c["source_id"], []).append(c["ordinal"])
    for sid, ords in per_source.items():
        assert ords == sorted(ords), f"ordinals out of order for {sid}"
    for s in sources:
        assert s["source_id"].startswith("gk-")
        assert s["authority_class"] in (
            "PRIMARY_REFERENCE", "ENCYCLOPEDIC", "ACADEMIC_REFERENCE",
            "GOVERNMENT_PUBLICATION", "INSTITUTIONAL", "GENERAL_REFERENCE",
            "UNKNOWN")
        assert s["freshness_class"] in (
            "STATIC", "SLOW_CHANGING", "TIME_SENSITIVE", "UNKNOWN")
        assert _source_record_hash(s) == s["content_hash"]


def _write_corpus(base: Path, sources: list[dict], chunks: list[dict],
                  snapshot_date: str) -> None:
    base.mkdir(parents=True, exist_ok=True)

    def write_jsonl(path: Path, rows: list[dict]) -> None:
        text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False)
                       + "\n" for r in rows)
        path.write_text(text, encoding="utf-8", newline="\n")

    write_jsonl(base / "sources.jsonl", sources)
    write_jsonl(base / "chunks.jsonl", chunks)
    domains = sorted({tag for s in sources for tag in s["topic_tags"]})
    manifest = {
        "corpus_version": "mango-general-knowledge-corpus-v1",
        "snapshot_date": snapshot_date,
        "source_count": len(sources),
        "chunk_count": len(chunks),
        "domains": domains,
        "license_summary": {
            "project_owned_fixtures": len(sources),
            "notes": "Corpus is project-owned evaluation fixture material "
                     "(CC0-equivalent); retrieval-only, never used for "
                     "training; no third-party text ingested.",
        },
        "file_checksums": {
            "sources.jsonl": _sha256_lf(base / "sources.jsonl"),
            "chunks.jsonl": _sha256_lf(base / "chunks.jsonl"),
        },
    }
    blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    manifest["manifest_checksum"] = hashlib.sha256(
        blob.encode("utf-8")).hexdigest()
    (base / "corpus_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")


def main() -> int:
    result = build()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())