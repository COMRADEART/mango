"""evidence — structured answer/evidence contract (T5.13-T5.15).

The internal answer representation Mango's answering stage produces:

    {"answer", "used_retrieval", "used_math_tools", "sources",
     "confidence", "uncertainty_reason", "evidence_state"}

Evidence states (T5.14) — never auto-promote ambiguity to SUPPORTED:
  SUPPORTED             retrieved chunks materially back the answer
  PARTIALLY_SUPPORTED   some support, gaps remain
  INSUFFICIENT_EVIDENCE retrieval provided no usable support
  CONFLICTING_EVIDENCE  retrieved sources materially disagree (T5.15)

Conflicting evidence (T5.15) is preserved, not resolved: both sides stay
in the record, ranked by authority/date/context, and the uncertainty is
reported. No artificial consensus.
"""
from __future__ import annotations

import re

from dataclasses import dataclass, field, asdict

from sciencemath.rag.citations import Citation, claim_support_score
from sciencemath.rag.chunking import estimate_tokens

EVIDENCE_STATES = ("SUPPORTED", "PARTIALLY_SUPPORTED",
                   "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE")


@dataclass
class EvidenceSource:
    """One retrieved source attached to an answer (audit-record shape)."""
    source_id: str
    title: str
    chunk_id: str
    url: str = ""
    section: str = ""
    domain: str = ""
    retrieval_score: float | None = None
    rerank_score: float | None = None
    support: str = ""
    support_score: float | None = None
    conflicts_with: list[str] = field(default_factory=list)  # chunk_ids

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceContract:
    """The structured internal answer (T5.13)."""
    answer: str
    used_retrieval: bool = False
    used_math_tools: bool = False
    sources: list[EvidenceSource] = field(default_factory=list)
    confidence: str = "medium"          # low | medium | high
    uncertainty_reason: str | None = None
    evidence_state: str = "INSUFFICIENT_EVIDENCE"
    math_tool_results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sources"] = [s.to_dict() if isinstance(s, EvidenceSource) else s
                        for s in self.sources]
        return d

    def visible_text(self) -> str:
        """Concise, evidence-based visible answer (no chain-of-thought).
        Adds a sources line only when retrieval materially contributed."""
        text = self.answer.strip()
        if self.used_retrieval and self.sources:
            titles = []
            for s in self.sources:
                label = s.title or s.source_id
                if label not in titles:
                    titles.append(label)
            text += "\n\nSources: " + "; ".join(titles)
        if self.evidence_state == "INSUFFICIENT_EVIDENCE":
            text = ("Evidence is insufficient to answer confidently. "
                    + text)
        elif self.evidence_state == "CONFLICTING_EVIDENCE":
            text = ("Retrieved sources give conflicting information. "
                    + text)
        return text


# -- evidence-state determination (deterministic) ---------------------------

def _authority_key(src: dict) -> float:
    """Simple authority/date ranking for conflicting evidence (T5.15):
    peer-reviewed/government > encyclopedia > preprint/other; newer > older."""
    score = 0.0
    st = (src.get("source_type") or "").lower()
    if "government" in st or "agency" in st:
        score += 3.0
    elif "textbook" in st:
        score += 2.5
    elif "encyclopedia" in st:
        score += 2.0
    elif "preprint" in st:
        score += 0.5
    status = (src.get("peer_review_status") or "").lower()
    if status == "peer_reviewed":
        score += 1.5
    year = src.get("publication_date") or ""
    if year[:4].isdigit():
        score += min(1.0, max(0.0, (int(year[:4]) - 2000) / 100.0))
    return score


def determine_evidence_state(
    chunks: list[dict], *,
    support_threshold: float = 0.45,
    conflict_threshold: float = 0.30,
    reference_answer: str | None = None,
) -> tuple[str, list[EvidenceSource], str | None]:
    """Classify what the retrieved evidence supports.

    reference_answer: when the caller has a known-correct answer (eval
    harness), support is measured against it; otherwise a bare
    heuristic (top chunk scores) applies. Returns (state, sources,
    uncertainty_reason)."""
    if not chunks:
        return "INSUFFICIENT_EVIDENCE", [], "no usable retrieved evidence"
    sources: list[EvidenceSource] = []
    for c in chunks:
        score = (claim_support_score(reference_answer, c.get("text", ""))
                 if reference_answer else None)
        sources.append(EvidenceSource(
            source_id=c.get("source_id", "?"),
            title=c.get("title", "?"),
            chunk_id=c.get("chunk_id", "?"),
            url=c.get("url", ""),
            section=c.get("section", ""),
            domain=c.get("domain", ""),
            retrieval_score=c.get("score"),
            rerank_score=c.get("rerank_score"),
            support_score=score))
    if reference_answer is None:
        # no ground truth available: threshold on retrieval scores only
        top = max((s.retrieval_score or 0.0) for s in sources)
        if top < 0.30:
            return ("INSUFFICIENT_EVIDENCE", sources,
                    f"top retrieval score {top:.2f} below confidence floor")
        if top < 0.55:
            return "PARTIALLY_SUPPORTED", sources, None
        return "SUPPORTED", sources, None
    # with a reference answer: support scores decide
    supported = [s for s in sources if (s.support_score or 0.0) >= support_threshold]
    if not supported:
        return ("INSUFFICIENT_EVIDENCE", sources,
                "no retrieved chunk covers the answer's content")
    if len(supported) == 1 and (supported[0].support_score or 0.0) < 0.7:
        return "PARTIALLY_SUPPORTED", sources, None
    return "SUPPORTED", sources, None


