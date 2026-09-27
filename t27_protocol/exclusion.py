"""Prospective sealed historical-overlap interface; no historical rows are read."""
from __future__ import annotations

DIMENSIONS = (
    "case_ids", "entity_identities", "source_ids", "chunk_ids",
    "exact_queries", "exact_answers", "exact_source_text",
    "verbatim_attack_wording", "relations",
)


def policy() -> dict:
    return {
        "schema_version": "t27-historical-exclusion-policy-v1",
        "artifact": "T27_HISTORICAL_EXCLUSION_POLICY",
        "classification": "PUBLIC_SAFE", "dimensions": list(DIMENSIONS),
        "historical_source": "T26_SEALED_HASH_OVERLAP_ORACLE_ONLY",
        "oracle_contract": {
            "input": "dimension-tagged candidate SHA-256 sets",
            "output": "dimension-tagged overlap counts plus signed root",
            "raw_historical_values_returned": False,
            "row_identity_returned": False,
            "required_overlap": 0,
        },
        "t26_private_rows_opened": 0,
        "candidate_executions_on_t26_rows": 0,
        "required_at_real_construction": True,
    }


def validate_oracle_receipt(receipt: dict) -> bool:
    return (isinstance(receipt, dict) and
            receipt.get("dimensions") == {name: 0 for name in DIMENSIONS} and
            isinstance(receipt.get("oracle_root"), str) and
            len(receipt["oracle_root"]) == 64 and
            receipt.get("raw_historical_values_returned") is False)


def construction_ready_policy() -> dict:
    """Successor policy; the v1 preconstruction policy remains historical."""
    return {
        "schema_version": "t27-historical-exclusion-policy-v2",
        "artifact": "T27_CONSTRUCTION_READY_HISTORICAL_EXCLUSION_POLICY",
        "classification": "PUBLIC_SAFE", "dimensions": list(DIMENSIONS),
        "historical_sources": [
            "T21_T21R_HISTORICAL", "T22_PROTECTED", "T23_EXPOSED",
            "T24_PRIVATE_EVALUATED", "T25_PRIVATE_EVALUATED",
            "T26_SEALED_EVALUATED", "T27_PUBLIC_QUALIFICATION",
            "T27_DIAGNOSTICS", "T27_PUBLIC_REPRODUCER",
            "T27_SYNTHETIC_TERMINAL_MATRIX",
            "T27_SYNTHETIC_RECOVERY_REPLAN_EXAMPLES",
        ],
        "t26_boundary": {
            "implementation": "t26_protocol.t27_private_oracle:compare_hashes",
            "result_artifact": "T26_TO_T27_OVERLAP_ORACLE_RESULT",
            "input_values": "SHA256_ONLY", "output_values": "COUNTS_AND_ROOTS_ONLY",
            "private_rows_returned": 0,
        },
        "per_dimension_fields": [
            "applicable", "prospective_population", "historical_population",
            "overlap_count",
        ],
        "overall_prohibited_overlap_required": 0,
        "candidate_execution_on_historical_rows": False,
        "historical_private_row_exposure_to_author": 0,
        "required_before_real_construction_ledger": True,
    }
