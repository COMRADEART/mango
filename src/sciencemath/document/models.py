"""Normalized document, text-block, and tabular models with provenance."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, is_dataclass

UNKNOWN = "UNKNOWN"

PARSE_OK = "OK"
PARSE_WARNING = "WARNING"
PARSE_MALFORMED = "MALFORMED"
PARSE_EMPTY = "EMPTY"
PARSE_NEEDS_OCR = "NEEDS_OCR"
PARSE_UNSUPPORTED = "UNSUPPORTED"
PARSE_BLOCKED = "BLOCKED"

STRING = "STRING"
INTEGER = "INTEGER"
FLOAT = "FLOAT"
BOOLEAN = "BOOLEAN"
DATE = "DATE"
DATETIME = "DATETIME"
NULLABLE = "NULLABLE"
MIXED = "MIXED"
NULL_TYPE = "NULL"

MISSING_KINDS = (
    "PRESENT", "EMPTY", "NULL", "ZERO", "FALSE", "NAN", "NOT_PRESENT",
)


def content_sha(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _u(value) -> str:
    if value is None:
        return UNKNOWN
    v = str(value).strip()
    return v if v else UNKNOWN


@dataclass
class TextBlock:
    document_id: str
    block_id: str
    block_type: str
    text: str
    page: str = UNKNOWN
    section: str = UNKNOWN
    heading_path: tuple[str, ...] = ()
    paragraph_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    parent_block_id: str | None = None
    content_hash: str = UNKNOWN

    def __post_init__(self) -> None:
        if self.content_hash in ("", UNKNOWN):
            self.content_hash = content_sha(self.text or "")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["heading_path"] = list(self.heading_path)
        return d


@dataclass
class CellValue:
    raw_value: str | None
    interpreted_value: object
    inferred_type: str
    missing_kind: str = "PRESENT"
    source: str = UNKNOWN
    row: int | None = None
    column: str | None = None
    json_path: str = UNKNOWN
    formula_like: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ColumnSpec:
    name: str
    inferred_type: str
    nullable: bool = False
    null_count: int = 0
    unique_count: int | None = None
    original_name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Dataset:
    dataset_id: str
    source_document_id: str
    table_name: str
    columns: list[ColumnSpec]
    rows: list[dict[str, CellValue]]
    row_count: int = 0
    column_count: int = 0
    inferred_types: dict[str, str] = field(default_factory=dict)
    null_counts: dict[str, int] = field(default_factory=dict)
    primary_key_candidate: str | None = None
    schema_hash: str = UNKNOWN
    warnings: list[str] = field(default_factory=list)
    derived: bool = False
    source_row_ids: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.row_count = len(self.rows)
        self.column_count = len(self.columns)
        if not self.inferred_types:
            self.inferred_types = {c.name: c.inferred_type for c in self.columns}
        if not self.null_counts:
            self.null_counts = {c.name: c.null_count for c in self.columns}
        if self.schema_hash in ("", UNKNOWN):
            blob = "|".join(f"{c.name}:{c.inferred_type}" for c in self.columns)
            self.schema_hash = content_sha(blob)

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "source_document_id": self.source_document_id,
            "table_name": self.table_name,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": [c.to_dict() for c in self.columns],
            "inferred_types": self.inferred_types,
            "null_counts": self.null_counts,
            "primary_key_candidate": self.primary_key_candidate,
            "schema_hash": self.schema_hash,
            "warnings": list(self.warnings),
            "derived": self.derived,
            "source_row_ids": list(self.source_row_ids),
            "row_provenance": [
                {k: v.to_dict() for k, v in row.items()} for row in self.rows
            ],
        }


@dataclass
class NormalizedDocument:
    document_id: str
    filename: str
    file_type: str
    mime_type: str
    content_hash: str
    size_bytes: int
    parser_name: str
    parse_status: str
    parser_version: str = "t17-document-v1"
    page_count: str | int = UNKNOWN
    sheet_count: str | int = UNKNOWN
    encoding: str = UNKNOWN
    language: str = UNKNOWN
    metadata: dict = field(default_factory=dict)
    sections: list[str] = field(default_factory=list)
    blocks: list[TextBlock] = field(default_factory=list)
    tables: list[Dataset] = field(default_factory=list)
    records: list[dict] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    raw_bytes: bytes = field(default=b"", repr=False)
    text: str = ""

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "mime_type": self.mime_type,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "page_count": self.page_count,
            "sheet_count": self.sheet_count,
            "encoding": self.encoding,
            "language": self.language,
            "metadata": dict(self.metadata),
            "sections": list(self.sections),
            "tables": [t.to_dict() for t in self.tables],
            "records": list(self.records),
            "parse_warnings": list(self.parse_warnings),
            "parse_status": self.parse_status,
            "block_count": len(self.blocks),
            "text": self.text,
        }


@dataclass
class DocCitation:
    document_id: str
    claim_id: str
    block_id: str = UNKNOWN
    page: str = UNKNOWN
    section: str = UNKNOWN
    row: int | None = None
    column: str | None = None
    json_path: str = UNKNOWN
    span_text: str = ""
    valid: bool = False
    invalid_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def dump(obj) -> dict:
    if is_dataclass(obj) and not isinstance(obj, type):
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return asdict(obj)
    return obj
