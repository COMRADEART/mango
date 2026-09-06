"""citations — citation provenance enforcement (T5.12/T5.20).

A citation is VALID only if BOTH hold:
  1. the cited chunk was actually retrieved and supplied to the
     answering stage (provenance check — deterministic),
  2. the cited chunk supports the associated claim (support check —
     deterministic term/number-coverage proxy here; a model-based check
     can be added later without changing this contract).

Fabricated citations are never valid: citing a chunk that was not in
the retrieval result — or an unknown chunk id / wrong source id — fails
closed. This module is the single source of truth for that decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_CITATION_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class Citation:
    """One citation attached to an answer claim."""
    chunk_id: str
    source_id: str
    title: str
    url: str
    support: str            # the claim the citation supports
    retrieval_score: float | None = None
    rerank_score: float | None = None
    # validation outcome (filled by verify_citation)
    valid: bool = False
    invalid_reason: str | None = None


@dataclass
class CitationReport:
    citations: list[Citation] = field(default_factory=list)
    fabricated: list[Citation] = field(default_factory=list)
    unsupported: list[Citation] = field(default_factory=list)
    valid: list[Citation] = field(default_factory=list)

    @property
    def all_valid(self) -> bool:
        return bool(self.citations) and not self.fabricated and not self.unsupported


def claim_support_score(claim: str, chunk_text: str) -> float:
    """Deterministic support proxy: coverage of the claim's content
    terms (>=3 chars, lowercased) in the chunk, weighted; numbers in
    the claim MUST appear in the chunk to count as numeric support.
    Returns 0.0..1.0."""
    if not claim.strip() or not chunk_text.strip():
        return 0.0
    claim_terms = {t.lower() for t in _CITATION_TOKEN_RE.findall(claim)}
    chunk_lower = chunk_text.lower()
    if not claim_terms:
        return 0.0
    covered = sum(1 for t in claim_terms if t in chunk_lower)
    base = covered / len(claim_terms)
    numbers = _NUMBER_RE.findall(claim)
    if numbers:
        num_ok = all(n in chunk_lower for n in numbers)
        base = min(base, 1.0) if num_ok else base * 0.5
    return round(base, 3)


def verify_citation(citation: Citation, retrieved_chunks: dict[str, dict],
                    *, support_threshold: float = 0.45) -> Citation:
    """Validate one citation against the ACTUALLY retrieved chunk set.

    retrieved_chunks: {chunk_id: chunk} exactly what was supplied to the
    answering stage — nothing else may be cited (no post-filter
    citations, no registry lookups)."""
    chunk = retrieved_chunks.get(citation.chunk_id)
    if chunk is None:
        citation.valid = False
        citation.invalid_reason = "fabricated: chunk was not retrieved"
        return citation
    if citation.source_id and chunk.get("source_id") != citation.source_id:
        citation.valid = False
        citation.invalid_reason = (
            f"wrong source id: chunk belongs to {chunk.get('source_id')!r}")
        return citation
    if citation.title and chunk.get("title") and \
            citation.title.lower() != chunk["title"].lower():
        citation.valid = False
        citation.invalid_reason = "title does not match retrieved chunk"
        return citation
    support = claim_support_score(citation.support, chunk.get("text", ""))
    if support < support_threshold:
        citation.valid = False
        citation.invalid_reason = (
            f"unsupported claim (support score {support:.2f} < "
            f"{support_threshold:.2f})")
        return citation
    citation.valid = True
    citation.retrieval_score = citation.retrieval_score if \
        citation.retrieval_score is not None else chunk.get("score")
    return citation


def verify_answer_citations(answer: str, cited: list[Citation],
                            retrieved_chunks: dict[str, dict],
                            *, support_threshold: float = 0.45) -> CitationReport:
    """Verify every citation attached to an answer. A citation claiming
    to support something the answer does not contain is still checked
    for provenance (fabricated) and support."""
    report = CitationReport(citations=list(cited))
    for c in cited:
        verify_citation(c, retrieved_chunks, support_threshold=support_threshold)
        if c.valid:
            report.valid.append(c)
        elif c.invalid_reason and c.invalid_reason.startswith("fabricated"):
            report.fabricated.append(c)
        else:
            report.unsupported.append(c)
    return report


# ---------------------------------------------------------------------------
# T5R.7/T5R.8 deterministic citation attachment
# ---------------------------------------------------------------------------

def compute_evidence_refs(answer: str, chunks: list[dict], *,
                          support_threshold: float = 0.45) -> list[int]:
    """T5R.8: which supplied chunks materially support the final answer?

    Claim-level (not per-sentence): a chunk earns a ref iff
    claim_support_score(answer, chunk_text) >= support_threshold. The
    model never invents citation syntax — this is computed from what it
    actually received and wrote. Deterministic."""
    refs: list[int] = []
    for i, chunk in enumerate(chunks):
        if claim_support_score(answer, chunk.get("text", "")) \
                >= support_threshold:
            refs.append(i)
    return refs


def validate_evidence_refs(refs: list[int], n_chunks: int) -> tuple[list[int], list[int]]:
    """T5R.7 fail-closed index validation: refs outside the supplied
    chunk range are INVALID (a model-supplied index can point at nothing
    — it is dropped and reported, never silently accepted)."""
    ok, invalid = [], []
    for r in refs:
        # bool is an int subclass but never a valid index — fail closed
        (ok if isinstance(r, int) and not isinstance(r, bool)
         and 0 <= r < n_chunks else invalid).append(r)
    return ok, invalid


def attach_deterministic_citations(
        answer: str, chunks: list[dict], refs: list[int], *,
        support_threshold: float = 0.45) -> dict:
    """T5R.7: the system, not the model, attaches citation markers.

    Model produces the answer text; the system maps evidence indices to
    source:chunk ids and renders the citation block. Refs are validated
    fail-closed (out-of-range indices are dropped and reported). Only
    chunks whose text materially supports the answer end up cited, and
    each ref is returned as a Citation object so verify_citation can
    independently re-check provenance + support.

    Returns {"answer_with_sources": str, "citations": [Citation],
             "invalid_refs": [int]}."""
    ok_refs, invalid = validate_evidence_refs(refs, len(chunks))
    answer_core = answer.strip()
    citations: list[Citation] = []
    seen: set[str] = set()
    lines: list[str] = []
    for i in ok_refs:
        chunk = chunks[i]
        cid = chunk.get("chunk_id", "?")
        if cid in seen:
            continue
        seen.add(cid)
        support = claim_support_score(answer_core, chunk.get("text", ""))
        if support < support_threshold:
            continue      # index was legal but the chunk does not support
        citations.append(Citation(
            chunk_id=cid, source_id=chunk.get("source_id", "?"),
            title=chunk.get("title", "?"), url=chunk.get("url", "?"),
            support=answer_core, retrieval_score=chunk.get("score"),
            rerank_score=chunk.get("rerank_score")))
        lines.append(f"{chunk.get('source_id', '?')}:{cid}")
    if lines:
        answer_with = (f"{answer_core}\nSources: "
                       + "; ".join(f"[{s}]" for s in lines))
    else:
        answer_with = answer_core
    return {"answer_with_sources": answer_with, "citations": citations,
            "invalid_refs": invalid}


def _support_sentence(answer: str, marker_start: int) -> str:
    """The claim a citation tag supports: the text immediately before the
    tag, cut at the previous sentence/line boundary (deterministic)."""
    start = max(0, marker_start - 320)
    seg = answer[start:marker_start].replace("\n", " ").strip()
    boundaries = list(re.finditer(r"[.!?]\s+", seg))
    if boundaries and boundaries[-1].end() < len(seg) - 1:
        seg = seg[boundaries[-1].end():]
    return seg.strip()


def parse_inline_citations(answer: str, retrieved_chunks: dict[str, dict]) -> list[Citation]:
    """Parse [chunk_id]-style inline citations out of an answer text.

    Each citation's support sentence is the text preceding the tag (cut
    at the previous sentence boundary) so verify_citation can measure
    whether the cited chunk actually supports the claim."""
    found: list[Citation] = []
    seen: set[str] = set()
    for m in re.finditer(r"\[([A-Za-z0-9_.:\-]{4,120})\]", answer):
        cid = m.group(1)
        if cid in seen:
            continue
        seen.add(cid)
        chunk = retrieved_chunks.get(cid, {})
        found.append(Citation(
            chunk_id=cid, source_id=chunk.get("source_id", "?"),
            title=chunk.get("title", "?"), url=chunk.get("url", "?"),
            support=_support_sentence(answer, m.start()),
        ))
    return found