"""First-class one-shot construction and evaluation ledgers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from .errors import LedgerError

LEDGER_STATES = frozenset({"STARTED", "COMPLETE", "FAILED"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_exclusive(path: Path, payload: dict[str, Any]) -> None:
    """Create *path* exactly once using O_EXCL; no overwrite fallback exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise LedgerError(f"one-shot ledger already exists: {path}") from exc
    try:
        data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@dataclass
class _OneShotLedger:
    path: Path
    KIND: ClassVar[str] = "base"

    @classmethod
    def create_exclusive(
        cls, path: Path, experiment: str, metadata: dict[str, Any] | None = None
    ) -> "_OneShotLedger":
        payload = {
            "schema_version": "t21-ledger-v1",
            "artifact": f"T21_{cls.KIND.upper()}_LEDGER",
            "experiment": experiment,
            "kind": cls.KIND,
            "state": "STARTED",
            "attempt": 1,
            "started_at": _now(),
            "completed_at": None,
            "failed_at": None,
            "metadata": metadata or {},
        }
        create_exclusive(path, payload)
        return cls(path)

    @property
    def document(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError(f"invalid ledger: {self.path}") from exc
        if value.get("kind") != self.KIND or value.get("state") not in LEDGER_STATES:
            raise LedgerError(f"ledger identity/state invalid: {self.path}")
        return value

    @property
    def state(self) -> str:
        return str(self.document["state"])

    def _finish(self, target: str, details: dict[str, Any] | None = None) -> None:
        if target not in {"COMPLETE", "FAILED"}:
            raise LedgerError(f"illegal ledger target: {target}")
        document = self.document
        if document["state"] != "STARTED":
            raise LedgerError(f"forbidden transition {document['state']} -> {target}")
        document["state"] = target
        document["details"] = details or {}
        document["completed_at" if target == "COMPLETE" else "failed_at"] = _now()
        temporary = self.path.with_name(self.path.name + ".tmp")
        if temporary.exists():
            raise LedgerError(f"ledger transition temp already exists: {temporary}")
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    def complete(self, details: dict[str, Any] | None = None) -> None:
        self._finish("COMPLETE", details)

    def fail(self, details: dict[str, Any] | None = None) -> None:
        self._finish("FAILED", details)


class ConstructionLedger(_OneShotLedger):
    KIND = "construction"


class EvaluationLedger(_OneShotLedger):
    KIND = "evaluation"
