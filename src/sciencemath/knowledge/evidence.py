"""T21.12 — typed KnowledgeEvidencePack.

The pack is the single handoff from retrieval to synthesis: it carries the
normalized query, eligibility decision, snapshot date, ranked evidence
items with provenance, detected conflicts, freshness status, coverage
status, overall confidence, and a route recommendation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sciencemath.knowledge.schema import KnowledgeChunk, KnowledgeSourceRecord


@dataclass
class EvidenceItem:
    """One ranked evidence item with full provenance (T21.12)."""

    source_id: str
    chunk_id: str
    title: str
    section: str
    text_span: str
    score: float
    rank: int
    authority_class: str
    content_hash: str
    citation_id: str
    source_license: str = ""
    freshness_class: str = "UNKNOWN"
    topic_tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "section": self.section,
            "text_span": self.text_span,
            "score": self.score,
            "rank": self.rank,
            "authority_class": self.authority_class,
            "content_hash": self.content_hash,
            "citation_id": self.citation_id,
            "source_license": self.source_license,
            "freshness_class": self.freshness_class,
            "topic_tags": list(self.topic_tags),
            "metadata": dict(self.metadata),
        }


def make_citation_id(query: str, chunk_id: str, rank: int) -> str:
    """Deterministic, mechanically resolvable citation ID.

    Binds query + chunk + rank: two citations are equal only when they
    point at the same evidence for the same query in the same rank slot.
    """
    key = json.dumps({"q": query, "c": chunk_id, "r": rank},
                     sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"C{rank}-{digest}"


def build_evidence_pack(
    *, query: str, normalized_query: str, eligibility: dict,
    retrieval_status: str, snapshot_date: str,
    items: list[EvidenceItem], conflicts: list[dict],
    freshness_status: dict, coverage_status: dict,
    overall_confidence: float, route_recommendation: str,
) -> "KnowledgeEvidencePack":
    pack = KnowledgeEvidencePack(
        query=query,
        normalized_query=normalized_query,
        eligibility=eligibility,
        retrieval_status=retrieval_status,
        snapshot_date=snapshot_date,
        evidence_items=items,
        conflicts=conflicts,
        freshness_status=freshness_status,
        coverage_status=coverage_status,
        overall_confidence=overall_confidence,
        route_recommendation=route_recommendation,
    )
    for rank, item in enumerate(pack.evidence_items, start=1):
        item.rank = rank
        item.citation_id = make_citation_id(normalized_query, item.chunk_id,
                                            rank)
    return pack


@dataclass
class KnowledgeEvidencePack:
    """Typed evidence handoff (T21.12 minimum fields)."""

    query: str
    normalized_query: str
    eligibility: dict
    retrieval_status: str
    snapshot_date: str
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    freshness_status: dict = field(default_factory=dict)
    coverage_status: dict = field(default_factory=dict)
    overall_confidence: float = 0.0
    route_recommendation: str = "ANSWER"

    @property
    def by_citation(self) -> dict[str, EvidenceItem]:
        return {it.citation_id: it for it in self.evidence_items}

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "normalized_query": self.normalized_query,
            "eligibility": dict(self.eligibility),
            "retrieval_status": self.retrieval_status,
            "snapshot_date": self.snapshot_date,
            "evidence_items": [it.to_dict() for it in self.evidence_items],
            "conflicts": [dict(c) for c in self.conflicts],
            "freshness_status": dict(self.freshness_status),
            "coverage_status": dict(self.coverage_status),
            "overall_confidence": self.overall_confidence,
            "route_recommendation": self.route_recommendation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeEvidencePack":
        items = [
            EvidenceItem(
                source_id=d["source_id"],
                chunk_id=d["chunk_id"],
                title=d["title"],
                section=d["section"],
                text_span=d["text_span"],
                score=d["score"],
                rank=d["rank"],
                authority_class=d["authority_class"],
                content_hash=d["content_hash"],
                citation_id=d["citation_id"],
                source_license=d.get("source_license", ""),
                freshness_class=d.get("freshness_class", "UNKNOWN"),
                topic_tags=list(d.get("topic_tags") or []),
                metadata=dict(d.get("metadata") or {}),
            )
            for d in (data.get("evidence_items") or [])
        ]
        return cls(
            query=data["query"],
            normalized_query=data["normalized_query"],
            eligibility=dict(data.get("eligibility") or {}),
            retrieval_status=data["retrieval_status"],
            snapshot_date=data["snapshot_date"],
            evidence_items=items,
            conflicts=list(data.get("conflicts") or []),
            freshness_status=dict(data.get("freshness_status") or {}),
            coverage_status=dict(data.get("coverage_status") or {}),
            overall_confidence=float(data.get("overall_confidence") or 0.0),
            route_recommendation=data.get("route_recommendation", "ANSWER"),
        )


def items_from_chunks(
    ranked: list[tuple[str, float]],
    chunks_by_id: dict[str, KnowledgeChunk],
    sources_by_id: dict[str, KnowledgeSourceRecord],
    normalized_query: str,
) -> list[EvidenceItem]:
    """Project ranked (chunk_id, score) pairs into provenance-carrying
    EvidenceItems. Unknown chunk IDs are dropped (fail-closed provenance)."""
    out: list[EvidenceItem] = []
    for rank, (chunk_id, score) in enumerate(ranked, start=1):
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        source = sources_by_id.get(chunk.source_id)
        if source is None:
            continue
        out.append(EvidenceItem(
            source_id=chunk.source_id,
            chunk_id=chunk.chunk_id,
            title=source.source_title,
            section=chunk.section,
            text_span=chunk.text,
            score=score,
            rank=rank,
            authority_class=source.authority_class,
            content_hash=chunk.content_hash,
            citation_id=make_citation_id(normalized_query, chunk.chunk_id,
                                         rank),
            source_license=source.license,
            freshness_class=source.freshness_class,
            topic_tags=list(source.topic_tags),
            metadata=dict(chunk.metadata),
        ))
    return out