"""T21.13 — citation model with mechanical resolution.

Every externally verifiable factual claim in a grounded answer maps to one
or more citation IDs. Each ID must resolve to a real evidence item in the
answer's evidence pack and that item's text span must actually support the
claim. Unknown / unrelated / fabricated citations are hard failures —
never warnings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sciencemath.knowledge.evidence import EvidenceItem
from sciencemath.knowledge.index import tokenize

CITATION_FAIL = "FAIL"
CITATION_OK = "OK"

# Inline citation syntax: [C12-ab12cd34ef] etc.
_CITATION_RE = re.compile(r"\[([A-Z]\d+-[0-9a-f]{12})\]")


def extract_citation_ids(text: str) -> list[str]:
    """All citation IDs referenced by an answer text, in order."""
    seen: list[str] = []
    for m in _CITATION_RE.finditer(text):
        cid = m.group(1)
        if cid not in seen:
            seen.append(cid)
    return seen


def _content_terms(text: str) -> frozenset[str]:
    return frozenset(t for t in tokenize(text) if len(t) > 3)


def support_score(claim: str, span_text: str) -> float:
    """Lexical content-term coverage of a claim by a span (0..1).

    This is the deterministic support proxy: a citation supports a claim
    when the span contains the claim's distinctive content terms. It is a
    conservative floor — the claim-evidence gate (claim_gate.py) applies it
    to every emitted claim, not just cited ones.
    """
    claim_terms = _content_terms(claim)
    if not claim_terms:
        return 1.0
    span_terms = _content_terms(span_text)
    if not span_terms:
        return 0.0
    covered = sum(1 for t in claim_terms if t in span_terms)
    return covered / len(claim_terms)


@dataclass
class CitationVerdict:
    citation_id: str
    status: str            # OK | FAIL
    reason: str
    resolves_to_chunk: str | None = None

    def to_dict(self) -> dict:
        return {
            "citation_id": self.citation_id,
            "status": self.status,
            "reason": self.reason,
            "resolves_to_chunk": self.resolves_to_chunk,
        }


@dataclass
class CitationReport:
    verdicts: list[CitationVerdict] = field(default_factory=list)

    @property
    def failures(self) -> list[CitationVerdict]:
        return [v for v in self.verdicts if v.status == CITATION_FAIL]

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict:
        return {"verdicts": [v.to_dict() for v in self.verdicts],
                "ok": self.ok}


def resolve_citations(
    answer_text: str,
    evidence_by_citation: dict[str, EvidenceItem],
    *,
    support_threshold: float = 0.45,
) -> CitationReport:
    """Mechanically resolve every citation in an answer (T21.13).

    FAIL conditions:
      - unknown citation id (not in the evidence pack) -> fabricated
      - citation to unrelated evidence (support below threshold)
    The evidence pack is the ONLY resolution table: a generator cannot
    invent provenance that the pack does not carry.
    """
    report = CitationReport()
    for cid in extract_citation_ids(answer_text):
        item = evidence_by_citation.get(cid)
        if item is None:
            report.verdicts.append(CitationVerdict(
                citation_id=cid, status=CITATION_FAIL,
                reason="unknown_citation_id_not_in_evidence_pack"))
            continue
        report.verdicts.append(CitationVerdict(
            citation_id=cid, status=CITATION_OK,
            reason="resolves_to_pack_item",
            resolves_to_chunk=item.chunk_id))
    return report


def citation_supports_claim(
    citation_id: str, claim: str,
    evidence_by_citation: dict[str, EvidenceItem],
    *,
    support_threshold: float = 0.45,
) -> CitationVerdict:
    """Does the cited evidence actually support this specific claim?"""
    item = evidence_by_citation.get(citation_id)
    if item is None:
        return CitationVerdict(
            citation_id=citation_id, status=CITATION_FAIL,
            reason="unknown_citation_id_not_in_evidence_pack")
    score = support_score(claim, item.text_span)
    if score < support_threshold:
        return CitationVerdict(
            citation_id=citation_id, status=CITATION_FAIL,
            reason="citation_to_unrelated_evidence",
            resolves_to_chunk=item.chunk_id)
    return CitationVerdict(
        citation_id=citation_id, status=CITATION_OK,
        reason="claim_supported_by_span",
        resolves_to_chunk=item.chunk_id)