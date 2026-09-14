"""T16.19 — contradiction detection. Never average silently."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sciencemath.web.entailment import CONTRADICTS, entailment

RESOLVED = "resolved_contradiction"
UNRESOLVED = "unresolved_contradiction"
TEMPORAL_UPDATE = "temporal_update"
DIFFERENT_DEFINITIONS = "different_definitions"
DIFFERENT_SCOPES = "different_scopes"

_NUM = re.compile(
    r"(?<![A-Za-z])(?:\d+\.\d+|\d{2,})",
)


@dataclass
class Contradiction:
    claim: str
    source_a: str
    source_b: str
    span_a: str
    span_b: str
    nature: str
    date_difference: str
    authority_difference: str
    possible_explanation: str
    resolution: str

    def to_dict(self) -> dict:
        return asdict(self)


def detect_contradictions(claim: str, items: list[tuple]) -> list[Contradiction]:
    """items: list of (source, span_text)."""
    from sciencemath.web.diversity import duplicate_key
    from sciencemath.web.entailment import (
        CONTRADICTS, ENTAILS, PARTIALLY_ENTAILS, entailment,
    )
    relevant = []
    for s, e in items:
        st = entailment(claim, e)
        if st in (ENTAILS, PARTIALLY_ENTAILS):
            relevant.append((s, e, st))
    items = [(s, e) for s, e, _ in relevant]
    out: list[Contradiction] = []
    for i, (sa, ea) in enumerate(items):
        for sb, eb in items[i + 1:]:
            if sa.source_id == sb.source_id:
                continue
            if duplicate_key(sa) == duplicate_key(sb):
                continue
            a_vs_b = entailment(ea, eb)
            b_vs_a = entailment(eb, ea)
            nums_a, nums_b = set(_NUM.findall(ea)), set(_NUM.findall(eb))
            numeric_conflict = bool(nums_a and nums_b and nums_a != nums_b)
            named_conflict = (
                entailment(claim, ea) == CONTRADICTS
                or entailment(claim, eb) == CONTRADICTS
            )
            if not (numeric_conflict or named_conflict or a_vs_b == CONTRADICTS
                    or b_vs_a == CONTRADICTS):
                continue
            da = getattr(sa, "publication_date", "UNKNOWN")
            db = getattr(sb, "publication_date", "UNKNOWN")
            nature = "numeric_or_named_disagreement"
            resolution = UNRESOLVED
            expl = "sources disagree; not averaged"
            ta = getattr(sa, "trust_class", "UNKNOWN")
            tb = getattr(sb, "trust_class", "UNKNOWN")
            from sciencemath.web import trust as T
            a_pri, b_pri = T.is_primary(ta), T.is_primary(tb)
            if a_pri != b_pri:
                nature = "authority_difference"
                resolution = RESOLVED
                expl = "prefer primary/high-trust source; do not average"
            elif da != db and da != "UNKNOWN" and db != "UNKNOWN":
                nature = "date_difference"
                resolution = TEMPORAL_UPDATE
                expl = "later source may supersede earlier source"
            auth = f"{ta} vs {tb}"
            out.append(Contradiction(
                claim=claim, source_a=sa.source_id, source_b=sb.source_id,
                span_a=ea[:180], span_b=eb[:180], nature=nature,
                date_difference=f"{da} vs {db}",
                authority_difference=auth,
                possible_explanation=expl, resolution=resolution,
            ))
    return out
