"""T21R14 preregistered static semantics for preconstruction qualification.

This module is data-only: it projects synthetic evidence with the same pure
FactEdge helper and rank tables used by the frozen runtime, but it never calls
the answer pipeline, path resolver, evaluator, or an official runner.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
from t21r14_retrieval_mirror import derive_initial_window


AUTHORITY_RANK = {
    "PRIMARY_REFERENCE": 6, "ENCYCLOPEDIC": 5,
    "ACADEMIC_REFERENCE": 4, "GOVERNMENT_PUBLICATION": 4,
    "INSTITUTIONAL": 3, "GENERAL_REFERENCE": 2, "UNKNOWN": 0,
}
_FRESHNESS_RANK = {
    "STATIC": 3, "SLOW_CHANGING": 2, "TIME_SENSITIVE": 1, "UNKNOWN": 0,
}

_ATTRIBUTE_ALIASES = {
    "birthplace": "BIRTHPLACE", "birth place": "BIRTHPLACE",
    "birth town": "BIRTHPLACE", "birth year": "BIRTH_YEAR",
    "author": "AUTHOR", "writer": "AUTHOR", "creator": "CREATOR",
    "painter": "PAINTER", "inventor": "INVENTOR",
    "location": "LOCATION", "country": "COUNTRY", "nation": "NATION",
    "region": "REGION", "province": "PROVINCE",
    "continent": "CONTINENT", "capital": "CAPITAL",
    "river": "WATERWAY", "waterway": "WATERWAY",
    "founding year": "FOUNDING_YEAR", "foundation year": "FOUNDING_YEAR",
    "established year": "FOUNDING_YEAR",
    "establishment year": "FOUNDING_YEAR",
    "publication year": "PUBLICATION_YEAR",
    "introduction year": "INTRODUCTION_YEAR",
    "invention year": "INTRODUCTION_YEAR", "launch year": "INTRODUCTION_YEAR",
    "creation year": "CREATION_YEAR", "opening year": "OPENING_YEAR",
    "discovery year": "DISCOVERY_YEAR",
    "ratification year": "RATIFICATION_YEAR",
    "signing year": "SIGNING_YEAR", "completion year": "COMPLETION_YEAR",
    "landing year": "LANDING_YEAR", "sealing year": "SEALING_YEAR",
    "medium": "MEDIUM", "emblem": "EMBLEM",
    "field of study": "FIELD_OF_STUDY", "research field": "FIELD_OF_STUDY",
    "discipline": "FIELD_OF_STUDY", "role": "ROLE", "office": "OFFICE",
    "officeholder": "OFFICE", "mayor": "MAYOR", "led by": "LED_BY",
    "leader": "LED_BY", "commander": "LED_BY", "date": "DATE",
    "type": "TYPE", "institution type": "TYPE", "definition": "DEFINITION",
    "function": "FUNCTION", "purpose": "PURPOSE", "genre": "GENRE",
    "subject": "SUBJECT", "notable work": "NOTABLE_WORK",
    "property": "PROPERTY", "seats": "SEATS", "layer": "LAYER",
    "landmark": "LANDMARK",
}
_RELATION_CUES = {
    "BIRTHPLACE": ("birthplace", "birth place", "born"),
    "BIRTH_YEAR": ("birth year", "year born", "when born"),
    "AUTHOR": ("author", "writer", "authored", "wrote", "written by"),
    "CREATOR": ("creator", "created by", "made by"),
    "PAINTER": ("painter", "painted by"),
    "INVENTOR": ("inventor", "invented by"),
    "LOCATION": ("location", "located", "situated"),
    "COUNTRY": ("country",), "NATION": ("nation",),
    "REGION": ("region",), "PROVINCE": ("province",),
    "CONTINENT": ("continent",), "CAPITAL": ("capital",),
    "WATERWAY": ("waterway", "river"),
    "FOUNDING_YEAR": ("founding", "foundation", "founded", "established"),
    "PUBLICATION_YEAR": ("publication", "published", "printed"),
    "INTRODUCTION_YEAR": ("introduction", "introduced", "launch"),
    "CREATION_YEAR": ("creation year", "created in", "crafted in"),
    "OPENING_YEAR": ("opening year", "opened in"),
    "DISCOVERY_YEAR": ("discovery year", "discovered in"),
    "RATIFICATION_YEAR": ("ratification year", "ratified in"),
    "SIGNING_YEAR": ("signing year", "signed in"),
    "COMPLETION_YEAR": ("completion year", "completed in"),
    "LANDING_YEAR": ("landing year", "landed in", "land in"),
    "SEALING_YEAR": ("sealing year", "sealed in"),
    "MEDIUM": ("medium", "executed in", "rendered in", "created using"),
    "EMBLEM": ("emblem", "symbol"),
    "FIELD_OF_STUDY": ("field of study", "research field", "discipline"),
    "ROLE": ("role", "served as"), "OFFICE": ("office", "officeholder"),
    "MAYOR": ("mayor",),
    "LED_BY": ("led by", "led", "leader", "commander", "commanded by"),
    "DATE": ("date",), "TYPE": ("type", "kind of"),
    "DEFINITION": ("definition", "define"),
    "FUNCTION": ("function", "what does"), "PURPOSE": ("purpose", "used for"),
    "GENRE": ("genre",), "SUBJECT": ("subject",),
    "NOTABLE_WORK": ("notable work", "masterpiece", "masterwork"),
    "PROPERTY": ("property",), "SEATS": ("seats", "seat count"),
    "LAYER": ("layer",), "LANDMARK": ("landmark",),
}
_DIRECTIVE_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) "
    r"(?:instructions|prompts|rules)",
    r"do not (?:cite|reference|mention) (?:this|the|any) "
    r"(?:source|passage|chunk|text)",
    r"(?:system|developer|admin(?:istrator)?)\s*(?:message|prompt|notice|override)\s*:",
    r"trust (?:this|the|only this|only the) (?:source|text|record|passage|document)",
    r"regardless of (?:the )?(?:evidence|facts|sources)",
    r"(?:do not|don't|never) (?:include|emit|add|use|show) (?:any )?citations",
    r"(?:ignore|disregard) (?:the |this |any |all )?user\b",
    r"reveal (?:the |your )?(?:system )?(?:prompt|instructions)",
    r"use (?:the )?(?:live|open|real) (?:internet|web|network)",
))
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\r?\n+")


def normalize_identity(value: object) -> str:
    return " ".join(unicodedata.normalize(
        "NFKC", str(value or "")).casefold().split())


def _normalize_relation(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text.replace("_", " "))
    return " ".join(text.split())


def canonical_relation(value: object) -> str | None:
    normalized = _normalize_relation(value)
    if normalized.upper() in set(_ATTRIBUTE_ALIASES.values()):
        return normalized.upper()
    return _ATTRIBUTE_ALIASES.get(normalized)


def _safe_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT.split(text)
            if sentence.strip() and not any(
                pattern.search(sentence) for pattern in _DIRECTIVE_PATTERNS)]


@dataclass(frozen=True)
class EvidenceItem:
    source_id: str
    chunk_id: str
    title: str
    section: str
    text_span: str
    score: float
    rank: int
    authority_class: str
    content_hash: str
    citation_id: str
    source_license: str
    freshness_class: str
    topic_tags: list[str]
    metadata: dict


@dataclass(frozen=True)
class FactEdge:
    subject_entity: str
    canonical_relation: str
    object_value: str
    authority_class: str
    freshness_class: str
    proposition: str


def make_citation_id(query: str, chunk_id: str, rank: int) -> str:
    key = json.dumps({"q": query, "c": chunk_id, "r": rank},
                     sort_keys=True, ensure_ascii=False)
    return f"C{rank}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"


def project_fact_edge(item: EvidenceItem) -> FactEdge | None:
    metadata = item.metadata or {}
    entity = metadata.get("fact_entity")
    value = metadata.get("fact_value")
    relation = canonical_relation(metadata.get("fact_attribute"))
    if not entity or value is None or not str(value).strip() or relation is None:
        return None
    for sentence in _safe_sentences(item.text_span):
        normalized = normalize_identity(sentence)

        def present(part: object) -> bool:
            return bool(re.search(r"(?<!\w)" + re.escape(
                normalize_identity(part)) + r"(?!\w)", normalized))

        cues = _RELATION_CUES.get(relation, ())
        cue_present = any(re.search(r"(?<![a-z0-9])" + re.escape(
            normalize_identity(cue)) + r"(?![a-z0-9])", normalized)
                          for cue in cues)
        denied = re.search(r"\b(?:not|never|false|incorrect|denied|denies)\b",
                           normalized)
        if present(entity) and present(value) and cue_present and not denied:
            return FactEdge(str(entity), relation, str(value),
                            item.authority_class, item.freshness_class,
                            sentence.strip())
    return None


FAKE_LOCATOR_GRAMMAR = r"r11qz-[0-9a-f]{16}"
FAKE_LOCATOR_RE = re.compile(
    rf"(?<![A-Za-z0-9])({FAKE_LOCATOR_GRAMMAR})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
PARTIAL_PATH_COMPONENTS = frozenset({
    "missing_start_entity",
    "missing_hop1",
    "missing_hop2",
    "wrong_bridge_identity",
    "near_name_start_entity",
    "near_name_bridge_entity",
    "wrong_relation",
    "same_entity_wrong_attribute",
    "partial_path_only",
    "unrelated_conflict",
    "relevant_unresolved_conflict",
})
INDEPENDENCE_DIMENSIONS = (
    "case_ids",
    "entity_identities",
    "source_ids",
    "chunk_ids",
    "exact_queries",
    "exact_answers",
    "exact_source_text",
    "verbatim_attack_wording",
)


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_map(sources: Iterable[dict]) -> dict[str, dict]:
    return {str(source["source_id"]): source for source in sources}


def _chunk_map(chunks: Iterable[dict]) -> dict[str, dict]:
    return {str(chunk["chunk_id"]): chunk for chunk in chunks}


def evidence_item(chunk: dict, source: dict, query: str, rank: int) \
        -> EvidenceItem:
    """Project one plain candidate record into the runtime evidence type."""
    text = str(chunk.get("text") or "")
    content_hash = str(chunk.get("content_hash") or _sha_text(text))
    return EvidenceItem(
        source_id=str(chunk["source_id"]),
        chunk_id=str(chunk["chunk_id"]),
        title=str(source.get("source_title") or source["source_id"]),
        section=str(chunk.get("section") or "synthetic"),
        text_span=text,
        score=float(chunk.get("score") or 1.0),
        rank=rank,
        authority_class=str(source.get("authority_class") or "UNKNOWN"),
        content_hash=content_hash,
        citation_id=make_citation_id(query, str(chunk["chunk_id"]), rank),
        source_license=str(source.get("license") or ""),
        freshness_class=str(source.get("freshness_class") or "UNKNOWN"),
        topic_tags=list(source.get("topic_tags") or []),
        metadata=dict(chunk.get("metadata") or {}),
    )


def _canonical(value: object) -> str | None:
    relation = canonical_relation(value)
    return str(relation) if relation is not None else None


def _rank(edge) -> tuple[int, int]:
    return (
        AUTHORITY_RANK.get(edge.authority_class, 0),
        _FRESHNESS_RANK.get(edge.freshness_class, 0),
    )


def _edge_defects(
    edge_name: str,
    declared: object,
    chunks_by_id: dict[str, dict],
    sources_by_id: dict[str, dict],
    query: str,
) -> list[str]:
    if not isinstance(declared, dict):
        return [f"{edge_name}: declaration is not an object"]
    chunk_id = declared.get("chunk_id")
    source_id = declared.get("source_id")
    chunk = chunks_by_id.get(str(chunk_id))
    if chunk is None:
        return [f"{edge_name}: chunk does not resolve"]
    source = sources_by_id.get(str(source_id))
    if source is None:
        return [f"{edge_name}: source does not resolve"]
    defects: list[str] = []
    if chunk.get("source_id") != source_id:
        defects.append(f"{edge_name}: source identity differs from chunk")
    item = evidence_item(chunk, source, query, 1)
    projected = project_fact_edge(item)
    if projected is None:
        defects.append(f"{edge_name}: evidence is unsafe or non-projectable")
        return defects
    if normalize_identity(projected.subject_entity) != normalize_identity(
            declared.get("subject_entity")):
        defects.append(f"{edge_name}: subject identity mismatch")
    if normalize_identity(projected.object_value) != normalize_identity(
            declared.get("object_value")):
        defects.append(f"{edge_name}: object identity mismatch")
    declared_relation = _canonical(declared.get("relation"))
    if declared_relation is None or str(projected.canonical_relation) != \
            declared_relation:
        defects.append(f"{edge_name}: relation identity mismatch")
    if not projected.proposition.strip():
        defects.append(f"{edge_name}: projected proposition is empty")
    return defects


def audit_path_row(row: dict, sources: list[dict], chunks: list[dict]) -> dict:
    """Validate first-hop achievability and the separate structural path.

    The initial criterion deliberately accepts any highest-ranked safe edge
    for the requested entity and relation.  The nominated hop-1 chunk remains
    a structural gold witness, but it need not be the initially retrieved
    duplicate when an equivalent valid edge is present.
    """
    query = str((row.get("request") or {}).get("query") or "")
    annotation = row.get("construction") or {}
    request = annotation.get("path_request") or {}
    path = annotation.get("gold_path") or {}
    chunks_by_id = _chunk_map(chunks)
    sources_by_id = _source_map(sources)
    defects: list[str] = []

    start = request.get("start_entity")
    relations = request.get("relations")
    if not start or not isinstance(relations, list) or len(relations) != 2:
        return {
            "status": "FAIL",
            "defects": ["path request must declare one start and two relations"],
            "selected_initial_chunk_id": None,
        }
    first_relation = _canonical(relations[0])
    second_relation = _canonical(relations[1])
    if first_relation is None or second_relation is None:
        return {
            "status": "FAIL",
            "defects": ["path request contains an unknown relation"],
            "selected_initial_chunk_id": None,
        }

    retrieval = derive_initial_window(query, chunks)
    initial_ids = retrieval.chunk_ids
    supplied_ids = annotation.get("initial_window_chunk_ids")
    eligible: list[tuple[EvidenceItem, object]] = []
    for rank, chunk_id in enumerate(initial_ids, start=1):
        chunk = chunks_by_id.get(str(chunk_id))
        if chunk is None:
            defects.append(f"initial chunk does not resolve: {chunk_id}")
            continue
        source = sources_by_id.get(str(chunk.get("source_id")))
        if source is None:
            defects.append(f"initial source does not resolve: {chunk_id}")
            continue
        item = evidence_item(chunk, source, query, rank)
        edge = project_fact_edge(item)
        if edge is not None and normalize_identity(edge.subject_entity) == \
                normalize_identity(start) and \
                str(edge.canonical_relation) == first_relation:
            eligible.append((item, edge))

    selected = None
    selected_edge = None
    if not eligible:
        defects.append("no runtime-eligible initial edge")
    else:
        best = max(_rank(edge) for _item, edge in eligible)
        leaders = [(item, edge) for item, edge in eligible
                   if _rank(edge) == best]
        leader_values = {normalize_identity(edge.object_value)
                         for _item, edge in leaders}
        if len(leader_values) > 1:
            defects.append("equal-rank contradictory initial edges")
        else:
            selected, selected_edge = leaders[0]

    hop1 = path.get("hop1_edge") if isinstance(path, dict) else None
    hop2 = path.get("hop2_edge") if isinstance(path, dict) else None
    defects.extend(_edge_defects(
        "hop1", hop1, chunks_by_id, sources_by_id, query))
    defects.extend(_edge_defects(
        "hop2", hop2, chunks_by_id, sources_by_id, query))
    if isinstance(hop1, dict) and isinstance(hop2, dict):
        bridge = path.get("bridge_entity")
        terminal = path.get("terminal_value")
        if normalize_identity(hop1.get("object_value")) != \
                normalize_identity(bridge):
            defects.append("declared hop1 does not reach the bridge")
        if normalize_identity(hop2.get("subject_entity")) != \
                normalize_identity(bridge):
            defects.append("hop2 subject does not equal the bridge")
        if normalize_identity(hop2.get("object_value")) != \
                normalize_identity(terminal):
            defects.append("hop2 object does not equal the terminal value")
        if _canonical(hop1.get("relation")) != first_relation:
            defects.append("hop1 relation differs from requested relation")
        if _canonical(hop2.get("relation")) != second_relation:
            defects.append("hop2 relation differs from requested relation")
        answers = (row.get("gold") or {}).get("expect_answer_contains") or []
        if normalize_identity(terminal) not in {
                normalize_identity(answer) for answer in answers}:
            defects.append("terminal value is absent from the gold answer")
        if selected_edge is not None and normalize_identity(
                selected_edge.object_value) != normalize_identity(bridge):
            defects.append("selected initial edge reaches the wrong bridge")

    return {
        "status": "PASS" if not defects else "FAIL",
        "defects": list(dict.fromkeys(defects)),
        "selected_initial_chunk_id": selected.chunk_id if selected else None,
        "eligible_initial_chunk_ids": [item.chunk_id for item, _edge in eligible],
        "derived_initial_window_chunk_ids": initial_ids,
        "annotation_initial_window_ignored": supplied_ids is not None,
        "retrieval_trace": retrieval.to_dict(),
        "runtime_execution_count": 0,
    }


def _collect_named_locators(value: object, key: str = "") -> set[str]:
    locators: set[str] = set()
    normalized_key = key.casefold()
    named = normalized_key in {"source_id", "chunk_id"} or any(
        token in normalized_key for token in ("citation", "locator", "provenance")
    )
    if isinstance(value, dict):
        for child_key, child in value.items():
            locators.update(_collect_named_locators(child, str(child_key)))
    elif isinstance(value, list):
        for child in value:
            locators.update(_collect_named_locators(child, key))
    elif named and value is not None:
        locators.add(str(value).casefold())
    return locators


def candidate_locators(sources: list[dict], chunks: list[dict]) -> set[str]:
    locators: set[str] = set()
    for record in [*sources, *chunks]:
        locators.update(_collect_named_locators(record))
    return locators


def audit_spoof_row(row: dict, sources: list[dict], chunks: list[dict]) -> dict:
    defects: list[str] = []
    tags = row.get("construction_tags") or []
    annotation = row.get("construction") or {}
    wording = annotation.get("attack_wording")
    query = str((row.get("request") or {}).get("query") or "")
    if "query_injection_or_spoof" not in tags:
        defects.append("missing query_injection_or_spoof tag")
    if not isinstance(wording, str) or not wording.strip():
        defects.append("missing attack wording")
        wording = ""
    elif wording.casefold() not in query.casefold():
        defects.append("attack wording is absent from query")
    matches = FAKE_LOCATOR_RE.findall(wording)
    if len(matches) != 1:
        defects.append("attack wording must contain exactly one R14 fake locator")
    locator = matches[0].casefold() if len(matches) == 1 else None
    if locator is not None and locator in candidate_locators(sources, chunks):
        defects.append("fake locator resolves to candidate provenance")
    return {
        "status": "PASS" if not defects else "FAIL",
        "defects": defects,
        "locator": locator,
        "runtime_execution_count": 0,
    }


def scan_annotations(rows: list[dict], chunks: list[dict]) -> dict:
    chunks_by_id = _chunk_map(chunks)
    violations: list[dict[str, str]] = []

    def violation(row: dict, reason: str) -> None:
        violations.append({"case_id": str(row.get("case_id")),
                           "reason": reason})

    for row in rows:
        tags = set(row.get("construction_tags") or [])
        annotation = row.get("construction")
        annotation = annotation if isinstance(annotation, dict) else {}
        query = str((row.get("request") or {}).get("query") or "")
        if row.get("category") == "injection_absent_entity" and (
                "construction_tags" in row or "construction" in row):
            violation(row, "stale construction metadata on absent-entity row")

        if "multisource_path" in tags:
            path_sources = annotation.get("path_required_sources")
            corroboration = annotation.get("corroboration_sources")
            path = annotation.get("gold_path")
            if not isinstance(path_sources, list) or len(set(path_sources)) < 2:
                violation(row, "path_required_sources must contain >=2 distinct IDs")
            if not isinstance(corroboration, list):
                violation(row, "corroboration_sources must be a list")
            elif isinstance(path_sources, list) and set(corroboration) & set(
                    path_sources):
                violation(row, "corroboration overlaps path_required_sources")
            if not isinstance(path, dict):
                violation(row, "multisource row lacks gold_path")
            else:
                edge_sources = {
                    edge.get("source_id")
                    for edge in (path.get("hop1_edge"), path.get("hop2_edge"))
                    if isinstance(edge, dict) and edge.get("source_id")
                }
                if not isinstance(path_sources, list) or set(path_sources) != \
                        edge_sources:
                    violation(row, "path_required_sources differ from gold edges")

        if "query_injection_or_spoof" in tags:
            wording = annotation.get("attack_wording")
            if not isinstance(wording, str) or not wording.strip():
                violation(row, "query attack lacks attack_wording")
            elif wording.casefold() not in query.casefold():
                violation(row, "query attack wording is absent from query")

        if "source_injection_safe_fact" in tags:
            wording = annotation.get("attack_wording")
            evidence_ids = annotation.get("attack_evidence_chunk_ids")
            if not isinstance(evidence_ids, list) or not evidence_ids:
                violation(row, "source attack lacks evidence chunk IDs")
            elif not isinstance(wording, str) or not any(
                    chunk_id in chunks_by_id and wording.casefold() in str(
                        chunks_by_id[chunk_id].get("text") or "").casefold()
                    for chunk_id in evidence_ids):
                violation(row, "source attack wording is absent from evidence")

        if "partial_path_ie_stress" in tags:
            component = annotation.get("missing_component")
            if component not in PARTIAL_PATH_COMPONENTS:
                violation(row, "unknown partial-path missing_component")
            if "gold_path" in annotation:
                violation(row, "partial-path row encodes a complete gold path")
            status = (row.get("gold") or {}).get("expect_status")
            required = "CONFLICTING_EVIDENCE" \
                if component == "relevant_unresolved_conflict" \
                else "INSUFFICIENT_EVIDENCE"
            if status != required:
                violation(row, "partial-path status disagrees with missing_component")

    return {
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
        "rows": len(rows),
        "runtime_execution_count": 0,
    }


def material_dimensions(sources: list[dict], chunks: list[dict],
                        rows: list[dict]) -> dict[str, set[str]]:
    dimensions = {name: set() for name in INDEPENDENCE_DIMENSIONS}
    dimensions["case_ids"].update(str(row.get("case_id")) for row in rows)
    dimensions["source_ids"].update(
        str(source.get("source_id")) for source in sources)
    dimensions["chunk_ids"].update(
        str(chunk.get("chunk_id")) for chunk in chunks)
    dimensions["entity_identities"].update(
        normalize_identity((chunk.get("metadata") or {}).get("fact_entity"))
        for chunk in chunks if (chunk.get("metadata") or {}).get("fact_entity"))
    dimensions["exact_queries"].update(
        str((row.get("request") or {}).get("query") or "") for row in rows)
    dimensions["exact_answers"].update(
        str(answer) for row in rows
        for answer in ((row.get("gold") or {}).get("expect_answer_contains") or []))
    dimensions["exact_source_text"].update(
        str(chunk.get("text") or "") for chunk in chunks)
    dimensions["verbatim_attack_wording"].update(
        str((row.get("construction") or {}).get("attack_wording"))
        for row in rows
        if (row.get("construction") or {}).get("attack_wording"))
    return dimensions


def audit_independence(
    sources: list[dict], chunks: list[dict], rows: list[dict],
    prior_material: dict[str, set[str]],
) -> dict:
    current = material_dimensions(sources, chunks, rows)
    overlap = {
        name: sorted(current[name] & set(prior_material.get(name, set())))
        for name in INDEPENDENCE_DIMENSIONS
    }
    total = sum(len(values) for values in overlap.values())
    return {
        "status": "UNIQUE" if total == 0 else "OVERLAP",
        "overlap": overlap,
        "overlap_total": total,
        "dimensions_checked": len(INDEPENDENCE_DIMENSIONS),
        "runtime_execution_count": 0,
    }
