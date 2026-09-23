"""Closed, public T23 construction contract and deterministic leaf registry."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from t21_protocol.errors import ContractError

EXPERIMENT = "t23"
CANDIDATE_COMMIT = "e1be88fee99361bfd47dfa054a99637820cadda8"
CANDIDATE_TREE = "c88599484db10c0bcf3eeafa50d84746fa539060"
RUNTIME_ROOT = "63f3b446f6e147ee0635a74702920f6e5ca367847bb3d165d74341402c1941e1"
BASE_PRECONSTRUCTION_COMMIT = "366be09bba9073b8b8a63bddf8b377402212aa31"
BASE_PRECONSTRUCTION_TREE = "f67cec7b699ffa8b1d66bdc5532df1b6f96e4c6b"
OLD_FREEZE_SHA256 = "525cfeb62c34640eee4be1cc32bb4563aee264088f25c2d96c2b98a401ebc54c"
OLD_COMPONENT_ROOT = "a75ff25e67a1ac1e1f87afd6a8a0edbc57ea931c773db21e50a7e80c3e07482a"
OLD_FREEZE_ROOT = "f3910d60cc9ec50f0c57d34eb8abc8060df72847123ac852a9dd5dceb4fc762a"
AUTHORIZATION = "T23_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
EVALUATION_AUTHORIZATION = "T23_ONE_SHOT_OFFICIAL_EVALUATION"

# The 21 frozen graph nodes plus the suites directory: exactly 22 real paths.
PATHS = {
    "corpus": "rag/gk_holdout_t23",
    "suites": "evaluations/t23/suites",
    "inputs": "evaluations/t23/suites/inputs.jsonl",
    "gold": "evaluations/t23/suites/gold.jsonl",
    "construction_ledger": "evaluations/t23/construction_run_ledger.json",
    "construction_audits": "evaluations/t23/construction_audits.json",
    "manifest": "evaluations/t23/holdout_manifest.json",
    "seal": "evaluations/t23/HOLDOUT_FROZEN",
    "router_decisions": "evaluations/t23/router_decisions.jsonl",
    "selected_capability_execution": "evaluations/t23/selected_capability_execution.jsonl",
    "candidate_outputs": "evaluations/t23/candidate_outputs.jsonl",
    "router_evaluator": "evaluations/t23/router_evaluator.jsonl",
    "capability_evaluator": "evaluations/t23/capability_evaluator.jsonl",
    "raw_results": "evaluations/t23/raw_results.jsonl",
    "router_metric_evidence": "evaluations/t23/router_metric_evidence.json",
    "router_floor_evidence": "evaluations/t23/router_floor_evidence.json",
    "t22_disposable_scorer_rehearsal": "evaluations/t23/t22_disposable_scorer_rehearsal.json",
    "protected_t22_metric_evidence": "evaluations/t23/protected_t22_metric_evidence.json",
    "protected_t22_floor_evidence": "evaluations/t23/protected_t22_floor_evidence.json",
    "holdout_results": "evaluations/t23/holdout_results.json",
    "evaluation_provenance": "evaluations/t23/evaluation_provenance.json",
    "evaluation_ledger": "evaluations/t23/evaluation_run_ledger.json",
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
    "exclusion_sources": "evaluations/t23/construction_exclusion_sources.json",
}
STATES = ("PRECONSTRUCTION", "LEDGER_CREATED", "MATERIALIZED", "AUDITED",
          "GATE_PASS", "MANIFESTED", "SEALED", "FAILED")
LEGACY_TRANSITIONS = ["QUALIFIED", "CONSTRUCTION_STARTED", "CONSTRUCTED", "SEALED",
                      "EVALUATION_STARTED", "EVALUATION_COMPLETE"]
ROOT_KEYS = {"schema_version", "artifact", "experiment", "values", "fields"}
VALUE_KEYS = {"identity", "artifacts", "real_t23_paths", "shadow_namespace",
              "transitions", "authorization", "construction_authorized",
              "construction_design", "exclusion_sources", "construction_states",
              "construction_requirements"}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def enumerate_leaf_requirements(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate every frozen value leaf; no manually maintained count."""
    validate_t23_contract(document)
    leaves: list[dict[str, Any]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict) and value:
            for key in sorted(value):
                walk(value[key], f"{path}.{key}")
        elif isinstance(value, list) and value:
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        else:
            leaves.append({"requirement_id": f"T23-CON-{len(leaves)+1:04d}",
                           "contract_path": path, "operator": "equals",
                           "required_value": value,
                           "applicable_artifact": path.split(".")[1].split("[")[0]})

    walk(document["values"], "values")
    return leaves


