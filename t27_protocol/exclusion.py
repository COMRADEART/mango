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
