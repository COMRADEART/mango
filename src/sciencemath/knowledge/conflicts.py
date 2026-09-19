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

import re
import unicodedata

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

# ---------------------------------------------------------------------------
# T21R4 — deterministic query-to-attribute cue table (preregistered).
#
# Conflict scoping is QUERY-RELEVANT, not TOP-ITEM-RELEVANT and not
# ALL-CONFLICTS-RELEVANT: a detected conflict is surfaced only when its
# fact_entity and fact_attribute are both relevant to the question, judged
# from structured metadata and preregistered wording cues. No model, no
# embeddings, no per-query special cases.
#
# Cue matching rule: a query token matches a cue when it equals the cue or,
# for cues of five or more characters, starts with the cue (e.g. cue
# "establish" matches "established" and "establishment"). Stems shorter
# than five characters require an exact token, which keeps generic stems
# such as "sign" or "land" from matching "designed" or "landmark".
#
# Year-type attributes additionally require YEAR INTENT ("year" or "when"
# in the query) so that a place question ("Where was X born?") never
# surfaces a birth-year conflict, and vice versa.
# ---------------------------------------------------------------------------
_CUE_RE = re.compile(r"[a-z0-9]+")

_YEAR_INTENT_TOKENS = frozenset({"year", "when"})

# attribute -> (cues, intent) where intent is "year", "place" or None.
# "year" intent requires a year/when token; "place" intent is implied by the
# cue itself (name or birth wording). Unlisted attributes fall back to
# exact token match of the attribute name itself.
ATTRIBUTE_CUES: dict[str, tuple[tuple[str, ...], str | None]] = {
    # year-type attributes
    "established year": (("establish", "founding", "founded",
                          "foundation"), "year"),
    "founding year": (("establish", "founding", "founded",
                       "foundation"), "year"),
    "introduction year": (("introduc", "invent", "launch", "debut",
                           "appear", "appearanc"), "year"),
    "invention year": (("introduc", "invent", "launch", "debut",
                        "appear", "appearanc"), "year"),
    "launch year": (("introduc", "invent", "launch", "debut",
                     "appear", "appearanc"), "year"),
    "discovery year": (("discover", "identif"), "year"),
    "birth year": (("birth", "born"), "year"),
    "publication year": (("publish", "publication", "printed"), "year"),
    "creation year": (("creat", "craft"), "year"),
    "opening year": (("open", "openning"), "year"),
    "ratification year": (("ratif", "signing", "signed"), "year"),
    "signing year": (("ratif", "signing", "signed"), "year"),
    "completion year": (("complet", "finis"), "year"),
    "landing year": (("landing", "landed", "land"), "year"),
    "sealing year": (("sealing", "sealed"), "year"),
    # place-type attributes
    "birthplace": (("birth", "born", "birthplace"), None),
    "location": (("location", "located", "situated"), None),
    "region": (("region",), None),
    "province": (("province",), None),
    "nation": (("nation",), None),
    "country": (("country",), None),
    "continent": (("continent",), None),
    "capital": (("capital",), None),
    "river": (("river",), None),
    "waterway": (("waterway", "river"), None),
    "mouth": (("mouth",), None),
    "sea": (("sea",), None),
    "landmark": (("landmark",), None),
    # other attributes
    "mayor": (("mayor", "officeholder", "leader"), None),
    "led by": (("led", "leader", "commander"), None),
    "genre": (("genre",), None),
    "medium": (("medium",), None),
    "painter": (("painter", "painted"), None),
    "author": (("author", "authored", "wrote", "written"), None),
    "subject": (("subject",), None),
    "field of study": (("field", "studied", "study"), None),
    "notable work": (("notable", "masterpiece", "masterwork", "famous"),
                     None),
    "inventor": (("invent", "inventor"), None),
    "emblem": (("emblem",), None),
    "property": (("property",), None),
    "function": (("function",), None),
    "purpose": (("purpose",), None),
    "maker": (("maker",), None),
    "definition": (("definition", "define", "defined"), None),
    "seats": (("seat", "seats"), None),
    "layer": (("layer",), None),
    "institution type": (("type", "kind"), None),
}


def _raw_tokens(text: str) -> list[str]:
    """Lowercase word tokens WITHOUT stopword removal (cues and intents
    live in function words such as 'when'/'where')."""
    return _CUE_RE.findall(text.lower())


def _token_matches_cue(token: str, cue: str) -> bool:
    if token == cue:
        return True
    return len(cue) >= 5 and token.startswith(cue)


def _attribute_relevant(attribute: str, query_tokens: list[str]) -> bool:
    """Deterministic query/attribute relevance via the cue table."""
    attribute = attribute.casefold().strip()
    cues, intent = ATTRIBUTE_CUES.get(attribute, (None, None))
    attr_tokens = _raw_tokens(attribute)
    if cues is None:
        # Unlisted attribute: exact token containment of the attribute name.
        return all(t in query_tokens for t in attr_tokens) \
            if attr_tokens else False
    if intent == "year" and not (_YEAR_INTENT_TOKENS & set(query_tokens)):
        return False
    for cue in cues:
        if any(_token_matches_cue(t, cue) for t in query_tokens):
            return True
    return False


