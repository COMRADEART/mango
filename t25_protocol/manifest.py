"""T25 private manifest and public commitments.

The private manifest (in the store) binds every artifact by locator, role,
classification, canonical hash, and byte size. Public commitments bind only
hashes, roots, counts, locators, and frozen identities — publishable before
evaluation completes, blind-content-free by construction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .classification import CLASSES, classify
from .contract import EXPERIMENT, LOCATOR_SCHEME, validate_locator

PRIVATE_MANIFEST_SCHEMA = "t25-private-manifest-v1"
PUBLIC_MANIFEST_SCHEMA = "t25-public-manifest-commitment-v1"
PUBLIC_COMMITMENT_SCHEMA = "t25-public-construction-commitment-v1"


def _locator_forbidden(locator: str) -> bool:
    lowered = locator.lower()
    return (not locator.startswith(LOCATOR_SCHEME)
            or "http" in lowered or "@" in locator
            or ".." in locator)


MANIFEST_ID = "private_holdout_manifest"


def build_private_manifest(store: Any, *, identity: dict[str, Any],
                           audit_hashes: dict[str, str]) -> dict[str, Any]:
    if store.has(MANIFEST_ID):
        raise ValueError("T25 private manifest already exists")
    if not store.has("construction_gate"):
        raise ValueError("T25 private manifest requires the construction gate")
    gate = store.read("construction_gate")
    if gate.get("state") != "PASS":
        raise ValueError("T25 private manifest requires a passing construction gate")
    if not store.has("construction_run_ledger"):
        raise ValueError("T25 private manifest requires the construction ledger")
    if store.read("construction_run_ledger").get("state") != "GATE_PASS":
        raise ValueError("T25 private manifest requires a GATE_PASS construction ledger")
    counts = {name: 0 for name in CLASSES}
    artifacts = []
    for entry in store.commitments():
        if entry["artifact_logical_id"] == "construction_run_ledger":
            continue  # bound via the ledger hash inside the identity/seal
        if _locator_forbidden(entry["locator"]) or "http" in entry["locator"].lower():
            raise ValueError("private manifest locator exposes forbidden content")
        if entry["classification"] not in CLASSES:
            raise ValueError("unknown classification in private manifest")
        counts[entry["classification"]] += 1
        artifacts.append({key: entry[key] for key in sorted(entry)})
    manifest = {"schema_version": PRIVATE_MANIFEST_SCHEMA,
                "artifact": "T25_PRIVATE_HOLDOUT_MANIFEST", "experiment": EXPERIMENT,
                "identity": identity, "artifact_count": len(artifacts),
                "counts_by_class": counts,
                "artifacts": artifacts,
                "private_artifact_component_root": store.binding_free_component_root(),
                "private_holdout_root": store.holdout_root(),
                "blindness_audit_sha256": audit_hashes["blindness"],
                "exclusion_audit_sha256": audit_hashes["exclusion"],
                "uniqueness_audit_sha256": audit_hashes["uniqueness"],
                "public_manifest_commitment_included": False,
                "blind_content_included": False}
    store.write(MANIFEST_ID, manifest, role="private_holdout_manifest",
                schema_version=PRIVATE_MANIFEST_SCHEMA)
    return manifest


def verify_private_manifest(store: Any) -> dict[str, Any]:
    if not store.has(MANIFEST_ID):
        raise ValueError("T25 private manifest absent")
    manifest = store.read(MANIFEST_ID)
    if (manifest.get("schema_version") != PRIVATE_MANIFEST_SCHEMA
            or manifest.get("experiment") != EXPERIMENT
            or manifest.get("identity", {}).get("candidate_commit") is None):
        raise ValueError("T25 private manifest schema mismatch")
    counts = {name: 0 for name in CLASSES}
    for entry in manifest["artifacts"]:
        if classify(entry["artifact_role"]) != entry["classification"]:
            raise ValueError("private manifest classification drift")
        counts[entry["classification"]] += 1
        if _locator_forbidden(entry["locator"]):
            raise ValueError("private manifest locator exposes forbidden content")
        live = store.commitment(entry["artifact_logical_id"])
        if (live["canonical_sha256"] != entry["canonical_sha256"]
                or live["byte_size"] != entry["byte_size"]
                or live["locator"] != entry["locator"]):
            raise ValueError(f"private manifest binding drift: {entry['artifact_logical_id']}")
    if counts != manifest["counts_by_class"]:
        raise ValueError("private manifest class counts drift")
    if manifest["private_artifact_component_root"] != store.binding_free_component_root():
        raise ValueError("private manifest component root drift")
    if manifest["private_holdout_root"] != store.holdout_root():
        raise ValueError("private manifest holdout root drift")
    return {"status": "PASS", "binding_count": manifest["artifact_count"],
            "counts_by_class": counts,
            "private_artifact_component_root": manifest["private_artifact_component_root"],
            "private_holdout_root": manifest["private_holdout_root"]}


def build_public_construction_commitment(store: Any, ledger: dict[str, Any],
                                         seal: dict[str, Any]) -> dict[str, Any]:
    if seal.get("state") != "SEALED":
        raise ValueError("public construction commitment requires a sealed holdout")
    audits = store.read("construction_audits")
    from .ledgers import semantic_ledger_digest

    # Semantic ledger digest: deterministic across identical constructions
    # (wall-clock fields stripped), so the published commitment satisfies the
    # section 35 rehearsal determinism requirement.
    ledger_sha = semantic_ledger_digest(store.read("construction_run_ledger"))
    return {"schema_version": PUBLIC_COMMITMENT_SCHEMA,
            "artifact": "T25_PUBLIC_CONSTRUCTION_COMMITMENT", "experiment": EXPERIMENT,
            "candidate_commit": ledger["candidate_commit"],
            "candidate_tree": ledger["candidate_tree"],
            "preconstruction_commit": ledger["starting_preconstruction_commit"],
            "preconstruction_freeze_sha256": ledger["preconstruction_freeze_sha256"],
            "construction_contract_sha256": ledger["construction_contract_sha256"],
            "private_artifact_root": ledger["private_artifact_root"],
            "private_holdout_root": ledger["private_holdout_root"],
            "private_ledger_semantic_sha256": ledger_sha,
            "private_manifest_sha256": seal["private_manifest_sha256"],
            "blindness_audit_sha256": audits["blindness_audit_sha256"],
            "exclusion_audit_sha256": audits["exclusion_audit_sha256"],
            "uniqueness_audit_sha256": audits["uniqueness_audit_sha256"],
            "construction_gate_sha256": seal["construction_gate_sha256"],
            "artifacts": [dict(entry) for entry in store.commitments()
                          if entry["artifact_logical_id"] != "construction_run_ledger"],
            "blind_content_included": False}


def verify_public_construction_commitment(commitment: dict[str, Any],
                                          store: Any) -> dict[str, Any]:
    if (commitment.get("schema_version") != PUBLIC_COMMITMENT_SCHEMA
            or commitment.get("blind_content_included") is not False):
        raise ValueError("T25 public construction commitment schema mismatch")
    for entry in commitment["artifacts"]:
        if _locator_forbidden(entry["locator"]):
            raise ValueError("public commitment locator exposes forbidden content")
        live = store.commitment(entry["artifact_logical_id"])
        if live != entry:
            raise ValueError("public construction commitment binding drift")
    return {"status": "PASS", "artifact_count": len(commitment["artifacts"])}


def build_public_manifest_commitment(manifest: dict[str, Any], *, manifest_sha256: str,
                                     candidate_commit: str, candidate_tree: str,
                                     freeze_sha256: str,
                                     protocol_hashes: dict[str, str]) -> dict[str, Any]:
    if manifest.get("schema_version") != PRIVATE_MANIFEST_SCHEMA:
        raise ValueError("public manifest commitment requires the private manifest")
    commitment = {"schema_version": PUBLIC_MANIFEST_SCHEMA,
                  "artifact": "T25_PUBLIC_MANIFEST_COMMITMENT", "experiment": EXPERIMENT,
                  "private_manifest_sha256": manifest_sha256,
                  "private_manifest_component_root": manifest["private_artifact_component_root"],
                  "private_artifact_root": manifest["private_artifact_component_root"],
                  "private_holdout_root": manifest["private_holdout_root"],
                  "artifact_counts_by_class": manifest["counts_by_class"],
                  "binding_count": manifest["artifact_count"],
                  "candidate_commit": candidate_commit, "candidate_tree": candidate_tree,
                  "freeze_sha256": freeze_sha256,
                  "protocol_hashes": dict(sorted(protocol_hashes.items())),
                  "blind_content_included": False}
    commitment["commitment_root"] = sha256_json(
        {key: value for key, value in commitment.items() if key != "commitment_root"})
    return commitment


def verify_public_manifest_commitment(commitment: dict[str, Any],
                                      manifest_sha256: str) -> dict[str, Any]:
    if (commitment.get("schema_version") != PUBLIC_MANIFEST_SCHEMA
            or commitment.get("blind_content_included") is not False):
        raise ValueError("T25 public manifest commitment schema mismatch")
    expected = sha256_json({key: value for key, value in commitment.items()
                            if key != "commitment_root"})
    if commitment["commitment_root"] != expected:
        raise ValueError("T25 public manifest commitment root mismatch")
    if commitment["private_manifest_sha256"] != manifest_sha256:
        raise ValueError("T25 public manifest commitment does not bind the private manifest")
    return {"status": "PASS", "commitment_root": commitment["commitment_root"]}


def manifest_bytes_sha256(store: Any) -> str:
    return store.commitment("private_holdout_manifest")["canonical_sha256"]