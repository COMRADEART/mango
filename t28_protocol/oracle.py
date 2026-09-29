"""Fail-closed verifier for synthetic and authenticated-real T27 oracles.

The T28 oracle compares nine prospective fingerprint sets from the new T28
qualification/diagnostics material against the sealed official T27 store's
historical fingerprint sets (T28 authorization §6/§7).  Because T27's
official evaluation never happened and never will, the authenticated
commitments are construction commitments plus OFFICIAL EVALUATION ABSENCE:
UNSPENT_BUT_PERMANENTLY_INELIGIBLE, attempt 0, and eligibility
PERMANENTLY_NOT_AUTHORIZED_FOR_T27.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .contract import (
    T27_CONSTRUCTION_ATTEMPT, T27_CONSTRUCTION_STATE,
    T27_OFFICIAL_EVALUATION_ATTEMPT, T27_OFFICIAL_EVALUATION_ELIGIBILITY,
    T27_OFFICIAL_EVALUATION_STATE,
)
from .exclusion import DIMENSIONS

ARTIFACT = "T27_TO_T28_OVERLAP_ORACLE_RESULT"
REAL_SCHEMA = "t28-t27-sealed-overlap-oracle-result-v2"
SYNTHETIC_SCHEMA = "t28-t27-synthetic-overlap-oracle-result-v1"
SYNTHETIC_EVALUATION_STATE = "SYNTHETIC_SEALED_UNEVALUATED"
SEALED_ORACLE = (
    "t27_protocol.t28_private_oracle:run_sealed_t27_to_t28_overlap_oracle"
)
SYNTHETIC_ORACLE = "t27_protocol.t28_private_oracle:compare_hashes"

COMMITMENT_FIELDS = (
    "t27_public_construction_commit", "t27_construction_ledger_sha256",
    "t27_construction_ledger_root", "t27_private_manifest_sha256",
    "t27_construction_seal_sha256", "t27_private_holdout_root",
)


def _hex(value: Any, length: int = 64) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def _validate_evaluation_absence_bindings(result: dict[str, Any],
                                          synthetic: bool) -> None:
    state = result.get("t27_official_evaluation_state")
    attempt = result.get("t27_official_evaluation_attempt")
    eligibility = result.get("t27_official_evaluation_eligibility")
    if (result.get("t27_construction_state") != T27_CONSTRUCTION_STATE
            or result.get("t27_construction_attempt")
            != T27_CONSTRUCTION_ATTEMPT):
        raise ValueError("T27 construction must be authenticated SEALED/1")
    if synthetic:
        if state != SYNTHETIC_EVALUATION_STATE or attempt != 0:
            raise ValueError(
                "synthetic oracle must bind the disposable unevaluated state")
    else:
        if (state != T27_OFFICIAL_EVALUATION_STATE
                or attempt != T27_OFFICIAL_EVALUATION_ATTEMPT
                or eligibility != T27_OFFICIAL_EVALUATION_ELIGIBILITY):
            raise ValueError(
                "T27 official evaluation must be authenticated UNSPENT_"
                "BUT_PERMANENTLY_INELIGIBLE (attempt 0, permanently ineligible)")


def verify_oracle_result(result: dict[str, Any], *, mode: str = "SYNTHETIC",
                         root: Path | None = None,
                         expected_t28_root: str | None = None,
                         expected_t27_bindings: dict[str, Any] | None = None
                         ) -> dict[str, Any]:
    """Verify the exact schema, mode, identities, roots, and zero overlap."""
    required = {
        "schema_version", "artifact", "experiment", "mode",
        "official_commitment_scope", "oracle_implementation",
        "t27_store_authenticated", "t27_store_identity", "t27_namespace",
        *COMMITMENT_FIELDS,
        "t27_construction_state", "t27_construction_attempt",
        "t27_official_evaluation_state", "t27_official_evaluation_attempt",
        "t27_official_evaluation_eligibility",
        "t27_fingerprint_index_root", "t27_fingerprint_index_origin",
        "t28_prospective_fingerprint_root",
        "dimensions", "overall_prohibited_overlap",
        "oracle_execution_timestamp", "outside_boundary_private_rows_exposed",
        "result_sha256",
    }
    if mode != "SYNTHETIC":
        required |= {"t27_candidate_commit", "t27_candidate_runtime_root"}
    if not isinstance(result, dict) or set(result) != required:
        raise ValueError("T27 oracle result has unknown or absent fields")
    if result["artifact"] != ARTIFACT or result["experiment"] != "t28":
        raise ValueError("T27 oracle result identity mismatch")
    commitments_exact = False
    if mode == "REAL":
        from t27_protocol.t28_private_oracle import official_t27_commitments

        if root is None:
            raise ValueError("real oracle verification requires repository root")
        expected = official_t27_commitments(root)
        if (result["schema_version"] != REAL_SCHEMA
                or result["mode"] != "REAL_SEALED"
                or result["official_commitment_scope"] != "OFFICIAL_T27"
                or result["oracle_implementation"] != SEALED_ORACLE
                or result["t27_store_authenticated"] is not True):
            raise ValueError("real construction requires authenticated sealed T27 oracle")
        commitments_exact = all(result.get(key) == expected[key] for key in expected)
        if not commitments_exact:
            raise ValueError("real T27 oracle commitments are not exact official values")
    elif mode == "REAL_REHEARSAL":
        if (result["schema_version"] != REAL_SCHEMA
                or result["mode"] != "REAL_SEALED"
                or result["official_commitment_scope"] != "DISPOSABLE_STANDIN"
                or result["oracle_implementation"] != SEALED_ORACLE
                or result["t27_store_authenticated"] is not True):
            raise ValueError("real-mode oracle rehearsal is not store-authenticated")
        if expected_t27_bindings is not None:
            commitments_exact = all(result.get(key) == value
                                    for key, value in expected_t27_bindings.items())
            if not commitments_exact:
                raise ValueError("rehearsal T27 commitments are not exact")
        else:
            commitments_exact = True
    elif mode == "SYNTHETIC":
        if (result["schema_version"] != SYNTHETIC_SCHEMA
                or result["mode"] != "SYNTHETIC_DISPOSABLE"
                or result["official_commitment_scope"] != "SYNTHETIC_DISPOSABLE"
                or result["oracle_implementation"] != SYNTHETIC_ORACLE
                or result["t27_store_authenticated"] is not False):
            raise ValueError("synthetic oracle must use explicit disposable schema")
        if result["t27_official_evaluation_state"] != SYNTHETIC_EVALUATION_STATE:
            raise ValueError("synthetic oracle must bind the disposable state")
    else:
        raise ValueError("unknown T27 oracle verification mode")
    if expected_t28_root is not None and result[
            "t28_prospective_fingerprint_root"] != expected_t28_root:
        raise ValueError("T27 oracle prospective T28 root mismatch")
    for key in (*COMMITMENT_FIELDS, "t27_fingerprint_index_root",
                "t28_prospective_fingerprint_root"):
        # Commit SHAs are 40-hex; every other binding is a full SHA-256.
        if key in {"t27_public_construction_commit"}:
            continue
        if not _hex(result[key]):
            raise ValueError(f"invalid oracle binding: {key}")
    for key in ("t27_candidate_commit", "t27_public_construction_commit"):
        if key not in result:
            continue
        if (not isinstance(result[key], str) or len(result[key]) != 40
                or any(char not in "0123456789abcdef" for char in result[key])):
            raise ValueError(f"invalid oracle identity binding: {key}")
    if "t27_candidate_runtime_root" in result and not _hex(
            result["t27_candidate_runtime_root"]):
        raise ValueError("invalid oracle binding: t27_candidate_runtime_root")
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
        raise ValueError("T27-to-T28 prohibited overlap is nonzero")
    if result["outside_boundary_private_rows_exposed"] != 0:
        raise ValueError("T27 oracle exposed private rows outside sealed boundary")
    _validate_evaluation_absence_bindings(result, synthetic=mode == "SYNTHETIC")
    expected_hash = sha256_json({key: value for key, value in result.items()
                                 if key != "result_sha256"})
    if result["result_sha256"] != expected_hash:
        raise ValueError("T27 oracle result hash mismatch")
    return {
        "status": "PASS", "mode": mode,
        "dimension_count": len(DIMENSIONS),
        "overall_prohibited_overlap": 0,
        "result_sha256": result["result_sha256"],
        "t27_store_authenticated": result["t27_store_authenticated"],
        "t27_commitments_exact": commitments_exact,
        "t27_construction_state": result["t27_construction_state"],
        "t27_evaluation_absence_authenticated": True,
        "real_mode_not_synthetic": mode != "REAL" or result["mode"] == "REAL_SEALED",
        "synthetic_mode_explicit": mode != "SYNTHETIC" or
            result["mode"] == "SYNTHETIC_DISPOSABLE",
        "t27_private_rows_exposed_to_t28": 0,
    }