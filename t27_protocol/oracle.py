"""Fail-closed verifier for synthetic and authenticated-real T26 oracles."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .exclusion import DIMENSIONS

ARTIFACT = "T26_TO_T27_OVERLAP_ORACLE_RESULT"
REAL_SCHEMA = "t27-t26-sealed-overlap-oracle-result-v2"
SYNTHETIC_SCHEMA = "t27-t26-synthetic-overlap-oracle-result-v1"
SEALED_ORACLE = (
    "t26_protocol.t27_private_oracle:run_sealed_t26_to_t27_overlap_oracle"
)
SYNTHETIC_ORACLE = "t26_protocol.t27_private_oracle:compare_hashes"

COMMITMENT_FIELDS = (
    "t26_private_holdout_root", "t26_private_manifest_sha256",
    "t26_construction_seal_sha256", "t26_evaluation_ledger_sha256",
)


def _hex(value: Any, length: int = 64) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def verify_oracle_result(result: dict[str, Any], *, mode: str = "SYNTHETIC",
                         root: Path | None = None,
                         expected_t27_root: str | None = None,
                         expected_t26_bindings: dict[str, Any] | None = None
                         ) -> dict[str, Any]:
    """Verify the exact schema, mode, identities, roots, and zero overlap."""
    required = {
        "schema_version", "artifact", "experiment", "mode",
        "official_commitment_scope", "oracle_implementation",
        "t26_store_authenticated", "t26_store_identity", "t26_namespace",
        *COMMITMENT_FIELDS, "t26_official_evaluation_state",
        "t26_official_evaluation_attempt", "t26_fingerprint_index_root",
        "t26_fingerprint_index_origin", "t27_prospective_fingerprint_root",
        "dimensions", "overall_prohibited_overlap",
        "oracle_execution_timestamp", "outside_boundary_private_rows_exposed",
        "result_sha256",
    }
    if not isinstance(result, dict) or set(result) != required:
        raise ValueError("T26 oracle result has unknown or absent fields")
    if result["artifact"] != ARTIFACT or result["experiment"] != "t27":
        raise ValueError("T26 oracle result identity mismatch")
    commitments_exact = False
    if mode == "REAL":
        from t26_protocol.t27_private_oracle import official_t26_commitments

        if root is None:
            raise ValueError("real oracle verification requires repository root")
        expected = official_t26_commitments(root)
        if (result["schema_version"] != REAL_SCHEMA
                or result["mode"] != "REAL_SEALED"
                or result["official_commitment_scope"] != "OFFICIAL_T26"
                or result["oracle_implementation"] != SEALED_ORACLE
                or result["t26_store_authenticated"] is not True):
            raise ValueError("real construction requires authenticated sealed T26 oracle")
        commitments_exact = all(result.get(key) == expected[key] for key in expected)
        if not commitments_exact:
            raise ValueError("real T26 oracle commitments are not exact official values")
    elif mode == "REAL_REHEARSAL":
        if (result["schema_version"] != REAL_SCHEMA
                or result["mode"] != "REAL_SEALED"
                or result["official_commitment_scope"] != "DISPOSABLE_STANDIN"
                or result["oracle_implementation"] != SEALED_ORACLE
                or result["t26_store_authenticated"] is not True):
            raise ValueError("real-mode oracle rehearsal is not store-authenticated")
        if expected_t26_bindings is not None:
            commitments_exact = all(result.get(key) == value
                                    for key, value in expected_t26_bindings.items())
            if not commitments_exact:
                raise ValueError("rehearsal T26 commitments are not exact")
        else:
            commitments_exact = True
    elif mode == "SYNTHETIC":
        if (result["schema_version"] != SYNTHETIC_SCHEMA
                or result["mode"] != "SYNTHETIC_DISPOSABLE"
                or result["official_commitment_scope"] != "SYNTHETIC_DISPOSABLE"
                or result["oracle_implementation"] != SYNTHETIC_ORACLE
                or result["t26_store_authenticated"] is not False):
            raise ValueError("synthetic oracle must use explicit disposable schema")
    else:
        raise ValueError("unknown T26 oracle verification mode")
    if expected_t27_root is not None and result[
            "t27_prospective_fingerprint_root"] != expected_t27_root:
        raise ValueError("T26 oracle prospective T27 root mismatch")
    for key in (*COMMITMENT_FIELDS, "t26_fingerprint_index_root",
                "t27_prospective_fingerprint_root"):
        if not _hex(result[key]):
            raise ValueError(f"invalid oracle binding: {key}")
    if not isinstance(result["dimensions"], dict) or set(
            result["dimensions"]) != set(DIMENSIONS):
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
        for field in ("prospective_population", "historical_population",
                      "overlap_count"):
            if not isinstance(entry[field], int) or entry[field] < 0:
                raise ValueError(f"oracle population invalid: {name}.{field}")
        if entry["applicable"] and entry["prospective_population"] == 0:
            raise ValueError(f"applicable oracle dimension is empty: {name}")
        total += entry["overlap_count"]
    if total != 0 or result["overall_prohibited_overlap"] != 0:
        raise ValueError("T26-to-T27 prohibited overlap is nonzero")
    if result["outside_boundary_private_rows_exposed"] != 0:
        raise ValueError("T26 oracle exposed private rows outside sealed boundary")
    if (mode != "SYNTHETIC" and
            (result["t26_official_evaluation_state"] != "COMPLETE"
             or result["t26_official_evaluation_attempt"] != 1)):
        raise ValueError("T26 official evaluation state is not authenticated COMPLETE/1")
    expected_hash = sha256_json({key: value for key, value in result.items()
                                 if key != "result_sha256"})
    if result["result_sha256"] != expected_hash:
        raise ValueError("T26 oracle result hash mismatch")
    return {
        "status": "PASS", "mode": mode,
        "dimension_count": len(DIMENSIONS),
        "overall_prohibited_overlap": 0,
        "result_sha256": result["result_sha256"],
        "t26_store_authenticated": result["t26_store_authenticated"],
        "t26_commitments_exact": commitments_exact,
        "real_mode_not_synthetic": mode != "REAL" or result["mode"] == "REAL_SEALED",
        "synthetic_mode_explicit": mode != "SYNTHETIC" or
            result["mode"] == "SYNTHETIC_DISPOSABLE",
        "t26_private_rows_exposed_to_t27": 0,
    }
