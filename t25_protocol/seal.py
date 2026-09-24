"""T25 holdout seal: private seal artifact in the store plus a public commitment.

The public seal commitment binds candidate identity, preconstruction freeze,
construction contract, private artifact root, private ledger hash, audit
hashes, gate hash, and the private manifest hash — and nothing else.
"""
from __future__ import annotations

from typing import Any

from t21_protocol.util import sha256_json

from .contract import EXPERIMENT
from .ledgers import semantic_ledger_digest
from .manifest import MANIFEST_ID

SEAL_SCHEMA = "t25-holdout-sealed-v1"
PUBLIC_SEAL_SCHEMA = "t25-public-seal-commitment-v1"
SEAL_ID = "holdout_seal"


def seal_holdout(store: Any, manifest: dict[str, Any], *, real: bool) -> dict[str, Any]:
    if store.has(SEAL_ID):
        raise ValueError("T25 holdout already sealed")
    ledger_doc = store.read("construction_run_ledger")
    from .manifest import verify_private_manifest

    if verify_private_manifest(store)["status"] != "PASS":
        raise ValueError("T25 seal requires a verified private manifest")
    identity = manifest["identity"]
    gate_sha = store.commitment("construction_gate")["canonical_sha256"]
    marker = {"schema_version": SEAL_SCHEMA, "artifact": "T25_HOLDOUT_SEALED",
              "experiment": EXPERIMENT, "state": "SEALED",
              "workspace_mode": "REAL_EXPERIMENT" if real else "SYNTHETIC_DISPOSABLE",
              "material_mode": ledger_doc["material_mode"],
              "construction_authorized": real,
              "construction_attempts": 1,
              "candidate_rows_executed": 0,
              "private_manifest_sha256": store.commitment(MANIFEST_ID)["canonical_sha256"],
              "manifest_semantic_root": manifest["private_artifact_component_root"],
              "candidate_commit": ledger_doc["candidate_commit"],
              "candidate_tree": ledger_doc["candidate_tree"],
              "preconstruction_commit": ledger_doc["starting_preconstruction_commit"],
              "preconstruction_freeze_sha256": ledger_doc["preconstruction_freeze_sha256"],
              "component_root": ledger_doc["component_root"],
              "freeze_root": ledger_doc["freeze_root"],
              "construction_contract_sha256": ledger_doc["construction_contract_sha256"],
              "construction_gate_sha256": gate_sha,
              "author_lock_sha256": ledger_doc.get("author_lock_sha256"),
              "private_artifact_root": store.binding_free_component_root(),
              "blind_content_included": False}
    store.write(SEAL_ID, marker, role="holdout_seal", schema_version=SEAL_SCHEMA)
    return marker


def build_public_seal_commitment(store: Any, marker: dict[str, Any]) -> dict[str, Any]:
    if marker.get("state") != "SEALED":
        raise ValueError("public seal commitment requires a sealed holdout")
    ledger_doc = store.read("construction_run_ledger")
    audits = store.read("construction_audits")
    gate_sha = store.commitment("construction_gate")["canonical_sha256"]
    commitment = {"schema_version": PUBLIC_SEAL_SCHEMA,
                  "artifact": "T25_PUBLIC_SEAL_COMMITMENT", "experiment": EXPERIMENT,
                  "candidate_commit": marker["candidate_commit"],
                  "candidate_tree": marker["candidate_tree"],
                  "preconstruction_freeze_sha256": marker["preconstruction_freeze_sha256"],
                  "construction_contract_sha256": marker["construction_contract_sha256"],
                  "private_artifact_root": ledger_doc["private_artifact_root"],
                  "private_ledger_semantic_sha256": semantic_ledger_digest(ledger_doc),
                  "blindness_audit_sha256": audits["blindness_audit_sha256"],
                  "exclusion_audit_sha256": audits["exclusion_audit_sha256"],
                  "uniqueness_audit_sha256": audits["uniqueness_audit_sha256"],
                  "construction_gate_sha256": gate_sha,
                  "private_manifest_sha256": marker["private_manifest_sha256"],
                  "private_holdout_root": marker["private_artifact_root"],
                  "blind_content_included": False}
    commitment["public_seal_commitment_root"] = sha256_json(
        {key: value for key, value in commitment.items()
         if key != "public_seal_commitment_root"})
    return commitment


def verify_seal(store: Any) -> dict[str, Any]:
    if not store.has(SEAL_ID):
        raise ValueError("T25 holdout seal absent")
    marker = store.read(SEAL_ID)
    if (marker.get("schema_version") != SEAL_SCHEMA
            or marker.get("state") != "SEALED"
            or marker.get("candidate_rows_executed") != 0
            or marker.get("construction_attempts") != 1
            or marker.get("blind_content_included") is not False):
        raise ValueError("T25 seal schema/state mismatch")
    manifest_sha = store.commitment(MANIFEST_ID)["canonical_sha256"]
    if marker["private_manifest_sha256"] != manifest_sha:
        raise ValueError("T25 seal manifest binding mismatch")
    from .manifest import verify_private_manifest

    if verify_private_manifest(store)["status"] != "PASS":
        raise ValueError("T25 seal requires a verified private manifest")
    ledger_doc = store.read("construction_run_ledger")
    if ledger_doc["state"] != "SEALED":
        raise ValueError("T25 seal requires a SEALED construction ledger")
    expected = {
        "candidate_commit": ledger_doc["candidate_commit"],
        "candidate_tree": ledger_doc["candidate_tree"],
        "preconstruction_freeze_sha256": ledger_doc["preconstruction_freeze_sha256"],
        "construction_contract_sha256": ledger_doc["construction_contract_sha256"],
        "private_artifact_root": store.binding_free_component_root(),
    }
    if any(marker.get(key) != value for key, value in expected.items()):
        raise ValueError("T25 seal construction identity mismatch")
    return {"status": "PASS", "private_manifest_sha256": marker["private_manifest_sha256"],
            "candidate_commit": marker["candidate_commit"],
            "construction_gate_sha256": marker["construction_gate_sha256"]}