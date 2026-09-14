"""T21.14 — claim-evidence gate.

Every factual claim in a synthesized answer is classified against the
evidence pack:

  SUPPORTED            supported by one or more evidence items
  PARTIALLY_SUPPORTED  support below the confident threshold but nonzero
  UNSUPPORTED          no evidence item supports the claim (model-memory
                       backfill must never fill this gap — T21.21)
  CONTRADICTED         evidence items disagree on the claim
  NON_FACTUAL          connective/framing text, not an external claim

Only SUPPORTED factual claims may be emitted as confident factual
statements. PARTIALLY_SUPPORTED claims are qualified or removed.
UNSUPPORTED claims are removed (or trigger insufficient evidence).
CONTRADICTED claims are resolved by preregistered authority rules or the
answer becomes CONFLICTING_EVIDENCE.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sciencemath.knowledge.citations import support_score
from sciencemath.knowledge.evidence import EvidenceItem

SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
CONTRADICTED = "CONTRADICTED"
NON_FACTUAL = "NON_FACTUAL"

CLAIM_CLASSES = (SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, CONTRADICTED,
                 NON_FACTUAL)

# Thresholds (preregistered; frozen before FINAL — see floors.json).
SUPPORT_THRESHOLD = 0.45
PARTIAL_THRESHOLD = 0.30

# Sentence splitting keeps bracketed citation markers attached.
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
# A factual claim is one that asserts content beyond pure framing/connective
# text. Framing openers and meta-sentences are NON_FACTUAL.
_FRAMING_RE = re.compile(
    r"^(based on|according to|the evidence|the retrieved|the sources|"
    r"the corpus|insufficient evidence|this cannot be answered|i "
    r"(?:cannot|can't|do not)|no evidence|conflicting)\b", re.IGNORECASE)


def split_claims(answer_text: str) -> list[str]:
    cleaned = re.sub(r"\[([A-Z]\d+-[0-9a-f]{12})\]", "", answer_text)
    return [s.strip() for s in _SENT_RE.split(cleaned) if s.strip()]


@dataclass
class ClaimVerdict:
    claim: str
    classification: str
    best_score: float
    supporting_citation_ids: list[str] = field(default_factory=list)
    contradicting_citation_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "classification": self.classification,
            "best_score": self.best_score,
            "supporting_citation_ids": list(self.supporting_citation_ids),
            "contradicting_citation_ids": list(self.contradicting_citation_ids),
        }


def classify_claim(
    claim: str, items: list[EvidenceItem], *,
    support_threshold: float = SUPPORT_THRESHOLD,
    partial_threshold: float = PARTIAL_THRESHOLD,
    conflicts: list[dict] | None = None,
) -> ClaimVerdict:
    if not claim:
        return ClaimVerdict(claim=claim, classification=NON_FACTUAL,
                            best_score=0.0)
    if _FRAMING_RE.match(claim.strip()):
        return ClaimVerdict(claim=claim, classification=NON_FACTUAL,
                            best_score=0.0)
    scores: list[tuple[float, str]] = []
    for item in items:
        s = support_score(claim, item.text_span)
        scores.append((s, item.citation_id))
    scores.sort(reverse=True)
    best = scores[0][0] if scores else 0.0
    supporting = [cid for s, cid in scores if s >= support_threshold]
    partial = [cid for s, cid in scores
               if partial_threshold <= s < support_threshold]

    contradicted = False
    for conflict in conflicts or []:
        overlap = support_score(conflict.get("claim_key", ""), claim)
        if overlap >= support_threshold:
            contradicted = True
            break

    if contradicted:
        classification = CONTRADICTED
    elif supporting:
        classification = SUPPORTED
    elif partial:
        classification = PARTIALLY_SUPPORTED
    else:
        classification = UNSUPPORTED
    return ClaimVerdict(
        claim=claim,
        classification=classification,
        best_score=best,
        supporting_citation_ids=supporting,
        contradicting_citation_ids=[
            c.get("evidence_b", {}).get("citation_id", "")
            for c in (conflicts or []) if contradicted])


def review_answer(
    answer_text: str, items: list[EvidenceItem],
    conflicts: list[dict] | None = None,
) -> dict:
    """Gate an entire answer text claim-by-claim (T21.14 policy)."""
    verdicts = [classify_claim(c, items, conflicts=conflicts)
                for c in split_claims(answer_text)]
    counts = {cls: 0 for cls in CLAIM_CLASSES}
    for v in verdicts:
        counts[v.classification] += 1
    unsupported_confident = [
        v.claim for v in verdicts
        if v.classification in (UNSUPPORTED, CONTRADICTED)]
    return {
        "verdicts": [v.to_dict() for v in verdicts],
        "counts": counts,
        "unsupported_confident_claims": unsupported_confident,
        "all_claims_supported": not unsupported_confident
        and counts[SUPPORTED] + counts[NON_FACTUAL] > 0,
    }