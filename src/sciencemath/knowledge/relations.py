"""Deterministic canonical relation ontology for KNOWLEDGE_RAG.

The runtime binds a query to a closed relation identifier and compares it
with structured ``fact_attribute`` metadata.  Surface text aliases are a
fallback for queries and legacy chunks only; metadata remains authoritative.
No model, embedding similarity, fuzzy matching, or corpus-specific entity
name appears in this module.
"""
from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Mapping


class RelationId(StrEnum):
    BIRTHPLACE = "BIRTHPLACE"
    BIRTH_YEAR = "BIRTH_YEAR"
    AUTHOR = "AUTHOR"
    CREATOR = "CREATOR"
    PAINTER = "PAINTER"
    INVENTOR = "INVENTOR"
    LOCATION = "LOCATION"
    COUNTRY = "COUNTRY"
    NATION = "NATION"
    REGION = "REGION"
    PROVINCE = "PROVINCE"
    CONTINENT = "CONTINENT"
    CAPITAL = "CAPITAL"
    WATERWAY = "WATERWAY"
    FOUNDING_YEAR = "FOUNDING_YEAR"
    PUBLICATION_YEAR = "PUBLICATION_YEAR"
    INTRODUCTION_YEAR = "INTRODUCTION_YEAR"
    CREATION_YEAR = "CREATION_YEAR"
    OPENING_YEAR = "OPENING_YEAR"
    DISCOVERY_YEAR = "DISCOVERY_YEAR"
    RATIFICATION_YEAR = "RATIFICATION_YEAR"
    SIGNING_YEAR = "SIGNING_YEAR"
    COMPLETION_YEAR = "COMPLETION_YEAR"
    LANDING_YEAR = "LANDING_YEAR"
    SEALING_YEAR = "SEALING_YEAR"
    MEDIUM = "MEDIUM"
    EMBLEM = "EMBLEM"
    FIELD_OF_STUDY = "FIELD_OF_STUDY"
    ROLE = "ROLE"
    OFFICE = "OFFICE"
    MAYOR = "MAYOR"
    LED_BY = "LED_BY"
    DATE = "DATE"
    TYPE = "TYPE"
    DEFINITION = "DEFINITION"
    FUNCTION = "FUNCTION"
    PURPOSE = "PURPOSE"
    GENRE = "GENRE"
    SUBJECT = "SUBJECT"
    NOTABLE_WORK = "NOTABLE_WORK"
    PROPERTY = "PROPERTY"
    SEATS = "SEATS"
    LAYER = "LAYER"
    LANDMARK = "LANDMARK"


def normalize_relation_text(text: object) -> str:
    """NFKC/casefold relation text with deterministic underscore handling."""
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = value.replace("_", "-")
    value = re.sub(r"[^a-z0-9-]+", " ", value)
    return " ".join(value.replace("-", " ").split())


