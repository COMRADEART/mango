"""Derive T21R8 construction metrics from candidate files only.

This scanner is committed before the blind world exists.  The future static
gold audit must embed ``measure_candidate()["metrics"]`` and its violation
details.  No runtime or evaluator module is imported, and no holdout query is
executed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r8"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r8"
CONTRACT_PATH = OUT_DIR / "holdout_construction_contract.json"

PRIOR = {
    "T21": (ROOT / "evaluations" / "t21" / "suites",
            ROOT / "rag" / "gk_corpus"),
    "T21R": (ROOT / "evaluations" / "t21r" / "suites",
             ROOT / "rag" / "gk_holdout_t21r"),
    "T21R2": (ROOT / "evaluations" / "t21r2" / "suites",
              ROOT / "rag" / "gk_holdout_t21r2"),
    "T21R3": (ROOT / "evaluations" / "t21r3" / "suites",
              ROOT / "rag" / "gk_holdout_t21r3"),
    "T21R4": (ROOT / "evaluations" / "t21r4" / "suites",
              ROOT / "rag" / "gk_holdout_t21r4"),
    "T21R5": (ROOT / "evaluations" / "t21r5" / "suites",
              ROOT / "rag" / "gk_holdout_t21r5"),
    "T21R6": (ROOT / "evaluations" / "t21r6" / "suites",
              ROOT / "rag" / "gk_holdout_t21r6"),
    "T21R7": (ROOT / "evaluations" / "t21r7" / "suites",
              ROOT / "rag" / "gk_holdout_t21r7"),
}

IE_ENUM = {
    "missing_start_entity", "missing_hop1", "missing_hop2",
    "wrong_bridge_identity", "near_name_start_entity",
    "near_name_bridge_entity", "wrong_relation",
    "same_entity_wrong_attribute", "partial_path_only",
    "unrelated_conflict", "relevant_unresolved_conflict",
}
SCOPE_ENUM = {"hop1_only", "hop2_only", "both_hops", "exact"}

# The multisource_path quota is measured ONLY over rows in these suites; the
# construction tag alone (in any suite) never satisfies the quota.
MULTISOURCE_SUITES = ("multihop", "crossdomain")


def multisource_path_qualifies(row: dict, suite_name: str) -> bool:
    """True iff one candidate row counts toward the 1200-row
    ``multisource_path`` quota.  ALL of the following must hold:

    1. the row belongs to the multihop or crossdomain suite;
    2. the row carries the ``multisource_path`` construction tag;
    3. ``gold.required_sources`` holds >= 2 DISTINCT source IDs;
    4. ``construction.path_required_sources`` exists;
    5. ``path_required_sources`` holds >= 2 DISTINCT source IDs;
    6. every path-required source is in ``gold.required_sources``;
    7. the recorded gold path has both required reasoning edges (a hop1
       edge whose object equals the hop2 edge's subject).

    Optional corroboration sources contribute to NEITHER >= 2 count.
    """
    if suite_name not in MULTISOURCE_SUITES:
        return False
    if "multisource_path" not in (row.get("construction_tags") or []):
        return False
    gold = row.get("gold") or {}
    gold_sources = {str(source)
                    for source in (gold.get("required_sources") or [])}
    if len(gold_sources) < 2:
        return False
    annotation = row.get("construction") or {}
    path_sources = annotation.get("path_required_sources")
    if not isinstance(path_sources, list) or not path_sources:
        return False
    path_source_ids = {str(source) for source in path_sources}
    if len(path_source_ids) < 2:
        return False
    if not path_source_ids <= gold_sources:
        return False
    gold_path = annotation.get("gold_path") or {}
    hop1 = gold_path.get("hop1_edge") or {}
    hop2 = gold_path.get("hop2_edge") or {}
    if not hop1 or not hop2:
        return False
    return hop1.get("object_value") == hop2.get("subject_entity")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def _suite_rows(suites_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for directory in sorted(path for path in suites_dir.iterdir()
                            if path.is_dir()):
        candidates = ("dev.jsonl", "final.jsonl") \
            if suites_dir.name == "suites" and suites_dir.parent.name == "t21" \
            else ("holdout.jsonl",)
        for name in candidates:
            path = directory / name
            if path.exists():
                rows.extend(_load_jsonl(path))
    return rows


def _normalized_phrase(value: object) -> str:
    text = str(value or "").casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = _normalized_phrase(text)
    normalized_phrase = _normalized_phrase(phrase)
    if not normalized_phrase:
        return False
    return bool(re.search(
        rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])",
        normalized_text,
    ))


def _answers(rows: Iterable[dict]) -> set[str]:
    return {
        str(answer)
        for row in rows
        for answer in (row.get("gold", {}).get("expect_answer_contains") or [])
    }


def _entities(corpus_dir: Path, chunks: list[dict]) -> set[str]:
    entities = {
        _normalized_phrase((chunk.get("metadata") or {}).get("fact_entity"))
        for chunk in chunks
        if (chunk.get("metadata") or {}).get("fact_entity")
    }
    world = corpus_dir / "world.jsonl"
    if world.exists():
        for row in _load_jsonl(world):
            if row.get("type") == "WorldEntity":
                for field in ("entity_id", "name"):
                    if row.get(field):
                        entities.add(_normalized_phrase(row[field]))
    return {entity for entity in entities if entity}


def _prior_material(milestone: str) -> dict[str, set[str]]:
    suites_dir, corpus_dir = PRIOR[milestone]
    rows = _suite_rows(suites_dir)
    chunks = _load_jsonl(corpus_dir / "chunks.jsonl")
    sources = _load_jsonl(corpus_dir / "sources.jsonl")
    return {
        "case_ids": {row["case_id"] for row in rows},
        "entity_identities": _entities(corpus_dir, chunks),
        "source_ids": {source["source_id"] for source in sources},
        "chunk_ids": {chunk["chunk_id"] for chunk in chunks},
        "exact_queries": {row["request"]["query"] for row in rows},
        "exact_answers": _answers(rows),
        "exact_source_text": {chunk["text"] for chunk in chunks},
        "combined_text": {
            row["request"]["query"] for row in rows
        } | {chunk["text"] for chunk in chunks},
    }


def measure_candidate(root: Path = ROOT) -> dict:
    """Measure all construction-contract fields from candidate files."""
    out_dir = root / "evaluations" / "t21r8"
    corpus_dir = root / "rag" / "gk_holdout_t21r8"
    contract = json.loads((out_dir / "holdout_construction_contract.json")
                          .read_text(encoding="utf-8"))
    rows_by_suite: dict[str, list[dict]] = {}
    for short_name, rule in contract["suite_target_minimums"].items():
        path = out_dir / "suites" / rule["suite_id"] / "holdout.jsonl"
        rows_by_suite[short_name] = _load_jsonl(path)
    rows = [row for suite_rows in rows_by_suite.values() for row in suite_rows]
    chunks = _load_jsonl(corpus_dir / "chunks.jsonl")
    sources = _load_jsonl(corpus_dir / "sources.jsonl")
    chunks_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    sources_by_id = {source["source_id"]: source for source in sources}

    violations: list[dict] = []

    def violation(row: dict, reason: str) -> None:
        violations.append({"case_id": row.get("case_id"), "reason": reason})

    multihop = rows_by_suite["multihop"]
    crossdomain = rows_by_suite["crossdomain"]
    singlehop = rows_by_suite["singlehop"]
    conflict = rows_by_suite["conflict_abstention"]
    adversarial = rows_by_suite["adversarial"]

    families: dict[tuple[str, str], int] = {}
    multihop_mismatch = 0
    surface_rows = 0
    surface_mismatch = 0
    canonical_relations: set[str] = set()
    ie_configs: dict[str, int] = {}
    tag_counts = {
        "multisource_path": 0,
        "partial_path_ie_stress": 0,
        "relation_surface_sensitive": 0,
        "source_injection_safe_fact": 0,
        "safe_fact_with_directive": 0,
        "query_injection_or_spoof": 0,
    }
    attack_wordings: set[str] = set()

    def tagged(row: dict, tag: str) -> bool:
        return tag in (row.get("construction_tags") or [])

    for row in multihop:
        annotation = row.get("construction") or {}
        path = annotation.get("gold_path") or {}
        if path:
            family = (path["hop1_edge"]["relation"],
                      path["hop2_edge"]["relation"])
            families[family] = families.get(family, 0) + 1
        surfaces = annotation.get("surface_match")
        if tagged(row, "relation_surface_sensitive") and surfaces is not None:
            if not all(surfaces):
                multihop_mismatch += 1

    for row in multihop + singlehop:
        if not tagged(row, "relation_surface_sensitive"):
            continue
        surface_rows += 1
        annotation = row.get("construction") or {}
        relation = annotation.get("canonical_relation")
        if not isinstance(relation, list) or not relation:
            violation(row, "surface row lacks canonical_relation list")
        else:
            canonical_relations.update(str(item) for item in relation)
        if annotation.get("surface_template_source") != "builder_independent":
            violation(row, "surface templates not builder_independent")
        query_surfaces = annotation.get("surface_query")
        evidence_surfaces = annotation.get("surface_evidence")
        surfaces = annotation.get("surface_match")
        scope = annotation.get("paraphrase_scope")
        if not (isinstance(query_surfaces, list)
                and isinstance(evidence_surfaces, list)
                and isinstance(surfaces, list)
                and len(query_surfaces) == len(evidence_surfaces)
                and len(surfaces) == len(query_surfaces)):
            violation(row, "incomplete surface annotation")
            continue
        if scope not in SCOPE_ENUM:
            violation(row, "invalid paraphrase scope")
        recomputed = [q == e for q, e in zip(query_surfaces,
                                             evidence_surfaces)]
        if recomputed != surfaces:
            violation(row, "surface_match does not match recorded surfaces")
        if not all(surfaces):
            surface_mismatch += 1

    pair_counts: dict[frozenset, int] = {}
    two_source_two_domain = 0
    for row in crossdomain:
        gold = row.get("gold") or {}
        required_sources = set(gold.get("required_sources") or [])
        required_domains = set(gold.get("required_domains") or [])
        if len(required_sources) >= 2 and len(required_domains) >= 2:
            two_source_two_domain += 1
        pair_counts[frozenset(required_domains)] = \
            pair_counts.get(frozenset(required_domains), 0) + 1

    for row in rows:
        tags = set(row.get("construction_tags") or [])
        annotation = row.get("construction") or {}
        query = str((row.get("request") or {}).get("query", ""))
        for name in tag_counts:
            if name in tags:
                tag_counts[name] += 1
        if tagged(row, "multisource_path"):
            path_sources = annotation.get("path_required_sources")
            corroboration = annotation.get("corroboration_sources")
            gold_path = annotation.get("gold_path")
            if not isinstance(path_sources, list) or not path_sources:
                violation(row, "multisource row lacks path_required_sources")
                continue
            if not isinstance(corroboration, list) or not corroboration:
                violation(row, "multisource row lacks corroboration_sources")
                continue
            if not gold_path:
                violation(row, "multisource row lacks gold_path")
                continue
            gold_sources = set(row.get("gold", {}).get("required_sources")
                               or [])
            if any(source not in gold_sources for source in path_sources):
                violation(row, "path required source outside gold sources")
            if set(corroboration) & set(path_sources):
                violation(row, "corroboration overlaps path sources")
            hop1 = gold_path.get("hop1_edge") or {}
            hop2 = gold_path.get("hop2_edge") or {}
            bridge = gold_path.get("bridge_entity")
            terminal = gold_path.get("terminal_value")
            if not hop1 or not hop2 or not bridge or not terminal:
                violation(row, "incomplete gold path record")
            elif (hop1.get("object_value") != bridge
                  or hop2.get("subject_entity") != bridge
                  or hop2.get("object_value") != terminal):
                violation(row, "bridge or terminal identity mismatch")
            elif terminal not in (row.get("gold", {})
                                  .get("expect_answer_contains") or []):
                violation(row, "terminal value missing from gold answer")
        if tagged(row, "partial_path_ie_stress"):
            component = annotation.get("missing_component")
            if component not in IE_ENUM:
                violation(row, "unknown missing_component")
                continue
            ie_configs[component] = ie_configs.get(component, 0) + 1
            if "gold_path" in annotation:
                violation(row, "IE row encodes a complete gold path")
            status = (row.get("gold") or {}).get("expect_status")
            if component == "relevant_unresolved_conflict":
                if status != "CONFLICTING_EVIDENCE":
                    violation(row, "unresolved conflict must be "
                                   "CONFLICTING_EVIDENCE")
            elif status != "INSUFFICIENT_EVIDENCE":
                violation(row, "IE gold status must be INSUFFICIENT_EVIDENCE")
        if tags & {"source_injection_safe_fact", "query_injection_or_spoof"}:
            wording = annotation.get("attack_wording")
            if not wording:
                violation(row, "attack row lacks attack_wording")
                continue
            attack_wordings.add(_normalized_phrase(wording))
            if "query_injection_or_spoof" in tags and not \
                    _contains_phrase(query, str(wording)):
                violation(row, "query attack wording is not in query")
            if "source_injection_safe_fact" in tags:
                evidence_ids = annotation.get("attack_evidence_chunk_ids")
                if not isinstance(evidence_ids, list) or not evidence_ids:
                    violation(row, "source attack lacks evidence chunk IDs")
                elif not any(
                    chunk_id in chunks_by_id and _contains_phrase(
                        chunks_by_id[chunk_id]["text"], str(wording))
                    for chunk_id in evidence_ids
                ):
                    violation(row, "source attack wording is not in evidence")
                for field in ("safe_fact_entity", "safe_fact_attribute",
                              "safe_fact_value"):
                    if field not in annotation:
                        violation(row, f"safe-fact row lacks {field}")

    multihop_rows = len(multihop)
    crossdomain_rows = len(crossdomain)
    largest_family = max(families.values(), default=0)
    largest_pair = max(pair_counts.values(), default=0)
    # The measured quota denominator: only rows satisfying every
    # multisource_path_qualifies condition.  The raw tag count is recorded
    # separately so tagged-but-not-qualifying rows stay visible.
    multisource_path_rows = sum(
        1 for name, suite_rows in rows_by_suite.items()
        for row in suite_rows
        if multisource_path_qualifies(row, name))

    current = {
        "case_ids": {row["case_id"] for row in rows},
        "entity_identities": _entities(corpus_dir, chunks),
        "source_ids": {source["source_id"] for source in sources},
        "chunk_ids": {chunk["chunk_id"] for chunk in chunks},
        "exact_queries": {row["request"]["query"] for row in rows},
        "exact_answers": _answers(rows),
        "exact_source_text": {chunk["text"] for chunk in chunks},
    }
    independence: dict[str, dict[str, int]] = {}
    for milestone in contract["independence_requirements"][
            "comparison_milestones"]:
        prior = _prior_material(milestone)
        independence[milestone] = {
            dimension: len(current[dimension] & prior[dimension])
            for dimension in contract["independence_requirements"][
                "zero_overlap_dimensions"]
            if dimension != "verbatim_attacks"
        }
        prior_text = tuple(prior["combined_text"])
        independence[milestone]["verbatim_attacks"] = sum(
            1 for wording in attack_wordings
            if any(_contains_phrase(text, wording) for text in prior_text))

    metrics = {
        "annotation_violations": len(violations),
        "total_rows": len(rows),
        "suite_rows": {name: len(suite_rows)
                       for name, suite_rows in rows_by_suite.items()},
        "stresses": {
            "multihop_rows": multihop_rows,
            "multihop_chain_families": len(families),
            "multihop_largest_family_count": largest_family,
            "multihop_largest_chain_family_share": (
                largest_family / multihop_rows if multihop_rows else 0.0),
            "multihop_surface_mismatch_rows": multihop_mismatch,
            "crossdomain_rows": crossdomain_rows,
            "crossdomain_two_source_two_domain_rows": two_source_two_domain,
            "domain_pair_families": len(pair_counts),
            "largest_domain_pair_count": largest_pair,
            "largest_domain_pair_share": (
                largest_pair / crossdomain_rows if crossdomain_rows else 0.0),
            "multisource_path_rows": multisource_path_rows,
            "multisource_path_tagged_rows": tag_counts["multisource_path"],
            "partial_path_ie_rows": tag_counts["partial_path_ie_stress"],
            "ie_configurations": ie_configs,
            "relation_surface_sensitive_rows": surface_rows,
            "canonical_relations": sorted(canonical_relations),
            "relation_surface_mismatch_rows": surface_mismatch,
            "source_injection_safe_fact_rows": tag_counts[
                "source_injection_safe_fact"],
            "safe_fact_with_directive_rows": tag_counts[
                "safe_fact_with_directive"],
            "query_injection_or_spoof_rows": tag_counts[
                "query_injection_or_spoof"],
        },
        "independence": independence,
    }
    return {"metrics": metrics, "annotation_violation_details": violations}