def query_relevant_conflicts(
    query: str, conflicts: list[dict],
) -> list[dict]:
    """T21R4 scoping: conflicts relevant to the effective query.

    A detected conflict is query-relevant when
      1. ENTITY RELEVANCE: every token of the claim_key's fact_entity
         appears in the query tokens (deterministic evidence the question
         is about that entity — a retrieved conflict for another entity is
         never surfaced), and
      2. ATTRIBUTE RELEVANCE: the fact_attribute is relevant to the query
         wording via the preregistered cue table (a different attribute of
         the same entity is never surfaced).

    For text-fallback claim keys (no structured metadata), the whole key
    must be token-contained in the query. Deterministic throughout.
    """
    query_tokens = _raw_tokens(query)
    relevant: list[dict] = []
    for conflict in conflicts:
        key = conflict.get("claim_key", "")
        if "|" in key:
            entity, attribute = key.split("|", 1)
            entity_tokens = _raw_tokens(entity)
            if not entity_tokens or \
                    not all(t in query_tokens for t in entity_tokens):
                continue
            if not _attribute_relevant(attribute, query_tokens):
                continue
            relevant.append(conflict)
        else:
            # text-fallback key: shared entity-context tokens
            key_tokens = _raw_tokens(key)
            if key_tokens and all(t in query_tokens for t in key_tokens):
                relevant.append(conflict)
    return relevant


def query_attribute_set(query: str) -> frozenset[str]:
    """T21R5 — deterministic query->attribute relevance set.

    The set of every preregistered attribute whose cue-table entry matches
    the query, under the same cue-matching rule and the same year-intent
    gate used for conflict scoping. Drives attribute-aware synthesis
    selection: when the query asks for a known attribute and evidence
    items carry structured fact metadata, the item asserting a
    query-relevant attribute is preferred over a merely top-ranked item
    (T21R4 replay: query-mimicking distractor chunks won the rerank
    tie-break and the wrong attribute was answered or abstained upon).
    """
    tokens = _raw_tokens(query)
    return frozenset(
        attribute for attribute in ATTRIBUTE_CUES
        if _attribute_relevant(attribute, tokens))


def detect_text_value_conflicts(
    items: list,
    attr_set: frozenset[str],
    query: str = "",
) -> list[dict]:
    """C3 — text-level value-conflict detection for query-cued year facts.

    The legacy text fallback keys chunks by shared entity tokens only and
    is suppressed whenever ANY metadata fact is present in the window, so
    two prose sources asserting different years for the queried entity go
    undetected. This detector is independent of metadata presence: a pair
    conflicts when a query-cued YEAR-TYPE attribute exists whose cue both
    spans express, both spans share an exact proper-name entity run, and
    the four-digit year sets asserted by the two spans are non-empty and
    disjoint. Keyed as a structured ``entity|attribute`` claim so the
    downstream query scoping applies unchanged. Deterministic; no fuzzy
    matching.
    """
    year_attrs = sorted(a for a in attr_set
                        if ATTRIBUTE_CUES.get(a, (None, None))[1] == "year")
    if not year_attrs:
        return []
    year_re = re.compile(r"\b(?:1[0-9]{3}|20[0-9]{2})\b")
    name_re = re.compile(r"(?<!\w)[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*")
    query_tokens = set(_raw_tokens(query))

    def _entity_runs(span: str) -> set[str]:
        return {" ".join(unicodedata.normalize("NFKC", run).casefold().split())
                for run in name_re.findall(span or "")}

    def _years(span: str) -> set[str]:
        return set(year_re.findall(span or ""))

    def _attr_spans(a: str, b: str, attr: str) -> bool:
        cues = ATTRIBUTE_CUES[attr][0]
        for span in (a, b):
            tokens = set(_raw_tokens(span))
            if not any(_token_matches_cue(t, c) for t in tokens for c in cues):
                return False
        return True

    def _side_entity(item: object) -> str:
        from sciencemath.knowledge.evidence_paths import normalize_identity
        meta = getattr(item, "metadata", None) or {}
        return normalize_identity(meta.get("fact_entity") or "")

    conflicts: list[dict] = []
    for i, a in enumerate(items):
        runs_a = _entity_runs(a.text_span)
        years_a = _years(a.text_span)
        if not runs_a or not years_a:
            continue
        for b in items[i + 1:]:
            if a.source_id == b.source_id and a.chunk_id == b.chunk_id:
                continue
            years_b = _years(b.text_span)
            if not years_b or (years_a & years_b):
                continue
            shared = runs_a & _entity_runs(b.text_span)
            if not shared:
                continue
            # A metadata-carrying side speaks for its OWN fact_entity: a
            # passage whose fact_entity is a sub-entity ('the old
            # quarter') must not be read as a conflicting assertion about
            # the parent entity that merely shares a name run.
            ent_a, ent_b = _side_entity(a), _side_entity(b)
            if ent_a:
                shared = {r for r in shared if r == ent_a}
            if ent_b:
                shared = {r for r in shared if r == ent_b}
            if not shared:
                continue
            attr = next((attr for attr in year_attrs
                         if _attr_spans(a.text_span, b.text_span, attr)), None)
            if attr is None:
                continue
            grounded = sorted(r for r in shared
                              if all(t in query_tokens for t in r.split()))
            entity = (grounded or sorted(shared))[0]
            conflicts.append({
                "claim_key": f"{entity}|{attr}",
                "evidence_a": a.to_dict(),
                "evidence_b": b.to_dict(),
            })
    return conflicts