# Attribute aliases are exact after normalization.  They mirror the corpus
# metadata vocabulary and intentionally do not infer a relation from a merely
# related word.
ATTRIBUTE_RELATIONS: Mapping[str, RelationId] = {
    "birthplace": RelationId.BIRTHPLACE,
    "birth place": RelationId.BIRTHPLACE,
    "birth town": RelationId.BIRTHPLACE,
    "birth year": RelationId.BIRTH_YEAR,
    "author": RelationId.AUTHOR,
    "writer": RelationId.AUTHOR,
    "creator": RelationId.CREATOR,
    "painter": RelationId.PAINTER,
    "inventor": RelationId.INVENTOR,
    "location": RelationId.LOCATION,
    "country": RelationId.COUNTRY,
    "nation": RelationId.NATION,
    "region": RelationId.REGION,
    "province": RelationId.PROVINCE,
    "continent": RelationId.CONTINENT,
    "capital": RelationId.CAPITAL,
    "river": RelationId.WATERWAY,
    "waterway": RelationId.WATERWAY,
    "founding year": RelationId.FOUNDING_YEAR,
    "foundation year": RelationId.FOUNDING_YEAR,
    "established year": RelationId.FOUNDING_YEAR,
    "establishment year": RelationId.FOUNDING_YEAR,
    "publication year": RelationId.PUBLICATION_YEAR,
    "introduction year": RelationId.INTRODUCTION_YEAR,
    "invention year": RelationId.INTRODUCTION_YEAR,
    "launch year": RelationId.INTRODUCTION_YEAR,
    "creation year": RelationId.CREATION_YEAR,
    "opening year": RelationId.OPENING_YEAR,
    "discovery year": RelationId.DISCOVERY_YEAR,
    "ratification year": RelationId.RATIFICATION_YEAR,
    "signing year": RelationId.SIGNING_YEAR,
    "completion year": RelationId.COMPLETION_YEAR,
    "landing year": RelationId.LANDING_YEAR,
    "sealing year": RelationId.SEALING_YEAR,
    "medium": RelationId.MEDIUM,
    "emblem": RelationId.EMBLEM,
    "field of study": RelationId.FIELD_OF_STUDY,
    "research field": RelationId.FIELD_OF_STUDY,
    "discipline": RelationId.FIELD_OF_STUDY,
    "role": RelationId.ROLE,
    "office": RelationId.OFFICE,
    "officeholder": RelationId.OFFICE,
    "mayor": RelationId.MAYOR,
    "led by": RelationId.LED_BY,
    "date": RelationId.DATE,
    "type": RelationId.TYPE,
    "institution type": RelationId.TYPE,
    "definition": RelationId.DEFINITION,
    "function": RelationId.FUNCTION,
    "purpose": RelationId.PURPOSE,
    "genre": RelationId.GENRE,
    "subject": RelationId.SUBJECT,
    "notable work": RelationId.NOTABLE_WORK,
    "property": RelationId.PROPERTY,
    "seats": RelationId.SEATS,
    "layer": RelationId.LAYER,
    "landmark": RelationId.LANDMARK,
}


# Query aliases are phrases or conservative word stems.  A tuple member that
# ends in ``*`` is a token prefix; all other members are token sequences.
QUERY_ALIASES: Mapping[RelationId, tuple[str, ...]] = {
    RelationId.BIRTHPLACE: (
        "birthplace", "birth place", "birth town", "town of birth",
        "place of birth", "born", "birth",
    ),
    RelationId.BIRTH_YEAR: ("birth year", "year born", "when born"),
    RelationId.AUTHOR: ("author", "writer", "authored", "wrote", "written by"),
    RelationId.CREATOR: ("creator", "created by", "made by"),
    RelationId.PAINTER: ("painter", "painted by"),
    RelationId.INVENTOR: ("inventor", "invented by", "invention of"),
    RelationId.LOCATION: ("location", "located", "situated", "where"),
    RelationId.COUNTRY: ("country",),
    RelationId.NATION: ("nation",),
    RelationId.REGION: ("region",),
    RelationId.PROVINCE: ("province",),
    RelationId.CONTINENT: ("continent",),
    RelationId.CAPITAL: ("capital",),
    RelationId.WATERWAY: ("waterway", "river"),
    RelationId.FOUNDING_YEAR: (
        "founding", "foundation", "founded", "established",
        "establishment year",
    ),
    RelationId.PUBLICATION_YEAR: (
        "publication", "published", "publish", "printed",
        "year of publication",
    ),
    RelationId.INTRODUCTION_YEAR: (
        "introduction", "introduced", "introduce", "debut",
        "first appeared", "launch", "invention year",
    ),
    RelationId.CREATION_YEAR: ("creation year", "created in", "crafted in"),
    RelationId.OPENING_YEAR: ("opening year", "opened in"),
    RelationId.DISCOVERY_YEAR: ("discovery year", "discovered in"),
    RelationId.RATIFICATION_YEAR: ("ratification year", "ratified in"),
    RelationId.SIGNING_YEAR: ("signing year", "signed in"),
    RelationId.COMPLETION_YEAR: ("completion year", "completed in"),
    RelationId.LANDING_YEAR: ("landing year", "landed in"),
    RelationId.SEALING_YEAR: ("sealing year", "sealed in"),
    RelationId.MEDIUM: (
        "medium", "executed in", "rendered in", "created using",
        "made using", "used for",
    ),
    RelationId.EMBLEM: ("emblem", "symbol", "bears the emblem"),
    RelationId.FIELD_OF_STUDY: (
        "field of study", "study field", "research field", "discipline",
        "active in",
    ),
    RelationId.ROLE: ("role", "served as"),
    RelationId.OFFICE: ("office", "officeholder"),
    RelationId.MAYOR: ("mayor",),
    RelationId.LED_BY: ("led by", "led", "leader", "commander",
                        "commanded by"),
    RelationId.DATE: ("date", "when"),
    RelationId.TYPE: ("type", "kind of"),
    RelationId.DEFINITION: ("definition", "define", "what is"),
    RelationId.FUNCTION: ("function", "what does", "used to"),
    RelationId.PURPOSE: ("purpose", "used for"),
    RelationId.GENRE: ("genre",),
    RelationId.SUBJECT: ("subject",),
    RelationId.NOTABLE_WORK: ("notable work", "masterpiece", "masterwork"),
    RelationId.PROPERTY: ("property",),
    RelationId.SEATS: ("seats", "seat count"),
    RelationId.LAYER: ("layer",),
    RelationId.LANDMARK: ("landmark",),
}


