"""T24 private construction and evaluation ledgers, with public safe receipts.

The real ledgers live only inside the private artifact store. Public receipts
bind hashes, state, and attempt counts only — never blind content.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.errors import LedgerError
from t21_protocol.ledger import create_exclusive
from t21_protocol.util import sha256_json

from .contract import EXPERIMENT

CONSTRUCTION_SCHEMA = "t24-construction-ledger-v1"
EVALUATION_SCHEMA = "t24-evaluation-ledger-v1"
CONSTRUCTION_STATES = ("PRECONSTRUCTION", "LEDGER_CREATED", "MATERIALIZED", "AUDITED",
                       "GATE_PASS", "MANIFESTED", "SEALED")
NEXT = {"LEDGER_CREATED": "MATERIALIZED", "MATERIALIZED": "AUDITED", "AUDITED": "GATE_PASS",
        "GATE_PASS": "MANIFESTED", "MANIFESTED": "SEALED"}


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n").encode("utf-8")


class T24ConstructionLedger:
    """One-shot private construction ledger; never stored in public Git."""

    def __init__(self, document: dict[str, Any], *, write_hook=None) -> None:
        self.document = document
        self._write_hook = write_hook

    @classmethod
    def create_exclusive(cls, *, store: Any, bindings: dict[str, Any],
                         authorization: str, attempt: int = 1) -> "T24ConstructionLedger":
        if attempt != 1:
            raise ValueError("T24 construction ledger permits attempt 1 only")
        if store.has("construction_run_ledger"):
            raise ValueError("T24 one-shot construction ledger already exists")
        document = {"schema_version": CONSTRUCTION_SCHEMA, "artifact": "T24_CONSTRUCTION_LEDGER",
                    "experiment": EXPERIMENT, "kind": "construction", "state": "LEDGER_CREATED",
                    "attempt": attempt, "authorization": authorization,
                    "material_mode": bindings["material_mode"],
                    "real_namespace": bindings["real_namespace"],
                    "starting_preconstruction_commit": bindings["starting_preconstruction_commit"],
                    "starting_preconstruction_tree": bindings["starting_preconstruction_tree"],
                    "candidate_commit": bindings["candidate_commit"],
                    "candidate_tree": bindings["candidate_tree"],
                    "preconstruction_freeze_sha256": bindings["preconstruction_freeze_sha256"],
                    "component_root": bindings["component_root"],
                    "freeze_root": bindings["freeze_root"],
                    "construction_contract_sha256": bindings["construction_contract_sha256"],
                    "author_lock_sha256": bindings.get("author_lock_sha256"),
                    "private_artifact_root": store.binding_free_component_root(),
                    "private_store_identity": store.store_identity,
                    "private_holdout_root": store.holdout_root(),
                    "events": [{"state": "LEDGER_CREATED", "at": _now()}],
                    "created_at": _now(), "updated_at": _now()}
        store.write("construction_run_ledger", document, role="construction_run_ledger",
                    schema_version=CONSTRUCTION_SCHEMA)
        return cls(document).bind(store)

    def advance(self, target: str) -> dict[str, Any]:
        if self.document["state"] not in NEXT:
            raise LedgerError(f"forbidden transition {self.document['state']} -> {target}")
        if NEXT[self.document["state"]] != target:
            raise LedgerError(f"forbidden transition {self.document['state']} -> {target}")
        self.document["state"] = target
        self.document["events"].append({"state": target, "at": _now()})
        self.document["updated_at"] = _now()
        self.document["private_artifact_root"] = self._store.binding_free_component_root()
        self.document["private_holdout_root"] = self._store.holdout_root()
        self._store.replace("construction_run_ledger", self.document)
        return self.document

    def bind(self, store: Any) -> "T24ConstructionLedger":
        self._store = store
        return self

    def fail(self, error: Exception) -> dict[str, Any]:
        if self.document["state"] == "SEALED":
            raise LedgerError("sealed construction ledger cannot fail")
        self.document["state"] = "FAILED"
        self.document["events"].append({"state": "FAILED", "at": _now(),
                                        "error_type": type(error).__name__, "error": str(error)})
        self.document["updated_at"] = _now()
        self._store.replace("construction_run_ledger", self.document)
        return self.document

    @property
    def state(self) -> str:
        return str(self.document["state"])


def load_construction_ledger(store: Any) -> T24ConstructionLedger:
    if not store.has("construction_run_ledger"):
        raise ValueError("T24 construction ledger absent")
    return T24ConstructionLedger(store.read("construction_run_ledger")).bind(store)


def verify_construction_ledger(store: Any, *, expected_namespace: str) -> dict[str, Any]:
    ledger = load_construction_ledger(store)
    document = ledger.document
    if document.get("schema_version") != CONSTRUCTION_SCHEMA or document.get("kind") != "construction":
        raise ValueError("T24 construction ledger schema mismatch")
    if document["real_namespace"] != expected_namespace:
        raise ValueError("T24 construction ledger namespace mismatch")
    if document["attempt"] != 1:
        raise ValueError("T24 construction ledger attempt mismatch")
    states = [event["state"] for event in document["events"]]
    if not states or states[0] != "LEDGER_CREATED":
        raise ValueError("T24 construction ledger must start at LEDGER_CREATED")
    for index in range(1, len(states)):
        previous, current = states[index - 1], states[index]
        if current == "FAILED":
            if previous not in {"LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS", "MANIFESTED"}:
                raise ValueError("T24 construction ledger transition invalid")
        elif NEXT.get(previous) != current:
            raise ValueError("T24 construction ledger transition invalid")
    expected_last = states[-1]
    if document["state"] != expected_last:
        raise ValueError("T24 construction ledger state/event mismatch")
    return {"status": "PASS", "state": document["state"], "attempt": document["attempt"],
            "ledger_sha256": ledger_sha256(document)}


def ledger_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(document)).hexdigest()


def build_construction_receipt(document: dict[str, Any]) -> dict[str, Any]:
    """Public receipt: hashes, state, attempt, private artifact root — nothing else."""
    return {"schema_version": "t24-public-construction-receipt-v1",
            "artifact": "T24_CONSTRUCTION_PUBLIC_RECEIPT", "experiment": EXPERIMENT,
            "state": document["state"], "attempt": document["attempt"],
            "ledger_sha256": ledger_sha256(document),
            "private_artifact_root": document["private_artifact_root"],
            "blind_content_included": False}


class T24EvaluationLedger:
    """One-shot private evaluation ledger: attempt 1, no retry, no delete/recreate."""

    def __init__(self, document: dict[str, Any], *, store: Any) -> None:
        self.document = document
        self._store = store

    @classmethod
    def create_exclusive(cls, *, store: Any, material_mode: str, seal_commitment_sha256: str,
                         private_artifact_root: str, gold_firewall_verified: bool) -> "T24EvaluationLedger":
        if not gold_firewall_verified:
            raise ValueError("T24 evaluation ledger requires prior gold-firewall verification")
        if store.has("evaluation_run_ledger"):
            raise ValueError("T24 one-shot evaluation ledger already exists")
        document = {"schema_version": EVALUATION_SCHEMA, "artifact": "T24_EVALUATION_LEDGER",
                    "experiment": EXPERIMENT, "kind": "evaluation", "state": "STARTED",
                    "attempt": 1, "material_mode": material_mode,
                    "seal_commitment_sha256": seal_commitment_sha256,
                    "private_artifact_root": private_artifact_root,
                    "gold_firewall_verified": True,
                    "firewall_counters": None, "rows_executed": 0,
                    "started_at": _now(), "completed_at": None, "failed_at": None}
        store.write("evaluation_run_ledger", document, role="evaluation_run_ledger",
                    schema_version=EVALUATION_SCHEMA)
        return cls(document, store=store)

    def _finish(self, target: str, details: dict[str, Any]) -> dict[str, Any]:
        if self.document["state"] != "STARTED":
            raise LedgerError(f"forbidden transition {self.document['state']} -> {target}")
        self.document["state"] = target
        self.document["details"] = details
        if target == "COMPLETE":
            self.document["completed_at"] = _now()
        else:
            self.document["failed_at"] = _now()
        self._store.replace("evaluation_run_ledger", self.document)
        return self.document

    def complete(self, details: dict[str, Any]) -> dict[str, Any]:
        return self._finish("COMPLETE", details)

    def fail(self, details: dict[str, Any]) -> dict[str, Any]:
        return self._finish("FAILED", details)

    @property
    def state(self) -> str:
        return str(self.document["state"])


def load_evaluation_ledger(store: Any) -> T24EvaluationLedger:
    if not store.has("evaluation_run_ledger"):
        raise ValueError("T24 evaluation ledger absent")
    return T24EvaluationLedger(store.read("evaluation_run_ledger"), store=store)


def verify_evaluation_ledger(store: Any) -> dict[str, Any]:
    ledger = load_evaluation_ledger(store)
    document = ledger.document
    if (document.get("schema_version") != EVALUATION_SCHEMA
            or document.get("kind") != "evaluation"
            or document.get("attempt") != 1
            or document.get("state") not in {"STARTED", "COMPLETE", "FAILED"}):
        raise ValueError("T24 evaluation ledger identity/state invalid")
    return {"status": "PASS", "state": document["state"], "attempt": document["attempt"]}


def build_evaluation_receipt(document: dict[str, Any]) -> dict[str, Any]:
    """Public evaluation receipt — publishable only after evaluation completes."""
    if document.get("state") != "COMPLETE":
        raise ValueError("T24 evaluation receipt requires a COMPLETE evaluation ledger")
    return {"schema_version": "t24-public-evaluation-receipt-v1",
            "artifact": "T24_EVALUATION_PUBLIC_RECEIPT", "experiment": EXPERIMENT,
            "state": document["state"], "attempt": document["attempt"],
            "ledger_sha256": hashlib.sha256(_canonical(document)).hexdigest(),
            "private_artifact_root": document["private_artifact_root"],
            "blind_content_included": False}


def semantic_ledger_digest(document: dict[str, Any]) -> str:
    """Timestamp-free digest used for rehearsal determinism comparisons."""
    stripped = json.loads(json.dumps(document))
    for field in ("created_at", "updated_at", "started_at", "completed_at", "failed_at"):
        stripped.pop(field, None)
    for event in stripped.get("events", []):
        event.pop("at", None)
    if "details" in stripped:
        details = stripped["details"]
        for field in ("completed_at", "failed_at"):
            details.pop(field, None)
    return sha256_json(stripped)