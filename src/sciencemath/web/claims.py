"""T16.11–T16.12 — claim model and claim/evidence graph.

A claim without evidence must not silently become SUPPORTED.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

SUPPORTED = "SUPPORTED"
SUPPORTED_WITH_CAVEAT = "SUPPORTED_WITH_CAVEAT"
CONTESTED = "CONTESTED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CONTRADICTED = "CONTRADICTED"
INFERRED = "INFERRED"

CLAIM_STATUSES = (
    SUPPORTED, SUPPORTED_WITH_CAVEAT, CONTESTED, INSUFFICIENT_EVIDENCE,
    CONTRADICTED, INFERRED,
)

CLAIM_TYPES = (
    "FACT", "DATE", "ATTRIBUTE", "NUMERIC", "STATUS", "DEFINITION",
    "INFERENCE",
)


@dataclass
class EvidenceEdge:
    source_id: str
    source_span: str
    support_type: str  # supported_by | contradicted_by
    entailment_status: str
    evidence_id: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Claim:
    claim_id: str
    claim_text: str
    claim_type: str = "FACT"
    time_scope: str = "UNKNOWN"
    confidence: str = "UNCERTAIN"
    evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    status: str = INSUFFICIENT_EVIDENCE

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClaimGraph:
    claims: list[Claim] = field(default_factory=list)
    supported_by: list[EvidenceEdge] = field(default_factory=list)
    contradicted_by: list[EvidenceEdge] = field(default_factory=list)

    def add_support(self, claim: Claim, edge: EvidenceEdge) -> None:
        if claim not in self.claims:
            self.claims.append(claim)
        if edge.evidence_id not in claim.evidence_ids:
            claim.evidence_ids.append(edge.evidence_id)
        self.supported_by.append(edge)

    def add_contradiction(self, claim: Claim, edge: EvidenceEdge) -> None:
        if claim not in self.claims:
            self.claims.append(claim)
        if edge.evidence_id not in claim.contradicting_evidence_ids:
            claim.contradicting_evidence_ids.append(edge.evidence_id)
        self.contradicted_by.append(edge)

    def finalize(self) -> None:
        for c in self.claims:
            has_s = bool(c.evidence_ids)
            has_c = bool(c.contradicting_evidence_ids)
            if has_s and has_c:
                c.status = CONTESTED
                c.confidence = "CONTESTED"
            elif has_s and c.status == INSUFFICIENT_EVIDENCE:
                # only promote when edges were added as support
                c.status = SUPPORTED
                c.confidence = "SUPPORTED"
            elif has_c and not has_s:
                c.status = CONTRADICTED
                c.confidence = "CONTESTED"
            elif not has_s:
                c.status = INSUFFICIENT_EVIDENCE
                c.confidence = "INSUFFICIENT_EVIDENCE"

    def to_dict(self) -> dict:
        return {
            "claims": [c.to_dict() for c in self.claims],
            "supported_by": [e.to_dict() for e in self.supported_by],
            "contradicted_by": [e.to_dict() for e in self.contradicted_by],
        }