def canonical_relation(attribute: object) -> RelationId | None:
    """Return the canonical ID for an exact fact-attribute value."""
    return ATTRIBUTE_RELATIONS.get(normalize_relation_text(attribute))


def _has_phrase(normalized: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])",
                          normalized))


def query_relations(query: str) -> frozenset[RelationId]:
    """Return every deterministic canonical relation expressed by a query."""
    normalized = normalize_relation_text(query)
    tokens = set(normalized.split())
    found: set[RelationId] = set()
    for relation, aliases in QUERY_ALIASES.items():
        if any(_has_phrase(normalized, normalize_relation_text(alias))
               for alias in aliases):
            found.add(relation)

    # Resolve the two common contextual ambiguities conservatively.
    if RelationId.BIRTHPLACE in found:
        if tokens & {"year", "when", "date"} and not (
                tokens & {"where", "town", "place", "city", "village"}):
            found.discard(RelationId.BIRTHPLACE)
            found.add(RelationId.BIRTH_YEAR)
    if RelationId.PURPOSE in found and RelationId.MEDIUM in found:
        if "medium" in tokens:
            found.discard(RelationId.PURPOSE)
        elif not (tokens & {"art", "artwork", "painting", "portrait",
                            "sculpture", "drawing"}):
            found.discard(RelationId.MEDIUM)
    return frozenset(found)


def evidence_relation(metadata: Mapping[str, object] | None,
                      text: str = "") -> RelationId | None:
    """Canonical relation for evidence, preferring fact metadata."""
    metadata = metadata or {}
    attribute = metadata.get("fact_attribute")
    if attribute:
        return canonical_relation(attribute)
    inferred = query_relations(text)
    return next(iter(sorted(inferred, key=str)), None) if len(inferred) == 1 \
        else None


def relation_matches(query: str, metadata: Mapping[str, object] | None,
                     text: str = "") -> bool:
    """Whether evidence asserts one of the canonical relations requested."""
    requested = query_relations(query)
    if not requested:
        return True
    actual = evidence_relation(metadata, text)
    return actual in requested if actual is not None else False


RELATION_ONTOLOGY_VERSION = "t21r7-v1"


