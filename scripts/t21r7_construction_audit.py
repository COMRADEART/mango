"""Derive T21R7 construction metrics from candidate files only.

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
OUT_DIR = ROOT / "evaluations" / "t21r7"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r7"
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
}


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
    out_dir = root / "evaluations" / "t21r7"
    corpus_dir = root / "rag" / "gk_holdout_t21r7"
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

    violations: list[dict] = []
    relation_rows = 0
    mismatch_rows = 0
    canonical_relations: set[str] = set()
    qualifier_rows = 0
    qualifier_types = {
        "non_binding_qualifier": 0,
        "identity_critical_qualifier": 0,
    }
    tag_counts = {
        "routing_boundary": 0,
        "absent_entity_conflict_stress": 0,
        "source_injection_safe_fact": 0,
        "query_injection_or_spoof": 0,
    }
    attack_wordings: set[str] = set()

    def violation(row: dict, reason: str) -> None:
        violations.append({"case_id": row.get("case_id"), "reason": reason})

    for row in rows:
        tags = set(row.get("construction_tags") or [])
        annotation = row.get("construction") or {}
        query = str((row.get("request") or {}).get("query", ""))
        if "relation_paraphrase_sensitive" in tags:
            relation_rows += 1
            relation = annotation.get("canonical_relation")
            token = annotation.get("evidence_relation_token")
            evidence_ids = annotation.get("relation_evidence_chunk_ids")
            if not relation or not token or not isinstance(evidence_ids, list) \
                    or not evidence_ids:
                violation(row, "incomplete relation-stress annotation")
            else:
                canonical_relations.add(str(relation))
                missing = [chunk_id for chunk_id in evidence_ids
                           if chunk_id not in chunks_by_id]
                if missing:
                    violation(row, "relation evidence chunk is missing")
                evidence_has_token = any(
                    _contains_phrase(chunks_by_id[chunk_id]["text"], str(token))
                    for chunk_id in evidence_ids if chunk_id in chunks_by_id)
                if not evidence_has_token:
                    violation(row, "evidence relation token is not in evidence")
                elif not _contains_phrase(query, str(token)):
                    mismatch_rows += 1
        if "qualifier_sensitive" in tags:
            qualifier_rows += 1
            qtype = annotation.get("qualifier_type")
            literal = annotation.get("qualifier_literal")
            if qtype not in qualifier_types or not literal:
                violation(row, "invalid qualifier annotation")
            else:
                qualifier_types[str(qtype)] += 1
                if not _contains_phrase(query, str(literal)):
                    violation(row, "qualifier literal is not in query")
        for tag in tag_counts:
            if tag in tags:
                tag_counts[tag] += 1
        if tags & {"source_injection_safe_fact", "query_injection_or_spoof"}:
            wording = annotation.get("attack_wording")
            if not wording:
                violation(row, "attack row lacks attack_wording")
            else:
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
            if any(_contains_phrase(text, wording) for text in prior_text)
        )

    metrics = {
        "annotation_violations": len(violations),
        "total_rows": len(rows),
        "suite_rows": {name: len(suite_rows)
                       for name, suite_rows in rows_by_suite.items()},
        "stresses": {
            "relation_paraphrase_sensitive_rows": relation_rows,
            "canonical_relations": sorted(canonical_relations),
            "relation_surface_mismatch_rows": mismatch_rows,
            "qualifier_sensitive_rows": qualifier_rows,
            "non_binding_qualifier": qualifier_types[
                "non_binding_qualifier"],
            "identity_critical_qualifier": qualifier_types[
                "identity_critical_qualifier"],
            "routing_boundary_rows": tag_counts["routing_boundary"],
            "absent_entity_conflict_stress_rows": tag_counts[
                "absent_entity_conflict_stress"],
            "source_injection_safe_fact_rows": tag_counts[
                "source_injection_safe_fact"],
            "query_injection_or_spoof_rows": tag_counts[
                "query_injection_or_spoof"],
        },
        "independence": independence,
    }
    return {"metrics": metrics, "annotation_violation_details": violations}
