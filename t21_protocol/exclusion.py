"""Hash-only historical/remediation exclusion validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .util import read_json, sha256_bytes, sha256_file

DIMENSIONS = (
    "case_ids",
    "entity_identities",
    "source_ids",
    "chunk_ids",
    "exact_queries",
    "exact_answers",
    "exact_source_text",
    "verbatim_attack_wording",
)
REMEDIATION_DIMENSIONS = (*DIMENSIONS, "relations")


def fingerprint(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def validate_historical_policy(policy: dict[str, Any], root: Path) -> dict[str, Any]:
    history_keys = {"r14_protocol_history", "r15_protocol_history", "r16_protocol_history"}
    required = {
        "schema_version",
        "artifact",
        "experiment",
        "raw_values_included",
        "historical_milestone_count",
        "milestones",
        "upstream_registry",
        "upstream_registry_sha256",
    }
    accepted = required | {"r14_protocol_history"}, required | {"r15_protocol_history"}, required | {"r16_protocol_history"}
    if set(policy) not in accepted:
        raise ValidationError("historical exclusion policy violates closed schema")
    present_history = sorted(history_keys & set(policy))
    if len(present_history) != 1:
        raise ValidationError("historical exclusion policy must name exactly one prior protocol history")
    history_key = present_history[0]
    if policy["raw_values_included"] is not False:
        raise ValidationError("historical exclusion policy contains raw values")
    if policy["historical_milestone_count"] != len(policy["milestones"]):
        raise ValidationError("historical milestone count mismatch")
    if policy["historical_milestone_count"] < 14:
        raise ValidationError("fewer than 14 historical milestones")
    if "T21R14" in policy["milestones"]:
        raise ValidationError("R14 must not be represented as fake blind material")
    prior = policy[history_key]
    if prior.get("blind_fingerprints_invented") is not False:
        raise ValidationError(f"{history_key} invents blind fingerprints")
    upstream = root / policy["upstream_registry"]
    if not upstream.is_file() or sha256_file(upstream) != policy["upstream_registry_sha256"]:
        raise ValidationError("historical upstream registry hash mismatch")
    upstream_doc = read_json(upstream)
    if upstream_doc.get("raw_values_included") is not False:
        raise ValidationError("upstream registry is not hash-only")
    return {
        "status": "PASS",
        "historical_milestones": policy["historical_milestone_count"],
        "dimensions": len(DIMENSIONS),
        f"{history_key.removesuffix('_protocol_history')}_protocol_history_only": True,
    }


def validate_remediation_policy(policy: dict[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "artifact", "experiment", "raw_values_included", "dimensions", "source"}
    if set(policy) != required:
        raise ValidationError("remediation exclusion policy violates closed schema")
    if policy["raw_values_included"] is not False:
        raise ValidationError("remediation exclusion contains raw values")
    if set(policy["dimensions"]) != set(REMEDIATION_DIMENSIONS):
        raise ValidationError("remediation exclusion is missing a dimension")
    for name, values in policy["dimensions"].items():
        if not isinstance(values, list):
            raise ValidationError(f"remediation dimension is not an array: {name}")
        if any(not isinstance(value, str) or len(value) != 64 for value in values):
            raise ValidationError(f"remediation dimension includes a raw value: {name}")
    return {"status": "PASS", "dimensions": len(policy["dimensions"])}


def audit_fingerprints(rows: Iterable[dict[str, Any]], forbidden: dict[str, set[str]]) -> dict[str, Any]:
    collisions: list[dict[str, str]] = []
    mapping = {
        "case_ids": "case_id",
        "entity_identities": "entity_identity",
        "source_ids": "source_id",
        "chunk_ids": "chunk_id",
        "exact_queries": "query",
        "exact_answers": "answer",
        "exact_source_text": "source_text",
        "verbatim_attack_wording": "attack_wording",
        "relations": "relation",
    }
    for row in rows:
        for dimension, field in mapping.items():
            value = row.get(field)
            if isinstance(value, str) and fingerprint(value) in forbidden.get(dimension, set()):
                collisions.append({"dimension": dimension, "fingerprint": fingerprint(value)})
    return {"status": "PASS" if not collisions else "FAIL", "collisions": collisions}
