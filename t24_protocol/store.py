"""T24 private artifact store: blind material held outside public Git entirely.

Artifacts are addressed by logical id and bound by canonical SHA-256, byte
size, schema version, and a locator identifier that never exposes private
content, a filesystem path, or a public-download URL. Stores must live outside
the repository worktree. Real-material stores require the construction token;
rehearsal stores are disposable and synthetic only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .classification import CLASSES, classify
from .contract import LOCATOR_SCHEME, REAL_NAMESPACE

ROOT = Path(__file__).resolve().parents[1]
STORE_SCHEMA = "t24-private-store-v1"
MUTABLE_IDS = frozenset({"construction_run_ledger", "evaluation_run_ledger"})
BINDING_IDS = frozenset({"construction_run_ledger", "evaluation_run_ledger",
                         "private_holdout_manifest", "holdout_seal"})
DISPOSABLE_NAMESPACES = frozenset({"t24-shadow-disposable", "t24-qualification"})
REAL_NAMESPACES = frozenset({REAL_NAMESPACE})
AUTHORIZED_REAL_NAMESPACE = ("T24_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION",)


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n").encode("utf-8")


class PrivateArtifactStore:
    def __init__(self, root: Path, *, store_identity: str, namespace: str,
                 construction_authorization: str | None = None) -> None:
        root = Path(root).resolve()
        if root.is_relative_to(ROOT.resolve()):
            raise ValueError("T24 private artifact store must live outside the repository")
        if not store_identity or "/" in store_identity:
            raise ValueError("invalid private store identity")
        if namespace in REAL_NAMESPACES and construction_authorization not in AUTHORIZED_REAL_NAMESPACE:
            raise ValueError("real-material T24 store requires the construction authorization token")
        if namespace not in REAL_NAMESPACES and namespace not in DISPOSABLE_NAMESPACES:
            raise ValueError("unknown T24 store namespace")
        self.root = root
        self.store_identity = store_identity
        self.namespace = namespace
        self.root.mkdir(parents=True, exist_ok=True)
        self.commitments_path = self.root / "commitments.json"
        if not self.commitments_path.exists():
            self.commitments_path.write_text(json.dumps({
                "schema_version": STORE_SCHEMA, "store_identity": store_identity,
                "namespace": namespace, "commitments": []},
                sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
        index = json.loads(self.commitments_path.read_text(encoding="utf-8"))
        if index.get("store_identity") != store_identity or index.get("namespace") != namespace:
            raise ValueError("private store identity mismatch")
        self._commitments: dict[str, dict[str, Any]] = {
            entry["artifact_logical_id"]: entry for entry in index["commitments"]}

    def _index_write(self) -> None:
        self.commitments_path.write_text(json.dumps({
            "schema_version": STORE_SCHEMA, "store_identity": self.store_identity,
            "namespace": self.namespace,
            "commitments": sorted(self._commitments.values(),
                                  key=lambda entry: entry["artifact_logical_id"])},
            sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")

    def locator(self, logical_id: str) -> str:
        return f"{LOCATOR_SCHEME}{self.store_identity}/{self.namespace}/{logical_id}"

    def write(self, logical_id: str, value: Any, *, role: str,
              schema_version: str) -> dict[str, Any]:
        if logical_id in self._commitments:
            raise ValueError(f"private artifact already exists: {logical_id}")
        return self._store_bytes(logical_id, value, role=role, schema_version=schema_version)

    def replace(self, logical_id: str, value: Any) -> dict[str, Any]:
        if logical_id not in MUTABLE_IDS or logical_id not in self._commitments:
            raise ValueError(f"artifact is immutable or absent: {logical_id}")
        return self._store_bytes(logical_id, value, role=self._commitments[logical_id]["artifact_role"],
                                 schema_version=self._commitments[logical_id]["schema_version"])

    def _store_bytes(self, logical_id: str, value: Any, *, role: str, schema_version: str) -> dict[str, Any]:
        data = _canonical_bytes(value) if not isinstance(value, bytes) else value
        classification = classify(role)
        artifact_path = self.root / "artifacts" / f"{logical_id.replace('/', '__')}.artifact"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(data)
        commitment = {"artifact_logical_id": logical_id, "artifact_role": role,
                      "classification": classification,
                      "canonical_sha256": hashlib.sha256(data).hexdigest(),
                      "byte_size": len(data), "schema_version": schema_version,
                      "locator": self.locator(logical_id)}
        self._commitments[logical_id] = commitment
        self._index_write()
        return commitment

    def read(self, logical_id: str) -> Any:
        if logical_id not in self._commitments:
            raise ValueError(f"private artifact absent: {logical_id}")
        data = self._read_bytes(logical_id)
        return json.loads(data.decode("utf-8"))

    def read_bytes(self, logical_id: str) -> bytes:
        return self._read_bytes(logical_id)

    def _read_bytes(self, logical_id: str) -> bytes:
        commitment = self._commitments[logical_id]
        artifact_path = self.root / "artifacts" / f"{logical_id.replace('/', '__')}.artifact"
        if not artifact_path.is_file():
            raise ValueError(f"private artifact missing on disk: {logical_id}")
        data = artifact_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != commitment["canonical_sha256"]:
            raise ValueError(f"private artifact hash mismatch: {logical_id}")
        if len(data) != commitment["byte_size"]:
            raise ValueError(f"private artifact byte size mismatch: {logical_id}")
        return data

    def commitments(self) -> list[dict[str, Any]]:
        return [self._commitments[key] for key in sorted(self._commitments)]

    def has(self, logical_id: str) -> bool:
        return logical_id in self._commitments

    def commitment(self, logical_id: str) -> dict[str, Any]:
        return dict(self._commitments[logical_id])

    def artifact_root(self, *, exclude: frozenset[str] = frozenset()) -> str:
        """Component root over artifact commitments (store index excluded)."""
        entries = [self._commitments[key] for key in sorted(self._commitments)
                   if key not in exclude]
        return sha256_json(entries)

    def binding_free_component_root(self) -> str:
        """Private artifact root: stable over all non-binding artifact commitments."""
        return self.artifact_root(exclude=BINDING_IDS)

    def blind_hashes(self) -> set[str]:
        """Byte hashes of every PRIVATE_BLIND artifact — the leak-scan input."""
        return {entry["canonical_sha256"] for entry in self._commitments.values()
                if entry["classification"] == "PRIVATE_BLIND"}

    def blind_commitments(self) -> list[dict[str, Any]]:
        return sorted((entry for entry in self._commitments.values()
                       if entry["classification"] == "PRIVATE_BLIND"),
                      key=lambda entry: entry["artifact_logical_id"])

    def holdout_root(self) -> str:
        return sha256_json(self.blind_commitments())

    def verify(self) -> dict[str, Any]:
        missing = [key for key in self._commitments if not self._exists(key)]
        mutated = []
        for logical_id in self._commitments:
            try:
                self._read_bytes(logical_id)
            except ValueError:
                mutated.append(logical_id)
        if missing or mutated:
            raise ValueError(f"private store verification failed: missing={missing} mutated={mutated}")
        return {"status": "PASS", "store_identity": self.store_identity,
                "namespace": self.namespace,
                "artifact_count": len(self._commitments),
                "component_root": self.binding_free_component_root(),
                "holdout_root": self.holdout_root()}

    def _exists(self, logical_id: str) -> bool:
        return (self.root / "artifacts" / f"{logical_id.replace('/', '__')}.artifact").is_file()

    def verify_classifications(self) -> int:
        counts: dict[str, int] = {}
        for entry in self._commitments.values():
            if entry["classification"] not in CLASSES:
                raise ValueError("store commitment carries an unknown classification")
            counts[entry["classification"]] = counts.get(entry["classification"], 0) + 1
        for entry in self._commitments.values():
            if not entry["locator"].startswith(f"{LOCATOR_SCHEME}{self.store_identity}/"):
                raise ValueError("store commitment locator mismatch")
        return len(self._commitments)


def store_config_document() -> dict[str, Any]:
    return {"schema_version": "t24-private-store-config-v1",
            "artifact": "T24_PRIVATE_STORE_CONFIG", "experiment": "t24",
            "locator_scheme": LOCATOR_SCHEME,
            "real_store_identity": "T24-STORE-01",
            "real_namespace": REAL_NAMESPACE,
            "real_namespace_requires_construction_token": True,
            "disposable_namespaces": sorted(DISPOSABLE_NAMESPACES),
            "store_location_policy": "OUTSIDE_PUBLIC_GIT_WORKTREE_HISTORY_AND_SERVICES",
            "example_root": "C:/T24_PRIVATE_EVALUATION",
            "locator_forbidden_content": ["PRIVATE_CONTENT", "FILESYSTEM_PATH",
                                          "PUBLIC_DOWNLOAD_URL"],
            "mutating_artifact_ids": sorted(MUTABLE_IDS),
            "immutable_artifacts": True}