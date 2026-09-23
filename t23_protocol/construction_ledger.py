"""T23 one-shot construction ledger and durable, fail-closed state machine."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from t21_protocol.errors import LedgerError
from t21_protocol.ledger import create_exclusive
from .contract import (AUTHORIZATION, BASE_PRECONSTRUCTION_COMMIT,
                       BASE_PRECONSTRUCTION_TREE, CANDIDATE_COMMIT,
                       CANDIDATE_TREE, OLD_FREEZE_SHA256, sha256_json)

FROZEN_FIELDS = {
    "authorization", "experiment", "attempt", "material_mode", "real_namespace",
    "starting_preconstruction_commit", "starting_preconstruction_tree",
    "candidate_commit", "candidate_tree", "preconstruction_freeze_sha256",
    "component_root", "freeze_root", "construction_contract_sha256",
    "author_lock_sha256",
}
NEXT = {"LEDGER_CREATED": "MATERIALIZED", "MATERIALIZED": "AUDITED",
        "AUDITED": "GATE_PASS"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def frozen_bindings(source_root: Path, *, real: bool, namespace: str) -> dict[str, Any]:
    source_root = Path(source_root).resolve()
    prior = source_root / "evaluations/t23/preconstruction_production_freeze_v2.json"
    if hashlib.sha256(prior.read_bytes()).hexdigest() != OLD_FREEZE_SHA256:
        raise ValueError("historical T23 freeze changed")
    latest = source_root / "evaluations/t23/preconstruction_production_freeze_v3.json"
    if real and not latest.is_file():
        raise ValueError("production T23 construction requires v3 freeze")
    freeze_path = latest if latest.is_file() else prior
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    starting_commit = BASE_PRECONSTRUCTION_COMMIT
    starting_tree = BASE_PRECONSTRUCTION_TREE
    if freeze.get("candidate_commit") != CANDIDATE_COMMIT or freeze.get("candidate_tree") != CANDIDATE_TREE:
        raise ValueError("preconstruction freeze candidate mismatch")
    if latest.is_file():
        committed = subprocess.run(
            ["git", "show", "HEAD:evaluations/t23/preconstruction_production_freeze_v3.json"],
            cwd=source_root, capture_output=True, check=False).stdout
        if committed != latest.read_bytes():
            raise ValueError("T23 v3 freeze does not match committed bytes")
        infrastructure = freeze.get("infrastructure_commit", "")
        tree = subprocess.run(["git", "rev-parse", f"{infrastructure}^{{tree}}"],
                              cwd=source_root, capture_output=True, check=False)
        parent = subprocess.run(["git", "rev-parse", f"{infrastructure}^"],
                                cwd=source_root, capture_output=True, check=False)
        if (tree.returncode or parent.returncode
                or tree.stdout.decode().strip() != freeze.get("infrastructure_tree")
                or parent.stdout.decode().strip() != BASE_PRECONSTRUCTION_COMMIT
                or freeze.get("infrastructure_parent") != BASE_PRECONSTRUCTION_COMMIT):
            raise ValueError("T23 v3 infrastructure ancestry/tree mismatch")
        keys = ("schema_version", "candidate_commit", "candidate_tree", "infrastructure_commit",
                "infrastructure_parent", "infrastructure_tree", "previous_freeze_sha256",
                "component_root")
        entries = freeze.get("components", [])
        if (freeze.get("schema_version") != "t23-preconstruction-production-freeze-v3"
                or freeze.get("previous_freeze_sha256") != OLD_FREEZE_SHA256
                or freeze.get("construction_authorized") is not False
                or freeze.get("real_t23_exposure") != 0
                or len(entries) != freeze.get("component_count")
                or len({item["path"] for item in entries}) != len(entries)
                or sha256_json(entries) != freeze.get("component_root")
                or sha256_json({key: freeze[key] for key in keys}) != freeze.get("freeze_root")):
            raise ValueError("T23 v3 freeze root or schema invalid")
        for item in entries:
            path = (source_root / item["path"]).resolve()
            if not path.is_relative_to(source_root) or not path.is_file():
                raise ValueError(f"T23 v3 component missing: {item['path']}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError(f"T23 v3 component hash mismatch: {item['path']}")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source_root,
                              capture_output=True, check=False)
        head_tree = subprocess.run(["git", "show", "-s", "--format=%T", "HEAD"],
                                   cwd=source_root, capture_output=True, check=False)
        head_parent = subprocess.run(["git", "rev-parse", "HEAD^"],
                                     cwd=source_root, capture_output=True, check=False)
        changed = subprocess.run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                                 cwd=source_root, capture_output=True, check=False)
        if (head.returncode or head_tree.returncode or head_parent.returncode or changed.returncode
                or head_parent.stdout.decode().strip() != infrastructure
                or changed.stdout.decode().splitlines()
                != ["evaluations/t23/preconstruction_production_freeze_v3.json"]):
            raise ValueError("T23 starting preconstruction commit is not the dedicated v3 freeze commit")
        starting_commit = head.stdout.decode().strip()
        starting_tree = head_tree.stdout.decode().strip()
    return {
        "authorization": AUTHORIZATION if real else "T23_SYNTHETIC_DISPOSABLE_CONSTRUCTION",
        "experiment": "T23", "attempt": 1,
        "material_mode": "REAL_BLIND" if real else "SYNTHETIC",
        "real_namespace": namespace,
        "starting_preconstruction_commit": starting_commit,
        "starting_preconstruction_tree": starting_tree,
        "candidate_commit": CANDIDATE_COMMIT, "candidate_tree": CANDIDATE_TREE,
        "preconstruction_freeze_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
        "component_root": freeze["component_root"], "freeze_root": freeze["freeze_root"],
        "construction_contract_sha256": hashlib.sha256(
            (source_root / "evaluations/t23/t23_master_contract.json").read_bytes()).hexdigest(),
        "author_lock_sha256": hashlib.sha256(
            (source_root / "evaluations/t23/author_lock.json").read_bytes()).hexdigest(),
    }


def verify_ledger(path: Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError("unreadable T23 construction ledger") from exc
    bindings = value.get("bindings")
    if (value.get("schema_version") != "t23-construction-ledger-v2"
            or value.get("artifact") != "T23_CONSTRUCTION_LEDGER"
            or not isinstance(bindings, dict) or set(bindings) != FROZEN_FIELDS
            or bindings.get("experiment") != "T23" or bindings.get("attempt") != 1
            or value.get("state") not in {"LEDGER_CREATED", "MATERIALIZED",
                                          "AUDITED", "GATE_PASS", "FAILED"}
            or value.get("identity_root") != sha256_json(bindings)
            or not isinstance(value.get("created_at"), str)
            or not isinstance(value.get("updated_at"), str)
            or not isinstance(value.get("events"), list)
            or not value["events"] or value["events"][0]["state"] != "LEDGER_CREATED"):
        raise LedgerError("T23 ledger schema, identity, or state invalid")
    if expected is not None and bindings != expected:
        raise LedgerError("T23 ledger frozen identity mismatch")
    states = [event.get("state") for event in value["events"]]
    prefix = ["LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS"]
    allowed = (prefix[:len(states)] if states[-1] != "FAILED"
               else prefix[:len(states)-1] + ["FAILED"])
    if states[-1] != value["state"] or states != allowed:
        raise LedgerError("T23 ledger transition history invalid")
    return value


class T23ConstructionLedger:
    def __init__(self, path: Path, bindings: dict[str, Any]):
        self.path = Path(path)
        self.bindings = bindings

    @classmethod
    def create_exclusive(cls, path: Path, bindings: dict[str, Any]) -> "T23ConstructionLedger":
        if set(bindings) != FROZEN_FIELDS or bindings["attempt"] != 1:
            raise LedgerError("T23 construction ledger bindings incomplete")
        stamp = now()
        payload = {"schema_version": "t23-construction-ledger-v2",
                   "artifact": "T23_CONSTRUCTION_LEDGER",
                   "bindings": bindings, "identity_root": sha256_json(bindings),
                   "created_at": stamp, "updated_at": stamp,
                   "state": "LEDGER_CREATED",
                   "events": [{"state": "LEDGER_CREATED", "at": stamp}]}
        create_exclusive(Path(path), payload)
        return cls(Path(path), bindings)

    @property
    def document(self) -> dict[str, Any]:
        return verify_ledger(self.path, self.bindings)

    def advance(self, target: str) -> None:
        doc = self.document
        if NEXT.get(doc["state"]) != target:
            raise LedgerError(f"forbidden T23 construction transition {doc['state']} -> {target}")
        self._replace(doc, target)

    def fail(self, reason: str) -> None:
        doc = self.document
        if doc["state"] in {"FAILED", "SEALED"}:
            raise LedgerError("T23 failed construction cannot retry")
        self._replace(doc, "FAILED", reason)

    def _replace(self, doc: dict[str, Any], target: str, reason: str | None = None) -> None:
        stamp = now()
        event = {"state": target, "at": stamp}
        if reason is not None:
            event["reason"] = reason
        doc["events"].append(event)
        doc["state"] = target
        doc["updated_at"] = stamp
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                dir=self.path.parent, prefix=self.path.name + ".transition-") as handle:
            json.dump(doc, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, self.path)


def construction_state(root: Path) -> str:
    """Infer post-ledger states from sealed artifacts without mutating bound bytes."""
    out = Path(root) / "evaluations/t23"
    ledger_path = out / "construction_run_ledger.json"
    if not ledger_path.exists():
        return "PRECONSTRUCTION"
    ledger = verify_ledger(ledger_path)
    state = ledger["state"]
    manifest = out / "holdout_manifest.json"
    seal = out / "HOLDOUT_FROZEN"
    if state == "FAILED":
        return "FAILED"
    if seal.exists() and not manifest.exists():
        raise LedgerError("T23 seal exists without manifest")
    if manifest.exists():
        if state != "GATE_PASS":
            raise LedgerError("T23 manifest before gate")
        state = "MANIFESTED"
    if seal.exists():
        state = "SEALED"
    return state