def validate_t23_contract(document: dict[str, Any], *, raise_on_error: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    if set(document) != ROOT_KEYS or document.get("schema_version") != "t23-master-contract-v2":
        errors.append("contract root/schema differs")
    if document.get("artifact") != "T23_MASTER_CONTRACT" or document.get("experiment") != EXPERIMENT:
        errors.append("T23 contract identity mismatch")
    values = document.get("values")
    if not isinstance(values, dict) or set(values) != VALUE_KEYS:
        errors.append("T23 values fields differ")
    else:
        if values["identity"] != {"candidate_commit": CANDIDATE_COMMIT, "candidate_tree": CANDIDATE_TREE,
                                   "runtime_root": RUNTIME_ROOT}:
            errors.append("qualified T23 candidate identity changed")
        if values["artifacts"] != PRECONSTRUCTION_ARTIFACTS | PATHS:
            errors.append("T23 artifact registry differs")
        if values["real_t23_paths"] != list(PATHS.values()) or len(set(PATHS.values())) != 22:
            errors.append("T23 22-path registry differs")
        if values["shadow_namespace"] != "t23-shadow-disposable":
            errors.append("shadow namespace differs")
        if values["transitions"] != LEGACY_TRANSITIONS:
            errors.append("legacy evaluation transitions differ")
        if values["construction_states"] != list(STATES):
            errors.append("construction state machine differs")
        if values["authorization"] != {"construction": AUTHORIZATION, "evaluation": EVALUATION_AUTHORIZATION}:
            errors.append("authorization differs")
        if values["construction_authorized"] is not False:
            errors.append("preconstruction may not authorize real construction")
        design = values.get("construction_design", {})
        try:
            suites = design["suite_mapping"]
            if (design["family_count"] != 16 or design["suite_count"] != 16
                    or design["cases_per_family"] != 80 or design["total_rows"] != 1280
                    or len(suites) != 16 or len(set(suites.values())) != 16
                    or set(suites) != set(design["families"])):
                errors.append("T23 exact family/suite design differs")
            if set(design["mixed_intent_variants"].values()) != {16}:
                errors.append("mixed intent exact design differs")
            if set(design["counterpressure_pairs"]) != {
                "current_web__static_local", "tool_required__tool_unnecessary",
                "insufficient_abstain__sufficient_answer", "security_refusal__ordinary_route"}:
                errors.append("counterpressure design differs")
            from .author import author_cases, shadow_labels
            root = Path(__file__).resolve().parents[1]
            spec = json.loads((root / "evaluations/t23/author_specification.json").read_text(encoding="utf-8"))
            _, expected_gold = author_cases(shadow_labels(), namespace="t23-shadow",
                                            spec=spec, attachment_path="documents/shadow.txt")
            capability = json.loads((root / "evaluations/t23/capability_registry.json").read_text(encoding="utf-8"))
            expected_design = {
                "families": spec["families"],
                "suite_mapping": spec["material_model"]["family_to_suite"],
                "mixed_intent_variants": {k: v["count"] for k, v in spec["mixed_intent_variants"].items()},
                "counterpressure_pairs": spec["counterpressure_pairs"],
                "candidate_visible_fields": spec["candidate_visible_fields"],
                "gold_only_fields": spec["gold_only_fields"],
                "taxonomy": spec["taxonomy"], "privacy": spec["privacy"],
                "source_pool_constraints": spec["source_pool_constraints"],
                "route_counts": dict(sorted(Counter(g["expected_route"] for g in expected_gold).items())),
                "reason_counts": dict(sorted(Counter(g["expected_reason"] for g in expected_gold).items())),
                "capability_labels": sorted(capability["capabilities"]),
                "case_id_pattern": spec["taxonomy"]["case_id_pattern"],
            }
            if any(design.get(k) != v for k, v in expected_design.items()):
                errors.append("T23 construction structure differs from frozen author specification")
        except (KeyError, TypeError, AttributeError):
            errors.append("T23 construction design incomplete")
        req = values.get("construction_requirements", {})
        if req != {"candidate_rows_executed": 0, "evaluator_rows_executed": 0,
                   "annotation_violations": 0, "exclusion_status": "PASS",
                   "blindness_status": "PASS", "uniqueness_status": "PASS",
                   "one_shot_attempt": 1}:
            errors.append("construction gate requirements differ")
        sources = values.get("exclusion_sources", {})
        if set(sources) != {"historical", "remediation", "qualification", "t22_anchor"}:
            errors.append("exclusion source registry incomplete")
        else:
            root = Path(__file__).resolve().parents[1]
            registry = json.loads((root / "evaluations/t23/construction_exclusion_sources.json").read_text(encoding="utf-8"))
            if sources != registry.get("sources"):
                errors.append("exclusion source hash bindings differ")
    if not isinstance(document.get("fields"), list) or set(document["fields"]) != {f"values.{k}" for k in VALUE_KEYS}:
        errors.append("T23 field registration incomplete")
    report = {"status": "PASS" if not errors else "FAIL", "errors": errors,
              "untyped_fields": 0, "unknown_fields": 0,
              "unknown_consumers": 0, "type_disagreements": 0}
    if errors and raise_on_error:
        raise ContractError("; ".join(errors))
    return report


def load_t23_contract(path: Any) -> Any:
    from t21_protocol.contract import Contract
    from t21_protocol.util import read_json
    target = Path(path).resolve()
    document = read_json(target)
    validate_t23_contract(document)
    return Contract(path=target, document=document)
