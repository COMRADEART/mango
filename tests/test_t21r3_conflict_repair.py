"""T21R3.2 — focused reproduction tests for the false-conflict defect.

T21R2's strict blind holdout (evaluations/t21r2/) recorded 64 false
over-abstentions with one root cause: the deterministic metadata path of
detect_conflicts compared text_span instead of fact_value, so two chunks
asserting the SAME fact_value in different wording were classified as
conflicting evidence.

These tests reproduce the two defect families against the preregistered
semantics (same entity + same attribute + same normalized fact_value =
NO value conflict). They were written to fail against the canonical
T21R2 code (recorded in evaluations/t21r3/t21r2_failure_freeze.json).
"""
from __future__ import annotations

import pytest

from sciencemath.knowledge.conflicts import detect_conflicts, resolve_conflicts
from sciencemath.knowledge.evidence import EvidenceItem
from sciencemath.knowledge.routing import CONFLICTING_EVIDENCE

RESOLVED_BY_AUTHORITY = "RESOLVED_BY_AUTHORITY"  # conflicts.py return value

_H = "0" * 12


def _item(source: str, cid: str, text: str, entity: str, attribute: str,
          value: str, *, authority: str = "ENCYCLOPEDIC",
          freshness: str = "STATIC") -> EvidenceItem:
    return EvidenceItem(
        source_id=source, chunk_id=cid, title="t", section="s",
        text_span=text, score=1.0, rank=0, authority_class=authority,
        content_hash=_H, citation_id="C1-x", freshness_class=freshness,
        metadata={"fact_entity": entity, "fact_attribute": attribute,
                  "fact_value": value})


def _pair_conflict_keys(items: list[EvidenceItem]) -> list[tuple[str, str]]:
    return [(c["evidence_a"]["chunk_id"], c["evidence_b"]["chunk_id"])
            for c in detect_conflicts(items)]


# 1. same entity + attribute + SAME fact_value + different wording -> no
#    value conflict (the exact T21R2 defect shape)
def test_same_value_restatement_is_not_a_conflict() -> None:
    a = _item("gk-aaaa11112222", "s0:emblem:0",
              "The emblem of the town of Abenshire is a rope walk.",
              "Abenshire", "emblem", "a rope walk")
    b = _item("gk-bbbb33334444", "s1:emblem-restated:0",
              "The town emblem of Abenshire is a rope walk.",
              "Abenshire", "emblem", "a rope walk")
    assert _pair_conflict_keys([a, b]) == []


# 2. same entity + attribute + DIFFERENT fact_value -> conflict
def test_different_value_is_a_conflict() -> None:
    a = _item("gk-aaaa11112222", "s0:emblem:0",
              "The emblem of the town of Abenshire is a rope walk.",
              "Abenshire", "emblem", "a rope walk")
    b = _item("gk-bbbb33334444", "s1:emblem:0",
              "Abenshire's town emblem is a pillbox.",
              "Abenshire", "emblem", "a pillbox")
    assert _pair_conflict_keys([a, b]) == [("s0:emblem:0", "s1:emblem:0")]


# 3. exact same fact repeated -> no conflict
def test_identical_fact_repetition_is_not_a_conflict() -> None:
    a = _item("gk-aaaa11112222", "s0:emblem:0",
              "The emblem of the town of Abenshire is a rope walk.",
              "Abenshire", "emblem", "a rope walk")
    b = _item("gk-bbbb33334444", "s1:emblem:0",
              "The emblem of the town of Abenshire is a rope walk.",
              "Abenshire", "emblem", "a rope walk")
    assert _pair_conflict_keys([a, b]) == []


# 4. authority-resolvable differing values -> RESOLVED_BY_AUTHORITY
def test_authority_resolution_prefers_higher_authority() -> None:
    a = _item("gk-aaaa11112222", "s0:loc:0",
              "The location of the institute Vale is Aldersgate.",
              "Vale", "location", "Aldersgate",
              authority="PRIMARY_REFERENCE")
    b = _item("gk-bbbb33334444", "s1:loc:0",
              "The institute Vale is located in Fenmoor.",
              "Vale", "location", "Fenmoor",
              authority="GENERAL_REFERENCE")
    conflicts = detect_conflicts([a, b])
    resolution, winner = resolve_conflicts(conflicts)
    assert resolution == RESOLVED_BY_AUTHORITY
    assert winner["chunk_id"] == "s0:loc:0"


# 5. freshness-resolvable differing values (equal authority) -> resolved
def test_freshness_resolution_prefers_fresher_snapshot() -> None:
    a = _item("gk-aaaa11112222", "s0:pop:0",
              "The mayor of the town of Brinklow is A. Hale.",
              "Brinklow", "mayor", "A. Hale",
              freshness="STATIC")
    b = _item("gk-bbbb33334444", "s1:pop:0",
              "B. Quill serves as the mayor of Brinklow.",
              "Brinklow", "mayor", "B. Quill",
              authority="ENCYCLOPEDIC", freshness="SLOW_CHANGING")
    conflicts = detect_conflicts([a, b])
    resolution, winner = resolve_conflicts(conflicts)
    assert resolution == RESOLVED_BY_AUTHORITY
    assert winner["chunk_id"] == "s0:pop:0"


