"""T16.15–T16.16 — citation integrity at claim granularity.

Critical fabrication tolerance: 0.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sciencemath.web.entailment import citable, entailment


@dataclass
class Citation:
    claim_id: str
    source_id: str
    url: str
    title: str
    evidence_id: str
    span_text: str
    entailment_status: str
    valid: bool = False
    invalid_reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def cite_claim(claim_id: str, claim_text: str, source, span_text: str,
               evidence_id: str, *, fetched_ids: set[str]) -> Citation:
    cit = Citation(
        claim_id=claim_id,
        source_id=getattr(source, "source_id", ""),
        url=getattr(source, "url", ""),
        title=getattr(source, "title", ""),
        evidence_id=evidence_id,
        span_text=span_text,
        entailment_status=entailment(claim_text, span_text),
    )
    sid = cit.source_id
    content = getattr(source, "content", "") or ""
    if sid not in fetched_ids:
        cit.invalid_reason = "fabricated: source was not fetched"
    elif sid.startswith("missing:") or getattr(source, "fetch_status", "") \
            in ("NOT_FOUND", "ERROR", "BLOCKED"):
        cit.invalid_reason = "citation to inaccessible source"
    elif span_text and span_text not in content:
        cit.invalid_reason = "fabricated_quote"
    elif not citable(cit.entailment_status):
        cit.invalid_reason = "citation attached to unsupported claim"
    else:
        cit.valid = True
    return cit


def fabrication_counts(citations: list[Citation]) -> dict:
    fab_src = sum(1 for c in citations
                  if c.invalid_reason and "fabricated: source" in c.invalid_reason)
    fab_quote = sum(1 for c in citations if c.invalid_reason == "fabricated_quote")
    fab_cit = sum(1 for c in citations if c.invalid_reason)
    unsupported = sum(
        1 for c in citations
        if c.invalid_reason == "citation attached to unsupported claim")
    return {
        "fabricated_sources": fab_src,
        "fabricated_citations": fab_cit,
        "fabricated_quotes": fab_quote,
        "unsupported_claims_marked_supported": unsupported,
    }
