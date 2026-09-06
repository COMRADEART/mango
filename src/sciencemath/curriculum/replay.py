"""T6.9 — Replay-buffer selection for curriculum stages.

Anti-forgetting mechanism: each curriculum stage mixes a controlled
fraction of representative, previously verified examples from earlier
stages (and from the frozen sciencemath-sft-v1 corpus) into the stage
training set. Selection is deterministic (seeded) and stratified:

  * stratified by macro domain and capability track
  * prefers verification state PASS, then UNKNOWN-reviewed, never FAIL
  * deduplicates by normalized question text
  * composition is reported explicitly (never silent)
"""
from __future__ import annotations

import hashlib
import re

from sciencemath.curriculum.capabilities import FAMILIES


def normalize_question(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").lower()).strip()


def _example_key(example: dict) -> str:
    q = example.get("question") or example.get("target_response", "")
    return normalize_question(q)[:200]


def _dedup_key(example: dict) -> str:
    return hashlib.sha256(_example_key(example).encode("utf-8")).hexdigest()


def _family_of(example: dict) -> str:
    fam = example.get("family") or example.get("domain")
    return fam or "general"


def _track_of(example: dict) -> str:
    return example.get("capability_track") or example.get("subject") or "general"


def select_replay(pool: list[dict], *, fraction: float,
                  target_size: int | None = None,
                  seed: int = 42,
                  exclude_questions: set[str] | None = None) -> tuple[list[dict], dict]:
    """Deterministic stratified replay selection.

    pool: candidate replay examples (already limited to prior-stage /
    frozen-corpus records carrying question + target_response + family +
    verification_state fields).
    fraction: fraction of the *target stage size* the replay should fill
    (or absolute target_size). Selection order: rank candidates by
    (verification PASS first, then hash order) inside each stratum so the
    choice is stable and independent of pool file order.
    Returns (selected, composition_report).
    """
    exclude = {normalize_question(q) for q in (exclude_questions or set())}
    candidates = []
    seen = set()
    for ex in pool:
        key = _dedup_key(ex)
        if key in seen:
            continue
        seen.add(key)
        if _example_key(ex) in exclude:
            continue
        candidates.append(ex)

    target = target_size if target_size is not None \
        else round(fraction * len(candidates))

    # strata: (macro family, capability track) — keeps replay balanced
    strata: dict[tuple[str, str], list[dict]] = {}
    for ex in candidates:
        macro = _macro(_family_of(ex))
        strata.setdefault((macro, _track_of(ex)), []).append(ex)

    selected: list[dict] = []
    order = sorted(strata, key=lambda s: (s[0], s[1]))
    per_stratum = max(1, target // max(1, len(order))) if order else 0
    leftover = []
    for stratum in order:
        bucket = sorted(strata[stratum],
                        key=lambda ex: (_rank(ex), _stable_hash(ex)))
        take = bucket[:per_stratum]
        selected.extend(take)
        leftover.extend(bucket[per_stratum:])
    if len(selected) < target:
        for ex in sorted(leftover, key=lambda ex: (_rank(ex),
                                                   _stable_hash(ex))):
            if len(selected) >= target:
                break
            selected.append(ex)

    composition = _composition(selected, requested=fraction)
    return selected, composition


def _rank(example: dict) -> int:
    v = (example.get("verification_state") or "").upper()
    return {"PASS": 0, "SOURCE_VERIFIED": 0, "UNKNOWN": 1, "": 1,
            "REVIEWED": 1}.get(v, 2)   # FAIL and anything else: last


def _stable_hash(example: dict) -> str:
    return _dedup_key(example)


def _macro(family: str) -> str:
    if family in FAMILIES:
        if family == "mathematics":
            return "mathematics"
        if family == "cross_domain":
            return "cross_domain"
        return "sciences"
    if family in ("math", "mathematics"):
        return "mathematics"
    if family == "cross_domain":
        return "cross_domain"
    if family in ("general", "interdisciplinary"):
        return "general"
    return "sciences"


def _composition(selected: list[dict], *, requested: float) -> dict:
    by_family: dict[str, int] = {}
    by_verification: dict[str, int] = {}
    for ex in selected:
        f = _macro(_family_of(ex))
        by_family[f] = by_family.get(f, 0) + 1
        v = (ex.get("verification_state") or "UNSPECIFIED").upper()
        by_verification[v] = by_verification.get(v, 0) + 1
    n = len(selected)
    return {
        "requested_fraction": requested,
        "selected": n,
        "by_macro": {k: round(v / n, 4) for k, v in by_family.items()}
        if n else {},
        "by_verification_state": by_verification,
    }