"""File-type identification. Never fake a parser."""
from __future__ import annotations

from pathlib import Path

from sciencemath.document.limits import FREE_LOCAL
from sciencemath.document.safety import ARCHIVE_EXT, BINARY_EXT, IMAGE_EXT, MACRO_EXT

EXT_MAP = {
    ".txt": ("txt", "text/plain", "TxtParser"),
    ".md": ("md", "text/markdown", "MarkdownParser"),
    ".markdown": ("md", "text/markdown", "MarkdownParser"),
    ".json": ("json", "application/json", "JsonParser"),
    ".jsonl": ("jsonl", "application/jsonl", "JsonlParser"),
    ".csv": ("csv", "text/csv", "CsvParser"),
    ".tsv": ("tsv", "text/tab-separated-values", "TsvParser"),
    ".html": ("html", "text/html", "HtmlParser"),
    ".htm": ("html", "text/html", "HtmlParser"),
    ".pdf": ("pdf", "application/pdf", "PdfParser"),
    ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              "XlsxParser"),
}


def sniff_bytes(data: bytes, filename: str = "") -> dict:
    name = Path(filename or "").name
    ext = Path(name).suffix.lower()
    head = data[:16] if data else b""
    file_type = "unknown"
    mime = "application/octet-stream"
    parser = None
    requires_ocr = False
    unsupported = False
    reason = None

    if ext in ARCHIVE_EXT or head.startswith(b"PK\x03\x04") and ext in ARCHIVE_EXT:
        unsupported = True
        file_type = "archive"
        reason = "archive_unsupported"
    elif ext in MACRO_EXT:
        unsupported = True
        file_type = "macro_office"
        reason = "macro_unsupported"
    elif ext in BINARY_EXT:
        unsupported = True
        file_type = "binary"
        reason = "binary_unsupported"
    elif ext == ".xlsx" or (
            head.startswith(b"PK") and ext == ".xlsx"):
        file_type, mime, parser = EXT_MAP[".xlsx"]
    elif head.startswith(b"%PDF") or ext == ".pdf":
        file_type, mime, parser = EXT_MAP[".pdf"]
    elif ext in EXT_MAP:
        file_type, mime, parser = EXT_MAP[ext]
    elif ext in IMAGE_EXT or head.startswith(b"\x89PNG") or head[:3] == b"\xff\xd8\xff":
        file_type = "image"
        mime = "image/*"
        requires_ocr = True
        reason = "image_only"
    elif not data:
        file_type = ext.lstrip(".") or "empty"
        reason = "empty"
        if ext in EXT_MAP:
            file_type, mime, parser = EXT_MAP[ext]
    else:
        # sniff text-ish JSON/CSV
        sample = data[:200].lstrip()
        if sample.startswith(b"{") or sample.startswith(b"["):
            file_type, mime, parser = EXT_MAP[".json"]
        elif b"," in sample and ext == "":
            file_type, mime, parser = EXT_MAP[".csv"]
        else:
            unsupported = True
            file_type = ext.lstrip(".") or "unknown"
            reason = "unsupported_type"

    return {
        "filename": name or "UNKNOWN",
        "file_type": file_type,
        "mime_type": mime,
        "parser_name": parser or "NONE",
        "supports": parser is not None and not unsupported and not requires_ocr,
        "cost_class": FREE_LOCAL,
        "requires_network": False,
        "requires_ocr": requires_ocr,
        "unsupported": unsupported,
        "reason": reason,
        "size_bytes": len(data),
    }


def identify_file(path: str | Path | None = None, *,
                  data: bytes | None = None, filename: str = "") -> dict:
    if data is None:
        if path is None:
            return sniff_bytes(b"", filename)
        p = Path(path)
        filename = filename or p.name
        try:
            data = p.read_bytes()
        except OSError:
            return {
                "filename": filename, "file_type": "unknown",
                "mime_type": "application/octet-stream", "parser_name": "NONE",
                "supports": False, "cost_class": FREE_LOCAL,
                "requires_network": False, "requires_ocr": False,
                "unsupported": True, "reason": "unreadable", "size_bytes": 0,
            }
    return sniff_bytes(data, filename)