def relation_phrase(text: str) -> RelationId | None:
    """Resolve a whole nominal relation alias, never a substring.

    A leading definite article is framing vocabulary, never part of the
    relation identity ('the location' resolves as 'location').
    """
    normalized = normalize_relation_text(text)
    stripped = re.sub(r"^the ", "", normalized)
    direct = canonical_relation(normalized) or canonical_relation(stripped)
    if direct:
        return direct
    matches = {r for r, aliases in QUERY_ALIASES.items()
               if {normalized, stripped} & {normalize_relation_text(a)
                                           for a in aliases}}
    return next(iter(matches)) if len(matches) == 1 else None


def parse_relation_path(query: str) -> tuple[str, tuple[RelationId, ...]] | None:
    """Parse bounded nominal composition and historic relative clauses.

    Grammar, not evidence names, defines identity boundaries. Any canonical
    relation can occupy either hop. More than two hops remain a plan, so the
    runtime can explicitly abstain rather than answer a prefix. Articles are
    preserved in entity tails: the split only separates on 'of', so the
    final identity keeps its surface form ('the hygrometer' stays intact)
    and exact structured matching governs the bind.
    """
    text = query.strip().rstrip("?.!").strip()
    # Nested nominal: what is the country of the location of X?
    text = re.sub(r"^(?:what is|who is|which is|identify|name|give|tell me)\s+", "", text, flags=re.I)
    text = re.sub(r"^the\s+", "", text, flags=re.I)
    # Trailing question frames are grammar, never identity: 'is in which
    # town' at the end of a nominal question is the interrogative frame,
    # not part of the final entity (the identity tail would otherwise
    # never match a fact_entity and every such question would abstain).
    # The born-pattern branch below keeps handling 'was born in which
    # town' questions (the verb is not followed directly by 'which').
    text = re.sub(
        r"\s+(?:is|was|are|were)\s+(?:in\s+)?which\s+"
        r"(?:town|city|village|place|year)\s*$",
        "", text, flags=re.I)

    def nominal(value):
        parts = re.split(r"\s+of\s+", value, flags=re.I)
        # Longest whole alias first ('place of birth', 'field of study').
        for i in range(len(parts) - 1, 0, -1):
            rel = relation_phrase(" of ".join(parts[:i]))
            if rel:
                tail = " of ".join(parts[i:]).strip()
                if re.match(r"(?:the\s+)?(?:town|city|village|person)\s+(?:of|who)\b", tail, re.I):
                    return None
                child = nominal(tail)
                if child:
                    return child[0], child[1] + (rel,)
                return tail, (rel,)
        return None

    # Nominal parsing must not swallow a trailing predicate as an identity.
    found = nominal(text)
    if found and not re.search(r"\bborn\b", found[0], re.I):
        return found
    # Historic relative/nominal framing: 'Within which town was the
    # author of X born?' / 'The author of X was born in which town?'.
    # The entity article stays inside the identity capture: exact
    # structured matching binds 'The Orrery of Harrow', not 'Orrery of
    # Harrow' — dropping the article makes every born-framed chain
    # abstain at hop 1.
    if re.search(r"\bborn\b", text, re.I):
        pattern = re.compile(
            r"(?:^|\bthe\s+)([\w -]+?)\s+of\s+"
            r"((?:the\s+)?.+?)\s+(?:was\s+)?born\b", re.I)
        pos = 0
        while True:
            match = pattern.search(text, pos)
            if not match:
                break
            rel = relation_phrase(match[1].strip())
            if rel:
                terminal = RelationId.BIRTH_YEAR if re.search(
                    r"\byear\b|\bwhen\b", query, re.I) else RelationId.BIRTHPLACE
                return match[2].strip(), (rel, terminal)
            # The first match may swallow leading grammar ('Where was the
            # leader of X born') into the relation capture so no relation
            # resolves; retry from the next definite-article anchor so the
            # bare relation phrase ('the leader') is tried.
            pos = match.start() + 1
    return None

