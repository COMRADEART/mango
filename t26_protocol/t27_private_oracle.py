"""Sealed T26-side hash-only overlap oracle for prospective T27 material.

This module is executed at the T26 private boundary.  Its public return value
contains populations and overlap counts only; it never returns a T26 value.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from t21_protocol.util import sha256_json
from t27_protocol.exclusion import DIMENSIONS

T27_PRIVATE_OVERLAP_ENGINE = (
    "t26_protocol.t27_private_oracle:T27_PRIVATE_OVERLAP_ENGINE"
)


def _hash_set(values: Any, name: str) -> set[str]:
    if not isinstance(values, (list, set, tuple)):
        raise ValueError(f"oracle dimension is not a hash set: {name}")
    output = set(values)
    if any(not isinstance(value, str) or len(value) != 64 or
           any(char not in "0123456789abcdef" for char in value)
           for value in output):
        raise ValueError(f"oracle received a non-SHA-256 value: {name}")
    return output


def compare_hashes(*, prospective_root: str,
                   prospective: dict[str, list[str]],
                   sealed_historical: dict[str, list[str]],
                   t26_bindings: dict[str, str],
                   timestamp: str | None = None) -> dict[str, Any]:
    if not isinstance(prospective_root, str) or len(prospective_root) != 64:
        raise ValueError("prospective fingerprint root invalid")
    if set(prospective) != set(DIMENSIONS) or set(sealed_historical) != set(DIMENSIONS):
        raise ValueError("oracle requires all nine dimensions")
    required_bindings = {
        "t26_private_holdout_root", "t26_private_manifest_sha256",
        "t26_construction_seal_sha256", "t26_evaluation_ledger_sha256",
    }
    if set(t26_bindings) != required_bindings or any(
            not isinstance(value, str) or len(value) != 64
            for value in t26_bindings.values()):
        raise ValueError("T26 sealed oracle bindings incomplete")
    dimensions = {}
    total = 0
    for name in DIMENSIONS:
        future = _hash_set(prospective[name], name)
        historical = _hash_set(sealed_historical[name], name)
        overlap = len(future & historical)
        total += overlap
        dimensions[name] = {
            "applicable": bool(future),
            "prospective_population": len(future),
            "historical_population": len(historical),
            "overlap_count": overlap,
        }
    core = {
        "schema_version": "t27-t26-overlap-oracle-result-v1",
        "artifact": "T26_TO_T27_OVERLAP_ORACLE_RESULT",
        "experiment": "t27", "oracle_implementation": T27_PRIVATE_OVERLAP_ENGINE,
        **t26_bindings,
        "t27_prospective_fingerprint_root": prospective_root,
        "dimensions": dimensions,
        "overall_prohibited_overlap": total,
        "oracle_execution_timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }
    return {**core, "result_sha256": sha256_json(core)}
