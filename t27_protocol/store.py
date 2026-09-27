"""T27 private-store primitives.

The implementation is public protocol code.  Real artifacts are accepted only
under a caller-supplied root outside every Git worktree.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

STORE_ID = "T27-STORE-01"
NAMESPACE = "t27"
LOCATOR = "t27-private://"
CLASSIFICATIONS = frozenset({
    "PRIVATE_LEDGER", "REAL_BLIND_INPUT", "REAL_BLIND_GOLD",
    "PRIVATE_FIXTURE", "PRIVATE_AUDIT", "PRIVATE_MANIFEST",
    "PRIVATE_SEAL", "PRIVATE_EVALUATION", "PUBLIC_SAFE",
    "SYNTHETIC_DISPOSABLE",
})


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class T27PrivateStore:
    """Write-once artifact store with mutable, hash-chained ledgers only."""

    def __init__(self, base: Path, *, repository_root: Path,
                 disposable: bool = False) -> None:
        self.base = Path(base).resolve()
        self.repository_root = Path(repository_root).resolve()
        self.disposable = bool(disposable)
        if self.base == self.repository_root or self.repository_root in self.base.parents:
            raise ValueError("T27 private store must be outside the repository")
        self.root = self.base / NAMESPACE
        self.root.mkdir(parents=True, exist_ok=True)
        probe = self.base
        while probe != probe.parent:
            if (probe / ".git").exists():
                raise ValueError("T27 private store must be outside Git worktrees")
            probe = probe.parent

    def path(self, logical_path: str) -> Path:
        logical = Path(logical_path)
        if logical.is_absolute() or ".." in logical.parts or not logical.parts:
            raise ValueError("invalid T27 private-store path")
        target = (self.root / logical).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("T27 private-store path escape")
        return target

    def has(self, logical_path: str) -> bool:
        return self.path(logical_path).is_file()

    def read_bytes(self, logical_path: str) -> bytes:
        path = self.path(logical_path)
        if not path.is_file():
            raise ValueError(f"private artifact absent: {logical_path}")
        return path.read_bytes()

    def read_json(self, logical_path: str) -> dict[str, Any]:
        value = json.loads(self.read_bytes(logical_path))
        if not isinstance(value, dict):
            raise ValueError(f"private artifact is not an object: {logical_path}")
        return value

    def write_once_bytes(self, logical_path: str, data: bytes) -> None:
        path = self.path(logical_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ValueError(f"private artifact already exists: {logical_path}") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            # The exclusive file intentionally remains as evidence of the attempt.
            raise

    def write_once_json(self, logical_path: str, value: Any) -> None:
        self.write_once_bytes(logical_path, _json_bytes(value))

    def replace_ledger(self, logical_path: str, value: dict[str, Any]) -> None:
        if logical_path not in {"construction/ledger.json", "evaluation/ledger.json"}:
            raise ValueError("only T27 ledgers may be replaced")
        path = self.path(logical_path)
        if not path.is_file():
            raise ValueError("ledger replacement requires an existing ledger")
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(_json_bytes(value))
        os.replace(temporary, path)

    def descriptor(self, logical_path: str, classification: str,
                   schema_type: str = "application/json") -> dict[str, Any]:
        if classification not in CLASSIFICATIONS:
            raise ValueError("unknown artifact classification")
        data = self.read_bytes(logical_path)
        return {
            "logical_id": f"{LOCATOR}{logical_path}",
            "path": logical_path,
            "classification": classification,
            "sha256": _sha(data),
            "byte_size": len(data),
            "schema_type": schema_type,
        }

    def verify(self) -> dict[str, Any]:
        """Verify every manifested artifact and every deterministic root."""
        missing = hash_mismatches = classification_mismatches = root_mismatches = 0
        checked = 0
        if not self.has("construction/manifest.json"):
            return {
                "status": "PASS", "artifact_count": 0,
                "missing_artifacts": 0, "hash_mismatches": 0,
                "classification_mismatches": 0, "root_mismatches": 0,
            }
        manifest = self.read_json("construction/manifest.json")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("T27 private manifest artifact list absent")
        for entry in artifacts:
            checked += 1
            if not isinstance(entry, dict) or set(entry) != {
                "logical_id", "path", "classification", "sha256",
                "byte_size", "schema_type",
            }:
                classification_mismatches += 1
                continue
            if entry["classification"] not in CLASSIFICATIONS:
                classification_mismatches += 1
            path = self.path(entry["path"])
            if not path.is_file():
                missing += 1
                continue
            data = path.read_bytes()
            if _sha(data) != entry["sha256"] or len(data) != entry["byte_size"]:
                hash_mismatches += 1
        ledger_path = self.path("construction/ledger.json")
        marker_path = self.path("markers/construction.one-shot")
        if not ledger_path.is_file() or not marker_path.is_file():
            missing += int(not ledger_path.is_file()) + int(not marker_path.is_file())
        else:
            from .construction import T27ConstructionLedger, verify_event_chain
            try:
                ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                event_dir = self.path("construction/events")
                journals = [json.loads(path.read_text(encoding="utf-8"))
                            for path in sorted(event_dir.glob("*.json"))]
                if (not verify_event_chain(ledger)
                        or journals != ledger.get("events")
                        or marker.get("bindings_sha256") != sha256_json(
                            ledger.get("bindings"))
                        or marker.get("genesis_event_hash") != ledger.get(
                            "events", [{}])[0].get("event_hash")):
                    hash_mismatches += 1
            except Exception:
                hash_mismatches += 1
        from .construction import manifest_roots

        recomputed = manifest_roots(artifacts, manifest["semantic_bindings"])
        for key, value in recomputed.items():
            if manifest.get(key) != value:
                root_mismatches += 1
        if self.has("construction/seal.json"):
            seal = self.read_json("construction/seal.json")
            if seal.get("manifest_sha256") != _sha(
                    self.read_bytes("construction/manifest.json")):
                hash_mismatches += 1
            if (seal.get("private_artifact_root") != manifest.get("private_artifact_root")
                    or seal.get("private_blind_root") != manifest.get("private_blind_root")):
                root_mismatches += 1
        passed = not any((missing, hash_mismatches, classification_mismatches,
                          root_mismatches))
        return {
            "status": "PASS" if passed else "FAIL", "artifact_count": checked,
            "missing_artifacts": missing, "hash_mismatches": hash_mismatches,
            "classification_mismatches": classification_mismatches,
            "root_mismatches": root_mismatches,
            "verification_root": sha256_json({
                "artifacts": artifacts, "roots": recomputed,
            }),
        }


def storage_policy_successor() -> dict[str, Any]:
    return {
        "schema_version": "t27-storage-policy-v2",
        "artifact": "T27_CONSTRUCTION_READY_PRIVATE_STORAGE_POLICY",
        "classification": "PUBLIC_SAFE", "store_id": STORE_ID,
        "namespace": NAMESPACE, "locator_scheme": LOCATOR,
        "supersedes_prospectively": "t27-storage-policy-v1",
        "historical_policy_rewritten": False,
        "construction_ledger_required_for_real": True,
        "construction_one_shot_required": True,
        "private_manifest_required": True,
        "holdout_seal_required": True,
        "store_verification_required": True,
        "evaluation_ledger_required_for_official": True,
        "real_blind_content_publication_allowed": False,
        "public_git_blind_blob_count_required": 0,
        "physical_storage_forbidden": [
            "repository", "git_worktrees", "git_history", "github",
            "public_github_actions_artifacts", "public_object_storage",
            "public_indexing",
        ],
        "private_fixture_optionality": {
            "allowed": True, "zero_fixtures_allowed": True,
            "every_present_fixture_manifested": True,
        },
    }
