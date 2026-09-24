"""Hash-only T25 exclusion engine: prior milestones, T22/T23/T24 anchors, qualification.

Every T25 construction input is fingerprinted across all nine exclusion
dimensions and must have zero overlap with any registered forbidden set —
including the T24_SEALED_EVALUATED anchor's provenance fingerprints (T24's
real blind material itself stays private-store-only and is never opened).
Unknown sources fail closed.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .anchor_t24 import ANCHOR_SCHEMA, DIMENSIONS

HEX = re.compile(r"^[0-9a-f]{64}$")
EXCLUDED_MILESTONES = 20  # 17 prior milestones + T22_SEALED + T23_EXPOSED_SEALED + T24_SEALED_EVALUATED


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"missing or escaping exclusion source: {relative}")
    return target


def _binding(root: Path, record: dict[str, Any], field: str = "path") -> Path:
    if not isinstance(record, dict) or field not in record or "sha256" not in record:
        raise ValueError("incomplete exclusion source binding")
    if not HEX.fullmatch(record["sha256"]):
        raise ValueError("incomplete exclusion source binding")
    path = _safe(root, record[field])
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"exclusion source hash mismatch: {record[field]}")
    return path


def _fingerprints_dimension(name: str, values: Any) -> set[str]:
    if not isinstance(values, list) or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in values):
        raise ValueError(f"invalid fingerprint dimension: {name}")
    return set(values)


def load_exclusion_sources(root: Path, registry: dict[str, Any]) -> dict[str, set[str]]:
    """Fail closed for absent anchors, incomplete milestones, or unknown dimensions."""
    if (not isinstance(registry, dict)
            or registry.get("schema_version") != "t25-exclusion-sources-v2"
            or not {"schema_version", "sources", "required_milestones",
                    "additional_anchors", "dimensions"} <= set(registry)):
        raise ValueError("exclusion source registry schema mismatch")
    if registry["required_milestones"] != list(_milestone_order(root)):
        raise ValueError("historical milestone order mismatch")
    if registry["dimensions"] != list(DIMENSIONS):
        raise ValueError("exclusion dimension set mismatch")
    if set(registry["additional_anchors"]) != {"T22_SEALED", "T23_EXPOSED_SEALED",
                                               "T24_SEALED_EVALUATED"}:
        raise ValueError("required anchor set mismatch")
    sources = registry["sources"]
    if set(sources) != {"t21_historical", "t22_anchor", "t23_exposed_sealed",
                        "t24_sealed_evaluated", "open_development",
                        "t25_public_qualification", "t25_disposable_rehearsal"}:
        raise ValueError("missing exclusion source category")
    forbidden: dict[str, set[str]] = {name: set() for name in DIMENSIONS}
    for name, entry in sources.items():
        kind = entry.get("kind")
        path = _binding(root, entry)
        if kind == "milestone_registry":
            document = json.loads(path.read_text(encoding="utf-8"))
            if (document.get("raw_values_included") is not False
                    or document.get("milestone_order") != registry["required_milestones"]):
                raise ValueError("historical milestone set incomplete")
            for milestone in registry["required_milestones"]:
                dimensions = document["milestones"][milestone].get("dimensions", {})
                if set(dimensions) != set(DIMENSIONS) - {"relations"}:
                    raise ValueError(f"unknown or missing historical fingerprint dimension: {milestone}")
                for dimension, anchor in dimensions.items():
                    values = anchor.get("fingerprints")
                    if (not isinstance(values, list) or anchor.get("count") != len(values)
                            or any(not isinstance(v, str) or not HEX.fullmatch(v) for v in values)):
                        raise ValueError(f"invalid historical fingerprint anchor: {milestone}/{dimension}")
                    forbidden[dimension].update(values)
        elif kind == "hash_only_anchor":
            document = json.loads(path.read_text(encoding="utf-8"))
            if (document.get("raw_values_included") is not False
                    or document.get("schema_version") != "t23-t22-hash-only-anchor-v1"
                    or len(document.get("source_sha256", {})) != 11):
                raise ValueError("T22 historical anchor incomplete")
            for relative, expected in document["source_sha256"].items():
                if hashlib.sha256(_safe(root, relative).read_bytes()).hexdigest() != expected:
                    raise ValueError(f"unreadable or changed T22 historical anchor: {relative}")
            for dimension, values in document.get("fingerprints", {}).items():
                forbidden[dimension].update(_fingerprints_dimension(dimension, values))
        elif kind == "exposed_sealed_anchor":
            document = json.loads(path.read_text(encoding="utf-8"))
            if (document.get("schema_version") != "t23-exposed-sealed-anchor-v1"
                    or document.get("raw_values_included") is not False
                    or set(document.get("dimensions", {})) != set(DIMENSIONS)):
                raise ValueError("T23 exposed-sealed anchor incomplete")
            for dimension in DIMENSIONS:
                forbidden[dimension].update(_fingerprints_dimension(
                    dimension, document["dimensions"][dimension]["fingerprints"]))
        elif kind == "sealed_evaluated_anchor":
            document = json.loads(path.read_text(encoding="utf-8"))
            if (document.get("schema_version") != ANCHOR_SCHEMA
                    or document.get("raw_values_included") is not False
                    or document.get("t24_must_not_be_rerun") is not True
                    or document.get("t24_private_material_must_not_be_opened") is not True
                    or document.get("t25_candidate_must_not_execute_on_t24_rows") is not True
                    or not isinstance(document.get("dimensions"), dict)):
                raise ValueError("T24 sealed-evaluated anchor incomplete")
            dimensions = document["dimensions"]
            if set(dimensions) != set(DIMENSIONS) | {"artifact_content"}:
                raise ValueError("T24 anchor dimension set mismatch")
            for dimension in DIMENSIONS:
                forbidden[dimension].update(_fingerprints_dimension(
                    dimension, dimensions[dimension]["fingerprints"]))
            # The artifact-content dimension hash-excludes every committed T24
            # artifact; it is bound here but audited as source provenance, not
            # against T25 row material.
            artifacts = dimensions["artifact_content"]
            _fingerprints_dimension("artifact_content", artifacts["fingerprints"])
            if artifacts.get("count", 0) < 25:
                raise ValueError("T24 anchor artifact-content dimension incomplete")
        elif kind == "remediation":
            document = json.loads(path.read_text(encoding="utf-8"))
            if (document.get("raw_values_included") is not False
                    or set(document.get("dimensions", {})) != set(DIMENSIONS)):
                raise ValueError("remediation dimensions incomplete")
            for dimension, values in document["dimensions"].items():
                forbidden[dimension].update(_fingerprints_dimension(dimension, values))
        elif kind == "qualification_rows":
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    for dimension, field in (("case_ids", "case_id"), ("exact_queries", "query")):
                        if not isinstance(row.get(field), str):
                            raise ValueError("qualification exclusion row incomplete")
                        forbidden[dimension].add(fingerprint(row[field]))
        elif kind == "t25_fingerprint_set":
            document = json.loads(path.read_text(encoding="utf-8"))
            if (document.get("schema_version") != "t25-dimension-fingerprint-set-v1"
                    or document.get("raw_values_included") is not False
                    or not isinstance(document.get("dimensions"), dict)
                    or set(document["dimensions"]) - set(DIMENSIONS)):
                raise ValueError("T25 fingerprint-set source incomplete")
            for dimension, values in document["dimensions"].items():
                forbidden[dimension].update(_fingerprints_dimension(dimension, values))
        else:
            raise ValueError(f"unknown exclusion source kind: {kind}")
    return forbidden


def _milestone_order(root: Path) -> list[str]:
    prior = json.loads((Path(root) / "evaluations/t22/prior_exclusion.json").read_text(encoding="utf-8"))
    return list(prior["milestone_order"])


def audit_exclusions(root: Path, registry: dict[str, Any], inputs: list[dict[str, Any]],
                     gold: list[dict[str, Any]], corpus: Any,
                     attachment_text: str | None = None) -> dict[str, Any]:
    """Zero-overlap proof for a candidate T25 holdout against every forbidden set."""
    from .contract import canonical

    forbidden = load_exclusion_sources(root, registry)
    observed: dict[str, list[str]] = {name: [] for name in DIMENSIONS}
    suite_queries: dict[str, set[str]] = {}
    for inp, expected in zip(inputs, gold):
        if inp.get("case_id") != expected.get("case_id"):
            raise ValueError("input/gold row identity mismatch")
        family = expected.get("family")
        query = inp.get("candidate_input", {}).get("query")
        if not isinstance(family, str) or not isinstance(query, str):
            raise ValueError("missing suite or query")
        observed["case_ids"].append(fingerprint(inp["case_id"]))
        query_hash = fingerprint(query)
        observed["exact_queries"].append(query_hash)
        suite_queries.setdefault(family, set()).add(query_hash)
        observed["exact_answers"].append(fingerprint(canonical(expected).decode("utf-8")))
        if family in {"security_adversarial", "route_override_adversarial"}:
            observed["verbatim_attack_wording"].append(query_hash)
    for source in corpus.sources:
        observed["source_ids"].append(fingerprint(source.source_id))
        observed["entity_identities"].append(fingerprint(source.source_title))
        if getattr(source, "content_text", None):
            observed["exact_source_text"].append(fingerprint(source.content_text))
        relations = getattr(source, "relations", None)
        if relations:
            observed["relations"].append(fingerprint(json.dumps(
                list(relations), sort_keys=True, separators=(",", ":"), ensure_ascii=True)))
    for chunk in corpus.chunks:
        observed["chunk_ids"].append(fingerprint(chunk.chunk_id))
        observed["exact_source_text"].append(fingerprint(chunk.text))
    if attachment_text is not None:
        observed["exact_source_text"].append(fingerprint(attachment_text))
    duplicates = {name: sum(count - 1 for count in Counter(values).values() if count > 1)
                  for name, values in observed.items()}
    collisions = {name: len(set(values) & forbidden[name]) for name, values in observed.items()}
    cross_suite = sum(1 for query in set(observed["exact_queries"])
                      if sum(query in values for values in suite_queries.values()) > 1)
    semantic = [hashlib.sha256(canonical(inp["candidate_input"])).hexdigest() for inp in inputs]
    semantic_duplicates = sum(count - 1 for count in Counter(semantic).values() if count > 1)
    violations = (sum(duplicates.values()) + sum(collisions.values()) + cross_suite
                  + semantic_duplicates)
    return {"schema_version": "t25-exclusion-audit-v1",
            "status": "PASS" if violations == 0 else "FAIL", "violations": violations,
            "excluded_milestones": EXCLUDED_MILESTONES,
            "excluded_anchors": ["T22_SEALED", "T23_EXPOSED_SEALED", "T24_SEALED_EVALUATED"],
            "fingerprint_dimensions": list(DIMENSIONS),
            "forbidden_counts": {k: len(v) for k, v in forbidden.items()},
            "collisions": collisions, "duplicates": duplicates,
            "cross_suite_collisions": cross_suite,
            "semantic_fingerprint_duplicates": semantic_duplicates}