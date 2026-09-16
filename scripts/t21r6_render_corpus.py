"""T21R6 — render the blind holdout corpus at rag/gk_holdout_t21r6/.

Consumes the structured world (rag/gk_holdout_t21r6/world.jsonl, built by
scripts/t21r6_world.py) and renders it into the exact runtime corpus
schema: sources.jsonl, chunks.jsonl, corpus_manifest.json.

BLIND-CONSTRUCTION RULE: this script does NOT import any
sciencemath.knowledge module. The runtime schema (source ids, chunk ids,
checksums, manifest format) is reimplemented here as pure data functions
and cross-checked against the frozen runtime schema by the static audit
and by tests/test_t21r6_blind_holdout_contract.py. The renderer may know
facts, entities, conflicts, sources, and sentence templates; it must not
execute, import, or probe the Mango runtime.

Sentence templates are written so that every fact chunk embeds the
attribute noun and the value, mirroring the vocabulary the gold queries
use (verified statically by scripts/t21r6_static_gold_audit.py against a
local reimplementation of the tokenizer's coverage arithmetic).

Usage: python scripts/t21r5_render_corpus.py
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import t21r6_world as W

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "rag" / "gk_holdout_t21r6"

LICENSE = "CC0-1.0 (project fixture; T21R6 blind holdout corpus; " \
          "evaluation only, not training material)"

# ---------------------------------------------------------------------------
# Local reimplementation of the frozen runtime schema (NO runtime import).
# Must stay byte-compatible with src/sciencemath/knowledge/schema.py and
# corpus.py; tests/test_t21r6_blind_holdout_contract.py cross-checks the
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
               "In the Fellwold gazetteer, the nation containing {e} is "
               "{v}; {e} lies within the nation of {v}."),
    "waterway": ("Geography",
                 "{e} is a Fellwold town on the waterway {v}; the "
                 "waterway of {e} is {v}."),
    "mayor": ("Government",
              f"The {W.SNAPSHOT_MONTH} officeholder roll records"
              " {v} as the mayor of {e}."),
    "emblem": ("Culture",
               "{e} keeps {v} as its town emblem; the emblem of {e} is "
               "{v}."),
    "province": ("Geography",
                 "{e} sits in {v}, a Fellwold province; the province "
                 "containing {e} is {v}."),
    "established year": ("History",
                         "{e} was founded in {v}; the establishment year "
                         "of the town {e} is {v}."),
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
        "The scholars directory lists {v} as the field of study of "
        "{e}.",
    "birth year":
        "The birth year of the scholar {e} is {v}; {e} was born in "
        "{v}.",
    "birthplace":
        "The scholar {e} was born in {v}, a Fellwold town; the "
        "birthplace of {e} is {v}.",
}

WORK_ATTR_SENTENCE = {
    "genre":
        "The register lists the genre of the work {e} as {v}.",
    "publication year":
        "The publication year of the work {e} is {v}; {e} appeared in "
        "print in {v}.",
    "subject":
        "The work {e} deals with the subject of {v}.",
}

AUTHOR_SENTENCE = ("{e} is the work of {v}; the author of {e} is {v}.")

ART_ATTR_SENTENCE = {
    "painter":
        "{v} painted the study {e}; the painter of {e} is {v}.",
    "creation year":
        "The creation year of the painting {e} is {v}; the study {e} "
        "was finished in {v}.",
    "medium":
        "The painting {e} was executed in {v}; the medium of {e} is "
        "{v}.",
}

INST_ATTR_SENTENCE = {
    "established year":
        "The establishment year of the institution {e} is {v}; {e} was "
        "established in {v}.",
    "location":
        "The institution {e} stands in {v}; the location of {e} is "
        "{v}.",
}

TECH_ATTR_SENTENCE = {
    "inventor":
        "The inventor of {e} is {v}; credit for {E} belongs to {v}.",
    "introduction year":
        "The introduction year of {e} is {v}; {E} first saw working "
        "use in {v}.",
    "property":
        "The notable property of {e} is {v}; the device {e} features "
        "{v}.",
}

CAPITAL_SENTENCE = ("The Fellwold edition of the nations atlas gives "
                    "the capital of {n} as the town of {t}; {t} is the "
                    "capital city of {n}.")

# Curated fact sentences: (entity, predicate) -> sentence.
CURATED_SENTENCE = {
    ("the Welland Canal", "opening year"):
        "The Welland Canal recorded its opening year as 1932; the canal "
        "opened in 1932.",
    ("a fjord", "definition"):
        "A fjord, by definition, is a long narrow sea inlet with steep "
        "sides.",
    ("the wedge", "function"):
        "The wedge has the function of splitting material by a driven "
        "edge.",
    ("the screw", "function"):
        "The screw has the function of fastening by a helical thread.",
    ("a peninsula", "definition"):
        "A peninsula, by definition, is land nearly surrounded by "
        "water.",
    ("a delta", "definition"):
        "A delta, by definition, is sediment deposited at a river "
        "mouth.",
    ("an embargo", "purpose"):
        "An embargo has the purpose of a ban on trade with a country.",
    ("a writ", "purpose"):
        "A writ has the purpose of a formal written court order.",
    ("a deposition", "definition"):
        "A deposition, by definition, is out-of-court sworn testimony.",
    ("a molecule", "definition"):
        "A molecule, by definition, is two or more atoms bonded "
        "together.",
    ("a glacier", "definition"):
        "A glacier, by definition, is a persistent mass of land ice.",
    ("the barometer", "function"):
        "The barometer has the function of measuring atmospheric "
        "pressure.",
    ("the microscope", "function"):
        "The microscope has the function of magnifying tiny objects by "
        "a lens.",
    ("an atlas", "purpose"):
        "An atlas has the purpose of a bound collection of maps.",
    ("a referendum", "purpose"):
        "A referendum has the purpose of a direct public vote on an "
        "issue.",
    ("a strait", "definition"):
        "A strait, by definition, is a narrow waterway joining two "
        "seas.",
}

SLOW_GEO_SENTENCE = {
    ("the Ganges", "mouth"):
        "The mouth of the Ganges empties into the Bay of Bengal.",
    ("the Yangtze", "mouth"):
        "The mouth of the Yangtze empties into the East China Sea.",
    ("the Jordan", "mouth"):
        "The mouth of the Jordan empties into the Dead Sea.",
    ("the Columbia", "mouth"):
        "The mouth of the Columbia empties into the Pacific Ocean.",
    ("the Tigris", "mouth"):
        "The mouth of the Tigris empties into the Shatt al-Arab.",
    ("Mount Etna", "country"):
        "Mount Etna rises within the country of Italy; the country of "
        "Mount Etna is Italy.",
}


def _cap_words(text: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in text.split())


# Near-duplicate false-conflict pairs: the SAME fact restated almost
# verbatim in a second source. Values are identical, so the conflict
# detector must not fire; the deduplicator merges the near-identical
# chunks and the answer proceeds normally. Entity selections are
# deterministic slices of the T21R6 world pools (13 pairs x 4 entities
# = 52 restatement entities; the suite builder emits 2 query phrasings
# each -> 104 same-value restatement rows, above the preregistered
# minimum of 100). Established-year restatements use only clean towns
# (index >= 50, outside the 50 unresolved-conflict towns).
def _near_dup_pairs() -> list[tuple[str, str, str, list[str]]]:
    return [
        ("realms_gazetteer", "traditions_annals", "emblem",
         W.TOWNS[44:48]),
        ("realms_gazetteer", "traditions_annals", "province",
         W.TOWNS[48:52]),
        ("works_register", "traditions_annals", "genre",
         [w["entity"] for w in W.WORKS[0:4]]),
        ("paintings_catalogue", "traditions_annals", "medium",
         [a["entity"] for a in W.ARTWORKS[0:4]]),
        ("realms_gazetteer", "realms_atlas", "waterway",
         W.TOWNS[52:56]),
        ("officeholders_register", "traditions_annals", "mayor",
         W.TOWNS[56:60]),
        ("establishments_register", "antiquarian_notes",
         "established year", W.TOWNS[60:64]),
        ("scholars_directory", "traditions_annals", "field of study",
         [p["entity"] for p in W.PEOPLE[0:4]]),
        ("scholars_directory", "antiquarian_notes", "birthplace",
         [p["entity"] for p in W.PEOPLE[4:8]]),
        ("works_register", "antiquarian_notes", "publication year",
         [w["entity"] for w in W.WORKS[4:8]]),
        ("paintings_catalogue", "antiquarian_notes", "painter",
         [a["entity"] for a in W.ARTWORKS[4:8]]),
        ("institutions_directory", "stable_reference_compendium",
         "location", [i["entity"] for i in W.INSTITUTIONS[30:34]]),
        ("inventions_registry", "technical_draft_register", "property",
         [t["entity"] for t in W.TECHS[30:34]]),
    ]


NEAR_DUP_TEMPLATE = {
    "emblem": "The town emblem of {e} is {v}.",
    "province": "The province of {e} is {v}.",
    "genre": "The work {e} is classified as a {v}.",
    "medium": "The medium of the painting {e} is {v}.",
    "waterway": "The waterway beside the town of {e} is {v}.",
    "mayor": "The mayor of the town of {e} is {v}.",
    "established year": "The town of {e} was established in {v}.",
    "field of study": "The field of study of the scholar {e} is {v}.",
    "birthplace": "The birthplace of the scholar {e} is {v}.",
    "publication year": "The work {e} was published in {v}.",
    "painter": "The painting {e} was painted by {v}.",
    "location": "The institution {e} is located in the town of {v}.",
    "property": "The device {e} is known for {v}.",
}


def _name_family_notes() -> list[str]:
    """Non-conflict distractor notes for the same-surname and
    same-first-name scholar families of this world (derived
    deterministically from the built people table)."""
    surnames: dict[str, list[str]] = {}
    firsts: dict[str, list[str]] = {}
    for person in W.PEOPLE:
        first, surname = person["entity"].rsplit(" ", 1)
        surnames.setdefault(surname, []).append(first)
        firsts.setdefault(first, []).append(surname)
    notes = []
    for surname, names in surnames.items():
        if len(names) > 1:
            notes.append(
                f"The scholars of the {surname} family appear in several "
                "town registers of the Fellwold.")
    for first, family in firsts.items():
        if len(family) > 1:
            notes.append(
                f"The directory lists several scholars who share the "
                f"first name {first}.")
    return notes


def build() -> dict:
    W.assert_disjoint()
    b = _Builder(_source_records())

    conflicted_equal = {r["entity"]: r for r in W.CONFLICTS
                        if r["class"] == "EQUAL_AUTHORITY_UNRESOLVED"}

    # ---- towns -----------------------------------------------------------
    for i, town in enumerate(W.TOWNS):
        for attr, (section, template) in TOWN_ATTR_SECTION.items():
            if attr == "established year" and town in conflicted_equal:
                continue   # conflict pair replaces the plain chunk
            value = _town_fact(town, attr)
            if value is None:
                continue
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
            text = _with_injection(register, title, attr, text)
            b.add(register, f"{title} — {attr}", text,
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

    # ---- institutions ---------------------------------------------------------
    for inst in W.INSTITUTIONS:
        for attr, template in INST_ATTR_SENTENCE.items():
            b.add("institutions_directory", f"{inst['entity']} — {attr}",
                  template.format(e=inst["entity"], v=inst[attr]),
                  _fact_meta(inst["entity"], attr, inst[attr]))

    # ---- technologies -----------------------------------------------------------
    for tech in W.TECHS:
        for attr, template in TECH_ATTR_SENTENCE.items():
            text = template.format(e=tech["entity"], v=tech[attr],
                                   E=_cap_words(tech["entity"]))
            text = _with_injection("inventions_registry",
                                   tech["entity"], attr, text)
            b.add("inventions_registry", f"{tech['entity']} — {attr}",
                  text, _fact_meta(tech["entity"], attr, tech[attr]))

    # ---- curated facts ------------------------------------------------------
    for entity, predicate, value, desc, _domain, _tag in W.CURATED_FACTS:
        sentence = CURATED_SENTENCE[(entity, predicate)]
        text = f"{desc} {sentence}"
        b.add("stable_reference_compendium", f"{entity} — {predicate}",
              text, _fact_meta(entity, predicate, value))

    # ---- slow-changing reference facts ------------------------------------------
    for entity, predicate, value, desc, _domain in W.SLOW_GEOGRAPHY_FACTS:
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
                f"The town of {entity} was established in "
                f"{canon['canonical_value']}, according to the Roll of "
                f"Town Foundings.")
            b.add(canon["canonical_source"],
                  f"{entity} — {attr} (conflict a)",
                  canon_text,
                  _fact_meta(entity, attr, canon["canonical_value"]))
            b.add(canon["alt_source"], f"{entity} — {attr} (conflict b)",
                  f"The Roll of Foundation Records lists the town of "
                  f"{entity} as established in "
                  f"{canon['alt_value']}.",
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
    for src_a, src_b, attr, entities in _near_dup_pairs():
        for entity in entities:
            value = _lookup_fact(entity, attr)
            if value is None:
                raise SystemExit(f"near-dup fact missing: {entity} {attr}")
            template = NEAR_DUP_TEMPLATE[attr]
            base = template.format(e=entity, v=value)
            b.add(src_a, f"{entity} — {attr} (record)",
                  base, _fact_meta(entity, attr, value))
            restated = _restate(attr, base)
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
    for text in _name_family_notes():
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
        "emblem": ("The town emblem of", "The emblem kept by the town of"),
        "province": ("The province of", "The Fellwold province of"),
        "genre": ("is classified as a", "belongs to the genre of"),
        "medium": ("The medium of the painting", "The painting medium of"),
        "waterway": ("The waterway beside the town of",
                     "The town stands beside the waterway"),
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


_FACT_INDEX: dict[tuple[str, str], str] | None = None


def _town_fact(entity: str, attr: str) -> str | None:
    global _FACT_INDEX
    if _FACT_INDEX is None:
        _FACT_INDEX = {}
        for line in (BASE / "world.jsonl").read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec["type"] == "WorldFact":
                _FACT_INDEX[(rec["subject"], rec["predicate"])] = \
                    rec["object"]
    return _FACT_INDEX.get((entity, attr))


def _lookup_fact(entity: str, attr: str) -> str | None:
    return _town_fact(entity, attr)


# ---------------------------------------------------------------------------
# Mechanical disjointness + structural invariants (data only)
# ---------------------------------------------------------------------------


def _assert_disjoint(sources: list[dict], chunks: list[dict]) -> None:
    old_source_ids: set[str] = set()
    old_chunk_texts: set[str] = set()
    for rel in ("rag/gk_corpus", "rag/gk_holdout_t21r",
                "rag/gk_holdout_t21r2", "rag/gk_holdout_t21r3",
                "rag/gk_holdout_t21r4", "rag/gk_holdout_t21r5"):
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