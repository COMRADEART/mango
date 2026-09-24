"""T25 artifact classification: every artifact has exactly one class, unknown fails closed."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATION_ARTIFACT = ROOT / "evaluations" / "t25" / "t25_artifact_classification.json"
SCHEMA = "t25-artifact-classification-v1"

CLASSES = ("PUBLIC_SAFE", "PRIVATE_BLIND", "PRIVATE_EVALUATION", "PUBLIC_AFTER_EVALUATION")

ROLE_CLASSIFICATION: dict[str, str] = {
    # Private blind material (never in public Git before evaluation completion).
    "suite_inputs": "PRIVATE_BLIND",
    "suite_gold": "PRIVATE_BLIND",
    "suite_family": "PRIVATE_BLIND",
    "holdout_corpus_sources": "PRIVATE_BLIND",
    "holdout_corpus_chunks": "PRIVATE_BLIND",
    "holdout_corpus_manifest": "PRIVATE_BLIND",
    "holdout_document_attachment": "PRIVATE_BLIND",
    "holdout_exclusion_inputs": "PRIVATE_BLIND",
    # Private evaluation machinery and results.
    "construction_run_ledger": "PRIVATE_EVALUATION",
    "construction_audits_index": "PRIVATE_EVALUATION",
    "blindness_audit": "PRIVATE_EVALUATION",
    "exclusion_audit": "PRIVATE_EVALUATION",
    "uniqueness_audit": "PRIVATE_EVALUATION",
    "static_audit": "PRIVATE_EVALUATION",
    "construction_gate": "PRIVATE_EVALUATION",
    "private_holdout_manifest": "PRIVATE_EVALUATION",
    "holdout_seal": "PRIVATE_EVALUATION",
    "evaluation_run_ledger": "PRIVATE_EVALUATION",
    "gold_firewall_verification": "PRIVATE_EVALUATION",
    "router_decisions": "PRIVATE_EVALUATION",
    "selected_capability_execution": "PRIVATE_EVALUATION",
    "candidate_outputs": "PRIVATE_EVALUATION",
    "router_evaluator": "PRIVATE_EVALUATION",
    "capability_evaluator": "PRIVATE_EVALUATION",
    "raw_results": "PRIVATE_EVALUATION",
    "router_metric_evidence": "PRIVATE_EVALUATION",
    "router_floor_evidence": "PRIVATE_EVALUATION",
    "t22_disposable_scorer_rehearsal": "PRIVATE_EVALUATION",
    "protected_t22_metric_evidence": "PRIVATE_EVALUATION",
    "protected_t22_floor_evidence": "PRIVATE_EVALUATION",
    "holdout_results": "PRIVATE_EVALUATION",
    "evaluation_provenance": "PRIVATE_EVALUATION",
    # Public-safe commitments (hashes, roots, locators only).
    "construction_public_commitment": "PUBLIC_SAFE",
    "manifest_public_commitment": "PUBLIC_SAFE",
    "construction_public_receipt": "PUBLIC_SAFE",
    "evaluation_public_receipt": "PUBLIC_SAFE",
    "master_contract": "PUBLIC_SAFE",
    "publication_policy": "PUBLIC_SAFE",
    "artifact_classification": "PUBLIC_SAFE",
    "private_store_config": "PUBLIC_SAFE",
    "t23_exposed_sealed_anchor": "PUBLIC_SAFE",
    "exclusion_source_registry": "PUBLIC_SAFE",
    "live_web_source_firewall_registry": "PUBLIC_SAFE",
    "author_specification": "PUBLIC_SAFE",
    "author_lock": "PUBLIC_SAFE",
    "production_evaluation_graph": "PUBLIC_SAFE",
    "production_router_metric_registry": "PUBLIC_SAFE",
    "preregistered_router_floors": "PUBLIC_SAFE",
    "production_provider_config": "PUBLIC_SAFE",
    "candidate_identity": "PUBLIC_SAFE",
    "qualification_data": "PUBLIC_SAFE",
    "qualification_exclusions": "PUBLIC_SAFE",
    "rehearsal_exclusions": "PUBLIC_SAFE",
    "candidate_protection_report": "PUBLIC_SAFE",
    "rehearsal_report": "PUBLIC_SAFE",
    "doctor_report": "PUBLIC_SAFE",
    "preconstruction_freeze": "PUBLIC_SAFE",
    "author_implementation": "PUBLIC_SAFE",
    # Public only after evaluation completes.
    "official_result_summary": "PUBLIC_AFTER_EVALUATION",
    "official_router_metric_evidence": "PUBLIC_AFTER_EVALUATION",
    "official_router_floor_evidence": "PUBLIC_AFTER_EVALUATION",
}


class UnknownArtifactClassification(ValueError):
    pass


def classify(role: str) -> str:
    """Fail closed: an unknown artifact role has no classification."""
    try:
        return ROLE_CLASSIFICATION[role]
    except KeyError as exc:
        raise UnknownArtifactClassification(
            f"unknown T25 artifact role has no classification: {role}") from exc


def classification_registry_document() -> dict[str, Any]:
    return {"schema_version": SCHEMA,
            "artifact": "T25_ARTIFACT_CLASSIFICATION",
            "experiment": "t25",
            "classes": list(CLASSES),
            "unknown_classification": "FAIL_CLOSED",
            "role_count": len(ROLE_CLASSIFICATION),
            "roles": dict(sorted(ROLE_CLASSIFICATION.items()))}


def validate_classification_registry(document: dict[str, Any]) -> bool:
    if (document.get("schema_version") != SCHEMA
            or document.get("classes") != list(CLASSES)
            or document.get("unknown_classification") != "FAIL_CLOSED"
            or document.get("role_count") != len(document.get("roles", {}))):
        return False
    roles = document["roles"]
    return (set(roles) == set(ROLE_CLASSIFICATION)
            and all(roles[role] == ROLE_CLASSIFICATION[role] for role in roles)
            and all(value in CLASSES for value in roles.values()))


def load_classification_registry() -> dict[str, Any]:
    document = json.loads(CLASSIFICATION_ARTIFACT.read_text(encoding="utf-8"))
    if not validate_classification_registry(document):
        raise ValueError("T25 artifact classification registry drift")
    return document