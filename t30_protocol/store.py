"""T30 private-store primitives with ledger-first enforcement.

The implementation is public protocol code.  Real artifacts are accepted only
under a caller-supplied root outside every Git worktree.  Unlike the T27 store
this port carries the T30 evaluation-protocol corrections:

* a durable, monotonic access journal recording every store operation, which
  supplies the official mechanical-ordering evidence for T30_EVALUATION
  (ledger marker written strictly before the first blind read, the first gold
  read, workspace creation, and the first candidate execution),
* a hard ledger-bound guard that refuses opening any ``blind/`` or
  ``gold/`` artifact before an evaluation ledger exists, and
* a machine-only verify() boundary over blind artifact bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

STORE_ID = "T30-STORE-01"
NAMESPACE = "t30"
LOCATOR = "t30-private://"
CLASSIFICATIONS = frozenset({
    "PRIVATE_LEDGER", "REAL_BLIND_INPUT", "REAL_BLIND_GOLD",
    "PRIVATE_FIXTURE", "PRIVATE_AUDIT", "PRIVATE_MANIFEST",
    "PRIVATE_SEAL", "PRIVATE_EVALUATION", "PUBLIC_SAFE",
    "SYNTHETIC_DISPOSABLE",
    # Recovery-reachability remediation: the sealed transient-fault control
    # schedule is neither gold nor candidate input nor public metadata.
    "PRIVATE_EVALUATION_CONTROL",
})
CONSTRUCTION_LEDGER_PATH = "construction/ledger.json"
EVALUATION_LEDGER_PATH = "evaluation/ledger.json"
EVALUATION_MARKER_PATH = "markers/evaluation.one-shot"
CONSTRUCTION_MARKER_PATH = "markers/construction.one-shot"
#: ``control/`` holds the PRIVATE_EVALUATION_CONTROL recovery schedule; like
#: blind material it may be hashed machine-only but never parsed pre-ledger.
LEDGER_GUARDED_PREFIXES = ("blind/", "control/")

OP_KINDS = (
    "read_bytes", "read_json", "write_once", "write_once_json",
    "replace_ledger", "mkdir", "verify", "bind_ledger", "marker",
    "candidate_execution", "candidate_execution_pre_ledger_refused",
)


class PreLedgerViolation(RuntimeError):
    """Raised when blind material is touched before an evaluation ledger exists."""


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class T30PrivateStore:
    """Write-once artifact store with mutable, hash-chained ledgers only."""

    def __init__(self, base: Path, *, repository_root: Path,
                 disposable: bool = False) -> None:
        self.base = Path(base).resolve()
        self.repository_root = Path(repository_root).resolve()
        self.disposable = bool(disposable)
        if self.base == self.repository_root or self.repository_root in self.base.parents:
            raise ValueError("T30 private store must be outside the repository")
        self.root = self.base / NAMESPACE
        self.root.mkdir(parents=True, exist_ok=True)
        probe = self.base
        while probe != probe.parent:
            if (probe / ".git").exists():
                raise ValueError("T30 private store must be outside Git worktrees")
            probe = probe.parent
        self._ledger_bound = False
        self._ledger_genesis: str | None = None

    # ------------------------------------------------------------------
    # durable access journal
    # ------------------------------------------------------------------
    @property
    def journal_path(self) -> Path:
        return self.root / "access_journal.jsonl"

    def journal_length(self) -> int:
        """Public accessor for the durable access-journal length."""
        return self._scan_journal_length()

    def _scan_journal_length(self) -> int:
        path = self.journal_path
        if not path.is_file():
            return 0
        entries = 0
        with path.open("rb") as handle:
            for line in handle:
                if line.strip():
                    entries += 1
        return entries

    def _journal(self, op: str, path: str | None = None,
                 extra: dict[str, Any] | None = None) -> int:
        """Append one access/order record durably; returns its sequence number."""
        seq = self._scan_journal_length() + 1
        record: dict[str, Any] = {
            "seq": seq, "store": STORE_ID, "op": op,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": path, **(extra or {}),
        }
        payload = (json.dumps({key: value for key, value in record.items()
                               if value is not None},
                              sort_keys=True, separators=(",", ":")) + "\n"
                   ).encode("utf-8")
        with self.journal_path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return seq

    def journal_records(self, start: int, end: int | None = None
                        ) -> list[dict[str, Any]]:
        """Read journal records in [start, end]; blind bodies are never here."""
        end = self.journal_length() + 1 if end is None else end + 1
        records: list[dict[str, Any]] = []
        with self.journal_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                value = json.loads(line)
                if start <= value["seq"] < end:
                    records.append(value)
        return records

    # ------------------------------------------------------------------
    # ledger binding (T30 correction for §14/§19/§31)
    # ------------------------------------------------------------------
    def bind_evaluation_ledger(self, ledger: dict[str, Any]) -> int:
        """Bind the exclusive evaluation ledger; unlocks blind material reads.

        Binding is one-way: a bound store cannot be unbound, and the genesis
        event hash of the bound ledger must be provided.
        """
        if self._ledger_bound:
            raise ValueError("T30 private store already ledger-bound")
        state = ledger.get("state")
        if state not in {"STARTED", "EXECUTED", "SCORED", "COMPLETE", "FAILED"}:
            raise ValueError("binding requires a materialized evaluation ledger")
        genesis = (ledger.get("events") or [{}])[0].get("event_hash")
        if not isinstance(genesis, str) or len(genesis) != 64:
            raise ValueError("binding requires the ledger genesis event hash")
        self._ledger_bound = True
        self._ledger_genesis = genesis
        return self._journal("bind_ledger", EVALUATION_LEDGER_PATH,
                             {"ledger_genesis": genesis})

    @property
    def ledger_bound(self) -> bool:
        return self._ledger_bound

    def _guard_pre_ledger(self, logical_path: str) -> None:
        if self._ledger_bound:
            return
        if any(logical_path.startswith(prefix) for prefix in LEDGER_GUARDED_PREFIXES):
            self._journal("pre_ledger_refused", logical_path)
            raise PreLedgerViolation(
                "T30 blind material is ledger-first: " f"{logical_path}")

    # ------------------------------------------------------------------
    # access primitives (order-journaled)
    # ------------------------------------------------------------------
    def path(self, logical_path: str) -> Path:
        logical = Path(logical_path)
        if logical.is_absolute() or ".." in logical.parts or not logical.parts:
            raise ValueError("invalid T30 private-store path")
        target = (self.root / logical).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("T30 private-store path escape")
        if logical_path.startswith("evaluation/workspaces/"):
            self._journal("workspace_path_requested", logical_path)
        return target

    def has(self, logical_path: str) -> bool:
        exists = self.path(logical_path).is_file()
        self._journal("has", logical_path, {"exists": exists})
        return exists

    def read_bytes(self, logical_path: str) -> bytes:
        self._guard_pre_ledger(logical_path)
        path = self.path(logical_path)
        if not path.is_file():
            self._journal("read_refused_absent", logical_path)
            raise ValueError(f"private artifact absent: {logical_path}")
        data = path.read_bytes()
        self._journal("read_bytes", logical_path, {"bytes": len(data)})
        return data

    def read_json(self, logical_path: str) -> dict[str, Any]:
        self._guard_pre_ledger(logical_path)
        value = self.read_bytes(logical_path)
        try:
            parsed = json.loads(value)
        except ValueError:
            self._journal("read_json_malformed", logical_path)
            raise
        self._journal("read_json", logical_path, {"bytes": len(value)})
        if not isinstance(parsed, dict):
            raise ValueError(f"private artifact is not an object: {logical_path}")
        return parsed

    def write_once_bytes(self, logical_path: str, data: bytes) -> None:
        path = self.path(logical_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            self._journal("write_refused_exists", logical_path)
            raise ValueError(f"private artifact already exists: {logical_path}") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            self._journal("write_once", logical_path, {"bytes": len(data)})
        except Exception:
            # The exclusive file intentionally remains as evidence of the attempt.
            raise

    def write_once_json(self, logical_path: str, value: Any) -> None:
        self.write_once_bytes(logical_path, _json_bytes(value))

    def replace_ledger(self, logical_path: str, value: dict[str, Any]) -> None:
        if logical_path not in {CONSTRUCTION_LEDGER_PATH, EVALUATION_LEDGER_PATH}:
            raise ValueError("only T30 ledgers may be replaced")
        path = self.path(logical_path)
        if not path.is_file():
            raise ValueError("ledger replacement requires an existing ledger")
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(_json_bytes(value))
        os.replace(temporary, path)
        self._journal("replace_ledger", logical_path, {"state": value.get("state")})

    def descriptor(self, logical_path: str, classification: str,
                   schema_type: str = "application/json") -> dict[str, Any]:
        if classification not in CLASSIFICATIONS:
            raise ValueError("unknown artifact classification")
        # Machine-only §31 boundary: blind bodies are hashed as raw bytes
        # only for construction-time commitments — rows parsed = 0,
        # rows exposed = 0, content returned = 0.  This accessor is the only
        # blind-tolerant read and never deserializes rows.
        path = self.path(logical_path)
        if not path.is_file():
            self._journal("read_refused_absent", logical_path)
            raise ValueError(f"private artifact absent: {logical_path}")
        data = path.read_bytes()
        self._journal("machine_only_blind_hash", logical_path,
                      {"bytes": len(data)})
        return {
            "logical_id": f"{LOCATOR}{logical_path}",
            "path": logical_path,
            "classification": classification,
            "sha256": _sha(data),
            "byte_size": len(data),
            "schema_type": schema_type,
        }

    def create_evaluation_workspace(self, ledger: dict[str, Any],
                                    workspace_name: str) -> Path:
        """Create one evaluation workspace, ledger-bound and post-ledger only."""
        if not self._ledger_bound:
            self._journal("workspace_pre_ledger_refused", workspace_name)
            raise PreLedgerViolation(
                "T30 evaluation workspaces require the exclusive ledger first")
        if ledger.get("state") != "STARTED":
            raise ValueError("workspaces require a STARTED ledger")
        target = self.path(f"evaluation/workspaces/{workspace_name}")
        target.mkdir(parents=True)
        self._journal("workspace_created", f"evaluation/workspaces/{workspace_name}")
        return target

    def record_candidate_execution(self, workspace_name: str) -> int:
        """Journal one candidate execution (§23 ordering instrumentation).

        Candidate executions are ledger-bound and recorded after workspace
        creation; a pre-ledger execution attempt is refused and journaled.
        """
        if not self._ledger_bound:
            self._journal("candidate_execution_pre_ledger_refused", workspace_name)
            raise PreLedgerViolation(
                "T30 candidate execution requires the exclusive ledger first")
        return self._journal("candidate_execution",
                             f"evaluation/workspaces/{workspace_name}")

    def verify(self) -> dict[str, Any]:
        """Verify manifested artifacts; machine-only over blind material.

        Blind artifact bodies are hashed as raw bytes only: rows parsed = 0,
        rows exposed = 0, blind content returned = 0.
        """
        missing = hash_mismatches = classification_mismatches = root_mismatches = 0
        blind_rows_deserialized = 0
        checked = 0
        if not self.has("construction/manifest.json"):
            return {
                "status": "PASS", "artifact_count": 0,
                "missing_artifacts": 0, "hash_mismatches": 0,
                "classification_mismatches": 0, "root_mismatches": 0,
                "blind_rows_deserialized": 0,
                "machine_only_blind_hashing_boundary": True,
            }
        manifest = json.loads(self.read_bytes("construction/manifest.json"))
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("T30 private manifest artifact list absent")
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
        # Machine-only integrity hashing of blind bodies: raw bytes only.
        for logical in ("blind/inputs.json", "blind/gold.json",
                        "control/recovery_control.json"):
            if not self.has(logical):
                missing += 1
        ledger_path = self.path(CONSTRUCTION_LEDGER_PATH)
        marker_path = self.path(CONSTRUCTION_MARKER_PATH)
        if not ledger_path.is_file() or not marker_path.is_file():
            missing += int(not ledger_path.is_file()) + int(not marker_path.is_file())
        else:
            from .construction import T30ConstructionLedger, verify_event_chain
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
            seal = json.loads(self.read_bytes("construction/seal.json"))
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
            "machine_only_blind_hashing_boundary": True,
            "blind_rows_deserialized": blind_rows_deserialized,
            "verification_root": sha256_json({
                "artifacts": artifacts, "roots": recomputed,
            }),
        }


def storage_policy_successor() -> dict[str, Any]:
    return {
        "schema_version": "t30-storage-policy-v2",
        "artifact": "T30_CONSTRUCTION_READY_PRIVATE_STORAGE_POLICY",
        "classification": "PUBLIC_SAFE", "store_id": STORE_ID,
        "namespace": NAMESPACE, "locator_scheme": LOCATOR,
        "supersedes_prospectively": "t30-storage-policy-v1",
        "historical_policy_rewritten": False,
        "construction_ledger_required_for_real": True,
        "construction_one_shot_required": True,
        "private_manifest_required": True,
        "holdout_seal_required": True,
        "store_verification_required": True,
        "evaluation_ledger_required_for_official": True,
        "ledger_before_blind_material": True,
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