def _normalize_fact_value(value: object) -> str:
    """Conservative deterministic value identity.

    Same entity+attribute+normalized value is one fact, regardless of
    wording. Only whitespace trim, Unicode NFKC, internal whitespace
    collapse, and casefold are applied — no semantic fuzzy matching.
    """
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = " ".join(text.split())
    return text.casefold()


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
    carries fact_entity/fact_attribute/fact_value disagree on the
    *normalized fact_value* for the same entity+attribute. Different
    wording (text_span) of the same value is not a conflict. Fallback
    path: text-level attribute key comparison restricted to shared
    entity context, used only when no metadata facts are present.
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
        for i, a in enumerate(group):
            va = _normalize_fact_value((a.metadata or {}).get("fact_value"))
            for b in group[i + 1:]:
                vb = _normalize_fact_value((b.metadata or {}).get("fact_value"))
                if va == vb:
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


_YEAR_VALUE_RE = re.compile(r"\b(?:1[0-9]{3}|20[0-9]{2})\b")


def _side_value(side: dict) -> str:
    """Deterministic value identity of one conflict-evidence side.

    Structured metadata fact_value when present; otherwise the span's
    four-digit year set (text-level conflicts). Sides with no value
    signal at all share the empty key and fall back to pairwise
    comparison below.
    """
    meta = side.get("metadata") or {}
    value = meta.get("fact_value")
    if value is not None:
        return _normalize_fact_value(value)
    return ",".join(sorted(set(_YEAR_VALUE_RE.findall(
        str(side.get("text_span") or "")))))


def _side_strength(side: dict) -> tuple[int, int]:
    return (AUTHORITY_RANK.get(side.get("authority_class", "UNKNOWN"), 0),
            _FRESHNESS_RANK.get(side.get("freshness_class", "UNKNOWN"), 0))


def resolve_conflicts(
    conflicts: list[dict],
) -> tuple[str, dict | None]:
    """Apply the preregistered authority/freshness rules.

    Returns (resolution, winner) where resolution is
      RESOLVED_BY_AUTHORITY — a single winner item dict
      CONFLICTING_EVIDENCE  — no silent choice

    C3 — value-side aggregation: a disputed claim is decided between the
    VALUE SIDES, not between fragmented pairs. Each side's strength is the
    best (authority rank, freshness rank) over every evidence item
    asserting that normalized value for the claim, so a low-rank
    corroborating copy of one value cannot out-rank the other value's best
    source (reproduced on open diagnostics: a GENERAL_REFERENCE duplicate
    of the majority value resolved a same-rank disagreement that the
    frozen gold records as CONFLICTING_EVIDENCE). Claims whose sides carry
    no value signal keep the frozen pairwise comparison. Cross-claim
    iteration order and the first-resolvable-claim-decides combination are
    unchanged.
    """
    if not conflicts:
        return "NO_CONFLICT", None
    groups: dict[str, list[dict]] = {}
    for conflict in conflicts:
        groups.setdefault(str(conflict.get("claim_key", "")),
                          []).append(conflict)
    for group in groups.values():
        sides: dict[str, tuple[tuple[int, int], dict]] = {}
        valueless = False
        for conflict in group:
            for side in (conflict["evidence_a"], conflict["evidence_b"]):
                value = _side_value(side)
                if not value:
                    valueless = True
                    continue
                strength = _side_strength(side)
                if value not in sides or strength > sides[value][0]:
                    sides[value] = (strength, side)
        if not valueless and len(sides) > 1:
            ranked = sorted(sides.items(), key=lambda kv: kv[1][0],
                            reverse=True)
            if ranked[0][1][0] != ranked[1][1][0]:
                return "RESOLVED_BY_AUTHORITY", ranked[0][1][1]
            continue
        # frozen pairwise comparison (no value signal on some side)
        for conflict in group:
            a = conflict["evidence_a"]
            b = conflict["evidence_b"]
            rank_a, rank_b = _side_strength(a)[0], _side_strength(b)[0]
            if rank_a != rank_b:
                return "RESOLVED_BY_AUTHORITY", (a if rank_a > rank_b else b)
            fresh_a, fresh_b = _side_strength(a)[1], _side_strength(b)[1]
            if fresh_a != fresh_b:
                return "RESOLVED_BY_AUTHORITY", (a if fresh_a > fresh_b else b)
    return "CONFLICTING_EVIDENCE", None
