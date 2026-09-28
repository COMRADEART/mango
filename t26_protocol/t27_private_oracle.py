"""Authenticated sealed T26-to-T27 hash-only overlap oracle.

The production entrypoint authenticates exact official T26 private-store bytes
against public commitments before it derives or loads a nine-dimensional hash
index. Only counts, roots, and official commitment hashes cross the boundary.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from t21_protocol.util import sha256_json
from t27_protocol.exclusion import DIMENSIONS

from .lifecycle import STORE_ID, T26PrivateStore

SYNTHETIC_ORACLE_ID = "t26_protocol.t27_private_oracle:compare_hashes"
SEALED_ORACLE_ID = (
    "t26_protocol.t27_private_oracle:run_sealed_t26_to_t27_overlap_oracle"
)
# Historical compatibility name. It no longer identifies the production path.
T27_PRIVATE_OVERLAP_ENGINE = SYNTHETIC_ORACLE_ID

REAL_SCHEMA = "t27-t26-sealed-overlap-oracle-result-v2"
SYNTHETIC_SCHEMA = "t27-t26-synthetic-overlap-oracle-result-v1"
ARTIFACT = "T26_TO_T27_OVERLAP_ORACLE_RESULT"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_set(values: Any, name: str) -> set[str]:
    if not isinstance(values, (list, set, tuple)):
        raise ValueError(f"oracle dimension is not a hash set: {name}")
    output = set(values)
    if any(not isinstance(value, str) or len(value) != 64 or
           any(char not in "0123456789abcdef" for char in value)
           for value in output):
        raise ValueError(f"oracle received a non-SHA-256 value: {name}")
    return output


def _validate_sets(values: dict[str, list[str]], label: str) -> None:
    if not isinstance(values, dict) or set(values) != set(DIMENSIONS):
        raise ValueError(f"{label} requires all nine dimensions")
    for name in DIMENSIONS:
        _hash_set(values[name], name)


def official_t26_commitments(root: Path) -> dict[str, str | int]:
    """Exact public anchors for the already sealed official T26 store."""
    root = Path(root).resolve()
    addendum = json.loads((root /
        "evaluations/t26/T26_EVALUATION_PROTOCOL_ADDENDUM_V3.json")
        .read_text(encoding="utf-8"))
    receipt = json.loads((root /
        "evaluations/t26/T26_EVALUATION_PUBLIC_RECEIPT.json")
        .read_text(encoding="utf-8"))
    if (receipt.get("state") != "COMPLETE" or receipt.get("attempt") != 1
            or receipt.get("construction_seal_sha256") !=
            addendum.get("construction_seal_sha256")):
        raise ValueError("official T26 public commitment anchors disagree")
    return {
        "t26_store_identity": STORE_ID,
        "t26_namespace": "t26",
        "t26_private_holdout_root": addendum["private_blind_root"],
        "t26_private_manifest_sha256": addendum["private_manifest_sha256"],
        "t26_construction_seal_sha256": addendum["construction_seal_sha256"],
        "t26_evaluation_ledger_sha256": receipt["evaluation_ledger_sha256"],
        "t26_official_evaluation_state": "COMPLETE",
        "t26_official_evaluation_attempt": 1,
    }


def _verify_event_chain(ledger: dict[str, Any]) -> bool:
    events = ledger.get("events")
    if not isinstance(events, list) or not events:
        return False
    previous: str | None = None
    for index, event in enumerate(events):
        if not isinstance(event, dict) or "event_hash" not in event:
            return False
        body = {key: value for key, value in event.items() if key != "event_hash"}
        expected_previous = event.get("previous_event_hash")
        if index == 0 and expected_previous not in {None, "0" * 64}:
            return False
        if index > 0 and expected_previous != previous:
            return False
        if event.get("event_index") != index or event["event_hash"] != sha256_json(body):
            return False
        previous = event["event_hash"]
    return (ledger.get("state") == "COMPLETE"
            and ledger.get("final_event_hash") == previous
            and ledger.get("event_count", len(events)) == len(events))


def _authenticate_store(store: T26PrivateStore,
                        expected: dict[str, str | int]) -> dict[str, Any]:
    if not isinstance(store, T26PrivateStore):
        raise ValueError("sealed T26 oracle requires T26PrivateStore")
    if (store.root.name != STORE_ID or store.namespace.name != "t26"
            or expected.get("t26_store_identity") != STORE_ID
            or expected.get("t26_namespace") != "t26"):
        raise ValueError("wrong T26 sealed store identity")
    verification = store.verify()
    required_paths = (
        "construction/manifest.json", "construction/seal.json",
        "evaluation/ledger.json", "markers/evaluation.one-shot",
    )
    if not all(store.has(path) for path in required_paths):
        raise ValueError("official T26 sealed-store artifact absent")
    manifest_bytes = store.read_bytes("construction/manifest.json")
    seal_bytes = store.read_bytes("construction/seal.json")
    ledger_bytes = store.read_bytes("evaluation/ledger.json")
    manifest = json.loads(manifest_bytes)
    seal = json.loads(seal_bytes)
    ledger = json.loads(ledger_bytes)
    observed = {
        "t26_store_identity": STORE_ID,
        "t26_namespace": "t26",
        "t26_private_holdout_root": manifest.get("private_blind_root"),
        "t26_private_manifest_sha256": _sha(manifest_bytes),
        "t26_construction_seal_sha256": _sha(seal_bytes),
        "t26_evaluation_ledger_sha256": _sha(ledger_bytes),
        "t26_official_evaluation_state": ledger.get("state"),
        "t26_official_evaluation_attempt": ledger.get("attempt"),
    }
    if observed != expected:
        raise ValueError("T26 private store does not match exact official commitments")
    if (seal.get("state") != "SEALED" or seal.get("attempt") != 1
            or seal.get("private_manifest_sha256") != observed[
                "t26_private_manifest_sha256"]
            or seal.get("private_blind_root") != observed[
                "t26_private_holdout_root"]
            or not _verify_event_chain(ledger)):
        raise ValueError("T26 sealed construction/evaluation state authentication failed")
    marker = store.read("markers/evaluation.one-shot")
    if (marker.get("attempt") != 1 or marker.get("ledger_genesis_hash") !=
            ledger["events"][0]["event_hash"]):
        raise ValueError("T26 official evaluation one-shot marker mismatch")
    return {"status": "PASS", "store_verification": verification, **observed}


def _load_or_derive_index(store: T26PrivateStore) -> tuple[dict[str, list[str]], str, str]:
    path = "construction/t27_overlap_fingerprint_index.json"
    if store.has(path):
        document = store.read(path)
        if (document.get("schema_version") != "t26-sealed-t27-fingerprint-index-v1"
                or document.get("artifact") != "T26_SEALED_T27_FINGERPRINT_INDEX"
                or set(document.get("dimensions", {})) != set(DIMENSIONS)):
            raise ValueError("sealed T26 fingerprint index invalid")
        dimensions = {name: sorted(_hash_set(document["dimensions"][name], name))
                      for name in DIMENSIONS}
        root = sha256_json(dimensions)
        if document.get("index_root") != root:
            raise ValueError("sealed T26 fingerprint index root mismatch")
        return dimensions, root, "PRE_EXISTING_SEALED"
    if not (store.has("construction/inputs.json") and
            store.has("construction/gold.json")):
        raise ValueError("T26 fingerprint index and derivation inputs absent")
    # Machine-only derivation inside the authenticated boundary. No value from
    # these rows is returned or logged.
    from .exclusion import observed_bundle_fingerprints

    cases = json.loads(store.read_bytes("construction/inputs.json"))
    gold = json.loads(store.read_bytes("construction/gold.json"))
    observed = observed_bundle_fingerprints(cases, gold, [])
    dimensions = {name: sorted(_hash_set(observed[name], name)) for name in DIMENSIONS}
    return dimensions, sha256_json(dimensions), "DERIVED_INTERNAL_MACHINE_ONLY"


def _build_result(*, prospective_root: str,
                  prospective: dict[str, list[str]],
                  historical: dict[str, list[str]],
                  bindings: dict[str, str | int], mode: str,
                  scope: str, implementation: str,
                  store_authenticated: bool, index_root: str,
                  index_origin: str, timestamp: str | None) -> dict[str, Any]:
    if not isinstance(prospective_root, str) or len(prospective_root) != 64:
        raise ValueError("prospective fingerprint root invalid")
    _validate_sets(prospective, "prospective oracle input")
    _validate_sets(historical, "historical oracle index")
    if sha256_json({name: sorted(set(prospective[name])) for name in DIMENSIONS}) != prospective_root:
        raise ValueError("prospective fingerprint root does not bind supplied hashes")
    dimensions = {}
    total = 0
    for name in DIMENSIONS:
        future = _hash_set(prospective[name], name)
        prior = _hash_set(historical[name], name)
        overlap = len(future & prior)
        total += overlap
        dimensions[name] = {
            "applicable": bool(future),
            "prospective_population": len(future),
            "historical_population": len(prior),
            "overlap_count": overlap,
        }
    core = {
        "schema_version": REAL_SCHEMA if mode == "REAL_SEALED" else SYNTHETIC_SCHEMA,
        "artifact": ARTIFACT, "experiment": "t27", "mode": mode,
        "official_commitment_scope": scope,
        "oracle_implementation": implementation,
        "t26_store_authenticated": store_authenticated,
        **bindings,
        "t26_fingerprint_index_root": index_root,
        "t26_fingerprint_index_origin": index_origin,
        "t27_prospective_fingerprint_root": prospective_root,
        "dimensions": dimensions,
        "overall_prohibited_overlap": total,
        "oracle_execution_timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "outside_boundary_private_rows_exposed": 0,
    }
    return {**core, "result_sha256": sha256_json(core)}


def compare_hashes(*, prospective_root: str,
                   prospective: dict[str, list[str]],
                   sealed_historical: dict[str, list[str]],
                   t26_bindings: dict[str, str],
                   timestamp: str | None = None) -> dict[str, Any]:
    """Disposable compatibility helper; production real mode rejects it."""
    required = {
        "t26_private_holdout_root", "t26_private_manifest_sha256",
        "t26_construction_seal_sha256", "t26_evaluation_ledger_sha256",
    }
    if set(t26_bindings) != required:
        raise ValueError("synthetic T26 bindings incomplete")
    bindings: dict[str, str | int] = {
        "t26_store_identity": "SYNTHETIC-T26-STORE",
        "t26_namespace": "t26-synthetic",
        **t26_bindings,
        "t26_official_evaluation_state": "SYNTHETIC_COMPLETE",
        "t26_official_evaluation_attempt": 1,
    }
    return _build_result(
        prospective_root=prospective_root, prospective=prospective,
        historical=sealed_historical, bindings=bindings,
        mode="SYNTHETIC_DISPOSABLE", scope="SYNTHETIC_DISPOSABLE",
        implementation=SYNTHETIC_ORACLE_ID, store_authenticated=False,
        index_root=sha256_json({name: sorted(set(sealed_historical[name]))
                                for name in DIMENSIONS}),
        index_origin="SYNTHETIC_EXPLICIT", timestamp=timestamp)


def _run_authenticated(*, store: T26PrivateStore,
                       prospective_root: str,
                       prospective: dict[str, list[str]],
                       expected: dict[str, str | int], scope: str,
                       timestamp: str | None = None) -> dict[str, Any]:
    authenticated = _authenticate_store(store, expected)
    historical, index_root, index_origin = _load_or_derive_index(store)
    bindings = {key: authenticated[key] for key in (
        "t26_store_identity", "t26_namespace", "t26_private_holdout_root",
        "t26_private_manifest_sha256", "t26_construction_seal_sha256",
        "t26_evaluation_ledger_sha256", "t26_official_evaluation_state",
        "t26_official_evaluation_attempt")}
    return _build_result(
        prospective_root=prospective_root, prospective=prospective,
        historical=historical, bindings=bindings, mode="REAL_SEALED",
        scope=scope, implementation=SEALED_ORACLE_ID,
        store_authenticated=True, index_root=index_root,
        index_origin=index_origin, timestamp=timestamp)


def run_sealed_t26_to_t27_overlap_oracle(*, root: Path,
                                         store: T26PrivateStore,
                                         prospective_root: str,
                                         prospective: dict[str, list[str]],
                                         timestamp: str | None = None
                                         ) -> dict[str, Any]:
    """Production entrypoint; caller-provided commitments are not accepted."""
    return _run_authenticated(
        store=store, prospective_root=prospective_root, prospective=prospective,
        expected=official_t26_commitments(root), scope="OFFICIAL_T26",
        timestamp=timestamp)


def _event(index: int, state: str, previous: str | None) -> dict[str, Any]:
    event = {"event_index": index, "event_type": state,
             "timestamp": f"2026-09-27T01:00:0{index}+00:00",
             "previous_event_hash": "0" * 64 if index == 0 else previous,
             "payload": {"disposable": True}}
    return {**event, "event_hash": sha256_json(event)}


def disposable_real_mode_oracle_result(*, root: Path,
                                       prospective_root: str,
                                       prospective: dict[str, list[str]],
                                       variant: int = 0) -> dict[str, Any]:
    """Production-semantics rehearsal using an isolated authenticated stand-in."""
    historical = {name: [sha256_json(("sealed-t26-standin", variant, name))]
                  for name in DIMENSIONS}
    index = {
        "schema_version": "t26-sealed-t27-fingerprint-index-v1",
        "artifact": "T26_SEALED_T27_FINGERPRINT_INDEX",
        "dimensions": historical,
        "index_root": sha256_json(historical),
    }
    with TemporaryDirectory(prefix="t26-t27-sealed-oracle-") as directory:
        store = T26PrivateStore(Path(directory) / STORE_ID, Path(root).resolve())
        holdout_root = sha256_json(("standin-holdout", variant))
        manifest = {
            "schema_version": "t26-private-manifest-v4",
            "artifact": "T26_PRIVATE_MANIFEST",
            "private_blind_root": holdout_root,
            "private_artifact_root": sha256_json(("standin-artifacts", variant)),
            "artifacts": [],
        }
        manifest_meta = store.write_once(
            "construction/manifest.json", manifest,
            classification="PRIVATE_EVALUATION")
        seal = {
            "schema_version": "t26-holdout-seal-v3",
            "artifact": "T26_HOLDOUT_SEALED", "state": "SEALED", "attempt": 1,
            "private_manifest_sha256": manifest_meta["sha256"],
            "private_blind_root": holdout_root,
        }
        seal_meta = store.write_once(
            "construction/seal.json", seal,
            classification="PRIVATE_EVALUATION")
        prior = None
        events = []
        for number, state in enumerate(("STARTED", "EXECUTED", "SCORED", "COMPLETE")):
            event = _event(number, state, prior)
            prior = event["event_hash"]
            events.append(event)
        ledger = {
            "schema_version": "t26-production-bound-evaluation-ledger-v1",
            "artifact": "T26_OFFICIAL_EVALUATION_LEDGER", "attempt": 1,
            "state": "COMPLETE", "events": events, "event_count": len(events),
            "final_event_hash": prior,
        }
        ledger_meta = store.write_once(
            "evaluation/ledger.json", ledger,
            classification="PRIVATE_EVALUATION")
        store.write_once("markers/evaluation.one-shot", {
            "schema_version": "t26-evaluation-one-shot-marker-v1",
            "artifact": "T26_EVALUATION_ONE_SHOT_SPENT", "attempt": 1,
            "ledger_genesis_hash": events[0]["event_hash"],
        }, classification="PRIVATE_EVALUATION")
        store.write_once("construction/t27_overlap_fingerprint_index.json", index,
                         classification="PRIVATE_EVALUATION")
        expected: dict[str, str | int] = {
            "t26_store_identity": STORE_ID, "t26_namespace": "t26",
            "t26_private_holdout_root": holdout_root,
            "t26_private_manifest_sha256": manifest_meta["sha256"],
            "t26_construction_seal_sha256": seal_meta["sha256"],
            "t26_evaluation_ledger_sha256": ledger_meta["sha256"],
            "t26_official_evaluation_state": "COMPLETE",
            "t26_official_evaluation_attempt": 1,
        }
        return _run_authenticated(
            store=store, prospective_root=prospective_root,
            prospective=prospective, expected=expected,
            scope="DISPOSABLE_STANDIN", timestamp=(
                f"2026-09-27T01:00:0{variant}+00:00"))


def real_mode_oracle_rehearsal(root: Path) -> dict[str, Any]:
    prospective = {name: [sha256_json(("prospective-standin", name))]
                   for name in DIMENSIONS}
    prospective_root = sha256_json(prospective)
    result = disposable_real_mode_oracle_result(
        root=root, prospective_root=prospective_root,
        prospective=prospective, variant=0)
    return {
        "schema_version": "t27-real-mode-oracle-rehearsal-v1",
        "artifact": "T27_REAL_MODE_T26_ORACLE_REHEARSAL",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "oracle_implementation": result["oracle_implementation"],
        "official_commitment_scope": result["official_commitment_scope"],
        "store_authenticated": result["t26_store_authenticated"],
        "evaluation_state": result["t26_official_evaluation_state"],
        "evaluation_attempt": result["t26_official_evaluation_attempt"],
        "dimension_count": len(result["dimensions"]),
        "overall_prohibited_overlap": result["overall_prohibited_overlap"],
        "index_origin": result["t26_fingerprint_index_origin"],
        "index_root": result["t26_fingerprint_index_root"],
        "result_sha256": result["result_sha256"],
        "outside_boundary_private_rows_exposed": 0,
    }
