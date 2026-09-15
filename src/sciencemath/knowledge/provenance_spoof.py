"""T21R3 — query-side provenance spoof rejection.

User-provided citation / source / chunk IDs are NOT provenance. Only
retrieved, corpus-validated evidence may establish citation authority.
This module extracts concrete IDs claimed in the query and rejects any
that do not exist in the loaded corpus.

Harmless discussion of citation *syntax* (no concrete ID token) is not
flagged.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sciencemath.knowledge.corpus import KnowledgeCorpus

# Concrete source id: gk- + 12 hex digits.
_SOURCE_ID_RE = re.compile(r"\bgk-([0-9a-f]{12})\b", re.IGNORECASE)
# Concrete chunk id: gk-xxxxxxxxxxxx:<token>
_CHUNK_ID_RE = re.compile(
    r"\b(gk-[0-9a-f]{12}:[A-Za-z0-9_.:-]+)\b", re.IGNORECASE)
# Emitted citation form C12-ab12cd34ef (rank + content hash prefix).
_CITATION_ID_RE = re.compile(r"\b(C\d+-[0-9a-f]{8,})\b", re.IGNORECASE)

# Phrases that treat a user-supplied id as authoritative evidence.
_PROVENANCE_CLAIM_CUES = re.compile(
    r"(?:according to|per|from|cite|citing|use|trust|reference|see)\b",
    re.IGNORECASE,
)


def extract_claimed_ids(query: str) -> dict[str, list[str]]:
    """Extract concrete source/chunk/citation ID tokens from ``query``."""
    chunks = [m.group(1) for m in _CHUNK_ID_RE.finditer(query)]
    # Source ids that are not already the prefix of a claimed chunk id.
    chunk_prefixes = {c.split(":", 1)[0].lower() for c in chunks}
    sources = []
    for m in _SOURCE_ID_RE.finditer(query):
        sid = f"gk-{m.group(1).lower()}"
        if sid not in chunk_prefixes:
            sources.append(sid)
    citations = [m.group(1) for m in _CITATION_ID_RE.finditer(query)]
    return {
        "source_ids": sources,
        "chunk_ids": [c.lower() if c.lower().startswith("gk-") else c
                      for c in chunks],
        "citation_ids": citations,
    }


def scan_provenance_spoof(query: str, corpus: KnowledgeCorpus) -> dict:
    """Reject nonexistent / user-forced provenance claims.

    Returns a report with ``flagged`` True when the query claims at least
    one concrete ID that is not present in ``corpus``. Citation-form IDs
    claimed in the query are always rejected (they are runtime-emitted
    labels, never user-supplied evidence).
    """
    claimed = extract_claimed_ids(query)
    fake_sources: list[str] = []
    fake_chunks: list[str] = []
    fake_citations: list[str] = list(claimed["citation_ids"])

    for sid in claimed["source_ids"]:
        if corpus.source(sid) is None:
            # Case-insensitive fallback for hex ids.
            if not any(s.lower() == sid.lower()
                       for s in corpus.sources_by_id):
                fake_sources.append(sid)
    for cid in claimed["chunk_ids"]:
        if corpus.chunk(cid) is None:
            if not any(existing.lower() == cid.lower()
                       for existing in corpus.chunks_by_id):
                fake_chunks.append(cid)

    # Only treat ID tokens as spoof when they appear as provenance claims
    # OR when a nonexistent chunk/source id is present (always unsafe).
    has_fake = bool(fake_sources or fake_chunks or fake_citations)
    cue = bool(_PROVENANCE_CLAIM_CUES.search(query))
    # Nonexistent concrete IDs are always rejected; existent IDs mentioned
    # without a provenance cue are allowed (harmless discussion / echo).
    flagged = bool(fake_sources or fake_chunks) or (
        bool(fake_citations) and cue)

    return {
        "flagged": flagged,
        "claimed": claimed,
        "fake_sources": fake_sources,
        "fake_chunks": fake_chunks,
        "fake_citations": fake_citations,
        "reason": ("nonexistent_source_or_chunk_id" if (
                       fake_sources or fake_chunks)
                   else "user_supplied_citation_id" if flagged
                   else "none"),
    }
