"""Closed T23 contract validation; earlier T21/T22 schemas are untouched."""
from __future__ import annotations

from typing import Any

from t21_protocol.errors import ContractError

EXPERIMENT = "t23"
ROOT_KEYS = {"schema_version", "artifact", "experiment", "values", "fields"}
VALUE_KEYS = {
    "identity", "artifacts", "real_t23_paths", "shadow_namespace",
    "transitions", "authorization", "construction_authorized",
}
PATHS = {
    "corpus": "rag/gk_holdout_t23",
    "suites": "evaluations/t23/suites",
    "construction_ledger": "evaluations/t23/construction_run_ledger.json",
    "manifest": "evaluations/t23/holdout_manifest.json",
    "seal": "evaluations/t23/HOLDOUT_FROZEN",
    "evaluation_ledger": "evaluations/t23/evaluation_run_ledger.json",
    "router_outputs": "evaluations/t23/router_decisions.jsonl",
    "candidate_outputs": "evaluations/t23/candidate_outputs.jsonl",
    "raw_results": "evaluations/t23/raw_results.jsonl",
    "holdout_results": "evaluations/t23/holdout_results.json",
}
PRECONSTRUCTION_ARTIFACTS = {
    "author_spec": "evaluations/t23/author_specification.json",
    "author_lock": "evaluations/t23/author_lock.json",
    "evaluation_graph": "evaluations/t23/production_evaluation_graph.json",
    "router_metrics": "evaluations/t23/production_router_metric_registry.json",
    "t22_metrics": "evaluations/t22/official_metric_registry.json",
    "router_contract": "evaluations/t23/executive_router_contract.json",
    "route_registry": "evaluations/t23/route_registry.json",
    "capability_registry": "evaluations/t23/capability_registry.json",
    "historical_exclusion": "evaluations/t23/historical_exclusion.json",
    "privacy_policy": "evaluations/t23/private_blind_policy.json",
    "provider_config": "evaluations/t23/production_provider_config.json",
}
TRANSITIONS = [
    "QUALIFIED", "CONSTRUCTION_STARTED", "CONSTRUCTED", "SEALED",
    "EVALUATION_STARTED", "EVALUATION_COMPLETE",
]


def validate_t23_contract(document: dict[str, Any], *, raise_on_error: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    if set(document) != ROOT_KEYS:
        errors.append("contract root fields differ")
    if document.get("schema_version") != "t23-master-contract-v1":
        errors.append("unsupported T23 contract schema")
    if document.get("artifact") != "T23_MASTER_CONTRACT" or document.get("experiment") != EXPERIMENT:
        errors.append("T23 contract identity mismatch")
    values = document.get("values")
    if not isinstance(values, dict) or set(values) != VALUE_KEYS:
        errors.append("T23 values fields differ")
    else:
        if values["identity"] != {"candidate_commit": "29750b8403be4e8bab87bb40e86aa882ba35e80e", "candidate_tree": "89b1069729e6cab459f705c18691b08440163627", "runtime_root": "63f3b446f6e147ee0635a74702920f6e5ca367847bb3d165d74341402c1941e1"}:
            errors.append("qualified T23 candidate identity changed")
        if values["artifacts"] != PRECONSTRUCTION_ARTIFACTS | PATHS:
            errors.append("T23 artifact registry differs or aliases T22")
        if values["real_t23_paths"] != list(PATHS.values()):
            errors.append("real path allowlist differs")
        if values["shadow_namespace"] != "t23-shadow-disposable":
            errors.append("shadow namespace must be isolated")
        if values["transitions"] != TRANSITIONS:
            errors.append("T23 construction/evaluation transitions differ")
        if values["authorization"] != {"construction": "T23_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION", "evaluation": "T23_ONE_SHOT_OFFICIAL_EVALUATION"}:
            errors.append("authorization tokens differ")
        if values["construction_authorized"] is not False:
            errors.append("preconstruction may not authorize real construction")
    fields = document.get("fields")
    if not isinstance(fields, list) or set(fields) != {f"values.{key}" for key in VALUE_KEYS}:
        errors.append("T23 field registration incomplete")
    report = {"status": "PASS" if not errors else "FAIL", "untyped_fields": 0,
              "unknown_fields": 0, "unknown_consumers": 0,
              "type_disagreements": 0, "errors": errors}
    if errors and raise_on_error:
        raise ContractError("; ".join(errors))
    return report


def load_t23_contract(path: Any) -> Any:
    """Use the shared Contract value API with T23's additive closed validator."""
    from pathlib import Path
    from t21_protocol.contract import Contract
    from t21_protocol.util import read_json

    target = Path(path).resolve()
    document = read_json(target)
    validate_t23_contract(document)
    return Contract(path=target, document=document)
