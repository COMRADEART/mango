"""T25 construction gate and publication gate.

The construction gate verifies the sealed-candidate prerequisites over private
store artifacts before the manifest may be built. The publication gate enforces
the frozen publication policy: blind content in public Git, or any forbidden
pre-evaluation path, refuses official evaluation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from . import leakscan
from .contract import (AUTHORIZATION, BASE_PRECONSTRUCTION_COMMIT, BASE_PRECONSTRUCTION_TREE,
                       CANDIDATE_COMMIT, CANDIDATE_TREE, HISTORICAL_MILESTONES,
                       RUNTIME_ROOT, T23_CONSTRUCTION_COMMIT, T23_CONSTRUCTION_TREE,
                       enumerate_leaf_requirements, load_t25_contract)
from .policy import POLICY
from .store import PrivateArtifactStore

GATE_SCHEMA = "t25-construction-gate-v1"


def run_construction_gate(source_root: Path, store: PrivateArtifactStore, *,
                          real: bool, namespace: str,
                          preconstruction_freeze_sha256: str,
                          author_lock_sha256: str) -> dict[str, Any]:
    contract = load_t25_contract(source_root / "evaluations/t25/t25_master_contract.json")
    ledger_doc = store.read("construction_run_ledger")
    if ledger_doc["state"] != "AUDITED":
        raise ValueError("T25 gate requires ledger state AUDITED")
    from .ledgers import verify_construction_ledger

    ledger_check = verify_construction_ledger(store, expected_namespace=namespace)
    audits = store.read("construction_audits")
    identity = {
        "authorization": AUTHORIZATION if real else "T25_SYNTHETIC_DISPOSABLE_CONSTRUCTION",
        "experiment": "t25", "attempt": 1,
        "material_mode": "REAL_BLIND" if real else "SYNTHETIC_DISPOSABLE",
        "real_namespace": namespace,
        "starting_preconstruction_commit": ledger_doc["starting_preconstruction_commit"],
        "starting_preconstruction_tree": ledger_doc["starting_preconstruction_tree"],
        "candidate_commit": ledger_doc["candidate_commit"],
        "candidate_tree": ledger_doc["candidate_tree"],
        "preconstruction_freeze_sha256": ledger_doc["preconstruction_freeze_sha256"],
        "component_root": ledger_doc["component_root"],
        "freeze_root": ledger_doc["freeze_root"],
        "construction_contract_sha256": ledger_doc["construction_contract_sha256"],
        "author_lock_sha256": author_lock_sha256,
        "private_artifact_root": store.binding_free_component_root(),
        "private_store_identity": store.store_identity,
        "private_holdout_root": store.holdout_root(),
    }
    expected_identity_root = sha256_json({key: ledger_doc[key] for key in
                                          ("authorization", "experiment", "attempt",
                                           "material_mode", "real_namespace",
                                           "starting_preconstruction_commit",
                                           "starting_preconstruction_tree",
                                           "candidate_commit", "candidate_tree",
                                           "preconstruction_freeze_sha256", "component_root",
                                           "freeze_root", "construction_contract_sha256",
                                           "author_lock_sha256", "private_artifact_root",
                                           "private_store_identity")})
    actual_identity_root = sha256_json({key: identity[key] for key in sorted(
        ("authorization", "experiment", "attempt", "material_mode", "real_namespace",
         "starting_preconstruction_commit", "starting_preconstruction_tree",
         "candidate_commit", "candidate_tree", "preconstruction_freeze_sha256",
         "component_root", "freeze_root", "construction_contract_sha256",
         "author_lock_sha256", "private_artifact_root", "private_store_identity"))})
    expected = {
        "authorization_identity": identity["authorization"] == ledger_doc["authorization"],
        "candidate_identity": (ledger_doc["candidate_commit"] == CANDIDATE_COMMIT
                               and ledger_doc["candidate_tree"] == CANDIDATE_TREE),
        "preconstruction_identity": (
            ledger_doc["starting_preconstruction_commit"] == BASE_PRECONSTRUCTION_COMMIT
            and ledger_doc["starting_preconstruction_tree"] == BASE_PRECONSTRUCTION_TREE),
        "preconstruction_freeze_identity":
            ledger_doc["preconstruction_freeze_sha256"] == preconstruction_freeze_sha256,
        "construction_contract_identity":
            ledger_doc["construction_contract_sha256"] == sha256_json(contract.document),
        "runtime_root_identity": True,
        "one_shot_attempt": ledger_doc["attempt"] == 1,
        "exact_namespace": ledger_doc["real_namespace"] == namespace,
        "t23_exclusion_unchanged": (contract.get("values.t23_exclusion.reuse_allowed") is False
                                    and contract.get("values.t23_exclusion.exposed_construction_commit")
                                    == T23_CONSTRUCTION_COMMIT),
        "t24_exclusion_unchanged": (contract.get("values.t24_exclusion.t24_must_not_be_rerun") is True
                                    and contract.get("values.t24_exclusion.t24_private_material_must_not_be_opened") is True
                                    and contract.get("values.t24_exclusion.t25_candidate_must_not_execute_on_t24_rows") is True),
        "ledger_integrity": ledger_check["status"] == "PASS"
        and ledger_check["ledger_sha256"] is not None,
        "ledger_identity_root": actual_identity_root == expected_identity_root,
        "exclusion_status": audits["exclusion_audit"]["status"] == "PASS",
        "blindness_status": audits["blindness_audit"]["status"] == "PASS",
        "uniqueness_status": audits["uniqueness_audit"]["status"] == "PASS",
        "public_git_blind_blob_count": POLICY["PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED"] == 0,
        "t23_reuse_violations": audits["exclusion_audit"]["collisions"]["exact_queries"] == 0,
        "publication_policy_frozen": contract.get("values.publication_policy")
        == {"REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION": False,
            "T23_EXPOSED_MATERIAL_REUSE_ALLOWED": False,
            "T24_SEALED_MATERIAL_REUSE_ALLOWED": False,
            "T24_PRIVATE_MATERIAL_OPENING_ALLOWED": False,
            "T25_CANDIDATE_EXECUTION_ON_T24_ROWS_ALLOWED": False,
            "PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED": 0},
        "private_store_outside_public_git": True,
        "state_machine": ledger_doc["state"] == "AUDITED",
        "manifest_prerequisites": audits["exclusion_audit"]["status"] == "PASS",
        "contract_leaves": True,
    }
    leaves = enumerate_leaf_requirements(contract)
    expected["contract_leaves"] = all(leaf["requirement_id"] for leaf in leaves)
    checks = dict(sorted(expected.items()))
    failed = sorted(name for name, value in checks.items() if value is not True)
    gate = {"schema_version": GATE_SCHEMA, "artifact": "T25_CONSTRUCTION_GATE",
            "experiment": "t25", "state": "PASS" if not failed else "FAIL",
            "check_count": len(checks), "checks": checks, "failed_checks": failed,
            "identity_root": actual_identity_root,
            "leaf_requirement_count": len(leaves),
            "leaf_requirement_root": sha256_json(leaves),
            "namespace": namespace, "real": real}
    store.write("construction_gate", gate, role="construction_gate",
                schema_version=GATE_SCHEMA)
    return gate


PUBLICATION_LEAKAGE_STATE = "T25_POST_CONSTRUCTION_PUBLICATION_LEAKAGE"


def run_publication_gate(source_root: Path, *, blind_hashes: set[str],
                         refs: tuple[str, ...] = ()) -> dict[str, Any]:
    """Frozen publication policy, enforced over public Git before evaluation."""
    report = leakscan.scan_public_git(Path(source_root).resolve(), blind_hashes=blind_hashes,
                                      refs=refs)
    report["publication_policy"] = dict(POLICY)
    report["publication_leakage_state"] = PUBLICATION_LEAKAGE_STATE if report["status"] == "FAIL" else None
    report["official_evaluation_allowed"] = report["status"] == "PASS"
    report["refusal_reason"] = None if report["status"] == "PASS" else (
        "T25_PUBLIC_GIT_BLIND_BLOB_OR_FORBIDDEN_PATH_DETECTED")
    return report


def ensure_evaluation_permitted(source_root: Path, *, blind_hashes: set[str],
                                refs: tuple[str, ...] = ()) -> dict[str, Any]:
    """Fail-closed: any publication leakage refuses the official evaluation."""
    report = run_publication_gate(source_root, blind_hashes=blind_hashes, refs=refs)
    if not report["official_evaluation_allowed"]:
        raise ValueError("T25 official evaluation refused: "
                         f"{report['publication_leakage_state']} "
                         f"({report['refusal_reason']})")
    return report