# 6. unresolved different values (equal authority + freshness) ->
#    CONFLICTING_EVIDENCE
def test_unresolved_value_conflict_surfaces() -> None:
    a = _item("gk-aaaa11112222", "s0:river:0",
              "The River Sol crosses the town of Duncote.",
              "Duncote", "river", "River Sol")
    b = _item("gk-bbbb33334444", "s1:river:0",
              "The town of Duncote stands on the River Wen.",
              "Duncote", "river", "River Wen")
    conflicts = detect_conflicts([a, b])
    resolution, winner = resolve_conflicts(conflicts)
    assert resolution == CONFLICTING_EVIDENCE
    assert winner is None


# 7. unrelated attributes on the same entity -> no conflict
def test_unrelated_attributes_are_not_conflicts() -> None:
    a = _item("gk-aaaa11112222", "s0:emblem:0",
              "The emblem of the town of Elverton is a bell tower.",
              "Elverton", "emblem", "a bell tower")
    b = _item("gk-bbbb33334444", "s1:province:0",
              "The province of Elverton is Marshland.",
              "Elverton", "province", "Marshland")
    assert _pair_conflict_keys([a, b]) == []


# 8. same attribute on different entities -> no conflict
def test_different_entities_same_attribute_is_not_a_conflict() -> None:
    a = _item("gk-aaaa11112222", "s0:emblem:0",
              "The emblem of the town of Fennbridge is a mill wheel.",
              "Fennbridge", "emblem", "a mill wheel")
    b = _item("gk-bbbb33334444", "s1:emblem:0",
              "The emblem of the town of Ganmere is a bell tower.",
              "Ganmere", "emblem", "a bell tower")
    assert _pair_conflict_keys([a, b]) == []


# Conservative normalization: the same value modulo whitespace, case and
# Unicode form is ONE value; wording alone never creates a conflict.
def test_conservative_normalization_merges_same_value() -> None:
    a = _item("gk-aaaa11112222", "s0:genre:0",
              "The genre of the novel The Anvil is pastoral.",
              "The Anvil", "genre", "pastoral")
    b = _item("gk-bbbb33334444", "s1:genre:0",
              "The Anvil is a work of pastoral fiction.",
              "The Anvil", "genre", "  Pastoral  ")
    assert _pair_conflict_keys([a, b]) == []


def test_scalar_normalization_merges_same_number() -> None:
    a = _item("gk-aaaa11112222", "s0:year:0",
              "The founding year of the academy Colding is 1493.",
              "Colding", "founding year", "1493")
    b = _item("gk-bbbb33334444", "s1:year:0",
              "The academy Colding was founded in  1493 .",
              "Colding", "founding year", " 1493 ")
    assert _pair_conflict_keys([a, b]) == []


# the metadata path must not fabricate conflicts from word order alone
# (active vs passive restatement of one value, as in the T21R2 example)
def test_reworded_same_fact_passive_voice_no_conflict() -> None:
    a = _item("gk-aaaa11112222", "s0:river:0",
              "River Sol crosses Marenton.", "Marenton", "river",
              "River Sol")
    b = _item("gk-bbbb33334444", "s1:river:0",
              "Marenton is crossed by the River Sol.", "Marenton",
              "river", "River Sol")
    assert _pair_conflict_keys([a, b]) == []


# groups containing BOTH a same-value restatement and a genuinely
# different value must produce only the genuinely differing pair
def test_group_pairs_only_across_distinct_values() -> None:
    a = _item("gk-aaaa11112222", "s0:emblem:0",
              "The emblem of the town of Harnlow is a rope walk.",
              "Harnlow", "emblem", "a rope walk")
    b = _item("gk-bbbb33334444", "s1:emblem:0",
              "Harnlow's town emblem is a rope walk.", "Harnlow",
              "emblem", "a rope walk")
    c = _item("gk-cccc55556666", "s2:emblem:0",
              "The town emblem of Harnlow is a pillbox.", "Harnlow",
              "emblem", "a pillbox")
    assert set(_pair_conflict_keys([a, b, c])) == {
        ("s0:emblem:0", "s2:emblem:0"),
        ("s1:emblem:0", "s2:emblem:0")}


# the text-only fallback path stays inert for metadata-carrying items
def test_text_fallback_not_used_when_metadata_present() -> None:
    a = _item("gk-aaaa11112222", "s0:emblem:0",
              "The emblem of the town of Quainton is a pillbox.",
              "Quainton", "emblem", "a pillbox")
    b = _item("gk-bbbb33334444", "s1:emblem:0",
              "Quainton keeps a pillbox as its town emblem.",
              "Quainton", "emblem", "a pillbox")
    assert detect_conflicts([a, b], frozenset({"quainton", "emblem"})) == []