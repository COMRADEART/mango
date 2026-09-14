"""T21.3 — frozen local knowledge corpus model.

Typed source records and chunks with deterministic IDs: re-indexing
identical source content must produce identical IDs. IDs are derived from
source identity (title/publisher/revision) and content hashes, never from
build order. Authority and freshness classes are closed vocabularies
(T21.16 / T21.26). Retrieved corpus text is DATA: instruction authority 0
(T21.19); the runtime never executes, stores, or transmits it.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

FRESHNESS_CLASSES = (
    "STATIC",          # never changes (historical events, authored works)
    "SLOW_CHANGING",   # stable enough for a frozen snapshot (capitals, seats)
    "TIME_SENSITIVE",  # can change faster than the snapshot (officeholders)
    "UNKNOWN",
)
FRESHNESS_CLASSES_SET = frozenset(FRESHNESS_CLASSES)

AUTHORITY_CLASSES = (
    "PRIMARY_REFERENCE",        # primary reference work for the domain
    "ENCYCLOPEDIC",             # general encyclopedic coverage
    "ACADEMIC_REFERENCE",       # academic/scholarly reference
    "GOVERNMENT_PUBLICATION",   # government/civics publication
    "INSTITUTIONAL",            # institutional publication
    "GENERAL_REFERENCE",        # general reference collection
    "UNKNOWN",
)
AUTHORITY_CLASSES_SET = frozenset(AUTHORITY_CLASSES)

_SOURCE_LANG = "en"


class SchemaError(ValueError):
    """Raised when a corpus record fails validation."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")
    return slug or "section"


def source_record_hash(record: "KnowledgeSourceRecord") -> str:
    """Deterministic content hash over the source's canonical fields."""
    blob = json.dumps({
        "source_id": record.source_id,
        "source_title": record.source_title,
        "publisher_or_collection": record.publisher_or_collection,
        "revision_or_version": record.revision_or_version,
        "text": record.content_text,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def chunk_checksum(text: str) -> str:
    return _sha256(text)


@dataclass
class KnowledgeSourceRecord:
    """One frozen source in the knowledge corpus (T21.3 minimum fields)."""

    source_id: str
    source_title: str
    source_type: str
    source_uri_or_origin: str
    publisher_or_collection: str
    license: str
    revision_or_version: str
    retrieved_at_or_snapshot_date: str
    language: str
    authority_class: str
    freshness_class: str
    topic_tags: list[str] = field(default_factory=list)
    content_text: str = ""
    content_hash: str = ""
    document_hash: str = ""

    def __post_init__(self) -> None:
        if self.authority_class not in AUTHORITY_CLASSES_SET:
            raise SchemaError(
                f"authority_class {self.authority_class!r} not in "
                f"{AUTHORITY_CLASSES}")
        if self.freshness_class not in FRESHNESS_CLASSES_SET:
            raise SchemaError(
                f"freshness_class {self.freshness_class!r} not in "
                f"{FRESHNESS_CLASSES}")
        if not self.source_id.startswith("gk-"):
            raise SchemaError(
                f"source_id {self.source_id!r} must use the gk- prefix so "
                "citation provenance cannot collide with the T5R corpus")
        if not self.content_hash:
            self.content_hash = source_record_hash(self)
        if not self.document_hash:
            self.document_hash = self.content_hash

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_title": self.source_title,
            "source_type": self.source_type,
            "source_uri_or_origin": self.source_uri_or_origin,
            "publisher_or_collection": self.publisher_or_collection,
            "license": self.license,
            "revision_or_version": self.revision_or_version,
            "retrieved_at_or_snapshot_date": self.retrieved_at_or_snapshot_date,
            "language": self.language,
            "authority_class": self.authority_class,
            "freshness_class": self.freshness_class,
            "topic_tags": list(self.topic_tags),
            "content_hash": self.content_hash,
            "document_hash": self.document_hash,
        }

    @classmethod
    def from_dict(cls, data: dict, content_text: str = "") \
            -> "KnowledgeSourceRecord":
        return cls(
            source_id=data["source_id"],
            source_title=data["source_title"],
            source_type=data["source_type"],
            source_uri_or_origin=data["source_uri_or_origin"],
            publisher_or_collection=data["publisher_or_collection"],
            license=data["license"],
            revision_or_version=data["revision_or_version"],
            retrieved_at_or_snapshot_date=data[
                "retrieved_at_or_snapshot_date"],
            language=data["language"],
            authority_class=data["authority_class"],
            freshness_class=data["freshness_class"],
            topic_tags=list(data.get("topic_tags") or []),
            content_text=content_text,
            content_hash=data["content_hash"],
            document_hash=data["document_hash"],
        )


def make_source_id(title: str, publisher: str, revision: str) -> str:
    """Deterministic source ID: gk-<sha1(identity)[:12]>."""
    key = f"{title}|{publisher}|{revision}"
    return "gk-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def make_chunk_id(source_id: str, section: str, ordinal: int) -> str:
    """Deterministic chunk ID: <source_id>:<section-slug>:<ordinal>."""
    return f"{source_id}:{_slug(section)}:{ordinal}"


@dataclass
class KnowledgeChunk:
    """One retrievable chunk of a frozen knowledge source (T21.3)."""

    chunk_id: str
    source_id: str
    section: str
    text: str
    ordinal: int
    span: tuple[int, int]
    metadata: dict = field(default_factory=dict)
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = chunk_checksum(self.text)

    @property
    def span_start(self) -> int:
        return self.span[0]

    @property
    def span_end(self) -> int:
        return self.span[1]

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "section": self.section,
            "text": self.text,
            "ordinal": self.ordinal,
            "span": [self.span[0], self.span[1]],
            "metadata": dict(self.metadata),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeChunk":
        return cls(
            chunk_id=data["chunk_id"],
            source_id=data["source_id"],
            section=data["section"],
            text=data["text"],
            ordinal=data["ordinal"],
            span=(data["span"][0], data["span"][1]),
            metadata=dict(data.get("metadata") or {}),
            content_hash=data["content_hash"],
        )


def chunk_source_text(source: KnowledgeSourceRecord,
                      sections: list[tuple[str, str]]) -> list[KnowledgeChunk]:
    """Split a source's sections into deterministic ordered chunks.

    ``sections`` is an ordered list of (section, text). Chunk ordinals are
    per-source, so re-indexing identical content yields identical chunk IDs
    and checksums.
    """
    chunks: list[KnowledgeChunk] = []
    for ordinal, (section, text) in enumerate(sections):
        chunks.append(KnowledgeChunk(
            chunk_id=make_chunk_id(source.source_id, section, ordinal),
            source_id=source.source_id,
            section=section,
            text=text,
            ordinal=ordinal,
            span=(0, len(text)),
            metadata={"topic_tags": list(source.topic_tags)},
        ))
    return chunks


def validate_chunk_invariants(chunks: list[KnowledgeChunk]) -> list[str]:
    """Structural checks: unique IDs, checksum agreement, ordinal order."""
    problems: list[str] = []
    seen: set[str] = set()
    per_source: dict[str, list[int]] = {}
    for c in chunks:
        if c.chunk_id in seen:
            problems.append(f"duplicate chunk_id {c.chunk_id}")
        seen.add(c.chunk_id)
        if chunk_checksum(c.text) != c.content_hash:
            problems.append(f"checksum mismatch {c.chunk_id}")
        per_source.setdefault(c.source_id, []).append(c.ordinal)
    for sid, ords in per_source.items():
        if ords != sorted(ords):
            problems.append(f"ordinals out of order for {sid}")
    return problems