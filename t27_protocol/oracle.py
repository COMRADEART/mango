"""Hash-only verifier for the sealed T26-to-T27 overlap oracle."""
from __future__ import annotations

from typing import Any

from t21_protocol.util import sha256_json

from .exclusion import DIMENSIONS

SCHEMA = "t27-t26-overlap-oracle-result-v1"
ARTIFACT = "T26_TO_T27_OVERLAP_ORACLE_RESULT"
REQUIRED_ORACLE = "t26_protocol.t27_private_oracle:T27_PRIVATE_OVERLAP_ENGINE"


def verify_oracle_result(result: dict[str, Any]) -> dict[str, Any]:
    """Verify a commitment without opening a T26 row or returning a value."""
    required = {
        "schema_version", "artifact", "experiment", "oracle_implementation",
        "t26_private_holdout_root", "t26_private_manifest_sha256",
        "t26_construction_seal_sha256", "t26_evaluation_ledger_sha256",
        "t27_prospective_fingerprint_root", "dimensions",
        "overall_prohibited_overlap", "oracle_execution_timestamp",
        "result_sha256",
    }
    if not isinstance(result, dict) or set(result) != required:
        raise ValueError("T26 oracle result has unknown or absent fields")
    if result["schema_version"] != SCHEMA or result["artifact"] != ARTIFACT:
        raise ValueError("T26 oracle result schema mismatch")
    if result["experiment"] != "t27" or result["oracle_implementation"] != REQUIRED_ORACLE:
        raise ValueError("T26 oracle identity mismatch")
    for key in (
        "t26_private_holdout_root", "t26_private_manifest_sha256",
        "t26_construction_seal_sha256", "t26_evaluation_ledger_sha256",
        "t27_prospective_fingerprint_root",
    ):
        if not isinstance(result[key], str) or len(result[key]) != 64:
            raise ValueError(f"invalid oracle binding: {key}")
    if not isinstance(result["dimensions"], dict) or set(result["dimensions"]) != set(DIMENSIONS):
        raise ValueError("oracle must bind all nine exclusion dimensions")
    total = 0
    for name in DIMENSIONS:
        entry = result["dimensions"][name]
        if not isinstance(entry, dict) or set(entry) != {
            "applicable", "prospective_population", "historical_population",
            "overlap_count",
        }:
            raise ValueError(f"oracle dimension binding mismatch: {name}")
        if not isinstance(entry["applicable"], bool):
            raise ValueError(f"oracle applicability invalid: {name}")
        for field in ("prospective_population", "historical_population", "overlap_count"):
            if not isinstance(entry[field], int) or entry[field] < 0:
                raise ValueError(f"oracle population invalid: {name}.{field}")
        if entry["applicable"] and entry["prospective_population"] == 0:
            raise ValueError(f"applicable oracle dimension is empty: {name}")
        total += entry["overlap_count"]
    if total != 0 or result["overall_prohibited_overlap"] != 0:
        raise ValueError("T26-to-T27 prohibited overlap is nonzero")
    expected = sha256_json({key: value for key, value in result.items()
                            if key != "result_sha256"})
    if result["result_sha256"] != expected:
        raise ValueError("T26 oracle result hash mismatch")
    return {
        "status": "PASS", "dimension_count": len(DIMENSIONS),
        "overall_prohibited_overlap": 0,
        "result_sha256": result["result_sha256"],
        "t26_private_rows_exposed_to_t27": 0,
    }
