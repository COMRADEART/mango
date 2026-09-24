"""T25 master contract: frozen identities, publication policy, leaf requirements.

The T25 candidate is a NEW candidate (authorization §18): the authorized §8
remediation changes the runtime, so the candidate changed = true and a fresh
candidate commit + identity records are required. T24's history is frozen
exactly (§1) and excluded hash-only through the T24_SEALED_EVALUATED anchor
(§14); T24's real blind material stays private-store-only and is never opened.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json
from t23_protocol.contract import canonical

from .author import derive_design, load_spec

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "evaluations" / "t25" / "t25_master_contract.json"

EXPERIMENT = "t25"
# T25 candidate identity (authorization §18): the authorized §8 remediation
# commit on t25-preconstruction (parent = T24 receipt commit d64160b).
CANDIDATE_COMMIT = "ba34f7b2cc46158a5064a8e1c217f53e4d2dbf83"
CANDIDATE_TREE = "459ed3a39ad011b1d061f037348ea0a80bf8f131"
RUNTIME_ROOT = "2beb7a068de3afd0ab0ce25a7a9748fc5cffe6ca04f2db53c1c4d9c71bf87ea9"
BASE_PRECONSTRUCTION_COMMIT = "d64160bf0ebb715a6a30647d06e420b7dde6b24e"
BASE_PRECONSTRUCTION_TREE = "57199cd464694d4ec32754d40f3360aa9946e811"
T23_CONSTRUCTION_COMMIT = "aa613c30483f697295f6f993319e37fd45b07f12"
T23_CONSTRUCTION_TREE = "79e4db563171aece893dd700820bfed5555e975a"
# Frozen T24 history (authorization §1) — never modified, never rerun.
T24_CONSTRUCTION_COMMIT = "71e829d5d7b89298e5c504a0b55278037ec90f28"
T24_RECEIPT_COMMIT = "d64160bf0ebb715a6a30647d06e420b7dde6b24e"
T24_CANDIDATE_COMMIT = "e1be88fee99361bfd47dfa054a99637820cadda8"

AUTHORIZATION = "T25_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
EVALUATION_AUTHORIZATION = "T25_ONE_SHOT_OFFICIAL_EVALUATION"

SHADOW_NAMESPACE = "t25-shadow-disposable"
QUALIFICATION_NAMESPACE = "t25-qualification"
REAL_NAMESPACE = "t25"

STORE_IDENTITY_REAL = "T25-STORE-01"
LOCATOR_SCHEME = "t25-private://"


def locator(logical_id: str, *, store_identity: str = STORE_IDENTITY_REAL,
            namespace: str = REAL_NAMESPACE) -> str:
    if not logical_id or logical_id.startswith("/") or ".." in logical_id:
        raise ValueError("invalid private artifact logical id")
    return f"t25-private://{store_identity}/{namespace}/{logical_id}"


def validate_locator(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith(LOCATOR_SCHEME):
        return False
    if "http" in value or "://" in value[len(LOCATOR_SCHEME):]:
        return False
    body = value[len(LOCATOR_SCHEME):]
    return bool(body) and ".." not in body.split("/") and "@" not in body


# Locator identifiers for real T25 private material. Locators never expose
# private content, filesystem paths, or public-download URLs.
LOCATORS = {
    "construction_run_ledger": locator("construction_run_ledger"),
    "suite_inputs": locator("suites/inputs.jsonl"),
    "suite_gold": locator("suites/gold.jsonl"),
    "holdout_corpus_sources": locator("corpus/sources.jsonl"),
    "holdout_corpus_chunks": locator("corpus/chunks.jsonl"),
    "holdout_corpus_manifest": locator("corpus/corpus_manifest.json"),
    "blindness_audit": locator("audits/blindness_audit"),
    "exclusion_audit": locator("audits/exclusion_audit"),
    "uniqueness_audit": locator("audits/uniqueness_audit"),
    "static_audit": locator("audits/static_audit"),
    "construction_gate": locator("construction_gate"),
    "private_holdout_manifest": locator("private_holdout_manifest"),
    "holdout_seal": locator("holdout_seal"),
    "construction_public_commitment": locator("construction_public_commitment"),
    "manifest_public_commitment": locator("manifest_public_commitment"),
    "construction_public_receipt": locator("construction_public_receipt"),
    "evaluation_run_ledger": locator("evaluation_run_ledger"),
    "gold_firewall_verification": locator("gold_firewall_verification"),
    "router_decisions": locator("evaluation/router_decisions.jsonl"),
    "selected_capability_execution": locator("evaluation/selected_capability_execution.jsonl"),
    "candidate_outputs": locator("evaluation/candidate_outputs.jsonl"),
    "router_evaluator": locator("evaluation/router_evaluator.jsonl"),
    "capability_evaluator": locator("evaluation/capability_evaluator.jsonl"),
    "raw_results": locator("evaluation/raw_results.jsonl"),
    "router_metric_evidence": locator("evaluation/router_metric_evidence.json"),
    "router_floor_evidence": locator("evaluation/router_floor_evidence.json"),
    "t22_disposable_scorer_rehearsal": locator("evaluation/t22_disposable_scorer_rehearsal.json"),
    "protected_t22_metric_evidence": locator("evaluation/protected_t22_metric_evidence.json"),
    "protected_t22_floor_evidence": locator("evaluation/protected_t22_floor_evidence.json"),
    "holdout_results": locator("evaluation/holdout_results.json"),
    "evaluation_provenance": locator("evaluation/evaluation_provenance.json"),
}


CONSTRUCTION_STATES = ("PRECONSTRUCTION", "LEDGER_CREATED", "MATERIALIZED", "AUDITED",
                       "GATE_PASS", "MANIFESTED", "SEALED", "FAILED")
CONSTRUCTION_TRANSITIONS = CONSTRUCTION_STATES[:7] + ("FAILED",)

HISTORICAL_MILESTONES = (
    "T21", "T21R", "T21R2", "T21R3", "T21R4", "T21R5", "T21R6", "T21R7",
    "T21R8_DIAGNOSTIC", "T21R9_SEALED", "T21R10_SEALED", "T21R11_INVALID_SEALED",
    "T21R12_FAILED_PARTIAL_BLIND", "T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE",
    "T21R15_SEALED_UNEVALUABLE", "T21R16_OFFICIAL_EVALUATED_MEASUREMENT_INVALID",
    "T21R17_OFFICIAL_VALID_CAPABILITY_FAILURE",
)


def master_contract_document(spec_path: Path | None = None) -> dict[str, Any]:
    spec = load_spec() if spec_path is None else load_spec(spec_path)
    design = derive_design(spec)
    values = {
                "artifacts": {
                    "master_contract": "evaluations/t25/t25_master_contract.json",
                    "publication_policy": "evaluations/t25/t25_publication_policy.json",
                    "artifact_classification": "evaluations/t25/t25_artifact_classification.json",
                    "private_store_config": "evaluations/t25/t25_private_store_config.json",
                    "t23_exposed_sealed_anchor": "evaluations/t25/t23_exposed_sealed_anchor.json",
                    "t24_sealed_evaluated_anchor": "evaluations/t25/t24_sealed_evaluated_anchor.json",
                    "exclusion_source_registry": "evaluations/t25/t25_exclusion_sources.json",
                    "live_web_source_firewall_registry": "evaluations/t25/live_web_source_firewall_registry.json",
                    "author_specification": "evaluations/t25/author_specification.json",
                    "author_lock": "evaluations/t25/author_lock.json",
                    "production_evaluation_graph": "evaluations/t25/production_evaluation_graph.json",
                    "production_router_metric_registry": "evaluations/t25/production_router_metric_registry.json",
                    "preregistered_router_floors": "evaluations/t25/router_metric_registry.json",
                    "production_provider_config": "evaluations/t25/production_provider_config.json",
                    "candidate_identity": "evaluations/t25/candidate_identity.json",
                    "preconstruction_freeze": "evaluations/t25/preconstruction_freeze.json",
                },
                "authorization": AUTHORIZATION,
                "candidate_identity": {
                    "candidate_commit": CANDIDATE_COMMIT,
                    "candidate_tree": CANDIDATE_TREE,
                    "runtime_root": RUNTIME_ROOT,
                    "unchanged_from_t23_candidate": False,
                    "unchanged_from_t24_candidate": False,
                    "new_candidate_authorized_by": "T25 authorization section 18",
                },
                "construction_design": design,
                "construction_requirements": {
                    "annotation_violations": 0,
                    "blindness_status": "PASS",
                    "exclusion_status": "PASS",
                    "uniqueness_status": "PASS",
                    "one_shot_attempt": 1,
                    "candidate_rows_executed": 0,
                    "evaluator_rows_executed": 0,
                    "public_git_blind_blob_count": 0,
                    "gold_firewall_refusal_proofs_required": True,
                    "t23_reuse_violations": 0,
                    "t24_reuse_violations": 0,
                },
                "construction_states": list(CONSTRUCTION_STATES),
                "evaluation": {
                    "one_shot_attempt": 1,
                    "cannot_start_before": "SEALED",
                    "promotion_cannot_start_before": "EVALUATED",
                    "no_retry": True,
                    "no_delete_or_recreate": True,
                    "evaluation_token": EVALUATION_AUTHORIZATION,
                },
                "exclusion_sources": {
                    "registry_artifact": "evaluations/t25/t25_exclusion_sources.json",
                    "required_milestones": list(HISTORICAL_MILESTONES),
                    "additional_anchors": ["T22_SEALED", "T23_EXPOSED_SEALED",
                                           "T24_SEALED_EVALUATED"],
                    "dimensions": ["case_ids", "entity_identities", "source_ids", "chunk_ids",
                                   "exact_queries", "exact_answers", "exact_source_text",
                                   "verbatim_attack_wording", "relations"],
                },
                "publication_policy": {
                    "REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION": False,
                    "T23_EXPOSED_MATERIAL_REUSE_ALLOWED": False,
                    "T24_SEALED_MATERIAL_REUSE_ALLOWED": False,
                    "T24_PRIVATE_MATERIAL_OPENING_ALLOWED": False,
                    "T25_CANDIDATE_EXECUTION_ON_T24_ROWS_ALLOWED": False,
                    "PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED": 0,
                },
                "storage_policy": {
                    "public_repository_allowed": ["SCHEMAS", "PROTOCOL_CODE", "PREREGISTRATION",
                                                  "CANDIDATE_IDENTITY", "HASHES", "COMMITMENTS",
                                                  "ROOTS", "NON_SECRET_MANIFEST_METADATA",
                                                  "AUDIT_SUMMARIES", "PUBLIC_SAFE_QUALIFICATION_DATA"],
                    "public_repository_forbidden": ["REAL_BLIND_INPUTS", "REAL_BLIND_GOLD",
                                                    "REAL_SUITE_ROWS", "PRIVATE_CORPUS",
                                                    "PRIVATE_ATTACHMENTS", "PRIVATE_SOURCE_TEXT",
                                                    "CANDIDATE_OUTPUTS_ON_REAL_ROWS",
                                                    "RAW_OFFICIAL_RESULTS"],
                    "private_store_required": True,
                    "locator_scheme": LOCATOR_SCHEME,
                    "locator_example": LOCATORS["suite_inputs"],
                },
                "t23_exclusion": {
                    "exposed_construction_commit": T23_CONSTRUCTION_COMMIT,
                    "exposed_construction_tree": T23_CONSTRUCTION_TREE,
                    "reuse_allowed": False,
                    "material": "ALL_T23_BLIND_ARTIFACTS_PERMANENTLY_EXCLUDED",
                    "anchor_artifact": "evaluations/t25/t23_exposed_sealed_anchor.json",
                    "t23_must_not_be_evaluated": True,
                },
                "t24_exclusion": {
                    "sealed_construction_commit": T24_CONSTRUCTION_COMMIT,
                    "receipt_commit": T24_RECEIPT_COMMIT,
                    "candidate_commit": T24_CANDIDATE_COMMIT,
                    "reuse_allowed": False,
                    "material": "ALL_T24_BLIND_ARTIFACTS_PRIVATE_STORE_ONLY",
                    "anchor_artifact": "evaluations/t25/t24_sealed_evaluated_anchor.json",
                    "t24_must_not_be_rerun": True,
                    "t24_private_material_must_not_be_opened": True,
                    "t25_candidate_must_not_execute_on_t24_rows": True,
                },
                "transitions": {
                    "construction": list(CONSTRUCTION_TRANSITIONS[:7]),
                    "failure": ["FAILED"],
                    "evaluation_cannot_start_before": "SEALED",
                    "promotion_cannot_start_before": "EVALUATED",
                },
                "shadow_namespace": SHADOW_NAMESPACE,
                "qualification_namespace": QUALIFICATION_NAMESPACE,
            }
    return {"schema_version": "t25-master-contract-v1",
            "artifact": "T25_MASTER_CONTRACT", "experiment": EXPERIMENT,
            "fields": sorted(f"values.{name}" for name in values),
            "values": values}


ROOT_KEYS = frozenset({"schema_version", "artifact", "experiment", "fields", "values"})


class Contract:
    def __init__(self, path: Path, document: dict[str, Any]) -> None:
        self.path = path
        self.document = document

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.document
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                if default is not None:
                    return default
                raise KeyError(dotted)
            node = node[part]
        return node


def _walk_leaves(values: dict[str, Any], prefix: str, leaves: list[dict[str, Any]]) -> None:
    for key in sorted(values):
        value = values[key]
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            _walk_leaves(value, dotted, leaves)
        else:
            leaves.append({"requirement_id": None, "field": dotted, "operator": "equals",
                           "required_value": value, "applicable_artifact": "T25_MASTER_CONTRACT"})


def enumerate_leaf_requirements(contract: "Contract | dict[str, Any]") -> list[dict[str, Any]]:
    document = contract.document if isinstance(contract, Contract) else contract
    validate_t25_contract(document)
    leaves: list[dict[str, Any]] = []
    _walk_leaves(document["values"], "values", leaves)
    for index, leaf in enumerate(leaves, start=1):
        leaf["requirement_id"] = f"T25-CON-{index:04d}"
    return leaves


def validate_t25_contract(document: dict[str, Any]) -> None:
    if not isinstance(document, dict) or set(document) != set(ROOT_KEYS):
        raise ValueError("invalid T25 master contract envelope")
    if (document["schema_version"] != "t25-master-contract-v1"
            or document["artifact"] != "T25_MASTER_CONTRACT"
            or document["experiment"] != EXPERIMENT
            or document["fields"] != sorted(f"values.{name}"
                                            for name in document["values"])):
        raise ValueError("T25 master contract identity or field list mismatch")
    values = document["values"]
    if set(values) != {
            "artifacts", "authorization", "candidate_identity", "construction_design",
            "construction_requirements", "construction_states", "evaluation",
            "exclusion_sources", "publication_policy", "qualification_namespace",
            "shadow_namespace", "storage_policy", "t23_exclusion", "t24_exclusion",
            "transitions"}:
        raise ValueError("T25 master contract value set mismatch")
    # Authorization must be the exact construction token. Construction itself
    # stays unauthorized here; only a real construction ledger ever flips it.
    if values["authorization"] != AUTHORIZATION:
        raise ValueError("T25 contract authorization token mismatch")
    policy = values["publication_policy"]
    if (policy.get("REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION") is not False
            or policy.get("T23_EXPOSED_MATERIAL_REUSE_ALLOWED") is not False
            or policy.get("T24_SEALED_MATERIAL_REUSE_ALLOWED") is not False
            or policy.get("T24_PRIVATE_MATERIAL_OPENING_ALLOWED") is not False
            or policy.get("T25_CANDIDATE_EXECUTION_ON_T24_ROWS_ALLOWED") is not False
            or policy.get("PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED") != 0):
        raise ValueError("T25 contract publication policy forbidden or incomplete")
    identity = values["candidate_identity"]
    if (identity["candidate_commit"] != CANDIDATE_COMMIT
            or identity["candidate_tree"] != CANDIDATE_TREE
            or identity["runtime_root"] != RUNTIME_ROOT
            or identity.get("unchanged_from_t23_candidate") is not False
            or identity.get("unchanged_from_t24_candidate") is not False):
        raise ValueError("T25 contract candidate identity mismatch")
    # §18: the T25 candidate must be NEW — never one of the frozen T23/T24
    # candidate identities, and never the T24 construction/receipt commits.
    if identity["candidate_commit"] in {T23_CONSTRUCTION_COMMIT, T24_CONSTRUCTION_COMMIT,
                                        T24_RECEIPT_COMMIT, T24_CANDIDATE_COMMIT}:
        raise ValueError("T25 contract candidate identity must be a new candidate")
    candidate_file = ROOT / "evaluations" / "t25" / "candidate_identity.json"
    if candidate_file.exists():
        on_disk = json.loads(candidate_file.read_text(encoding="utf-8"))["t25_candidate"]
        if (on_disk["candidate_commit"] != CANDIDATE_COMMIT
                or on_disk["candidate_tree"] != CANDIDATE_TREE
                or on_disk["runtime_root"] != RUNTIME_ROOT
                or on_disk.get("unchanged_from_t23_candidate") is not False
                or on_disk.get("unchanged_from_t24_candidate") is not False):
            raise ValueError("T25 contract/candidate artifact identity drift")
    t23 = values["t23_exclusion"]
    if (t23["exposed_construction_commit"] != T23_CONSTRUCTION_COMMIT
            or t23["exposed_construction_tree"] != T23_CONSTRUCTION_TREE
            or t23["reuse_allowed"] is not False
            or t23.get("t23_must_not_be_evaluated") is not True):
        raise ValueError("T25 contract T23 exclusion mismatch")
    t24 = values["t24_exclusion"]
    if (t24["sealed_construction_commit"] != T24_CONSTRUCTION_COMMIT
            or t24["receipt_commit"] != T24_RECEIPT_COMMIT
            or t24["candidate_commit"] != T24_CANDIDATE_COMMIT
            or t24["reuse_allowed"] is not False
            or t24.get("t24_must_not_be_rerun") is not True
            or t24.get("t24_private_material_must_not_be_opened") is not True
            or t24.get("t25_candidate_must_not_execute_on_t24_rows") is not True):
        raise ValueError("T25 contract T24 exclusion mismatch")
    if values["shadow_namespace"] != SHADOW_NAMESPACE:
        raise ValueError("T25 contract shadow namespace mismatch")
    if values["qualification_namespace"] != QUALIFICATION_NAMESPACE:
        raise ValueError("T25 contract qualification namespace mismatch")
    expected_design = derive_design(load_spec())
    if values["construction_design"] != expected_design:
        raise ValueError("T25 contract construction design drift from author machinery")
    requirements = values["construction_requirements"]
    if (requirements.get("one_shot_attempt") != 1
            or requirements.get("annotation_violations") != 0
            or requirements.get("candidate_rows_executed") != 0
            or requirements.get("evaluator_rows_executed") != 0
            or requirements.get("public_git_blind_blob_count") != 0
            or requirements.get("t23_reuse_violations") != 0
            or requirements.get("t24_reuse_violations") != 0
            or requirements.get("gold_firewall_refusal_proofs_required") is not True):
        raise ValueError("T25 contract construction requirements mismatch")
    if list(values["construction_states"]) != list(CONSTRUCTION_STATES):
        raise ValueError("T25 contract construction state machine mismatch")
    evaluation = values["evaluation"]
    if (evaluation["one_shot_attempt"] != 1 or evaluation["cannot_start_before"] != "SEALED"
            or evaluation["promotion_cannot_start_before"] != "EVALUATED"
            or evaluation["no_retry"] is not True or evaluation["no_delete_or_recreate"] is not True
            or evaluation["evaluation_token"] != EVALUATION_AUTHORIZATION):
        raise ValueError("T25 contract evaluation gate mismatch")
    transitions = values["transitions"]
    if (transitions["construction"] != list(CONSTRUCTION_TRANSITIONS[:7])
            or transitions["evaluation_cannot_start_before"] != "SEALED"
            or transitions["promotion_cannot_start_before"] != "EVALUATED"):
        raise ValueError("T25 contract transitions mismatch")


def load_t25_contract(path: Path = CONTRACT) -> Contract:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_t25_contract(document)
    return Contract(Path(path), document)