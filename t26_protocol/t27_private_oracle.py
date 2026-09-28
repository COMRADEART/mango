"""Authenticated sealed T26-to-T27 hash-only overlap oracle.

The production entrypoint authenticates exact official T26 private-store bytes
against public commitments before it derives or loads a nine-dimensional hash
index. Only counts, roots, and official commitment hashes cross the boundary.

The official one-shot evaluation marker is authenticated at the exact official
V4 layout (``t26_protocol.evaluation_v4:MARKER_PATH``/``MARKER_SCHEMA``); the
``markers/evaluation.one-shot`` path is a refused legacy layout and is never
accepted as an alternative in real mode.
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

from .evaluation_v4 import MARKER_PATH as _V4_MARKER_PATH
from .evaluation_v4 import MARKER_SCHEMA as _V4_MARKER_SCHEMA
from .lifecycle import STORE_ID, T26PrivateStore

SYNTHETIC_ORACLE_ID = "t26_protocol.t27_private_oracle:compare_hashes"
SEALED_ORACLE_ID = (
    "t26_protocol.t27_private_oracle:run_sealed_t26_to_t27_overlap_oracle"
)
METADATA_AUTHENTICATION_ID = (
    "t26_protocol.t27_private_oracle:authenticate_official_t26_store_for_t27"
)
# Historical compatibility name. It no longer identifies the production path.
T27_PRIVATE_OVERLAP_ENGINE = SYNTHETIC_ORACLE_ID

REAL_SCHEMA = "t27-t26-sealed-overlap-oracle-result-v2"
SYNTHETIC_SCHEMA = "t27-t26-synthetic-overlap-oracle-result-v1"
ARTIFACT = "T26_TO_T27_OVERLAP_ORACLE_RESULT"

# The official marker path/schema are imported from the authoritative official
# T26 V4 evaluation contract; they are additionally pinned by exact literals in
# ``official_marker_binding`` so any future drift fails tests/doctor/freeze.
OFFICIAL_MARKER_PATH = _V4_MARKER_PATH
OFFICIAL_MARKER_SCHEMA = _V4_MARKER_SCHEMA
OFFICIAL_MARKER_ARTIFACT = "T26_EVALUATION_ONE_SHOT_SPENT"
OFFICIAL_MARKER_EXPERIMENT = "t26"
OFFICIAL_MARKER_FIELDS = (
    "schema_version", "artifact", "experiment", "attempt",
    "ledger_genesis_hash", "created_at",
)
OFFICIAL_LEDGER_PATH = "evaluation/ledger.json"
OFFICIAL_MANIFEST_PATH = "construction/manifest.json"
OFFICIAL_SEAL_PATH = "construction/seal.json"
OFFICIAL_LEDGER_STATES = ("STARTED", "EXECUTED", "SCORED", "COMPLETE")
# Refused legacy marker layout. Never accepted as an alternative in real mode.
LEGACY_MARKER_PATH = "markers/evaluation.one-shot"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def official_marker_binding() -> dict[str, Any]:
    """Exact frozen equality between this oracle and the official V4 contract."""
    return {
        "schema_version": "t27-t26-official-marker-binding-v1",
        "artifact": "T27_T26_OFFICIAL_MARKER_BINDING",
        "classification": "PUBLIC_SAFE",
        "marker_source": "t26_protocol.evaluation_v4:MARKER_PATH/MARKER_SCHEMA",
        "official_marker_path": OFFICIAL_MARKER_PATH,
        "official_marker_schema": OFFICIAL_MARKER_SCHEMA,
        "official_marker_artifact": OFFICIAL_MARKER_ARTIFACT,
        "official_marker_experiment": OFFICIAL_MARKER_EXPERIMENT,
        "official_marker_fields": list(OFFICIAL_MARKER_FIELDS),
        "oracle_marker_path": OFFICIAL_MARKER_PATH,
        "oracle_marker_schema": OFFICIAL_MARKER_SCHEMA,
        "marker_path_exact": (
            OFFICIAL_MARKER_PATH == "evaluation/one_shot_spent.json"),
        "marker_schema_exact": (
            OFFICIAL_MARKER_SCHEMA == "t26-evaluation-one-shot-marker-v2"),
        "legacy_marker_path": LEGACY_MARKER_PATH,
        "legacy_marker_path_accepted": False,
    }


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


def _verify_official_evaluation_ledger(ledger: dict[str, Any]) -> None:
    """Official V4 ledger envelope: COMPLETE/1, 4 events, exact state chain."""
    if (ledger.get("state") != "COMPLETE" or ledger.get("attempt") != 1
            or ledger.get("experiment") != OFFICIAL_MARKER_EXPERIMENT
            or not isinstance(ledger.get("created_at"), str)
            or not ledger.get("created_at")):
        raise ValueError("T26 official evaluation ledger envelope invalid")
    if (not _verify_event_chain(ledger)
            or ledger.get("event_count") != len(OFFICIAL_LEDGER_STATES)
            or [event.get("event_type") for event in ledger.get("events", [])]
            != list(OFFICIAL_LEDGER_STATES)):
        raise ValueError("T26 official evaluation ledger chain invalid")


def _authenticate_official_marker(store: T26PrivateStore,
                                  ledger: dict[str, Any]) -> dict[str, Any]:
    """Full official one-shot marker authentication against the V4 contract."""
    raw = store.read_bytes(OFFICIAL_MARKER_PATH)
    marker = json.loads(raw)
    if not isinstance(marker, dict) or set(marker) != set(OFFICIAL_MARKER_FIELDS):
        raise ValueError("T26 official evaluation marker field set invalid")
    if (marker.get("schema_version") != OFFICIAL_MARKER_SCHEMA
            or marker.get("artifact") != OFFICIAL_MARKER_ARTIFACT
            or marker.get("experiment") != OFFICIAL_MARKER_EXPERIMENT
            or marker.get("attempt") != 1):
        raise ValueError("T26 official evaluation marker identity mismatch")
    genesis = ledger["events"][0]["event_hash"]
    if marker.get("ledger_genesis_hash") != genesis:
        raise ValueError("T26 official marker genesis does not match ledger")
    if marker.get("created_at") != ledger.get("created_at"):
        raise ValueError("T26 official marker creation value invalid")
    commitment = store.commitment(OFFICIAL_MARKER_PATH)
    if (commitment.get("logical_id") != OFFICIAL_MARKER_PATH
            or commitment.get("locator") != store.locator(OFFICIAL_MARKER_PATH)
            or commitment.get("sha256") != _sha(raw)
            or commitment.get("bytes") != len(raw)
            or commitment.get("classification") != "PRIVATE_EVALUATION"):
        raise ValueError("T26 official marker commitment authentication failed")
    return {
        "t26_official_marker_path": OFFICIAL_MARKER_PATH,
        "t26_official_marker_schema": OFFICIAL_MARKER_SCHEMA,
        "t26_official_marker_artifact": OFFICIAL_MARKER_ARTIFACT,
        "t26_official_marker_attempt": marker["attempt"],
        "t26_official_marker_committed": True,
        "t26_official_marker_genesis_matches_ledger": True,
        "t26_official_marker_ledger_genesis_hash": genesis,
        "t26_official_marker_sha256": _sha(raw),
        "t26_official_marker_bytes": len(raw),
    }


def _authenticate_store(store: T26PrivateStore,
                        expected: dict[str, str | int]) -> dict[str, Any]:
    if not isinstance(store, T26PrivateStore):
        raise ValueError("sealed T26 oracle requires T26PrivateStore")
    if (store.root.name != STORE_ID or store.namespace.name != "t26"
            or expected.get("t26_store_identity") != STORE_ID
            or expected.get("t26_namespace") != "t26"):
        raise ValueError("wrong T26 sealed store identity")
    verification = store.verify()
    if store.has(LEGACY_MARKER_PATH):
        raise ValueError(
            "ambiguous legacy official T26 marker layout present; exactly one "
            "authoritative official-marker layout is accepted")
    required_paths = (
        OFFICIAL_MANIFEST_PATH, OFFICIAL_SEAL_PATH,
        OFFICIAL_LEDGER_PATH, OFFICIAL_MARKER_PATH,
    )
    if not all(store.has(path) for path in required_paths):
        raise ValueError("official T26 sealed-store artifact absent")
    manifest_bytes = store.read_bytes(OFFICIAL_MANIFEST_PATH)
    seal_bytes = store.read_bytes(OFFICIAL_SEAL_PATH)
    ledger_bytes = store.read_bytes(OFFICIAL_LEDGER_PATH)
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
                "t26_private_holdout_root"]):
        raise ValueError("T26 sealed construction state authentication failed")
    _verify_official_evaluation_ledger(ledger)
    marker_evidence = _authenticate_official_marker(store, ledger)
    return {"status": "PASS", "store_verification": verification, **observed,
            **marker_evidence}


def authenticate_official_t26_store_for_t27(
        root: Path, store: T26PrivateStore,
        expected: dict[str, str | int] | None = None) -> dict[str, Any]:
    """Metadata-only read-only authentication of an official T26 sealed store.

    Performs store identity verification, ``store.verify()``, manifest
    commitment verification, seal verification, evaluation ledger verification,
    official marker verification, and official commitment equality. It never
    reads construction inputs/gold, never derives fingerprint sets, never runs
    overlap comparison, and never executes candidate code. Only identity,
    counts, and already-published hashes are returned.
    """
    if expected is None:
        expected = official_t26_commitments(root)
        scope = "OFFICIAL_T26"
        commitments_exact = True
    else:
        scope = "DISPOSABLE_STANDIN"
        commitments_exact = True
    authentication = _authenticate_store(store, expected)
    verification = authentication["store_verification"]
    report = {
        "schema_version": "t27-t26-official-store-metadata-authentication-v1",
        "artifact": "T27_T26_OFFICIAL_STORE_METADATA_AUTHENTICATION",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "official_commitment_scope": scope,
        "t26_store_authenticated": True,
        "t26_official_commitments_exact": commitments_exact,
        "t26_store_identity": STORE_ID, "t26_namespace": "t26",
        "t26_artifact_count": verification["artifact_count"],
        "t26_private_holdout_root": authentication["t26_private_holdout_root"],
        "t26_private_manifest_sha256": authentication[
            "t26_private_manifest_sha256"],
        "t26_construction_seal_sha256": authentication[
            "t26_construction_seal_sha256"],
        "t26_evaluation_ledger_sha256": authentication[
            "t26_evaluation_ledger_sha256"],
        "t26_official_evaluation_state": authentication[
            "t26_official_evaluation_state"],
        "t26_official_evaluation_attempt": authentication[
            "t26_official_evaluation_attempt"],
        "t26_evaluation_event_count": len(OFFICIAL_LEDGER_STATES),
        "t26_official_marker_path": authentication["t26_official_marker_path"],
        "t26_official_marker_schema": authentication[
            "t26_official_marker_schema"],
        "t26_official_marker_artifact": authentication[
            "t26_official_marker_artifact"],
        "t26_official_marker_attempt": authentication[
            "t26_official_marker_attempt"],
        "t26_official_marker_committed": authentication[
            "t26_official_marker_committed"],
        "t26_official_marker_genesis_matches_ledger": authentication[
            "t26_official_marker_genesis_matches_ledger"],
        "t26_official_marker_ledger_genesis_hash": authentication[
            "t26_official_marker_ledger_genesis_hash"],
        "t26_official_marker_sha256": authentication[
            "t26_official_marker_sha256"],
        "t26_official_marker_bytes": authentication["t26_official_marker_bytes"],
        "t26_legacy_marker_path_present": store.has(LEGACY_MARKER_PATH),
        "t26_private_rows_read": 0, "t26_gold_rows_read": 0,
        "t26_raw_output_rows_read": 0, "t26_scored_rows_read": 0,
        "t26_candidate_reruns": 0,
        "t27_fingerprint_derivation_invoked": False,
        "outside_boundary_private_rows_exposed": 0,
    }
    return {**report, "authentication_sha256": sha256_json(report)}


T26_STORE_AUTHENTICATION_FIELDS = (
    "schema_version", "artifact", "classification", "status",
    "official_commitment_scope", "t26_store_authenticated",
    "t26_official_commitments_exact",
    "t26_store_identity", "t26_namespace", "t26_artifact_count",
    "t26_private_holdout_root", "t26_private_manifest_sha256",
    "t26_construction_seal_sha256", "t26_evaluation_ledger_sha256",
    "t26_official_evaluation_state", "t26_official_evaluation_attempt",
    "t26_evaluation_event_count",
    "t26_official_marker_path", "t26_official_marker_sha256",
    "t26_official_marker_bytes", "t26_official_marker_schema",
    "t26_official_marker_artifact", "t26_official_marker_attempt",
    "t26_official_marker_committed",
    "t26_official_marker_genesis_matches_ledger",
    "t26_official_marker_ledger_genesis_hash",
    "t26_legacy_marker_path_present",
    "t26_private_rows_read", "t26_gold_rows_read",
    "t26_raw_output_rows_read", "t26_scored_rows_read",
    "t26_candidate_reruns", "t27_fingerprint_derivation_invoked",
    "outside_boundary_private_rows_exposed", "authentication_sha256",
)


def validate_t26_store_authentication_evidence(evidence: dict[str, Any], *,
                                               real: bool) -> dict[str, Any]:
    """Fail-closed validation of metadata-only T26 store authentication."""
    if not isinstance(evidence, dict) or set(evidence) != set(
            T26_STORE_AUTHENTICATION_FIELDS):
        raise ValueError("T26 store authentication evidence shape invalid")
    if (evidence["schema_version"] !=
            "t27-t26-official-store-metadata-authentication-v1"
            or evidence["artifact"] !=
            "T27_T26_OFFICIAL_STORE_METADATA_AUTHENTICATION"):
        raise ValueError("T26 store authentication evidence identity invalid")
    if (evidence["status"] != "PASS" or evidence["classification"] != "PUBLIC_SAFE"
            or evidence["t26_store_authenticated"] is not True
            or evidence["t26_official_commitments_exact"] is not True
            or evidence["t26_official_evaluation_state"] != "COMPLETE"
            or evidence["t26_official_evaluation_attempt"] != 1
            or evidence["t26_evaluation_event_count"] != 4):
        raise ValueError("T26 store authentication evidence is not authenticated")
    if (evidence["t26_official_marker_path"] != OFFICIAL_MARKER_PATH
            or evidence["t26_official_marker_schema"] != OFFICIAL_MARKER_SCHEMA
            or evidence["t26_official_marker_artifact"] != OFFICIAL_MARKER_ARTIFACT
            or evidence["t26_official_marker_attempt"] != 1
            or evidence["t26_official_marker_committed"] is not True
            or evidence["t26_official_marker_genesis_matches_ledger"] is not True):
        raise ValueError("T26 official marker evidence not authenticated")
    if evidence["t26_legacy_marker_path_present"] is not False:
        raise ValueError("legacy T26 marker path present in authentication")
    if any(evidence[key] != 0 for key in (
            "t26_private_rows_read", "t26_gold_rows_read",
            "t26_raw_output_rows_read", "t26_scored_rows_read",
            "t26_candidate_reruns", "outside_boundary_private_rows_exposed")):
        raise ValueError("T26 store authentication read private rows")
    if evidence["t27_fingerprint_derivation_invoked"] is not False:
        raise ValueError("fingerprint derivation invoked during authentication")
    if real:
        if (evidence["official_commitment_scope"] != "OFFICIAL_T26"
                or evidence["t26_store_identity"] != STORE_ID):
            raise ValueError("real T27 construction requires exact official "
                             "T26 store authentication")
    elif evidence["official_commitment_scope"] != "DISPOSABLE_STANDIN":
        raise ValueError("synthetic T27 construction requires disposable "
                         "stand-in authentication")
    expected_hash = sha256_json({key: value for key, value in evidence.items()
                                 if key != "authentication_sha256"})
    if evidence["authentication_sha256"] != expected_hash:
        raise ValueError("T26 store authentication evidence hash mismatch")
    return {"status": "PASS"}


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


def disposable_t26_sealed_store(parent: Path, *, variant: int = 0,
                                legacy_marker: bool = False,
                                public_repo: Path | None = None,
                                ) -> tuple[T26PrivateStore, dict[str, str | int]]:
    """Disposable stand-in mirroring the official sealed T26 store layout.

    Mirrors the official logical paths, official marker schema, the official
    ledger/marker relationship, and the official commitment-index structure so
    rehearsals exercise production semantics exactly.
    """
    root = (Path(public_repo) if public_repo is not None
            else Path(__file__).resolve().parents[1])
    store = T26PrivateStore(Path(parent) / STORE_ID, root)
    created_at = "2026-09-27T01:00:00+00:00"
    holdout_root = sha256_json(("standin-holdout", variant))
    manifest = {
        "schema_version": "t26-private-manifest-v4",
        "artifact": "T26_PRIVATE_MANIFEST",
        "private_blind_root": holdout_root,
        "private_artifact_root": sha256_json(("standin-artifacts", variant)),
        "artifacts": [],
    }
    manifest_meta = store.write_once(
        OFFICIAL_MANIFEST_PATH, manifest,
        classification="PRIVATE_EVALUATION")
    seal = {
        "schema_version": "t26-holdout-seal-v3",
        "artifact": "T26_HOLDOUT_SEALED", "state": "SEALED", "attempt": 1,
        "private_manifest_sha256": manifest_meta["sha256"],
        "private_blind_root": holdout_root,
    }
    seal_meta = store.write_once(
        OFFICIAL_SEAL_PATH, seal, classification="PRIVATE_EVALUATION")
    prior = None
    events = []
    for number, state in enumerate(OFFICIAL_LEDGER_STATES):
        event = _event(number, state, prior)
        prior = event["event_hash"]
        events.append(event)
    ledger = {
        "schema_version": "t26-production-bound-evaluation-ledger-v1",
        "artifact": "T26_OFFICIAL_EVALUATION_LEDGER", "experiment": "t26",
        "attempt": 1, "state": "COMPLETE",
        "created_at": created_at, "updated_at": events[-1]["timestamp"],
        "events": events, "event_count": len(events),
        "final_event_hash": prior,
    }
    ledger_meta = store.write_once(
        OFFICIAL_LEDGER_PATH, ledger, classification="PRIVATE_EVALUATION")
    marker = {
        "schema_version": OFFICIAL_MARKER_SCHEMA,
        "artifact": OFFICIAL_MARKER_ARTIFACT,
        "experiment": OFFICIAL_MARKER_EXPERIMENT, "attempt": 1,
        "ledger_genesis_hash": events[0]["event_hash"],
        "created_at": created_at,
    }
    if legacy_marker:
        # Negative-control layout: the refused legacy path only.
        store.write_once(LEGACY_MARKER_PATH, {
            "schema_version": "t26-evaluation-one-shot-marker-v1",
            "artifact": OFFICIAL_MARKER_ARTIFACT, "attempt": 1,
            "ledger_genesis_hash": events[0]["event_hash"],
        }, classification="PRIVATE_EVALUATION")
    else:
        store.write_once(OFFICIAL_MARKER_PATH, marker,
                         classification="PRIVATE_EVALUATION")
    historical = {name: [sha256_json(("sealed-t26-standin", variant, name))]
                  for name in DIMENSIONS}
    index = {
        "schema_version": "t26-sealed-t27-fingerprint-index-v1",
        "artifact": "T26_SEALED_T27_FINGERPRINT_INDEX",
        "dimensions": historical,
        "index_root": sha256_json(historical),
    }
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
    return store, expected


def disposable_real_mode_oracle_result(*, root: Path,
                                       prospective_root: str,
                                       prospective: dict[str, list[str]],
                                       variant: int = 0) -> dict[str, Any]:
    """Production-semantics rehearsal using an isolated authenticated stand-in."""
    with TemporaryDirectory(prefix="t26-t27-sealed-oracle-") as directory:
        store, expected = disposable_t26_sealed_store(
            Path(directory), variant=variant, public_repo=Path(root).resolve())
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
        "official_marker_path": OFFICIAL_MARKER_PATH,
        "official_marker_schema": OFFICIAL_MARKER_SCHEMA,
        "official_marker_authenticated": True,
        "dimension_count": len(result["dimensions"]),
        "overall_prohibited_overlap": result["overall_prohibited_overlap"],
        "index_origin": result["t26_fingerprint_index_origin"],
        "index_root": result["t26_fingerprint_index_root"],
        "result_sha256": result["result_sha256"],
        "outside_boundary_private_rows_exposed": 0,
    }