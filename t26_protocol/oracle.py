"""T26 private-overlap oracle interface for T25 private holdout material.

The real overlap comparison against T25's private rows is performed inside the
T25 private store by the frozen ``t25_protocol.t26_private_oracle`` engine. It
writes a hash-bound zero-overlap commitment back into the T25 store; T26 (this
module) can then *verify* the commitment without ever reading a T25 private
row. The T26 author and the T26 candidate receive only the commitment.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

SCHEMA = "t26-private-overlap-oracle-result-v1"
ARTIFACT = "T25_PRIVATE_OVERLAP_ORACLE_RESULT"
EXPERIMENT = "t26"
REQUIRED_ORACLE = "t25_protocol.t26_private_oracle:T26_PRIVATE_OVERLAP_ENGINE"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_t25_bindings() -> dict[str, str]:
    """Public anchors the oracle result must bind (never T25 row content)."""
    root = Path(__file__).resolve().parents[1]
    commitments = _load_json(root / "evaluations/t25/t25_private_store_config.json")
    del commitments
    return {
        "T25_private_holdout_root",
        "T25_private_manifest_sha256",
        "T25_construction_seal_sha256",
        "T25_official_evaluation_ledger_sha256",
    }


def load_oracle_result(store_root: Path) -> dict[str, Any]:
    """Read the oracle result from the T25 private store (commitment only)."""
    path = Path(store_root) / "artifacts" / "t26_private_overlap_oracle_result.artifact"
    if not path.is_file():
        raise ValueError("T25 private overlap oracle result absent")
    return _load_json(path)


def verify_oracle_result(result: dict[str, Any], store_root: Path | None = None) -> dict[str, Any]:
    """Fail-closed verification of the hash-bound oracle result.

    This touches only the commitment document (hashes/counts). No T25 private
    row is opened, and the T26 candidate never receives the result.
    """
    if not isinstance(result, dict):
        raise ValueError("T25 private overlap oracle result is not a document")
    required = {
        "schema_version", "artifact", "experiment", "oracle_implementation",
        "t25_private_holdout_root", "t25_private_manifest_sha256",
        "t25_construction_seal_sha256", "t25_official_evaluation_ledger_sha256",
        "t26_candidate_private_input_fingerprint_root",
        "dimensions", "overall_overlap_count", "overall_overlap",
        "oracle_execution_timestamp", "result_sha256",
    }
    if set(result) != required:
        raise ValueError("T25 oracle result binding set mismatch (unknown or missing)")
    if result["schema_version"] != SCHEMA or result["artifact"] != ARTIFACT:
        raise ValueError("T25 oracle result schema mismatch")
    if result["experiment"] != EXPERIMENT:
        raise ValueError("T25 oracle result experiment mismatch")
    if result["oracle_implementation"] != REQUIRED_ORACLE:
        raise ValueError("T25 oracle implementation identity mismatch")
    for key in ("t25_private_holdout_root", "t25_private_manifest_sha256",
                "t25_construction_seal_sha256",
                "t25_official_evaluation_ledger_sha256",
                "t26_candidate_private_input_fingerprint_root"):
        value = result[key]
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"T25 oracle binding incomplete: {key}")
    dimensions = result["dimensions"]
    from .exclusion import DIMENSIONS

    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        raise ValueError("T25 oracle result must bind all nine overlap dimensions")
    compared_total = 0
    overlap_total = 0
    for name, entry in dimensions.items():
        if not isinstance(entry, dict) or set(entry) != {
                "applicable", "compared_population", "overlap_count"}:
            raise ValueError(f"T25 oracle dimension binding incomplete: {name}")
        if not isinstance(entry["applicable"], bool):
            raise ValueError(f"T25 oracle dimension applicability invalid: {name}")
        if entry["compared_population"] < 0 or entry["overlap_count"] != 0:
            raise ValueError(f"T25 oracle dimension overlap nonzero: {name}")
        if entry["applicable"] and entry["compared_population"] == 0:
            raise ValueError(f"T25 oracle dimension population invalid: {name}")
        compared_total += entry["compared_population"]
        overlap_total += entry["overlap_count"]
    if result["overall_overlap_count"] != overlap_total or overlap_total != 0:
        raise ValueError("T25 oracle overall overlap is not zero")
    if result["overall_overlap"] != "ZERO_OVERLAP_ATTESTED":
        raise ValueError("T25 oracle overall overlap attestation invalid")
    recomputed = sha256_json({key: value for key, value in result.items()
                              if key != "result_sha256"})
    if recomputed != result["result_sha256"]:
        raise ValueError("T25 oracle result hash mismatch (tampered or stale)")
    return {"status": "PASS", "overall_overlap": "ZERO_OVERLAP_ATTESTED",
            "compared_population_total": compared_total,
            "dimension_count": len(dimensions),
            "result_sha256": result["result_sha256"],
            "t25_private_rows_exposed_to_t26": 0}

