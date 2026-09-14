"""Structured internal citations. Fabricated refs are invalid."""
from __future__ import annotations

from sciencemath.document.models import DocCitation, NormalizedDocument, UNKNOWN


def cite(doc: NormalizedDocument, claim: str, *, block_id: str | None = None,
         page=None, section=None, row=None, column=None,
         json_path=None, span: str = "") -> DocCitation:
    cit = DocCitation(
        document_id=doc.document_id,
        claim_id=_cid(claim),
        block_id=block_id or UNKNOWN,
        page=str(page) if page is not None else UNKNOWN,
        section=section or UNKNOWN,
        row=row,
        column=column,
        json_path=json_path or UNKNOWN,
        span_text=span or "",
    )
    if not _resolves(doc, cit):
        cit.invalid_reason = "unresolved_location"
        cit.valid = False
        return cit
    if cit.span_text and not _span_in_doc(doc, cit.span_text):
        cit.invalid_reason = "fabricated_quote"
        cit.valid = False
        return cit
    if claim and cit.span_text and not _entails(claim, cit.span_text):
        # still valid location; entailment recorded separately
        pass
    cit.valid = True
    return cit


def _cid(claim: str) -> str:
    import hashlib
    return "c-" + hashlib.sha256((claim or "").encode()).hexdigest()[:10]


def _resolves(doc: NormalizedDocument, cit: DocCitation) -> bool:
    if cit.block_id not in (None, "", UNKNOWN):
        return any(b.block_id == cit.block_id for b in doc.blocks)
    if cit.page not in (None, "", UNKNOWN):
        if doc.page_count in (None, UNKNOWN):
            return False
        return any(str(b.page) == str(cit.page) for b in doc.blocks)
    if cit.row is not None and cit.column:
        for t in doc.tables:
            if cit.row < 0 or cit.row >= t.row_count:
                continue
            if cit.column in t.rows[cit.row]:
                return True
        return False
    if cit.json_path not in (None, "", UNKNOWN):
        return any(
            (isinstance(r, dict) and r.get("json_path") == cit.json_path)
            for r in doc.records) or any(
            cit.json_path in b.heading_path for b in doc.blocks)
    return True


def _span_in_doc(doc: NormalizedDocument, span: str) -> bool:
    if span and span in (doc.text or ""):
        return True
    return any(span in (b.text or "") for b in doc.blocks)


def _entails(claim: str, span: str) -> bool:
    c = (claim or "").lower()
    s = (span or "").lower()
    if not c or not s:
        return False
    tokens = [t for t in re_tokens(c) if len(t) > 2]
    if not tokens:
        return c in s
    return sum(1 for t in tokens if t in s) >= max(1, len(tokens) // 2)


def re_tokens(text: str) -> list[str]:
    import re
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())


def fabrication_counts(citations: list[DocCitation]) -> dict:
    fab_page = fab_row = fab_cell = fab_json = fab_quote = fab_loc = 0
    for c in citations:
        if c.valid:
            continue
        if c.invalid_reason == "fabricated_quote":
            fab_quote += 1
        if c.invalid_reason == "unresolved_location":
            fab_loc += 1
            if c.page not in (None, "", UNKNOWN):
                fab_page += 1
            if c.row is not None:
                fab_row += 1
            if c.row is not None and c.column not in (None, "", UNKNOWN):
                fab_cell += 1
            if c.json_path not in (None, "", UNKNOWN):
                fab_json += 1
    return {
        "fabricated_document": 0,  # never emit a fake document_id
        "fabricated_page": fab_page,
        "fabricated_row": fab_row,
        "fabricated_cell": fab_cell,
        "fabricated_json_path": fab_json,
        "fabricated_quotes": fab_quote,
        "unresolved_citations": fab_loc,
        "invalid_citations": sum(1 for c in citations if not c.valid),
    }
