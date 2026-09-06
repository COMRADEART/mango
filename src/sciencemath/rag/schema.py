"""schema — normalized scientific document/chunk schema (T5.4).

Every indexed scientific record is normalized into SciDocument before it
may enter rag/corpus/. Provenance fields are REQUIRED and never
fabricated: if a metadata value is unknown it stays None/"" — never a
made-up placeholder.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict

from sciencemath.rag.taxonomy import is_valid_domain, is_valid_subject

# fields every indexed chunk MUST carry with real (non-empty) values
REQUIRED_FIELDS = (
    "document_id", "source_id", "source_type", "title", "text",
    "domain", "url", "license", "attribution", "chunk_id", "retrieved_at",
)

# optional research-paper fields (never fabricated when unknown)
OPTIONAL_RESEARCH_FIELDS = (
    "authors", "doi", "pmid", "arxiv_id", "journal", "peer_review_status",
)

_CHUNK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{3,120}$")


@dataclass
class SciDocument:
    """Normalized scientific chunk (one retrievable unit)."""
    document_id: str
    source_id: str
    source_type: str
    title: str
    section: str            # section heading, "" if none recoverable
    domain: str             # canonical taxonomy domain (taxonomy.py)
    subject: str            # taxonomy subject, "" = domain-level
    text: str
    url: str
    revision: str           # revision id / edition / arxiv version, "" if unknown
    publication_date: str   # "" if unknown
    retrieved_at: str       # ISO date of retrieval — REQUIRED provenance
    license: str
    attribution: str
    chunk_id: str
    checksum: str           # sha256 over (text + provenance fields)
    # research-paper extras (None when unknown — never fabricated)
    authors: list[str] | None = None
    doi: str | None = None
    pmid: str | None = None
    arxiv_id: str | None = None
    journal: str | None = None
    peer_review_status: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SciDocument":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def chunk_checksum(doc: SciDocument) -> str:
    """Stable sha256 over text + provenance; detects any tampering or
    metadata drift between rebuilds."""
    payload = "\x1f".join([
        doc.document_id, doc.source_id, doc.title, doc.section,
        doc.domain, doc.text, doc.url, doc.revision,
        doc.license, doc.attribution, doc.chunk_id,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SchemaError(ValueError):
    """A record failed schema validation (bad/missing provenance)."""


def validate_document(doc: SciDocument, *, source_ids: set[str] | None = None,
                      strict_domain: bool = True) -> list[str]:
    """Validate one SciDocument. Returns [] if valid, else error strings.

    strict_domain=True enforces the canonical taxonomy (T5.3)."""
    errors: list[str] = []
    d = doc.to_dict()
    for name in REQUIRED_FIELDS:
        if not str(d.get(name) or "").strip():
            errors.append(f"missing required field: {name}")
    if strict_domain and doc.domain and not is_valid_domain(doc.domain):
        errors.append(f"non-canonical domain: {doc.domain!r}")
    if strict_domain and doc.subject and \
            not is_valid_subject(doc.domain, doc.subject):
        errors.append(f"subject {doc.subject!r} invalid for domain {doc.domain!r}")
    if doc.url and not doc.url.startswith(("http://", "https://")):
        errors.append(f"url not absolute: {doc.url!r}")
    if doc.text and not doc.text.strip():
        errors.append("empty text")
    if _CHUNK_ID_RE.match(doc.chunk_id) is None:
        errors.append(f"malformed chunk_id: {doc.chunk_id!r}")
    if source_ids is not None and doc.source_id not in source_ids:
        errors.append(f"source_id {doc.source_id!r} not in source registry")
    return errors


def normalize_record(raw: dict, *, source_ids: set[str] | None = None) -> SciDocument:
    """Coerce a raw dict into a validated SciDocument (raises SchemaError).

    Unknown metadata stays None/"" — this function NEVER invents values."""
    doc = SciDocument.from_dict({**{
        k: raw.get(k) for k in SciDocument.__dataclass_fields__}})
    for opt in OPTIONAL_RESEARCH_FIELDS:
        if getattr(doc, opt) in ("", []):
            setattr(doc, opt, None)
    if not doc.checksum:
        doc.checksum = chunk_checksum(doc)
    errors = validate_document(doc, source_ids=source_ids)
    if errors:
        raise SchemaError(
            f"document {doc.document_id or '<no id>'}: {'; '.join(errors)}")
    return doc