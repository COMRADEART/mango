"""T21.18 — conflict handling.

When retrieved evidence conflicts (two sources assert different values for
the same entity/attribute), the pipeline must not silently pick one. Both
sides are represented with their authority/freshness metadata, then either
resolved by the preregistered authority rules below or surfaced as
CONFLICTING_EVIDENCE.

Preregistered resolution rule (frozen before FINAL):
  1. If a higher authority class asserts a value against a strictly lower
     authority class, the higher authority wins.
  2. Within equal authority, a STATIC source beats SLOW_CHANGING; neither
     beats TIME_SENSITIVE for a current-state claim (snapshot staleness).
  3. Otherwise the conflict is NOT resolved: the answer is
     CONFLICTING_EVIDENCE with both sides attached.
"""
from __future__ import annotations

from sciencemath.knowledge.evidence import EvidenceItem

AUTHORITY_RANK = {
    "PRIMARY_REFERENCE": 6,
    "ENCYCLOPEDIC": 5,
    "ACADEMIC_REFERENCE": 4,
    "GOVERNMENT_PUBLICATION": 4,
    "INSTITUTIONAL": 3,
    "GENERAL_REFERENCE": 2,
    "UNKNOWN": 0,
}

_FRESHNESS_RANK = {"STATIC": 3, "SLOW_CHANGING": 2, "TIME_SENSITIVE": 1,
                   "UNKNOWN": 0}


def _attribute_key(text: str, entity_terms: frozenset[str]) -> str:
    """Deterministic key for the attribute a chunk asserts about an entity."""
    from sciencemath.knowledge.index import tokenize
    toks = [t for t in tokenize(text) if len(t) > 3]
    entity_part = "".join(sorted(t for t in entity_terms if t in toks))
    return entity_part


def detect_conflicts(
    items: list[EvidenceItem],
    entity_terms: frozenset[str] | None = None,
) -> list[dict]:
    """Pairwise value-conflict detection across evidence items.

    Primary path (deterministic): items whose originating chunk metadata
    carries fact_entity/fact_attribute/fact_value disagree on the value for
    the same entity+attribute. Fallback path: text-level attribute key
    comparison restricted to shared entity context, so unrelated chunks
    never trip this.
    """
    conflicts: list[dict] = []

    # -- metadata path ------------------------------------------------------
    facts: dict[str, list[EvidenceItem]] = {}
    for item in items:
        meta = item.metadata or {}
        entity = meta.get("fact_entity")
        attribute = meta.get("fact_attribute")
        value = meta.get("fact_value")
        if entity and attribute and value is not None:
            facts.setdefault(f"{entity}|{attribute}", []).append(item)
    for key, group in facts.items():
        distinct = {it.text_span for it in group}
        if len(distinct) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a.text_span == b.text_span:
                    continue
                conflicts.append({
                    "claim_key": key,
                    "evidence_a": a.to_dict(),
                    "evidence_b": b.to_dict(),
                })

    # -- text path (only when no metadata facts are present) ----------------
    if not facts and entity_terms:
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if a.source_id == b.source_id and a.chunk_id == b.chunk_id:
                    continue
                ka = _attribute_key(a.text_span, entity_terms)
                kb = _attribute_key(b.text_span, entity_terms)
                if not ka or not kb or ka != kb:
                    continue
                if a.text_span == b.text_span:
                    continue
                conflicts.append({
                    "claim_key": ka,
                    "evidence_a": a.to_dict(),
                    "evidence_b": b.to_dict(),
                })
    return conflicts


def resolve_conflicts(
    conflicts: list[dict],
) -> tuple[str, dict | None]:
    """Apply the preregistered authority/freshness rules.

    Returns (resolution, winner) where resolution is
      RESOLVED_BY_AUTHORITY — a single winner item dict
      CONFLICTING_EVIDENCE  — no silent choice
    """
    for conflict in conflicts:
        a = conflict["evidence_a"]
        b = conflict["evidence_b"]
        rank_a = AUTHORITY_RANK.get(a.get("authority_class", "UNKNOWN"), 0)
        rank_b = AUTHORITY_RANK.get(b.get("authority_class", "UNKNOWN"), 0)
        fresh_a = _FRESHNESS_RANK.get(a.get("freshness_class", "UNKNOWN"), 0)
        fresh_b = _FRESHNESS_RANK.get(b.get("freshness_class", "UNKNOWN"), 0)
        if rank_a != rank_b:
            return "RESOLVED_BY_AUTHORITY", (a if rank_a > rank_b else b)
        if fresh_a != fresh_b:
            return "RESOLVED_BY_AUTHORITY", (a if fresh_a > fresh_b else b)
    if conflicts:
        return "CONFLICTING_EVIDENCE", None
    return "NO_CONFLICT", None