"""Frozen machine-readable T25 publication and storage policies.

These values are frozen in the preconstruction freeze (section 39 of the T25
authorization) and are enforced fail-closed by the publication gate.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

ROOT = Path(__file__).resolve().parents[1]
POLICY_ARTIFACT = ROOT / "evaluations" / "t25" / "t25_publication_policy.json"
SCHEMA = "t25-publication-policy-v1"

POLICY: dict[str, Any] = {
    "REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION": False,
    "T23_EXPOSED_MATERIAL_REUSE_ALLOWED": False,
    "T24_SEALED_MATERIAL_REUSE_ALLOWED": False,
    "T24_PRIVATE_MATERIAL_OPENING_ALLOWED": False,
    "T25_CANDIDATE_EXECUTION_ON_T24_ROWS_ALLOWED": False,
    "PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED": 0,
    "LIVE_WEB_ISOLATION_OPTION": "OPTION_B_BLIND_MATERIAL_PRIVATE_UNTIL_EVALUATION_COMPLETES",
    "PRIVATE_STORE_EXAMPLE_ROOT": "C:/T25_PRIVATE_EVALUATION",
}

# Paths that must never exist in public Git before evaluation completion.
FORBIDDEN_PUBLIC_PATH_PATTERNS = (
    "evaluations/t25/suites/inputs.jsonl",
    "evaluations/t25/suites/gold.jsonl",
    "evaluations/t25/suites/families/",
    "evaluations/t25/suites/",
    "rag/gk_holdout_t25/",
    "documents/t25_private",
    "evaluations/t25/blind/",
    "evaluations/t24/suites/",
    "rag/gk_holdout_t24/",
    "documents/t24_private",
)


def path_forbidden(relative: str) -> bool:
    normalized = str(relative).replace("\\", "/")
    return any(pattern in normalized for pattern in FORBIDDEN_PUBLIC_PATH_PATTERNS)


def publication_policy_document() -> dict[str, Any]:
    return {"schema_version": SCHEMA,
            "artifact": "T25_PUBLICATION_POLICY",
            "experiment": "t25",
            "frozen_policy": POLICY,
            "enforcement": {
                "pre_evaluation_publication_gate": "FAIL_CLOSED",
                "post_construction_publication_leakage_state":
                    "T25_POST_CONSTRUCTION_PUBLICATION_LEAKAGE",
                "publication_gate_action_on_leak": "OFFICIAL_EVALUATION_REFUSED",
                "future_construction_publication_shape":
                    "COMMITMENTS_AND_HASHES_ONLY_NOT_T23_SHAPED_30_FILE_BLIND_COMMIT",
            },
            "public_repository_allowed_content": [
                "SCHEMAS", "PROTOCOL_CODE", "PREREGISTRATION", "CANDIDATE_IDENTITY",
                "HASHES", "COMMITMENTS", "ROOTS", "NON_SECRET_MANIFEST_METADATA",
                "AUDIT_SUMMARIES", "PUBLIC_SAFE_QUALIFICATION_DATA",
            ],
            "public_repository_forbidden_content": [
                "REAL_BLIND_INPUTS", "REAL_BLIND_GOLD", "REAL_SUITE_ROWS",
                "PRIVATE_CORPUS", "PRIVATE_ATTACHMENTS", "PRIVATE_SOURCE_TEXT",
                "CANDIDATE_OUTPUTS_ON_REAL_ROWS_BEFORE_EVALUATION_COMPLETION",
                "RAW_OFFICIAL_RESULTS_BEFORE_EVALUATION_COMPLETION",
            ],
            "private_offline_store_required_content": [
                "REAL_BLIND_INPUTS", "REAL_BLIND_GOLD", "PRIVATE_CORPUS",
                "PRIVATE_ATTACHMENTS", "REAL_CONSTRUCTION_LEDGER",
                "REAL_EVALUATION_LEDGER", "RAW_OFFICIAL_RESULTS",
            ]}


def policy_sha256() -> str:
    return sha256_json(POLICY)


def verify_policy_document(document: dict[str, Any]) -> bool:
    return (document.get("schema_version") == SCHEMA
            and document.get("frozen_policy") == POLICY
            and POLICY["REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION"] is False
            and POLICY["T23_EXPOSED_MATERIAL_REUSE_ALLOWED"] is False
            and POLICY["T24_SEALED_MATERIAL_REUSE_ALLOWED"] is False
            and POLICY["T24_PRIVATE_MATERIAL_OPENING_ALLOWED"] is False
            and POLICY["T25_CANDIDATE_EXECUTION_ON_T24_ROWS_ALLOWED"] is False
            and POLICY["PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED"] == 0)


def load_policy() -> dict[str, Any]:
    document = json.loads(POLICY_ARTIFACT.read_text(encoding="utf-8"))
    if not verify_policy_document(document):
        raise ValueError("T25 publication policy drift or forbidden relaxation")
    return document