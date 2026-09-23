"""Hash-only T23 historical, development, qualification, and collision audit."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .contract import canonical

DIMENSIONS = ("case_ids", "entity_identities", "source_ids", "chunk_ids",
              "exact_queries", "exact_answers", "exact_source_text",
              "verbatim_attack_wording", "relations")
HEX = re.compile(r"^[0-9a-f]{64}$")


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"missing or escaping exclusion source: {relative}")
    return target


def _source(root: Path, record: dict[str, str]) -> tuple[Path, Any]:
    if set(record) != {"path", "sha256"} or not HEX.fullmatch(record["sha256"]):
        raise ValueError("incomplete exclusion source binding")
    path = _safe(root, record["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"exclusion source hash mismatch: {record['path']}")
    return path, json.loads(path.read_text(encoding="utf-8")) if path.suffix == ".json" else None


def load_exclusion_sources(root: Path, registry: dict[str, Any]) -> dict[str, set[str]]:
    """Fail closed for absent anchors, incomplete milestones, or unknown dimensions."""
    if set(registry) != {"schema_version", "sources", "required_milestones"} or registry["schema_version"] != "t23-exclusion-sources-v1":
        raise ValueError("exclusion source registry schema mismatch")
    sources = registry["sources"]
    if set(sources) != {"historical", "remediation", "qualification", "t22_anchor"}:
        raise ValueError("missing exclusion source category")
    forbidden = {name: set() for name in DIMENSIONS}
    _, historical = _source(root, sources["historical"])
    if (historical.get("raw_values_included") is not False
            or historical.get("milestone_order") != registry["required_milestones"]
            or historical.get("historical_milestone_count") != len(registry["required_milestones"])
            or set(historical.get("milestones", {})) != set(registry["required_milestones"])):
        raise ValueError("historical milestone set incomplete")
    for milestone in registry["required_milestones"]:
        dimensions = historical["milestones"][milestone].get("dimensions", {})
        if set(dimensions) != set(DIMENSIONS) - {"relations"}:
            raise ValueError(f"unknown or missing historical fingerprint dimension: {milestone}")
        for name, entry in dimensions.items():
            values = entry.get("fingerprints")
            if not isinstance(values, list) or entry.get("count") != len(values) or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in values):
                raise ValueError(f"invalid historical fingerprint anchor: {milestone}/{name}")
            forbidden[name].update(values)
    _, remediation = _source(root, sources["remediation"])
    if remediation.get("raw_values_included") is not False or set(remediation.get("dimensions", {})) != set(DIMENSIONS):
        raise ValueError("remediation dimensions incomplete")
    for name, values in remediation["dimensions"].items():
        if not isinstance(values, list) or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in values):
            raise ValueError(f"invalid remediation fingerprint dimension: {name}")
        forbidden[name].update(values)
    qualification_path, _ = _source(root, sources["qualification"])
    with qualification_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            for name, field in (("case_ids", "case_id"), ("exact_queries", "query")):
                if not isinstance(row.get(field), str):
                    raise ValueError("qualification exclusion row incomplete")
                forbidden[name].add(fingerprint(row[field]))
    _, t22 = _source(root, sources["t22_anchor"])
    if t22.get("schema_version") != "t23-t22-hash-only-anchor-v1" or t22.get("raw_values_included") is not False or len(t22.get("source_sha256", {})) != 11:
        raise ValueError("T22 historical anchor incomplete")
    for relative, expected in t22["source_sha256"].items():
        if hashlib.sha256(_safe(root, relative).read_bytes()).hexdigest() != expected:
            raise ValueError(f"unreadable or changed T22 historical anchor: {relative}")
    for name, values in t22.get("fingerprints", {}).items():
        if name not in forbidden or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in values):
            raise ValueError(f"unknown T22 fingerprint dimension: {name}")
        forbidden[name].update(values)
    return forbidden


def audit_exclusions(root: Path, registry: dict[str, Any], inputs: list[dict[str, Any]],
                     gold: list[dict[str, Any]], corpus: Any) -> dict[str, Any]:
    forbidden = load_exclusion_sources(root, registry)
    observed: dict[str, list[str]] = {name: [] for name in DIMENSIONS}
    suite_queries: dict[str, set[str]] = {}
    for inp, expected in zip(inputs, gold):
        if inp.get("case_id") != expected.get("case_id"):
            raise ValueError("input/gold row identity mismatch")
        suite = expected.get("family")
        query = inp.get("candidate_input", {}).get("query")
        if not isinstance(suite, str) or not isinstance(query, str):
            raise ValueError("missing suite or query")
        observed["case_ids"].append(fingerprint(inp["case_id"]))
        query_hash = fingerprint(query)
        observed["exact_queries"].append(query_hash)
        suite_queries.setdefault(suite, set()).add(query_hash)
        if suite in {"security_adversarial", "route_override_adversarial"}:
            observed["verbatim_attack_wording"].append(query_hash)
    for source in corpus.sources:
        observed["source_ids"].append(fingerprint(source.source_id))
        observed["entity_identities"].append(fingerprint(source.source_title))
        if source.content_text:
            observed["exact_source_text"].append(fingerprint(source.content_text))
    for chunk in corpus.chunks:
        observed["chunk_ids"].append(fingerprint(chunk.chunk_id))
        observed["exact_source_text"].append(fingerprint(chunk.text))
    duplicates = {name: sum(count - 1 for count in Counter(values).values() if count > 1)
                  for name, values in observed.items()}
    collisions = {name: len(set(values) & forbidden[name]) for name, values in observed.items()}
    cross_suite = sum(1 for query in set(observed["exact_queries"])
                      if sum(query in values for values in suite_queries.values()) > 1)
    semantic = [hashlib.sha256(canonical(inp["candidate_input"])).hexdigest() for inp in inputs]
    semantic_duplicates = sum(count - 1 for count in Counter(semantic).values() if count > 1)
    violations = sum(duplicates.values()) + sum(collisions.values()) + cross_suite + semantic_duplicates
    return {"schema_version": "t23-exclusion-audit-v1",
            "status": "PASS" if violations == 0 else "FAIL", "violations": violations,
            "historical_milestones": len(registry["required_milestones"]) + 1,
            "fingerprint_dimensions": list(DIMENSIONS),
            "forbidden_counts": {k: len(v) for k, v in forbidden.items()},
            "collisions": collisions, "duplicates": duplicates,
            "cross_suite_collisions": cross_suite,
            "semantic_fingerprint_duplicates": semantic_duplicates}