NEGATION_RX = re.compile(
    r"\b(?:does\s+not|did\s+not|do\s+not|is\s+not|are\s+not|"
    r"was\s+not|were\s+not|cannot|can\s+not|will\s+not|would\s+not|"
    r"should\s+not|no\s+longer|never|not|neither)\s+([a-z]+|\d+(?:\.\d+)?)")


def _negated_terms(text: str) -> set[str]:
    """Content terms bound to a negation marker, e.g. 'does not flow'
    -> {'flow'}; 'not 660 degrees' -> {'660'}; 'no longer classified'
    -> {'classified'}."""
    return set(NEGATION_RX.findall(text))


def detect_conflicts(chunks: list[dict]) -> list[tuple[str, str]]:
    """Pairwise conflict detection between retrieved chunks (T5.15).

    Deterministic heuristic: two chunks CONFLICT when they share the
    same subject matter AND one chunk NEGATES a term the other asserts
    (e.g. 'glass does not flow' vs 'glass flows'). Two guards keep
    precision high: function words ('that', 'with', ...) never count
    toward the shared-terms gate, and a bare negation token somewhere
    in one chunk is not enough — the negation must bind a term the
    other chunk actually asserts. Returns [(chunk_id_a, chunk_id_b)]."""
    _FUNCTION_WORDS = {
        "that", "this", "with", "which", "from", "have", "been", "were",
        "their", "they", "also", "such", "into", "than", "then", "when",
        "what", "where", "there", "these", "those", "other", "about",
        "after", "before", "under", "over", "more", "most", "only",
        "some", "many", "both", "each", "while", "since", "until",
        "because", "however", "between", "through", "during", "same",
        "very", "much", "well", "here", "will", "would", "could",
        "should", "called", "example", "often", "used", "using", "known",
    }
    conflicts: list[tuple[str, str]] = []
    for i in range(len(chunks)):
        for j in range(i + 1, len(chunks)):
            a, b = chunks[i], chunks[j]
            ta, tb = (a.get("text") or "").lower(), (b.get("text") or "").lower()
            if not ta or not tb:
                continue
            terms_a = {w for w in re.findall(r"[a-z]{4,}", ta)
                       if w not in _FUNCTION_WORDS}
            terms_b = {w for w in re.findall(r"[a-z]{4,}", tb)
                       if w not in _FUNCTION_WORDS}
            if len(terms_a & terms_b) < 3:
                continue
            words_a = set(re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", ta))
            words_b = set(re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", tb))

            def _hits(negated: set[str], asserted: set[str]) -> bool:
                for t in negated:
                    for u in asserted:
                        if t == u or (len(t) >= 4 and
                                      (t.startswith(u) or u.startswith(t))):
                            return True
                return False

            a_negates_b = _hits(_negated_terms(ta), words_b)
            b_negates_a = _hits(_negated_terms(tb), words_a)
            # mutual negation is also a conflict
            if a_negates_b or b_negates_a:
                conflicts.append((a.get("chunk_id", "?"),
                                  b.get("chunk_id", "?")))
    return conflicts


def build_contract(answer: str, *, chunks: list[dict],
                   used_math_tools: bool = False,
                   math_tool_results: list[dict] | None = None,
                   reference_answer: str | None = None) -> EvidenceContract:
    """Assemble the evidence contract from retrieval + answer."""
    used_retrieval = bool(chunks)
    state, sources, reason = determine_evidence_state(
        chunks, reference_answer=reference_answer)
    conflicts = detect_conflicts(chunks)
    if conflicts:
        state = "CONFLICTING_EVIDENCE"
        reason = f"{len(conflicts)} conflicting chunk pair(s) retrieved"
        by_id = {c.get("chunk_id"): c for c in chunks}
        ranked = sorted(
            chunks, key=lambda c: _authority_key(c), reverse=True)
        rank = {c.get("chunk_id", "?"): i for i, c in enumerate(ranked)}
        for c in chunks:
            src = next(s for s in sources if s.chunk_id == c.get("chunk_id", "?"))
            src.conflicts_with = [b for (a, b) in conflicts
                                  if a == c.get("chunk_id", "?")] + \
                                 [a for (a, b) in conflicts
                                  if b == c.get("chunk_id", "?")]
            # rank preserved via list order of `sources` re-sorted below
        sources.sort(key=lambda s: rank.get(s.chunk_id, 99))
        reason += "; ranked by authority/date, both sides preserved"
    confidence = {"SUPPORTED": "high", "PARTIALLY_SUPPORTED": "medium",
                  "CONFLICTING_EVIDENCE": "low",
                  "INSUFFICIENT_EVIDENCE": "low"}[state]
    return EvidenceContract(
        answer=answer, used_retrieval=used_retrieval,
        used_math_tools=used_math_tools, sources=sources,
        confidence=confidence, uncertainty_reason=reason,
        evidence_state=state,
        math_tool_results=math_tool_results or [])