"""Exact keyword / phrase / heading / field / JSON-path search (no model)."""
from __future__ import annotations

import re

from sciencemath.document.limits import DocumentLimits
from sciencemath.document.models import NormalizedDocument


def search_document(doc: NormalizedDocument, query: str, *,
                    mode: str = "keyword",
                    limits: DocumentLimits | None = None) -> list[dict]:
    limits = limits or DocumentLimits()
    q = (query or "").strip()
    if not q:
        return []
    hits = []
    if mode == "json_path":
        for rec in doc.records:
            path = rec.get("json_path") if isinstance(rec, dict) else None
            if path == q or (path and path.endswith(q)):
                hits.append({"kind": "json_path", "json_path": path,
                             "value": rec.get("raw_value"),
                             "document_id": doc.document_id})
        for b in doc.blocks:
            if b.block_type == "json_value" and q in b.heading_path:
                hits.append({"kind": "json_path", "block_id": b.block_id,
                             "text": b.text, "document_id": doc.document_id})
        return hits[: limits.max_search_hits]
    if mode == "heading":
        for b in doc.blocks:
            if b.block_type == "heading" and q.lower() in b.text.lower():
                hits.append(_hit(doc, b, "heading"))
        return hits[: limits.max_search_hits]
    if mode == "column":
        for t in doc.tables:
            for spec in t.columns:
                if spec.name.lower() == q.lower():
                    hits.append({"kind": "column", "table": t.table_name,
                                 "column": spec.name,
                                 "document_id": doc.document_id})
        return hits[: limits.max_search_hits]
    if mode == "field":
        for t in doc.tables:
            for i, row in enumerate(t.rows):
                for col, cell in row.items():
                    if col.lower() == q.lower() or (
                            cell.raw_value and q.lower() in str(cell.raw_value).lower()):
                        hits.append({
                            "kind": "field", "table": t.table_name,
                            "row": i, "column": col,
                            "raw_value": cell.raw_value,
                            "document_id": doc.document_id,
                        })
                        if len(hits) >= limits.max_search_hits:
                            return hits
        return hits
    # keyword / phrase: exact for phrase
    phrase = mode == "phrase"
    needle = q if phrase else q.lower()
    for b in doc.blocks:
        hay = b.text if phrase else (b.text or "").lower()
        if needle and needle in hay:
            hits.append(_hit(doc, b, mode))
            if len(hits) >= limits.max_search_hits:
                break
    return hits


def _hit(doc, block, kind: str) -> dict:
    return {
        "kind": kind,
        "document_id": doc.document_id,
        "block_id": block.block_id,
        "page": block.page,
        "section": block.section,
        "heading_path": list(block.heading_path),
        "text": block.text,
        "content_hash": block.content_hash,
    }


def lookup_page(doc: NormalizedDocument, page) -> list[dict]:
    want = str(page)
    if want.upper() == "UNKNOWN" or doc.page_count == "UNKNOWN":
        return []
    return [_hit(doc, b, "page") for b in doc.blocks if str(b.page) == want]
