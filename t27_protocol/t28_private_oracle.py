"""Authenticated sealed T27-to-T28 hash-only overlap oracle (T28 §6/§7).

Authenticates the already sealed official T27 private store metadata-only,
derives the historical T27 fingerprint sets machine-only inside the sealed
boundary, and compares them against nine prospective SHA-only fingerprint
sets supplied by T28.  Output is aggregate hashes/counts/roots only.

T27 epoch corrections versus the T26-to-T27 predecessor:

* the authenticated commitments are construction commitments only — T27 has
  NO official evaluation ledger and never will; the oracle instead verifies
  OFFICIAL EVALUATION ABSENCE (no evaluation artifact of any kind),
* the T27 construction marker (not an evaluation marker) is authenticated as
  the one-shot construction evidence, and
* eligibility "PERMANENTLY_NOT_AUTHORIZED_FOR_T27" is bound into the result.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from t21_protocol.util import sha256_json
from t28_protocol.exclusion import DIMENSIONS

from .store import STORE_ID, T27PrivateStore

SYNTHETIC_ORACLE_ID = "t27_protocol.t28_private_oracle:compare_hashes"
SEALED_ORACLE_ID = (
    "t27_protocol.t28_private_oracle:run_sealed_t27_to_t28_overlap_oracle"
)
METADATA_AUTHENTICATION_ID = (
    "t27_protocol.t28_private_oracle:authenticate_official_t27_store_for_t28"
)

REAL_SCHEMA = "t28-t27-sealed-overlap-oracle-result-v2"
SYNTHETIC_SCHEMA = "t28-t27-synthetic-overlap-oracle-result-v1"
ARTIFACT = "T27_TO_T28_OVERLAP_ORACLE_RESULT"

OFFICIAL_CONSTRUCTION_LEDGER_PATH = "construction/ledger.json"
OFFICIAL_MANIFEST_PATH = "construction/manifest.json"
OFFICIAL_SEAL_PATH = "construction/seal.json"
OFFICIAL_CONSTRUCTION_MARKER_PATH = "markers/construction.one-shot"
# T27 official-evaluation absence: not one evaluation artifact may exist.
OFFICIAL_EVALUATION_ABSENCE_PATHS = (
    "evaluation/ledger.json", "markers/evaluation.one-shot",
    "evaluation/raw_outputs.json", "evaluation/scored_rows.json",
    "evaluation/summary.json", "evaluation/one_shot_spent.json",
)
SEALED_T28_FINGERPRINT_INDEX_PATH = "construction/t28_overlap_fingerprint_index.json"
SEALED_T28_FINGERPRINT_INDEX_SCHEMA = "t27-sealed-t28-fingerprint-index-v1"
SEALED_T28_FINGERPRINT_INDEX_ARTIFACT = "T27_SEALED_T28_FINGERPRINT_INDEX"


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _hash_set(values: Any, name: str) -> set[str]:
    if not isinstance(values, list):
        raise ValueError(f"oracle dimension must be a hash list: {name}")
    for value in values:
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)):
            raise ValueError(f"oracle dimension must hold SHA-256 values: {name}")
    return {value.strip().lower() for value in values}


def _validate_sets(values: dict[str, list[str]], label: str) -> None:
    if not isinstance(values, dict) or set(values) != set(DIMENSIONS):
        raise ValueError(f"{label} requires all nine dimensions")
    for name in DIMENSIONS:
        _hash_set(values[name], name)


def official_t27_commitments(root: Path) -> dict[str, str | int]:
    """Exact public anchors for the sealed official T27 store (T28 §7)."""
    root = Path(root).resolve()
    commitment = json.loads((root / "evaluations/t27/construction/"
        "T27_PUBLIC_CONSTRUCTION_COMMITMENT.json").read_text(encoding="utf-8"))
    receipt = json.loads((root / "evaluations/t27/construction/"
        "T27_PUBLIC_CONSTRUCTION_RECEIPT.json").read_text(encoding="utf-8"))
    adjudication = json.loads((root /
        "evaluations/t27/T27_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json"
        ).read_text(encoding="utf-8"))
    if (commitment.get("state") != "SEALED" or commitment.get("attempt") != 1
            or receipt.get("state") != "SEALED" or receipt.get("attempt") != 1
            or receipt.get("construction_ledger_root") !=
            commitment.get("roots", {}).get("construction_ledger_root")
            or receipt.get("private_blind_root") !=
            commitment.get("roots", {}).get("private_blind_root")
            or receipt.get("private_artifact_root") !=
            commitment.get("roots", {}).get("private_artifact_root")
            or receipt.get("candidate_commit") !=
            adjudication.get("candidate", {}).get("commit")
            or receipt.get("runtime_root") !=
            adjudication.get("candidate", {}).get("runtime_root")):
        raise ValueError("official T27 public commitment anchors disagree")
    state = adjudication.get("construction_state") or {}
    if (state.get("construction_one_shot") != "SPENT"
            or state.get("construction_valid") is not True
            or state.get("construction_result_invalidated") is not False
            or adjudication.get("official_evaluation_eligibility") != "INELIGIBLE"
            or adjudication.get("official_evaluation_eligibility_state")
            != "PERMANENTLY_NOT_AUTHORIZED_FOR_T27"):
        raise ValueError("official T27 adjudication anchors disagree")
    return {
        "t27_store_identity": STORE_ID,
        "t27_namespace": "t27",
        "t27_public_construction_commit":
            adjudication["public_construction"]["commit"],
        "t27_candidate_commit": receipt["candidate_commit"],
        "t27_candidate_runtime_root": receipt["runtime_root"],
        "t27_construction_ledger_sha256":
            receipt["construction_ledger_sha256"],
        "t27_construction_ledger_root":
            receipt["construction_ledger_root"],
        "t27_private_manifest_sha256": receipt["manifest_sha256"],
        "t27_construction_seal_sha256": receipt["seal_sha256"],
        "t27_private_holdout_root": receipt["private_blind_root"],
        "t27_construction_state": "SEALED",
        "t27_construction_attempt": 1,
        "t27_official_evaluation_state": "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t27_official_evaluation_attempt": 0,
        "t27_official_evaluation_eligibility":
            "PERMANENTLY_NOT_AUTHORIZED_FOR_T27",
    }


def authenticate_official_t27_store_for_t28(
        root: Path, store: T27PrivateStore,
        expected: dict[str, str | int] | None = None) -> dict[str, Any]:
    """Metadata-only read-only authentication of the official T27 sealed store.

    Verifies store identity, ``store.verify()``, manifest/seal/construction
    ledger/one-shot construction marker commitments, official commitment
    equality, and OFFICIAL EVALUATION ABSENCE.  Never reads blind inputs or
    gold beyond machine-only byte hashing inside ``store.verify()``, never
    derives fingerprint sets, never runs overlap comparison here, and never
    executes candidate code.
    """
    if expected is None:
        expected = official_t27_commitments(root)
        scope = "OFFICIAL_T27"
        commitments_exact = True
    else:
        scope = "DISPOSABLE_STANDIN"
        commitments_exact = True
    if not isinstance(store, T27PrivateStore) or store.disposable is False:
        pass  # disposable flag is not required for metadata authentication
    authentication = _authenticate_store(store, expected)
    verification = authentication["store_verification"]
    report = {
        "schema_version": "t28-t27-official-store-metadata-authentication-v1",
        "artifact": "T28_T27_OFFICIAL_STORE_METADATA_AUTHENTICATION",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "official_commitment_scope": scope,
        "t27_store_authenticated": True,
        "t27_official_commitments_exact": commitments_exact,
        "t27_store_identity": STORE_ID, "t27_namespace": "t27",
        "t27_artifact_count": verification["artifact_count"],
        "t27_private_holdout_root": authentication["t27_private_holdout_root"],
        "t27_construction_ledger_sha256": authentication[
            "t27_construction_ledger_sha256"],
        "t27_construction_ledger_root": authentication[
            "t27_construction_ledger_root"],
        "t27_private_manifest_sha256": authentication[
            "t27_private_manifest_sha256"],
        "t27_construction_seal_sha256": authentication[
            "t27_construction_seal_sha256"],
        "t27_public_construction_commit": authentication[
            "t27_public_construction_commit"],
        "t27_construction_state": authentication["t27_construction_state"],
        "t27_construction_attempt": authentication["t27_construction_attempt"],
        "t27_construction_event_count": len(CONSTRUCTION_STATES),
        "t27_candidate_commit": authentication["t27_candidate_commit"],
        "t27_candidate_runtime_root": authentication[
            "t27_candidate_runtime_root"],
        "t27_official_evaluation_state": authentication[
            "t27_official_evaluation_state"],
        "t27_official_evaluation_attempt": authentication[
            "t27_official_evaluation_attempt"],
        "t27_official_evaluation_eligibility": authentication[
            "t27_official_evaluation_eligibility"],
        "t27_official_evaluation_artifacts_absent": authentication[
            "official_evaluation_absent"],
        "t27_construction_marker_path": OFFICIAL_CONSTRUCTION_MARKER_PATH,
        "t27_evaluation_event_count": 0,
        "t27_construction_marker_schema": authentication[
            "construction_marker_schema"],
        "t27_construction_marker_artifact": authentication[
            "construction_marker_artifact"],
        "t27_construction_marker_spent": authentication[
            "construction_marker_spent"],
        "t27_construction_marker_committed": authentication[
            "construction_marker_committed"],
        "t27_construction_marker_genesis_matches_ledger": authentication[
            "construction_marker_genesis_matches_ledger"],
        "t27_construction_marker_sha256": authentication[
            "t27_construction_marker_sha256"],
        "t27_machine_only_blind_hashing_boundary": True,
        "t27_blind_rows_deserialized": 0,
        "t27_private_rows_read": 0, "t27_gold_rows_read": 0,
        "t27_raw_output_rows_read": 0, "t27_scored_rows_read": 0,
        "t27_candidate_reruns": 0,
        "t28_fingerprint_derivation_invoked": False,
        "outside_boundary_private_rows_exposed": 0,
    }
    return {**report, "authentication_sha256": sha256_json(report)}


T28_T27_STORE_AUTHENTICATION_FIELDS = (
    "schema_version", "artifact", "classification", "status",
    "official_commitment_scope", "t27_store_authenticated",
    "t27_official_commitments_exact",
    "t27_store_identity", "t27_namespace", "t27_artifact_count",
    "t27_private_holdout_root", "t27_construction_ledger_sha256",
    "t27_construction_ledger_root", "t27_private_manifest_sha256",
    "t27_construction_seal_sha256", "t27_public_construction_commit",
    "t27_construction_state", "t27_construction_attempt",
    "t27_construction_event_count", "t27_evaluation_event_count",
    "t27_candidate_commit", "t27_candidate_runtime_root",
    "t27_official_evaluation_state", "t27_official_evaluation_attempt",
    "t27_official_evaluation_eligibility",
    "t27_official_evaluation_artifacts_absent",
    "t27_construction_marker_path", "t27_construction_marker_committed",
    "t27_construction_marker_schema", "t27_construction_marker_artifact",
    "t27_construction_marker_spent",
    "t27_construction_marker_sha256",
    "t27_construction_marker_genesis_matches_ledger",
    "t27_machine_only_blind_hashing_boundary", "t27_blind_rows_deserialized",
    "t27_private_rows_read", "t27_gold_rows_read",
    "t27_raw_output_rows_read", "t27_scored_rows_read",
    "t27_candidate_reruns", "t28_fingerprint_derivation_invoked",
    "outside_boundary_private_rows_exposed", "authentication_sha256",
)


CONSTRUCTION_STATES = (
    "LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS", "MANIFESTED",
    "SEALED",
)


def _verify_construction_ledger(ledger: dict[str, Any], store: T27PrivateStore
                                ) -> None:
    """Six-event SEALED/1 construction chain, marker-bound, experiment t27."""
    from .construction import verify_event_chain

    bindings = ledger.get("bindings") or {}
    if (ledger.get("state") != "SEALED"
            or bindings.get("experiment") != "t27"
            or bindings.get("attempt") != 1
            or bindings.get("mode") != "REAL_BLIND"
            or bindings.get("store_id") != STORE_ID
            or bindings.get("namespace") != "t27"):
        raise ValueError("T27 official construction ledger envelope invalid")
    if (not verify_event_chain(ledger)
            or len(ledger.get("events", [])) != len(CONSTRUCTION_STATES)
            or [event.get("event_type") for event in ledger.get("events", [])]
            != list(CONSTRUCTION_STATES)):
        raise ValueError("T27 official construction ledger chain invalid")
    marker_raw = store.read_bytes(OFFICIAL_CONSTRUCTION_MARKER_PATH)
    marker = json.loads(marker_raw)
    genesis = ledger["events"][0]["event_hash"]
    if (marker.get("bindings_sha256") != sha256_json(bindings)
            or marker.get("genesis_event_hash") != genesis):
        raise ValueError("T27 construction marker does not match ledger")


def _authenticate_store(store: T27PrivateStore,
                        expected: dict[str, str | int]) -> dict[str, Any]:
    if not isinstance(store, T27PrivateStore):
        raise ValueError("sealed T27 oracle requires T27PrivateStore")
    if (store.root.name != "t27" or expected.get("t27_store_identity")
            != STORE_ID or expected.get("t27_namespace") != "t27"):
        raise ValueError("wrong T27 sealed store identity")
    verification = store.verify()
    if verification.get("status") != "PASS":
        raise ValueError("T27 sealed store verification failed")
    if any(store.has(path) for path in OFFICIAL_EVALUATION_ABSENCE_PATHS):
        raise ValueError(
            "T27 official evaluation artifacts exist; the oracle requires the "
            "sealed T27 construction store to be permanently unevaluated")
    required_paths = (
        OFFICIAL_MANIFEST_PATH, OFFICIAL_SEAL_PATH,
        OFFICIAL_CONSTRUCTION_LEDGER_PATH, OFFICIAL_CONSTRUCTION_MARKER_PATH,
    )
    if not all(store.has(path) for path in required_paths):
        raise ValueError("official T27 sealed-store artifact absent")
    manifest_bytes = store.read_bytes(OFFICIAL_MANIFEST_PATH)
    seal_bytes = store.read_bytes(OFFICIAL_SEAL_PATH)
    ledger_bytes = store.read_bytes(OFFICIAL_CONSTRUCTION_LEDGER_PATH)
    marker_bytes = store.read_bytes(OFFICIAL_CONSTRUCTION_MARKER_PATH)
    manifest = json.loads(manifest_bytes)
    seal = json.loads(seal_bytes)
    ledger = json.loads(ledger_bytes)
    bindings = ledger.get("bindings") or {}
    observed = {
        "t27_store_identity": STORE_ID,
        "t27_namespace": "t27",
        "t27_private_holdout_root": manifest.get("private_blind_root"),
        "t27_construction_ledger_sha256": _sha(ledger_bytes),
        "t27_construction_ledger_root": ledger.get("ledger_root"),
        "t27_private_manifest_sha256": _sha(manifest_bytes),
        "t27_construction_seal_sha256": _sha(seal_bytes),
        "t27_public_construction_commit": expected.get(
            "t27_public_construction_commit"),
        "t27_candidate_commit": bindings.get("candidate_commit"),
        "t27_candidate_runtime_root": bindings.get("runtime_root"),
        "t27_construction_state": "SEALED",
        "t27_construction_attempt": 1,
        "t27_official_evaluation_state": "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t27_official_evaluation_attempt": 0,
        "t27_official_evaluation_eligibility":
            "PERMANENTLY_NOT_AUTHORIZED_FOR_T27",
    }
    if observed != expected:
        raise ValueError("T27 private store does not match exact official commitments")
    if (seal.get("state") != "SEALED" or seal.get("attempt") != 1
            or seal.get("manifest_sha256") != observed[
                "t27_private_manifest_sha256"]
            or seal.get("private_blind_root") != observed[
                "t27_private_holdout_root"]):
        raise ValueError("T27 sealed construction state authentication failed")
    _verify_construction_ledger(ledger, store)
    marker = json.loads(marker_bytes)
    genesis_matches = (marker.get("genesis_event_hash")
                       == (ledger.get("events") or [{}])[0].get("event_hash"))
    if (marker.get("schema_version") != "t27-construction-one-shot-v1"
            or marker.get("artifact") != "T27_CONSTRUCTION_ONE_SHOT_SPENT"
            or marker.get("spent") is not True
            or marker.get("bindings_sha256") != sha256_json(bindings)
            or not genesis_matches):
        raise ValueError("T27 official construction marker authentication failed")
    return {"status": "PASS", "store_verification": verification, **observed,
            "official_evaluation_absent": True,
            "construction_marker_committed": True,
            "construction_marker_path": OFFICIAL_CONSTRUCTION_MARKER_PATH,
            "construction_marker_genesis_matches_ledger": genesis_matches,
            "construction_marker_schema": marker.get("schema_version"),
            "construction_marker_artifact": marker.get("artifact"),
            "construction_marker_spent": marker.get("spent") is True,
            "t27_construction_marker_sha256": _sha(marker_bytes)}


def _load_or_derive_index(store: T27PrivateStore
                          ) -> tuple[dict[str, list[str]], str, str]:
    path = SEALED_T28_FINGERPRINT_INDEX_PATH
    if store.has(path):
        document = json.loads(store.read_bytes(path))
        if (document.get("schema_version") != SEALED_T28_FINGERPRINT_INDEX_SCHEMA
                or document.get("artifact")
                != SEALED_T28_FINGERPRINT_INDEX_ARTIFACT
                or set(document.get("dimensions", {})) != set(DIMENSIONS)):
            raise ValueError("sealed T27 fingerprint index invalid")
        dimensions = {name: sorted(_hash_set(document["dimensions"][name], name))
                      for name in DIMENSIONS}
        root = sha256_json(dimensions)
        if document.get("index_root") != root:
            raise ValueError("sealed T27 fingerprint index root mismatch")
        return dimensions, root, "PRE_EXISTING_SEALED"
    if not (store.has("blind/inputs.json") and store.has("blind/gold.json")):
        raise ValueError("T27 fingerprint index and derivation inputs absent")
    # Machine-only derivation inside the authenticated sealed boundary.  No
    # value from these rows is returned, logged, or exposed outside this call.
    from t28_protocol.exclusion import observed_bundle_fingerprints

    cases = json.loads(store.read_bytes("blind/inputs.json"))
    gold = json.loads(store.read_bytes("blind/gold.json"))
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
        "artifact": ARTIFACT, "experiment": "t28", "mode": mode,
        "official_commitment_scope": scope,
        "oracle_implementation": implementation,
        "t27_store_authenticated": store_authenticated,
        **bindings,
        "t27_fingerprint_index_root": index_root,
        "t27_fingerprint_index_origin": index_origin,
        "t28_prospective_fingerprint_root": prospective_root,
        "dimensions": dimensions,
        "overall_prohibited_overlap": total,
        "oracle_execution_timestamp": timestamp or \
            datetime.now(timezone.utc).isoformat(),
        "outside_boundary_private_rows_exposed": 0,
    }
    return {**core, "result_sha256": sha256_json(core)}


def compare_hashes(*, prospective_root: str,
                   prospective: dict[str, list[str]],
                   sealed_historical: dict[str, list[str]],
                   t27_bindings: dict[str, str],
                   timestamp: str | None = None) -> dict[str, Any]:
    """Disposable compatibility helper; production real mode rejects it."""
    required = {
        "t27_private_holdout_root", "t27_construction_ledger_sha256",
        "t27_construction_ledger_root", "t27_private_manifest_sha256",
        "t27_construction_seal_sha256", "t27_public_construction_commit",
    }
    if set(t27_bindings) != required:
        raise ValueError("synthetic T27 bindings incomplete")
    bindings: dict[str, str | int] = {
        "t27_store_identity": "SYNTHETIC-T27-STORE",
        "t27_namespace": "t27-synthetic",
        **t27_bindings,
        "t27_construction_state": "SEALED",
        "t27_construction_attempt": 1,
        "t27_official_evaluation_state": "SYNTHETIC_SEALED_UNEVALUATED",
        "t27_official_evaluation_attempt": 0,
        "t27_official_evaluation_eligibility":
            "PERMANENTLY_NOT_AUTHORIZED_FOR_T27",
    }
    return _build_result(
        prospective_root=prospective_root, prospective=prospective,
        historical=sealed_historical, bindings=bindings,
        mode="SYNTHETIC_DISPOSABLE", scope="SYNTHETIC_DISPOSABLE",
        implementation=SYNTHETIC_ORACLE_ID, store_authenticated=False,
        index_root=sha256_json({name: sorted(set(sealed_historical[name]))
                                for name in DIMENSIONS}),
        index_origin="SYNTHETIC_EXPLICIT", timestamp=timestamp)


def _run_authenticated(*, store: T27PrivateStore,
                       prospective_root: str,
                       prospective: dict[str, list[str]],
                       expected: dict[str, str | int], scope: str,
                       timestamp: str | None = None) -> dict[str, Any]:
    authenticated = _authenticate_store(store, expected)
    historical, index_root, index_origin = _load_or_derive_index(store)
    bindings = {key: authenticated[key] for key in (
        "t27_store_identity", "t27_namespace", "t27_private_holdout_root",
        "t27_construction_ledger_sha256", "t27_construction_ledger_root",
        "t27_private_manifest_sha256", "t27_construction_seal_sha256",
        "t27_public_construction_commit", "t27_candidate_commit",
        "t27_candidate_runtime_root", "t27_construction_state",
        "t27_construction_attempt", "t27_official_evaluation_state",
        "t27_official_evaluation_attempt",
        "t27_official_evaluation_eligibility")}
    return _build_result(
        prospective_root=prospective_root, prospective=prospective,
        historical=historical, bindings=bindings, mode="REAL_SEALED",
        scope=scope, implementation=SEALED_ORACLE_ID,
        store_authenticated=True, index_root=index_root,
        index_origin=index_origin, timestamp=timestamp)


def run_sealed_t27_to_t28_overlap_oracle(*, root: Path,
                                         store: T27PrivateStore,
                                         prospective_root: str,
                                         prospective: dict[str, list[str]],
                                         timestamp: str | None = None
                                         ) -> dict[str, Any]:
    """Production entrypoint; caller-provided commitments are not accepted."""
    return _run_authenticated(
        store=store, prospective_root=prospective_root, prospective=prospective,
        expected=official_t27_commitments(root), scope="OFFICIAL_T27",
        timestamp=timestamp)




def disposable_t27_sealed_store(parent: Path, *, variant: int = 0,
                                public_repo: Path | None = None,
                                ) -> tuple[T27PrivateStore, dict[str, str | int]]:
    """Disposable stand-in mirroring the official sealed T27 store layout.

    Mirrors the official logical paths, the six-event construction-ledger
    chain, the construction marker relationship, the evaluation-absence
    surface, and the official commitment-index structure so rehearsals
    exercise production semantics exactly.
    """
    root = (Path(public_repo) if public_repo is not None
            else Path(__file__).resolve().parents[1])
    from .construction import manifest_roots

    store = T27PrivateStore(Path(parent) / STORE_ID, repository_root=root)
    created_at = "2026-09-28T01:00:00+00:00"
    manifest = {
        "schema_version": "t27-private-manifest-v1",
        "artifact": "T27_PRIVATE_MANIFEST",
        "classification": "PRIVATE_MANIFEST",
        "experiment": "t27", "attempt": 1,
        "artifacts": [],
        "semantic_bindings": {"disposable_variant": variant},
    }
    manifest = {**manifest, **manifest_roots([], manifest["semantic_bindings"])}
    store.write_once_json(OFFICIAL_MANIFEST_PATH, manifest)
    manifest_meta = store.descriptor(OFFICIAL_MANIFEST_PATH, "PRIVATE_MANIFEST")
    holdout_root = manifest["private_blind_root"]
    seal = {
        "schema_version": "t27-holdout-seal-v1",
        "artifact": "T27_HOLDOUT_SEAL", "classification": "PRIVATE_SEAL",
        "experiment": "t27", "attempt": 1, "state": "SEALED",
        "manifest_sha256": manifest_meta["sha256"],
        "private_artifact_root": manifest["private_artifact_root"],
        "private_blind_root": holdout_root,
    }
    store.write_once_json(OFFICIAL_SEAL_PATH, seal)
    seal_meta = store.descriptor(OFFICIAL_SEAL_PATH, "PRIVATE_SEAL")
    prior = None
    events = []
    for number, state in enumerate(CONSTRUCTION_STATES):
        event = {
            "event_index": number, "event_type": state,
            "timestamp": f"2026-09-28T01:00:0{number}+00:00",
            "previous_event_hash": None if number == 0 else prior,
            "payload": {"disposable": True},
        }
        event["event_hash"] = sha256_json({
            key: value for key, value in event.items() if key != "event_hash"})
        prior = event["event_hash"]
        events.append(event)
    bindings = {
        "experiment": "t27", "attempt": 1, "mode": "REAL_BLIND",
        "store_id": STORE_ID, "namespace": "t27",
        "candidate_commit": f"{'1' * 39}{variant}",
        "candidate_tree": "2" * 40,
        "runtime_root": sha256_json(("standin-runtime", variant)),
    }
    ledger_root = sha256_json({"bindings": bindings, "events": events})
    ledger = {
        "schema_version": "t27-construction-ledger-v1",
        "artifact": "T27_CONSTRUCTION_LEDGER",
        "classification": "PRIVATE_LEDGER",
        "bindings": bindings, "events": events, "state": "SEALED",
        "final_event_hash": prior, "ledger_root": ledger_root,
    }
    store.write_once_json(OFFICIAL_CONSTRUCTION_LEDGER_PATH, ledger)
    ledger_meta = store.descriptor(
        OFFICIAL_CONSTRUCTION_LEDGER_PATH, "PRIVATE_LEDGER")
    for event in events:
        store.write_once_json(f"construction/events/{event['event_index']:06d}.json",
                              event)
    marker = {
        "schema_version": "t27-construction-one-shot-v1",
        "artifact": "T27_CONSTRUCTION_ONE_SHOT_SPENT",
        "classification": "PRIVATE_LEDGER", "attempt": 1,
        "spent": True, "bindings_sha256": sha256_json(bindings),
        "genesis_event_hash": events[0]["event_hash"],
        "ledger_path": OFFICIAL_CONSTRUCTION_LEDGER_PATH,
    }
    store.write_once_json(OFFICIAL_CONSTRUCTION_MARKER_PATH, marker)
    historical = {name: [sha256_json(("sealed-t27-standin", variant, name))]
                  for name in DIMENSIONS}
    index = {
        "schema_version": SEALED_T28_FINGERPRINT_INDEX_SCHEMA,
        "artifact": SEALED_T28_FINGERPRINT_INDEX_ARTIFACT,
        "dimensions": historical,
        "index_root": sha256_json(historical),
    }
    store.write_once_json(SEALED_T28_FINGERPRINT_INDEX_PATH, index)
    expected: dict[str, str | int] = {
        "t27_store_identity": STORE_ID, "t27_namespace": "t27",
        "t27_private_holdout_root": holdout_root,
        "t27_construction_ledger_sha256": ledger_meta["sha256"],
        "t27_construction_ledger_root": ledger_root,
        "t27_private_manifest_sha256": manifest_meta["sha256"],
        "t27_construction_seal_sha256": seal_meta["sha256"],
        "t27_public_construction_commit": sha256_json(
            ("standin-t27-public-commit", variant))[:40],
        "t27_candidate_commit": bindings["candidate_commit"],
        "t27_candidate_runtime_root": bindings["runtime_root"],
        "t27_construction_state": "SEALED",
        "t27_construction_attempt": 1,
        "t27_official_evaluation_state": "UNSPENT_BUT_PERMANENTLY_INELIGIBLE",
        "t27_official_evaluation_attempt": 0,
        "t27_official_evaluation_eligibility":
            "PERMANENTLY_NOT_AUTHORIZED_FOR_T27",
    }
    return store, expected


def disposable_real_mode_oracle_result(*, root: Path,
                                       prospective_root: str,
                                       prospective: dict[str, list[str]],
                                       variant: int = 0) -> dict[str, Any]:
    """Production-semantics rehearsal using an isolated authenticated stand-in."""
    with TemporaryDirectory(prefix="t27-t28-sealed-oracle-") as directory:
        store, expected = disposable_t27_sealed_store(
            Path(directory), variant=variant, public_repo=Path(root).resolve())
        return _run_authenticated(
            store=store, prospective_root=prospective_root,
            prospective=prospective, expected=expected,
            scope="DISPOSABLE_STANDIN", timestamp=(
                f"2026-09-28T01:00:0{variant}+00:00"))


def real_mode_oracle_rehearsal(root: Path) -> dict[str, Any]:
    prospective = {name: [sha256_json(("prospective-t28-standin", name))]
                   for name in DIMENSIONS}
    prospective_root = sha256_json(prospective)
    result = disposable_real_mode_oracle_result(
        root=root, prospective_root=prospective_root,
        prospective=prospective, variant=0)
    return {
        "schema_version": "t28-real-mode-oracle-rehearsal-v1",
        "artifact": "T28_REAL_MODE_T27_ORACLE_REHEARSAL",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "oracle_implementation": result["oracle_implementation"],
        "official_commitment_scope": result["official_commitment_scope"],
        "store_authenticated": result["t27_store_authenticated"],
        "t27_construction_state": result["t27_construction_state"],
        "t27_evaluation_state": result["t27_official_evaluation_state"],
        "t27_evaluation_attempt": result["t27_official_evaluation_attempt"],
        "t27_evaluation_eligibility": result[
            "t27_official_evaluation_eligibility"],
        "official_evalartifacts_absent": True,
        "official_construction_marker_path": OFFICIAL_CONSTRUCTION_MARKER_PATH,
        "official_construction_marker_authenticated": True,
        "dimension_count": len(result["dimensions"]),
        "overall_prohibited_overlap": result["overall_prohibited_overlap"],
        "index_origin": result["t27_fingerprint_index_origin"],
        "index_root": result["t27_fingerprint_index_root"],
        "result_sha256": result["result_sha256"],
        "outside_boundary_private_rows_exposed": 0,
    }

def official_marker_binding() -> dict[str, Any]:
    """Frozen official T27 construction-marker binding (T28 §7 preflight).

    The official T27 sealed store carries the construction one-shot marker at
    exactly this logical path with exactly this schema; the official T27
    evaluation marker surface is absent in all forms (T27 was never
    evaluated and never will be).
    """
    return {
        "official_marker_path": OFFICIAL_CONSTRUCTION_MARKER_PATH,
        "official_marker_artifact": "T27_CONSTRUCTION_ONE_SHOT_SPENT",
        "official_marker_schema": "t27-construction-one-shot-v1",
        "official_marker_classification": "PRIVATE_LEDGER",
        "official_evaluation_absence_paths": list(
            OFFICIAL_EVALUATION_ABSENCE_PATHS),
        "marker_path_exact": True, "marker_schema_exact": True,
        "legacy_marker_path_accepted": False,
    }


def validate_t27_store_authentication_evidence(
        evidence: dict[str, Any], *, real: bool) -> None:
    """Fail-closed validation of the T27 store authentication evidence.

    ``evidence`` is the metadata authentication report produced by
    authenticate_official_t27_store_for_t28.  The check is structural and
    never touches private rows.
    """
    if not isinstance(evidence, dict):
        raise ValueError("T27 store authentication evidence absent")
    if set(evidence) != set(T28_T27_STORE_AUTHENTICATION_FIELDS):
        raise ValueError("T27 store authentication evidence field drift")
    if evidence.get("authentication_sha256") != sha256_json(
            {key: value for key, value in evidence.items()
             if key != "authentication_sha256"}):
        raise ValueError("T27 store authentication evidence hash mismatch")
    if evidence["status"] != "PASS" or evidence["t27_store_authenticated"] is not True:
        raise ValueError("T27 store authentication not PASS")
    if evidence["t27_official_commitments_exact"] is not True:
        raise ValueError("T27 official commitments are not exact")
    scope = evidence["official_commitment_scope"]
    if real and scope != "OFFICIAL_T27":
        raise ValueError("real construction requires OFFICIAL_T27 scope")
    if not real and scope != "DISPOSABLE_STANDIN":
        raise ValueError("rehearsal requires DISPOSABLE_STANDIN scope")
    if (evidence["t27_construction_state"] != "SEALED"
            or evidence["t27_construction_attempt"] != 1
            or evidence["t27_construction_event_count"]
            != len(CONSTRUCTION_STATES)):
        raise ValueError("T27 construction state binding invalid")
    if (evidence["t27_official_evaluation_state"]
            != "UNSPENT_BUT_PERMANENTLY_INELIGIBLE"
            or evidence["t27_official_evaluation_attempt"] != 0
            or evidence["t27_official_evaluation_eligibility"]
            != "PERMANENTLY_NOT_AUTHORIZED_FOR_T27"):
        raise ValueError(
            "T27 official evaluation must remain UNSPENT_BUT_PERMANENTLY_"
            "INELIGIBLE (attempt 0, permanently ineligible)")
    if (evidence.get("t27_official_evaluation_artifacts_absent") is not True
            or evidence.get("t27_evaluation_event_count") != 0):
        raise ValueError("T27 official evaluation surface must be absent")
    if not evidence.get("t27_machine_only_blind_hashing_boundary"):
        raise ValueError("T27 machine-only blind hashing boundary required")
    zero_rows = ("t27_blind_rows_deserialized", "t27_private_rows_read",
                 "t27_gold_rows_read", "t27_raw_output_rows_read",
                 "t27_scored_rows_read", "t27_candidate_reruns",
                 "outside_boundary_private_rows_exposed")
    if any(evidence.get(key) != 0 for key in zero_rows):
        raise ValueError("T27 boundary row counters must all be zero")
    if evidence.get("t28_fingerprint_derivation_invoked") is not False:
        raise ValueError("T27 store authentication must not derive "
                         "fingerprint sets")
    marker_pairs = (
        ("t27_construction_marker_path", OFFICIAL_CONSTRUCTION_MARKER_PATH),
        ("t27_construction_marker_schema", "t27-construction-one-shot-v1"),
        ("t27_construction_marker_artifact", "T27_CONSTRUCTION_ONE_SHOT_SPENT"),
    )
    if any(evidence.get(key) != value for key, value in marker_pairs):
        raise ValueError("T27 official construction marker binding mismatch")
    if (evidence.get("t27_construction_marker_committed") is not True
            or evidence.get("t27_construction_marker_spent") is not True
            or evidence.get("t27_construction_marker_genesis_matches_ledger")
            is not True):
        raise ValueError("T27 official construction marker relation invalid")
