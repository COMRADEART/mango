"""Fail-closed verifier for the sealed T27→T29 and T28→T29 dual oracles.

T29 authorization §8/§9: sealed machine-only dual oracles compare the nine
prospective fingerprint dimensions of T29's public material against the
historical fingerprint sets of BOTH official predecessor sealed stores
(T27-STORE-01 and T28-STORE-01) inside each sealed boundary.  No private
predecessor rows may leave the oracle boundary; only aggregate hashes,
counts, and roots cross it.

Because T27's and T28's official evaluations never happened and never will,
the authenticated commitments are construction commitments plus OFFICIAL
EVALUATION ABSENCE:

- T27: UNSPENT_BUT_PERMANENTLY_INELIGIBLE / attempt 0 /
  PERMANENTLY_NOT_AUTHORIZED_FOR_T27 (frozen T28 preconstruction record).
- T28: UNSPENT_BUT_PERMANENTLY_INELIGIBLE / attempt 0 / PERMANENTLY_INELIGIBLE
  (T29 authorization §10).

The T27→T29 oracle reuses the frozen T28-era T27-side machinery
(``t27_protocol.t28_private_oracle``) unchanged, re-branded into a T29
result.  The T28→T29 oracle is metadata-only against the real sealed T28
store: ``t28_protocol``'s frozen store API refuses pre-ledger blind reads
and T28 will never hold an evaluation ledger, so authentication reads the
construction metadata byte-directly (verifying the §10 commitments), scans
the durable access journal for evaluation-surface operations (exactly zero),
and derives the historical fingerprints machine-only from the raw blind
bytes via the frozen ``t28_protocol.exclusion`` extractor.  The frozen
``T28PrivateStore`` API is never instantiated against the real store, so
the sealed store bytes — access journal included — stay bit-stable across
every oracle invocation; the module proves that stability by re-reading the
journal inside authentication and binding its SHA-256 into the result.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from t21_protocol.util import sha256_json

from .contract import (
    T27_CONSTRUCTION_ATTEMPT, T27_CONSTRUCTION_STATE,
    T27_OFFICIAL_EVALUATION_ATTEMPT, T27_OFFICIAL_EVALUATION_ELIGIBILITY,
    T27_OFFICIAL_EVALUATION_STATE,
    T28_CONSTRUCTION_ATTEMPT, T28_CONSTRUCTION_STATE,
    T28_OFFICIAL_EVALUATION_ATTEMPT, T28_OFFICIAL_EVALUATION_ELIGIBILITY,
    T28_OFFICIAL_EVALUATION_STATE,
)
from .exclusion import DIMENSIONS

# ------------------------------------------------------------------ identity
PREDECESSORS = ("t27", "t28")

ARTIFACT_T27 = "T27_TO_T29_OVERLAP_ORACLE_RESULT"
ARTIFACT_T28 = "T28_TO_T29_OVERLAP_ORACLE_RESULT"
REAL_SCHEMA_T27 = "t29-t27-sealed-overlap-oracle-result-v1"
REAL_SCHEMA_T28 = "t29-t28-sealed-overlap-oracle-result-v1"
SYNTHETIC_SCHEMA_T27 = "t29-t27-synthetic-overlap-oracle-result-v1"
SYNTHETIC_SCHEMA_T28 = "t29-t28-synthetic-overlap-oracle-result-v1"
SYNTHETIC_EVALUATION_STATE = "SYNTHETIC_SEALED_UNEVALUATED"
SEALED_ORACLE_T27 = (
    "t29_protocol.oracle:run_sealed_t27_to_t29_overlap_oracle")
SEALED_ORACLE_T28 = (
    "t29_protocol.oracle:run_sealed_t28_to_t29_overlap_oracle")
SYNTHETIC_ORACLE = "t29_protocol.oracle:synthetic_overlap_oracle"

_ARTIFACT = {"t27": ARTIFACT_T27, "t28": ARTIFACT_T28}
_REAL_SCHEMA = {"t27": REAL_SCHEMA_T27, "t28": REAL_SCHEMA_T28}
_SYNTHETIC_SCHEMA = {"t27": SYNTHETIC_SCHEMA_T27,
                     "t28": SYNTHETIC_SCHEMA_T28}
_SEALED_ORACLE = {"t27": SEALED_ORACLE_T27, "t28": SEALED_ORACLE_T28}
_SCOPE_OFFICIAL = {"t27": "OFFICIAL_T27", "t28": "OFFICIAL_T28"}

# ------------------------------------------------------------ T28 store paths
T28_STORE_ID = "T28-STORE-01"
T28_NAMESPACE = "t28"
T28_OFFICIAL_MANIFEST_PATH = "construction/manifest.json"
T28_OFFICIAL_SEAL_PATH = "construction/seal.json"
T28_OFFICIAL_CONSTRUCTION_LEDGER_PATH = "construction/ledger.json"
T28_OFFICIAL_CONSTRUCTION_MARKER_PATH = "markers/construction.one-shot"
T28_OFFICIAL_EVALUATION_MARKER_PATH = "markers/evaluation.one-shot"
# Official T28 evaluation absence: not one evaluation artifact may exist, on
# disk or anywhere in the durable access journal (T28 adjudication verdict).
T28_OFFICIAL_EVALUATION_ABSENCE_PATHS = (
    "evaluation/ledger.json", T28_OFFICIAL_EVALUATION_MARKER_PATH,
    "evaluation/raw_outputs.json", "evaluation/scored_rows.json",
    "evaluation/summary.json", "evaluation/one_shot_spent.json",
)
#: The only paths a construction-era ``write_once`` may have ever created.
_T28_SANCTIONED_WRITE_PATHS = (
    T28_OFFICIAL_MANIFEST_PATH, T28_OFFICIAL_SEAL_PATH,
    T28_OFFICIAL_CONSTRUCTION_LEDGER_PATH,
    T28_OFFICIAL_CONSTRUCTION_MARKER_PATH,
    "blind/inputs.json", "blind/gold.json",
    "construction/static_design_audit.json",
    "construction/author_provenance.json",
    "construction/t27_oracle_result.json",
    "construction/historical_exclusion_audit.json",
    "construction/audit.json", "construction/contract_audit.json",
    "construction/gate.json",
)

# ------------------------------------------------------------ result schemas
#: Commitment fields of exactly the frozen §10 predecessor bindings.
T27_COMMITMENT_FIELDS = (
    "t27_public_construction_commit", "t27_construction_ledger_sha256",
    "t27_construction_ledger_root", "t27_private_manifest_sha256",
    "t27_construction_seal_sha256", "t27_private_holdout_root",
)
T28_COMMITMENT_FIELDS = (
    "t28_public_construction_commit", "t28_construction_ledger_sha256",
    "t28_construction_ledger_root", "t28_private_manifest_sha256",
    "t28_construction_seal_sha256", "t28_private_holdout_root",
)
_COMMITMENT_FIELDS = {"t27": T27_COMMITMENT_FIELDS,
                      "t28": T28_COMMITMENT_FIELDS}
#: Predecessor-bound fields a synthetic oracle result must contain exactly.
_T27_FIELDS = (
    "t27_store_authenticated", "t27_store_identity", "t27_namespace",
    "t27_public_construction_commit", "t27_construction_ledger_sha256",
    "t27_construction_ledger_root", "t27_private_manifest_sha256",
    "t27_construction_seal_sha256", "t27_private_holdout_root",
    "t27_construction_state", "t27_construction_attempt",
    "t27_official_evaluation_state", "t27_official_evaluation_attempt",
    "t27_official_evaluation_eligibility",
    "t27_fingerprint_index_root", "t27_fingerprint_index_origin",
)
_T28_FIELDS = (
    "t28_store_authenticated", "t28_store_identity", "t28_namespace",
    "t28_public_construction_commit", "t28_construction_ledger_sha256",
    "t28_construction_ledger_root", "t28_private_manifest_sha256",
    "t28_construction_seal_sha256", "t28_private_holdout_root",
    "t28_construction_state", "t28_construction_attempt",
    "t28_official_evaluation_state", "t28_official_evaluation_attempt",
    "t28_official_evaluation_eligibility",
    "t28_fingerprint_index_root", "t28_fingerprint_index_origin",
)
_FIELDS_PER_PREDECESSOR = {"t27": _T27_FIELDS, "t28": _T28_FIELDS}
#: Extra fields that only authenticated (official or rehearsal) results carry.
_REAL_EXTRA_FIELDS = {
    "t27": ("t27_candidate_commit", "t27_candidate_runtime_root"),
    "t28": (
        "t28_candidate_commit", "t28_candidate_runtime_root",
        "t28_construction_marker_sha256", "t28_machine_only_blind_boundary",
        "t28_blind_inputs_sha256", "t28_blind_gold_sha256",
        "t28_blind_rows_deserialized_in_boundary",
        "t28_gold_rows_deserialized_in_boundary",
        "t28_access_journal_records",
        "t28_journal_evaluation_surface_operations",
        "t28_access_journal_sha256"),
}
_SHARED_FIELDS = (
    "schema_version", "artifact", "experiment", "mode",
    "official_commitment_scope", "oracle_implementation",
    "t29_prospective_fingerprint_root", "dimensions",
    "overall_prohibited_overlap", "oracle_execution_timestamp",
    "outside_boundary_private_rows_exposed", "result_sha256",
)
CONSTRUCTION_STATES = (
    "LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS", "MANIFESTED",
    "SEALED",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex(value: Any, length: int = 64) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def _hash_set(values: Any, name: str) -> set[str]:
    if not isinstance(values, list):
        raise ValueError(f"oracle dimension must be a hash list: {name}")
    for value in values:
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)):
            raise ValueError(f"oracle dimension must hold SHA-256 values: "
                             f"{name}")
    return {value.strip().lower() for value in values}


def _validate_sets(values: dict[str, list[str]], label: str) -> None:
    if not isinstance(values, dict) or set(values) != set(DIMENSIONS):
        raise ValueError(f"{label} requires all nine dimensions")
    for name in DIMENSIONS:
        _hash_set(values[name], name)


# --------------------------------------------------------- official commitments
def official_t28_commitments(root: Path) -> dict[str, str | int]:
    """Exact public anchors for the sealed official T28 store (T29 §10)."""
    from .historical_anchor import T28_SEALED_COMMITMENTS

    root = Path(root).resolve()
    commitment = json.loads(
        (root / "evaluations/t28/construction/"
         "T28_PUBLIC_CONSTRUCTION_COMMITMENT.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (root / "evaluations/t28/construction/"
         "T28_PUBLIC_CONSTRUCTION_RECEIPT.json").read_text(encoding="utf-8"))
    adjudication = json.loads(
        (root / "evaluations/t28/"
         "T28_OFFICIAL_EVALUATION_ELIGIBILITY_ADJUDICATION.json").read_text(
            encoding="utf-8"))
    roots = commitment.get("roots", {})
    if (commitment.get("state") != T28_CONSTRUCTION_STATE
            or commitment.get("attempt") != T28_CONSTRUCTION_ATTEMPT
            or receipt.get("state") != T28_CONSTRUCTION_STATE
            or receipt.get("attempt") != T28_CONSTRUCTION_ATTEMPT
            or receipt.get("construction_ledger_root")
            != roots.get("construction_ledger_root")
            or receipt.get("private_blind_root")
            != roots.get("private_blind_root")
            or receipt.get("private_artifact_root")
            != roots.get("private_artifact_root")
            or receipt.get("candidate_commit")
            != adjudication.get("candidate", {}).get("commit")
            or receipt.get("runtime_root")
            != adjudication.get("candidate", {}).get("runtime_root")):
        raise ValueError("official T28 public commitment anchors disagree")
    state = adjudication.get("construction_state") or {}
    if (state.get("construction_one_shot") != "SPENT"
            or state.get("construction_valid") is not True
            or state.get("construction_result_invalidated") is not False
            or adjudication.get("official_evaluation_eligibility")
            != "INELIGIBLE"
            or adjudication.get("official_evaluation_eligibility_state")
            != "PERMANENTLY_INELIGIBLE"
            or adjudication.get("evaluation_attempt_count") != 0
            or adjudication.get("capability_status") != "NOT_MEASURED"):
        raise ValueError("official T28 adjudication anchors disagree")
    observed = {
        "t28_public_construction_commit":
            adjudication["public_construction"]["commit"],
        "t28_construction_ledger_sha256":
            receipt["construction_ledger_sha256"],
        "t28_construction_ledger_root": receipt["construction_ledger_root"],
        "t28_private_manifest_sha256": receipt["manifest_sha256"],
        "t28_construction_seal_sha256": receipt["seal_sha256"],
        "t28_private_holdout_root": receipt["private_blind_root"],
    }
    for key, value in T28_SEALED_COMMITMENTS.items():
        if observed.get(key) != value:
            raise ValueError(
                "official T28 commitments disagree with the frozen §10 values")
    return {
        "t28_store_identity": T28_STORE_ID, "t28_namespace": "t28",
        **observed,
        "t28_candidate_commit": receipt["candidate_commit"],
        "t28_candidate_runtime_root": receipt["runtime_root"],
        "t28_construction_state": T28_CONSTRUCTION_STATE,
        "t28_construction_attempt": T28_CONSTRUCTION_ATTEMPT,
        "t28_official_evaluation_state": T28_OFFICIAL_EVALUATION_STATE,
        "t28_official_evaluation_attempt": T28_OFFICIAL_EVALUATION_ATTEMPT,
        "t28_official_evaluation_eligibility":
            T28_OFFICIAL_EVALUATION_ELIGIBILITY,
    }


def official_t27_commitments_for_t29(root: Path) -> dict[str, str | int]:
    """Frozen T27 commitments re-exposed through their canonical loader."""
    from t27_protocol.t28_private_oracle import official_t27_commitments

    return official_t27_commitments(Path(root).resolve())


# ----------------------------------------------------------- T28 journal scan
def _scan_t28_access_journal(records: list[dict[str, Any]],
                             ) -> dict[str, int]:
    """Structurally validate the durable journal; count evaluation-surface
    operations.  The scan is metadata-only: journal records carry paths,
    operations, and booleans, never row payloads.  Every record that touches
    an official T28 evaluation surface must be a ``has`` existence probe
    answering ``exists: false``; blind surfaces may only ever be hashed
    machine-only after their single materialization write, never structurally
    read; and every construction-era write must have landed on the sanctioned
    construction path closure."""
    surface_operations = 0
    prior_seq = 0
    for record in records:
        if (not isinstance(record, dict)
                or not {"seq", "op", "path", "store"} <= set(record)
                or set(record) - {"seq", "op", "path", "store", "timestamp",
                                  "exists", "bytes"}):
            raise ValueError("T28 access journal record is malformed")
        if record["store"] != T28_STORE_ID:
            raise ValueError("T28 access journal names a foreign store")
        if record["op"] not in ("has", "write_once", "machine_only_blind_hash",
                                "replace_ledger", "read_bytes", "read_json"):
            raise ValueError("T28 access journal holds an unknown operation")
        if not isinstance(record["seq"], int) or record["seq"] != prior_seq + 1:
            raise ValueError("T28 access journal sequence is not dense")
        prior_seq = record["seq"]
        path = record["path"]
        op = record["op"]
        if path.startswith("evaluation/") or path.startswith(
                "markers/evaluation"):
            if op != "has" or record.get("exists") is not False:
                surface_operations += 1
        elif op in {"read_bytes", "read_json"} and path.startswith("blind/"):
            surface_operations += 1
        if op == "write_once":
            if (path not in _T28_SANCTIONED_WRITE_PATHS
                    and not path.startswith("construction/events/")):
                surface_operations += 1
        elif op == "replace_ledger" and path != \
                T28_OFFICIAL_CONSTRUCTION_LEDGER_PATH:
            surface_operations += 1
    return {
        "access_journal_records": prior_seq,
        "journal_evaluation_surface_operations": surface_operations,
        "journal_evaluation_absence_probes": sum(
            1 for record in records
            if record["path"].startswith("evaluation/")
            or record["path"].startswith("markers/evaluation")),
    }


def _verify_t28_construction_ledger(ledger: dict[str, Any]) -> None:
    """Six-event SEALED/1 construction chain, marker-bound, experiment t28."""
    events = ledger.get("events") or []
    bindings = ledger.get("bindings") or {}
    if (ledger.get("state") != T28_CONSTRUCTION_STATE
            or bindings.get("experiment") != "t28"
            or bindings.get("attempt") != 1
            or bindings.get("mode") != "REAL_BLIND"
            or bindings.get("store_id") != T28_STORE_ID
            or bindings.get("namespace") != "t28"
            or len(events) != len(CONSTRUCTION_STATES)):
        raise ValueError("T28 construction ledger bindings are not SEALED/1")
    previous: str | None = None
    for number, event in enumerate(events):
        if (event.get("event_index") != number
                or event.get("event_type") != CONSTRUCTION_STATES[number]):
            raise ValueError("T28 construction ledger chain is broken")
        if event.get("event_hash") != sha256_json(
                {key: value for key, value in event.items()
                 if key != "event_hash"}):
            raise ValueError("T28 construction event hash mismatch")
        if number > 0 and event.get("previous_event_hash") != previous:
            raise ValueError("T28 construction ledger chain is broken")
        previous = event["event_hash"]
    if (ledger.get("final_event_hash") != previous
            or ledger.get("ledger_root") != sha256_json(
                {"bindings": bindings, "events": events})):
        raise ValueError("T28 construction ledger root mismatch")


# --------------------------------------------- T28 metadata-only authentication
def authenticate_official_t28_store_for_t29(
        root: Path, store_root: Path, *,
        expected: dict[str, str | int] | None = None) -> tuple[
        dict[str, Any], dict[str, Any]]:
    """Metadata-only, byte-direct authentication of the official T28 store.

    Verifies the store identity, the §10 ledger/manifest/seal SHA-256 byte
    commitments, the six-event SEALED/1 construction chain, the bindings-
    bound spent construction one-shot marker, official commitment equality,
    and OFFICIAL EVALUATION ABSENCE (on disk and in the durable access
    journal).  Blind bodies are only byte-hashed after their integrity is
    bound through the authenticated manifest; they are never decoded here.
    Returns ``(report, boundary_payload)`` where ``report`` is the
    PUBLIC_SAFE authentication evidence and ``boundary_payload`` carries the
    raw blind bytes consumed by the machine-only fingerprint derivation; no
    private row content may leave the caller's boundary dictionary.
    """
    root = Path(root).resolve()
    store_root = Path(store_root)
    if store_root.name != T28_STORE_ID:
        raise ValueError("wrong T28 sealed store identity")
    namespace = store_root / T28_NAMESPACE
    if expected is None:
        expected = official_t28_commitments(root)
        scope = "OFFICIAL_T28"
    else:
        scope = "DISPOSABLE_STANDIN"
    journal_bytes = (namespace / "access_journal.jsonl").read_bytes()
    journal_sha = _sha(journal_bytes)
    records = [json.loads(line) for line in journal_bytes.splitlines()
               if line.strip()]
    counters = _scan_t28_access_journal(records)
    if counters["journal_evaluation_surface_operations"] != 0:
        raise ValueError("T28 access journal holds evaluation-surface "
                         "operations; the official T28 store must be "
                         "permanently unevaluated")
    for path in T28_OFFICIAL_EVALUATION_ABSENCE_PATHS:
        if namespace.joinpath(*path.split("/")).exists():
            raise ValueError("T28 official evaluation artifacts exist; the "
                             "oracle requires the sealed T28 store to be "
                             "permanently unevaluated")
    manifest_bytes = (namespace / T28_OFFICIAL_MANIFEST_PATH).read_bytes()
    seal_bytes = (namespace / T28_OFFICIAL_SEAL_PATH).read_bytes()
    ledger_bytes = (namespace /
                    T28_OFFICIAL_CONSTRUCTION_LEDGER_PATH).read_bytes()
    marker_bytes = (namespace /
                    T28_OFFICIAL_CONSTRUCTION_MARKER_PATH).read_bytes()
    blind_inputs_bytes = (namespace / "blind/inputs.json").read_bytes()
    blind_gold_bytes = (namespace / "blind/gold.json").read_bytes()
    manifest_sha = _sha(manifest_bytes)
    ledger_sha = _sha(ledger_bytes)
    seal_sha = _sha(seal_bytes)
    marker_sha = _sha(marker_bytes)
    blind_inputs_sha = _sha(blind_inputs_bytes)
    blind_gold_sha = _sha(blind_gold_bytes)
    if (manifest_sha != expected["t28_private_manifest_sha256"]
            or ledger_sha != expected["t28_construction_ledger_sha256"]
            or seal_sha != expected["t28_construction_seal_sha256"]):
        raise ValueError("T28 sealed metadata does not match the official "
                         "commitments")
    manifest = json.loads(manifest_bytes)
    seal = json.loads(seal_bytes)
    ledger = json.loads(ledger_bytes)
    marker = json.loads(marker_bytes)
    bindings = ledger.get("bindings") or {}
    if ledger.get("ledger_root") != expected["t28_construction_ledger_root"]:
        raise ValueError("T28 construction ledger root commitment mismatch")
    if (manifest.get("private_blind_root")
            != expected["t28_private_holdout_root"]
            or seal.get("manifest_sha256") != manifest_sha
            or seal.get("private_blind_root")
            != expected["t28_private_holdout_root"]
            or seal.get("private_artifact_root")
            != manifest.get("private_artifact_root")
            or seal.get("state") != T28_CONSTRUCTION_STATE
            or seal.get("attempt") != T28_CONSTRUCTION_ATTEMPT):
        raise ValueError("T28 sealed construction state authentication failed")
    _verify_t28_construction_ledger(ledger)
    for path, digest in (("blind/inputs.json", blind_inputs_sha),
                         ("blind/gold.json", blind_gold_sha)):
        entry = next((item for item in manifest.get("artifacts", [])
                      if isinstance(item, dict) and item.get("path") == path),
                     None)
        if entry is None or entry.get("sha256") != digest:
            raise ValueError(f"T28 manifest does not bind {path}")
    genesis_matches = (marker.get("genesis_event_hash")
                       == (ledger.get("events") or [{}])[0].get("event_hash"))
    if (marker.get("schema_version") != "t28-construction-one-shot-v1"
            or marker.get("artifact") != "T28_CONSTRUCTION_ONE_SHOT_SPENT"
            or marker.get("spent") is not True
            or marker.get("bindings_sha256") != sha256_json(bindings)
            or not genesis_matches):
        raise ValueError("T28 official construction marker authentication "
                         "failed")
    if (namespace / "access_journal.jsonl").read_bytes() != journal_bytes:
        raise ValueError("T28 access journal mutated during authentication")
    report: dict[str, Any] = {
        "schema_version": "t29-t28-official-store-metadata-authentication-v1",
        "artifact": "T29_T28_OFFICIAL_STORE_METADATA_AUTHENTICATION",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "oracle_implementation": (
            "t29_protocol.oracle:authenticate_official_t28_store_for_t29"),
        "official_commitment_scope": scope,
        "t28_store_authenticated": True,
        "t28_official_commitments_exact": scope == "OFFICIAL_T28",
        "t28_store_identity": T28_STORE_ID, "t28_namespace": "t28",
        "t28_artifact_count": len(manifest.get("artifacts", [])),
        "t28_private_holdout_root": manifest["private_blind_root"],
        "t28_construction_ledger_sha256": ledger_sha,
        "t28_construction_ledger_root": ledger["ledger_root"],
        "t28_private_manifest_sha256": manifest_sha,
        "t28_construction_seal_sha256": seal_sha,
        "t28_public_construction_commit": expected[
            "t28_public_construction_commit"],
        "t28_candidate_commit": bindings.get("candidate_commit"),
        "t28_candidate_runtime_root": bindings.get("runtime_root"),
        "t28_construction_state": T28_CONSTRUCTION_STATE,
        "t28_construction_attempt": T28_CONSTRUCTION_ATTEMPT,
        "t28_construction_event_count": len(CONSTRUCTION_STATES),
        "t28_evaluation_event_count": 0,
        "t28_official_evaluation_state": T28_OFFICIAL_EVALUATION_STATE,
        "t28_official_evaluation_attempt": T28_OFFICIAL_EVALUATION_ATTEMPT,
        "t28_official_evaluation_eligibility":
            T28_OFFICIAL_EVALUATION_ELIGIBILITY,
        "t28_official_evaluation_artifacts_absent": True,
        "t28_construction_marker_path": T28_OFFICIAL_CONSTRUCTION_MARKER_PATH,
        "t28_construction_marker_committed": True,
        "t28_construction_marker_schema": marker["schema_version"],
        "t28_construction_marker_artifact": marker["artifact"],
        "t28_construction_marker_spent": True,
        "t28_construction_marker_sha256": marker_sha,
        "t28_construction_marker_genesis_matches_ledger": genesis_matches,
        "t28_machine_only_blind_boundary": True,
        "t28_blind_inputs_sha256": blind_inputs_sha,
        "t28_blind_gold_sha256": blind_gold_sha,
        "t28_blind_rows_deserialized_in_authentication": 0,
        "t28_gold_rows_deserialized_in_authentication": 0,
        "t28_access_journal_records": counters["access_journal_records"],
        "t28_journal_evaluation_surface_operations": counters[
            "journal_evaluation_surface_operations"],
        "t28_journal_evaluation_absence_probes": counters[
            "journal_evaluation_absence_probes"],
        "t28_access_journal_sha256": journal_sha,
        "t28_private_rows_read": 0, "t28_gold_rows_read": 0,
        "t28_raw_output_rows_read": 0, "t28_scored_rows_read": 0,
        "t28_candidate_reruns": 0,
        "outside_boundary_private_rows_exposed": 0,
    }
    return (report, {
        "blind_inputs_bytes": blind_inputs_bytes,
        "blind_gold_bytes": blind_gold_bytes,
        "ledger_bindings": bindings,
    })


def _populated_row_list(document: Any, label: str) -> int:
    """Machine-only structural count of a blind row list (rows stay here)."""
    if not isinstance(document, list) or not document:
        raise ValueError(f"T28 blind {label} bundle is not a populated list")
    if not all(isinstance(row, dict) for row in document):
        raise ValueError(f"T28 blind {label} bundle holds non-object rows")
    return len(document)


# -------------------------------------------------- T28 fingerprint derivation
def derive_t28_historical_fingerprints(
        blind_inputs_bytes: bytes, blind_gold_bytes: bytes, *,
        blind_inputs_sha256: str, blind_gold_sha256: str
        ) -> tuple[dict[str, list[str]], str, int, int]:
    """Machine-only T28 fingerprint derivation inside the sealed boundary.

    Both blind documents are hashed and structurally parsed from the same
    raw bytes read once; the frozen ``t28_protocol.exclusion`` extractor
    runs on the parsed structures and only the aggregate fingerprint sets
    (SHA-256 value lists) ever leave this call.  No private row value is
    returned, logged, or exposed outside this boundary.
    """
    from t28_protocol.exclusion import observed_bundle_fingerprints

    if _sha(blind_inputs_bytes) != blind_inputs_sha256:
        raise ValueError("T28 blind inputs bytes are not manifest-authentic")
    if _sha(blind_gold_bytes) != blind_gold_sha256:
        raise ValueError("T28 blind gold bytes are not manifest-authentic")
    cases = json.loads(blind_inputs_bytes)
    gold = json.loads(blind_gold_bytes)
    case_rows = _populated_row_list(cases, "inputs")
    gold_rows = _populated_row_list(gold, "gold")
    if case_rows != gold_rows:
        raise ValueError("T28 blind bundle populations are not aligned")
    observed = observed_bundle_fingerprints(cases, gold, [])
    dimensions = {name: sorted(_hash_set(observed[name], name))
                  for name in DIMENSIONS}
    return dimensions, sha256_json(dimensions), case_rows, gold_rows


# --------------------------------------------------------------- result build
def build_oracle_result(*, predecessor: str, prospective_root: str,
                        prospective: dict[str, list[str]],
                        historical: dict[str, list[str]],
                        bindings: dict[str, Any], mode: str, scope: str,
                        implementation: str, store_authenticated: bool,
                        index_root: str, index_origin: str,
                        timestamp: str | None = None) -> dict[str, Any]:
    if predecessor not in PREDECESSORS:
        raise ValueError("unknown predecessor for the T29 dual oracle")
    if mode not in {"REAL_SEALED", "SYNTHETIC_DISPOSABLE"}:
        raise ValueError("unknown T29 oracle result mode")
    if not isinstance(prospective_root, str) or len(prospective_root) != 64:
        raise ValueError("prospective fingerprint root invalid")
    _validate_sets(prospective, "prospective oracle input")
    _validate_sets(historical, "historical oracle index")
    if sha256_json({name: sorted(set(prospective[name]))
                    for name in DIMENSIONS}) != prospective_root:
        raise ValueError("prospective fingerprint root does not bind the "
                         "supplied hashes")
    dimensions: dict[str, Any] = {}
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
        "schema_version": (
            _REAL_SCHEMA[predecessor] if mode == "REAL_SEALED"
            else _SYNTHETIC_SCHEMA[predecessor]),
        "artifact": _ARTIFACT[predecessor], "experiment": "t29",
        "mode": mode, "official_commitment_scope": scope,
        "oracle_implementation": implementation,
        f"{predecessor}_store_authenticated": store_authenticated,
        **bindings,
        f"{predecessor}_fingerprint_index_root": index_root,
        f"{predecessor}_fingerprint_index_origin": index_origin,
        "t29_prospective_fingerprint_root": prospective_root,
        "dimensions": dimensions,
        "overall_prohibited_overlap": total,
        "oracle_execution_timestamp": timestamp or _now(),
        "outside_boundary_private_rows_exposed": 0,
    }
    return {**core, "result_sha256": sha256_json(core)}


# ------------------------------------------------------------- T27 real runner
def run_sealed_t27_to_t29_overlap_oracle(
        *, root: Path, store_root: Path, prospective_root: str,
        prospective: dict[str, list[str]], timestamp: str | None = None
        ) -> dict[str, Any]:
    """Production T27→T29 entrypoint; caller-supplied commitments are not
    accepted.  The frozen T27-side machinery authenticates the official
    sealed T27 store metadata-only and derives the historical fingerprints
    machine-only; only aggregate hash sets cross the boundary."""
    from t27_protocol.store import T27PrivateStore
    from t27_protocol.t28_private_oracle import (
        STORE_ID, _authenticate_store, _load_or_derive_index,
    )

    root = Path(root).resolve()
    if store_root.name != STORE_ID:
        raise ValueError("wrong T27 sealed store identity")
    expected = official_t27_commitments_for_t29(root)
    store = T27PrivateStore(Path(store_root), repository_root=root)
    authentication = _authenticate_store(store, expected)
    historical, index_root, index_origin = _load_or_derive_index(store)
    keys = ("t27_store_identity", "t27_namespace", "t27_private_holdout_root",
            "t27_construction_ledger_sha256", "t27_construction_ledger_root",
            "t27_private_manifest_sha256", "t27_construction_seal_sha256",
            "t27_public_construction_commit", "t27_candidate_commit",
            "t27_candidate_runtime_root", "t27_construction_state",
            "t27_construction_attempt", "t27_official_evaluation_state",
            "t27_official_evaluation_attempt",
            "t27_official_evaluation_eligibility")
    bindings = {key: authentication[key] for key in keys}
    return build_oracle_result(
        predecessor="t27", prospective_root=prospective_root,
        prospective=prospective, historical=historical, bindings=bindings,
        mode="REAL_SEALED", scope="OFFICIAL_T27",
        implementation=SEALED_ORACLE_T27, store_authenticated=True,
        index_root=index_root, index_origin=index_origin,
        timestamp=timestamp)


# ------------------------------------------------------------- T28 real runner
def run_sealed_t28_to_t29_overlap_oracle(
        *, root: Path, store_root: Path, prospective_root: str,
        prospective: dict[str, list[str]], timestamp: str | None = None
        ) -> dict[str, Any]:
    """Production T28→T29 entrypoint; caller-supplied commitments are not
    accepted.  The official sealed T28 store is authenticated metadata-only
    (byte-direct §10 commitments plus a zero-evaluation-surface journal
    scan) and the historical fingerprints are derived machine-only from the
    sealed blind bytes with the frozen ``t28_protocol.exclusion`` extractor;
    no private T28 row value ever leaves the oracle boundary."""
    authentication, payload = authenticate_official_t28_store_for_t29(
        Path(root).resolve(), Path(store_root), expected=None)
    historical, index_root, inputs_rows, gold_rows = \
        derive_t28_historical_fingerprints(
            payload["blind_inputs_bytes"], payload["blind_gold_bytes"],
            blind_inputs_sha256=authentication["t28_blind_inputs_sha256"],
            blind_gold_sha256=authentication["t28_blind_gold_sha256"])
    keys = ("t28_store_identity", "t28_namespace", "t28_private_holdout_root",
            "t28_construction_ledger_sha256", "t28_construction_ledger_root",
            "t28_private_manifest_sha256", "t28_construction_seal_sha256",
            "t28_public_construction_commit", "t28_candidate_commit",
            "t28_candidate_runtime_root", "t28_construction_state",
            "t28_construction_attempt", "t28_official_evaluation_state",
            "t28_official_evaluation_attempt",
            "t28_official_evaluation_eligibility",
            "t28_construction_marker_sha256",
            "t28_machine_only_blind_boundary", "t28_blind_inputs_sha256",
            "t28_blind_gold_sha256", "t28_blind_rows_deserialized_in_boundary",
            "t28_gold_rows_deserialized_in_boundary",
            "t28_access_journal_records",
            "t28_journal_evaluation_surface_operations",
            "t28_access_journal_sha256")
    authentication["t28_blind_rows_deserialized_in_boundary"] = inputs_rows
    authentication["t28_gold_rows_deserialized_in_boundary"] = gold_rows
    bindings = {key: authentication[key] for key in keys}
    return build_oracle_result(
        predecessor="t28", prospective_root=prospective_root,
        prospective=prospective, historical=historical, bindings=bindings,
        mode="REAL_SEALED", scope=authentication["official_commitment_scope"],
        implementation=SEALED_ORACLE_T28, store_authenticated=True,
        index_root=index_root,
        index_origin="DERIVED_MACHINE_ONLY_FROM_SEALED_BLIND_BYTES",
        timestamp=timestamp)


# ------------------------------------------------------------- synthetic side
def synthetic_overlap_oracle(*, predecessor: str, prospective_root: str,
                             prospective: dict[str, list[str]],
                             sealed_historical: dict[str, list[str]],
                             predecessor_bindings: dict[str, str],
                             timestamp: str | None = None
                             ) -> dict[str, Any]:
    """Disposable explicit-synthetic oracle compatibility helper; production
    real mode rejects it.  ``predecessor_bindings`` must carry exactly the
    six frozen predecessor commitment fields."""
    if predecessor not in PREDECESSORS:
        raise ValueError("unknown predecessor for the T29 dual oracle")
    required = set(_COMMITMENT_FIELDS[predecessor])
    if not isinstance(predecessor_bindings, dict) \
            or set(predecessor_bindings) != required:
        raise ValueError(f"synthetic {predecessor} bindings incomplete")
    bindings: dict[str, Any] = {
        f"{predecessor}_store_identity":
            f"SYNTHETIC-{predecessor.upper()}-STORE",
        f"{predecessor}_namespace": f"{predecessor}-synthetic",
        **predecessor_bindings,
        f"{predecessor}_construction_state": "SEALED",
        f"{predecessor}_construction_attempt": 1,
        f"{predecessor}_official_evaluation_state":
            SYNTHETIC_EVALUATION_STATE,
        f"{predecessor}_official_evaluation_attempt": 0,
        f"{predecessor}_official_evaluation_eligibility":
            T27_OFFICIAL_EVALUATION_ELIGIBILITY
            if predecessor == "t27"
            else T28_OFFICIAL_EVALUATION_ELIGIBILITY,
    }
    historical = {name: sorted(_hash_set(sealed_historical[name], name))
                  for name in DIMENSIONS}
    return build_oracle_result(
        predecessor=predecessor, prospective_root=prospective_root,
        prospective=prospective, historical=historical, bindings=bindings,
        mode="SYNTHETIC_DISPOSABLE", scope="SYNTHETIC_DISPOSABLE",
        implementation=SYNTHETIC_ORACLE, store_authenticated=False,
        index_root=sha256_json(
            {name: sorted(set(sealed_historical[name]))
             for name in DIMENSIONS}),
        index_origin="SYNTHETIC_EXPLICIT", timestamp=timestamp)


# ---------------------------------------------------------------- verification
def _validate_absence_bindings(result: dict[str, Any], predecessor: str,
                               synthetic: bool) -> None:
    """Fail-closed predecessor construction/evaluation terminal bindings."""
    expected_states = {
        "t27": (T27_CONSTRUCTION_STATE, T27_OFFICIAL_EVALUATION_STATE,
                T27_OFFICIAL_EVALUATION_ELIGIBILITY),
        "t28": (T28_CONSTRUCTION_STATE, T28_OFFICIAL_EVALUATION_STATE,
                T28_OFFICIAL_EVALUATION_ELIGIBILITY),
    }[predecessor]
    construction_state, evaluation_state, eligibility = expected_states
    prefix = f"{predecessor}_"
    if (result[prefix + "construction_state"] != construction_state
            or result[prefix + "construction_attempt"] != 1):
        raise ValueError(f"{predecessor.upper()} construction must be "
                         "authenticated SEALED/1")
    state = result[prefix + "official_evaluation_state"]
    attempt = result[prefix + "official_evaluation_attempt"]
    eligibility_value = result[prefix + "official_evaluation_eligibility"]
    if synthetic:
        if state != SYNTHETIC_EVALUATION_STATE or attempt != 0:
            raise ValueError("synthetic oracle must bind the disposable "
                             "unevaluated state")
        if eligibility_value != eligibility:
            raise ValueError(f"synthetic {predecessor} eligibility binding "
                             "is unknown")
    elif (state != evaluation_state or attempt != 0
            or eligibility_value != eligibility):
        raise ValueError(f"{predecessor.upper()} official evaluation must be "
                         "authenticated UNSPENT_BUT_PERMANENTLY_INELIGIBLE "
                         "(attempt 0, permanently ineligible)")


_T28_BOUNDARY_HASH_FIELDS = (
    "t28_construction_marker_sha256", "t28_blind_inputs_sha256",
    "t28_blind_gold_sha256", "t28_access_journal_sha256",
)


def _validate_field_types(result: dict[str, Any], predecessor: str,
                          mode: str) -> None:
    """Type-exact validation of every predecessor-bound field."""
    prefix = f"{predecessor}_"
    commit_fields = {prefix + "public_construction_commit"}
    sha_fields = {
        prefix + "construction_ledger_sha256",
        prefix + "construction_ledger_root",
        prefix + "private_manifest_sha256", prefix + "construction_seal_sha256",
        prefix + "private_holdout_root", prefix + "fingerprint_index_root",
        "t29_prospective_fingerprint_root",
    }
    counter_fields = {prefix + "construction_attempt",
                      prefix + "official_evaluation_attempt"}
    bool_fields = {prefix + "store_authenticated"}
    if mode in {"REAL", "REAL_REHEARSAL"}:
        commit_fields |= {prefix + "candidate_commit"}
        sha_fields |= {prefix + "candidate_runtime_root"}
        if predecessor == "t28":
            sha_fields |= set(_T28_BOUNDARY_HASH_FIELDS)
            counter_fields |= {"t28_blind_rows_deserialized_in_boundary",
                               "t28_gold_rows_deserialized_in_boundary",
                               "t28_access_journal_records",
                               "t28_journal_evaluation_surface_operations"}
            bool_fields |= {"t28_machine_only_blind_boundary"}
    unknown = set(result) - set(_SHARED_FIELDS)
    for key in unknown:
        value = result[key]
        if key in commit_fields:
            if (not isinstance(value, str) or len(value) != 40
                    or any(char not in "0123456789abcdef" for char in value)):
                raise ValueError(f"invalid oracle identity binding: {key}")
        elif key in sha_fields:
            if not _hex(value):
                raise ValueError(f"invalid oracle binding: {key}")
        elif key in bool_fields:
            if not isinstance(value, bool):
                raise ValueError(f"invalid oracle binding: {key}")
        elif key in counter_fields:
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"invalid oracle binding: {key}")
        elif not isinstance(value, str) or not value:
            raise ValueError(f"invalid oracle binding: {key}")


def verify_oracle_result(result: dict[str, Any], *, predecessor: str,
                         mode: str = "SYNTHETIC", root: Path | None = None,
                         expected_t29_root: str | None = None,
                         expected_predecessor_bindings: dict[str, Any]
                         | None = None) -> dict[str, Any]:
    """Verify the exact schema, mode, identities, roots, and zero overlap."""
    if predecessor not in PREDECESSORS:
        raise ValueError("unknown predecessor for the T29 dual oracle")
    if mode not in {"REAL", "REAL_REHEARSAL", "SYNTHETIC"}:
        raise ValueError(f"unknown T29 {predecessor} oracle verification "
                         "mode")
    prefix = f"{predecessor}_"
    required: set[str] = set(_SHARED_FIELDS) | set(
        _FIELDS_PER_PREDECESSOR[predecessor]
        + (_REAL_EXTRA_FIELDS[predecessor]
           if mode in {"REAL", "REAL_REHEARSAL"} else ()))
    if not isinstance(result, dict) or set(result) != required:
        raise ValueError(f"T29 {predecessor} oracle result has unknown or "
                         "absent fields")
    if (result["artifact"] != _ARTIFACT[predecessor]
            or result["experiment"] != "t29"):
        raise ValueError(f"T29 {predecessor} oracle result identity mismatch")
    commitments_exact = False
    if mode == "REAL":
        if root is None:
            raise ValueError("real oracle verification requires repository "
                             "root")
        resolve = Path(root).resolve()
        if predecessor == "t27":
            from t27_protocol.t28_private_oracle import \
                official_t27_commitments as _official_commitments
        else:
            _official_commitments = official_t28_commitments
        expected = _official_commitments(resolve)
        if (result["schema_version"] != _REAL_SCHEMA[predecessor]
                or result["mode"] != "REAL_SEALED"
                or result["official_commitment_scope"]
                != _SCOPE_OFFICIAL[predecessor]
                or result["oracle_implementation"]
                != _SEALED_ORACLE[predecessor]
                or result[prefix + "store_authenticated"] is not True):
            raise ValueError(
                f"real construction requires an authenticated sealed "
                f"{predecessor.upper()} oracle")
        commitments_exact = all(result.get(key) == expected[key]
                                for key in expected)
        if not commitments_exact:
            raise ValueError(f"real {predecessor.upper()} oracle commitments "
                             "are not exact official values")
    elif mode == "REAL_REHEARSAL":
        if (result["schema_version"] != _REAL_SCHEMA[predecessor]
                or result["mode"] != "REAL_SEALED"
                or result["official_commitment_scope"] != "DISPOSABLE_STANDIN"
                or result["oracle_implementation"]
                != _SEALED_ORACLE[predecessor]
                or result[prefix + "store_authenticated"] is not True):
            raise ValueError("real-mode oracle rehearsal is not "
                             "store-authenticated")
        if expected_predecessor_bindings is not None:
            commitments_exact = all(
                result.get(key) == value
                for key, value in expected_predecessor_bindings.items())
            if not commitments_exact:
                raise ValueError(f"rehearsal {predecessor.upper()} "
                                 "commitments are not exact")
        else:
            commitments_exact = True
    elif mode == "SYNTHETIC":
        if (result["schema_version"] != _SYNTHETIC_SCHEMA[predecessor]
                or result["mode"] != "SYNTHETIC_DISPOSABLE"
                or result["official_commitment_scope"]
                != "SYNTHETIC_DISPOSABLE"
                or result["oracle_implementation"] != SYNTHETIC_ORACLE
                or result[prefix + "store_authenticated"] is not False):
            raise ValueError("synthetic oracle must use an explicit "
                             "disposable schema")
        if (result[prefix + "official_evaluation_state"]
                != SYNTHETIC_EVALUATION_STATE):
            raise ValueError("synthetic oracle must bind the disposable "
                             "state")
    _validate_field_types(result, predecessor, mode)
    if (expected_t29_root is not None
            and result["t29_prospective_fingerprint_root"]
            != expected_t29_root):
        raise ValueError("oracle prospective T29 root mismatch")
    if mode in {"REAL", "REAL_REHEARSAL"}:
        identity_expected = {"t27": "T27-STORE-01",
                             "t28": "T28-STORE-01"}[predecessor]
        namespace_expected = predecessor
    else:
        identity_expected = f"SYNTHETIC-{predecessor.upper()}-STORE"
        namespace_expected = f"{predecessor}-synthetic"
    if (result[prefix + "store_identity"] != identity_expected
            or result[prefix + "namespace"] != namespace_expected):
        raise ValueError(f"oracle store identity invalid for "
                         f"{predecessor.upper()}")
    if predecessor == "t28" and mode in {"REAL", "REAL_REHEARSAL"}:
        if result["t28_machine_only_blind_boundary"] is not True:
            raise ValueError("T28 oracle must bind the machine-only blind "
                             "boundary")
        if result["t28_journal_evaluation_surface_operations"] != 0:
            raise ValueError("T28 store journal shows evaluation-surface "
                             "operations")
        if result["t28_blind_rows_deserialized_in_boundary"] <= 0:
            raise ValueError("T28 oracle did not derive fingerprints "
                             "machine-only from the sealed blind bytes")
    if not isinstance(result["dimensions"], dict) or set(
            result["dimensions"]) != set(DIMENSIONS):
        raise ValueError("oracle must bind all nine exclusion dimensions")
    total = 0
    for name in DIMENSIONS:
        entry = result["dimensions"][name]
        if not isinstance(entry, dict) or set(entry) != {
            "applicable", "prospective_population", "historical_population",
            "overlap_count",
        }:
            raise ValueError(f"oracle dimension binding mismatch: {name}")
        if not isinstance(entry["applicable"], bool):
            raise ValueError(f"oracle applicability invalid: {name}")
        for field in ("prospective_population", "historical_population",
                      "overlap_count"):
            if not isinstance(entry[field], int) or entry[field] < 0:
                raise ValueError(f"oracle population invalid: "
                                 f"{name}.{field}")
        if entry["applicable"] and entry["prospective_population"] == 0:
            raise ValueError(f"applicable oracle dimension is empty: {name}")
        total += entry["overlap_count"]
    if total != 0 or result["overall_prohibited_overlap"] != 0:
        raise ValueError(f"{predecessor.upper()}-to-T29 prohibited overlap "
                         "is nonzero")
    if result["outside_boundary_private_rows_exposed"] != 0:
        raise ValueError(f"{predecessor.upper()} oracle exposed private rows "
                         "outside the sealed boundary")
    _validate_absence_bindings(result, predecessor,
                               synthetic=mode == "SYNTHETIC")
    expected_hash = sha256_json({key: value for key, value in result.items()
                                 if key != "result_sha256"})
    if result["result_sha256"] != expected_hash:
        raise ValueError(f"T29 {predecessor} oracle result hash mismatch")
    return {
        "status": "PASS", "predecessor": predecessor, "mode": mode,
        "dimension_count": len(DIMENSIONS),
        "overall_prohibited_overlap": 0,
        "result_sha256": result["result_sha256"],
        f"{predecessor}_store_authenticated":
            result[prefix + "store_authenticated"],
        f"{predecessor}_commitments_exact": commitments_exact,
        f"{predecessor}_construction_state":
            result[prefix + "construction_state"],
        f"{predecessor}_evaluation_absence_authenticated": True,
        f"{predecessor}_private_rows_exposed_to_t29": 0,
        "outside_boundary_private_rows_exposed": 0,
    }


# ------------------------------------------------------ disposable T28 stand-in
def disposable_t28_sealed_store(
        parent: Path, *, variant: int = 0
        ) -> tuple[Path, dict[str, str | int]]:
    """Disposable stand-in mirroring the official sealed T28 store layout.

    Built by plain deterministic writes (the frozen ``T28PrivateStore`` API
    is deliberately not instantiated), mirroring the official logical paths,
    the six-event construction-ledger chain, the bindings-bound construction
    marker, the evaluation-absence surface, and the durable access journal
    shape so the production T28→T29 metadata authentication semantics are
    exercised exactly.
    """
    parent = Path(parent)
    namespace = parent / T28_STORE_ID / T28_NAMESPACE
    (namespace / "construction/events").mkdir(parents=True, exist_ok=True)
    (namespace / "blind").mkdir(parents=True, exist_ok=True)
    (namespace / "markers").mkdir(parents=True, exist_ok=True)
    journal: list[dict[str, Any]] = []

    def record(op: str, path: str, *, exists: bool | None = None,
               bytes_written: int | None = None) -> None:
        entry = {"seq": len(journal) + 1, "op": op, "path": path,
                 "store": T28_STORE_ID,
                 "timestamp": f"2026-09-29T02:00:00+00:00"}
        if exists is not None:
            entry["exists"] = exists
        if bytes_written is not None:
            entry["bytes"] = bytes_written
        journal.append(entry)

    cases = [
        {"scenario_id": f"t28-standin-{variant}-{index}",
         "plan": {"goal": f"t28 standin goal {variant} {index}",
                  "steps": [{"step_id": f"step-{index}-{number}",
                             "input": f"standin input {variant} {index} "
                                      f"{number}", "action": "verify"}
                            for number in range(2)]}}
        for index in (0, 1)]
    gold = [{"expected_answer": f"t28 standin answer {variant} {index}"}
            for index in (0, 1)]

    def write_once(path: str, document: dict[str, Any],
                   classification: str) -> str:
        payload = json.dumps(
            document, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True).encode("utf-8")
        record("has", path, exists=False)
        record("write_once", path, bytes_written=len(payload))
        (namespace / "/".join(path.split("/"))).write_bytes(payload)
        return _sha(payload)

    blind_inputs_payload = json.dumps(
        cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
    blind_gold_payload = json.dumps(
        gold, sort_keys=True, separators=(",", ":")).encode("utf-8")
    blind_inputs_sha = _sha(blind_inputs_payload)
    blind_gold_sha = _sha(blind_gold_payload)
    holdout_root = sha256_json({"blind_inputs_sha256": blind_inputs_sha,
                                "blind_gold_sha256": blind_gold_sha})
    artifact_root = sha256_json(("standin-t28-artifact-root", variant))
    manifest = {
        "schema_version": "t28-private-manifest-v1",
        "artifact": "T28_PRIVATE_MANIFEST",
        "classification": "PRIVATE_MANIFEST",
        "experiment": "t28", "attempt": 1,
        "semantic_bindings": {"disposable_variant": variant},
        "private_artifact_root": artifact_root,
        "private_blind_root": holdout_root,
        "private_evaluation_root": sha256_json(
            ("standin-t28-evaluation-root", variant)),
        "construction_semantic_root": sha256_json(
            ("standin-t28-semantic-root", variant)),
        "artifacts": [
            {"logical_id": "t28_blind_inputs", "path": "blind/inputs.json",
             "schema_type": "REAL_BLIND_INPUT", "classification":
                 "REAL_BLIND_INPUT",
             "byte_size": len(blind_inputs_payload),
             "sha256": blind_inputs_sha},
            {"logical_id": "t28_blind_gold", "path": "blind/gold.json",
             "schema_type": "REAL_BLIND_GOLD",
             "classification": "REAL_BLIND_GOLD",
             "byte_size": len(blind_gold_payload),
             "sha256": blind_gold_sha},
        ],
    }
    manifest_payload = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode("utf-8")
    manifest_sha = _sha(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode("utf-8"))
    (namespace / "construction/manifest.json").write_bytes(manifest_payload)
    record("write_once", T28_OFFICIAL_MANIFEST_PATH,
           bytes_written=len(manifest_payload))
    seal = {
        "schema_version": "t28-holdout-seal-v1",
        "artifact": "T28_HOLDOUT_SEAL", "classification": "PRIVATE_SEAL",
        "experiment": "t28", "attempt": 1, "state": "SEALED",
        "manifest_sha256": manifest_sha,
        "private_artifact_root": artifact_root,
        "private_blind_root": holdout_root,
    }
    seal_sha = _sha(
        json.dumps(seal, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True).encode("utf-8"))
    (namespace / "construction/seal.json").write_text(
        json.dumps(seal, sort_keys=True, separators=(",", ":")),
        encoding="utf-8", newline="\n")
    events = []
    previous = None
    for number, state_name in enumerate(CONSTRUCTION_STATES):
        event = {
            "event_index": number, "event_type": state_name,
            "timestamp": f"2026-09-29T02:00:0{number}+00:00",
            "previous_event_hash": None if number == 0 else previous,
            "payload": {"disposable": True},
        }
        event["event_hash"] = sha256_json(
            {key: value for key, value in event.items()
             if key != "event_hash"})
        previous = event["event_hash"]
        events.append(event)
    bindings = {
        "experiment": "t28", "attempt": 1, "mode": "REAL_BLIND",
        "store_id": T28_STORE_ID, "namespace": "t28",
        "candidate_commit": f"{'1' * 39}{variant % 10}",
        "candidate_tree": "2" * 40,
        "runtime_root": sha256_json(("standin-t28-runtime", variant)),
    }
    ledger = {
        "schema_version": "t28-construction-ledger-v1",
        "artifact": "T28_CONSTRUCTION_LEDGER",
        "classification": "PRIVATE_LEDGER",
        "bindings": bindings, "events": events, "state": "SEALED",
        "final_event_hash": previous,
        "ledger_root": sha256_json({"bindings": bindings, "events": events}),
    }
    ledger_bytes = json.dumps(
        ledger, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ledger_sha = _sha(ledger_bytes)
    (namespace / "construction/ledger.json").write_bytes(ledger_bytes)
    marker = {
        "schema_version": "t28-construction-one-shot-v1",
        "artifact": "T28_CONSTRUCTION_ONE_SHOT_SPENT",
        "classification": "PRIVATE_LEDGER", "attempt": 1,
        "spent": True, "bindings_sha256": sha256_json(bindings),
        "genesis_event_hash": events[0]["event_hash"],
        "ledger_path": T28_OFFICIAL_CONSTRUCTION_LEDGER_PATH,
    }
    marker_payload = json.dumps(
        marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (namespace / T28_OFFICIAL_CONSTRUCTION_MARKER_PATH).write_bytes(
        marker_payload)
    (namespace / "blind/inputs.json").write_bytes(blind_inputs_payload)
    (namespace / "blind/gold.json").write_bytes(blind_gold_payload)
    for event_number, event in enumerate(events):
        (namespace /
         f"construction/events/{event_number:06d}.json").write_text(
            json.dumps(event, sort_keys=True, separators=(",", ":")),
            encoding="utf-8", newline="\n")
    # Minimal construction-era journal mirroring the official surface: only
    # sanctioned writes, machine-only blind hashes, and has-probes on the
    # official evaluation absence paths (exists false everywhere).
    for path in T28_OFFICIAL_EVALUATION_ABSENCE_PATHS:
        record("has", path, exists=False)
    for path, payload in (
            (T28_OFFICIAL_CONSTRUCTION_MARKER_PATH, marker_payload),
            (T28_OFFICIAL_CONSTRUCTION_LEDGER_PATH, ledger_bytes),
            ("blind/inputs.json", blind_inputs_payload),
            ("blind/gold.json", blind_gold_payload)):
        record("has", path, exists=False)
        record("write_once", path, bytes_written=len(payload))
    for path in ("blind/inputs.json", "blind/gold.json"):
        record("machine_only_blind_hash", path)
    (namespace / "access_journal.jsonl").write_text(
        "".join(json.dumps(entry, sort_keys=True,
                           separators=(",", ":")) + "\n"
                for entry in journal), encoding="utf-8", newline="\n")
    expected: dict[str, str | int] = {
        "t28_store_identity": T28_STORE_ID, "t28_namespace": "t28",
        "t28_public_construction_commit":
            sha256_json(("standin-t28-public-commit", variant))[:40],
        "t28_construction_ledger_sha256": ledger_sha,
        "t28_construction_ledger_root": ledger["ledger_root"],
        "t28_private_manifest_sha256": manifest_sha,
        "t28_construction_seal_sha256": seal_sha,
        "t28_private_holdout_root": holdout_root,
        "t28_candidate_commit": bindings["candidate_commit"],
        "t28_candidate_runtime_root": bindings["runtime_root"],
        "t28_construction_state": T28_CONSTRUCTION_STATE,
        "t28_construction_attempt": T28_CONSTRUCTION_ATTEMPT,
        "t28_official_evaluation_state": T28_OFFICIAL_EVALUATION_STATE,
        "t28_official_evaluation_attempt": T28_OFFICIAL_EVALUATION_ATTEMPT,
        "t28_official_evaluation_eligibility":
            T28_OFFICIAL_EVALUATION_ELIGIBILITY,
    }
    return (parent / T28_STORE_ID, expected)


def disposable_real_mode_oracle_result(
        *, predecessor: str, root: Path, prospective_root: str,
        prospective: dict[str, list[str]], variant: int = 0
        ) -> dict[str, Any]:
    """Production-semantics rehearsal on an isolated authenticated stand-in."""
    with TemporaryDirectory(
            prefix=f"t29-{predecessor}-sealed-oracle-") as directory:
        if predecessor == "t27":
            from t27_protocol.t28_private_oracle import (
                _authenticate_store, _load_or_derive_index,
                disposable_t27_sealed_store,
            )

            root = Path(root).resolve()
            store, expected = disposable_t27_sealed_store(
                Path(directory), variant=variant, public_repo=root)
            authentication = _authenticate_store(store, expected)
            historical, index_root, index_origin = _load_or_derive_index(store)
            keys = ("t27_store_identity", "t27_namespace",
                    "t27_private_holdout_root",
                    "t27_construction_ledger_sha256",
                    "t27_construction_ledger_root",
                    "t27_private_manifest_sha256",
                    "t27_construction_seal_sha256",
                    "t27_public_construction_commit", "t27_candidate_commit",
                    "t27_candidate_runtime_root", "t27_construction_state",
                    "t27_construction_attempt",
                    "t27_official_evaluation_state",
                    "t27_official_evaluation_attempt",
                    "t27_official_evaluation_eligibility")
            bindings = {key: authentication[key] for key in keys}
            scope = "DISPOSABLE_STANDIN"
        else:
            store_root, expected = disposable_t28_sealed_store(
                Path(directory), variant=variant)
            authentication, payload = authenticate_official_t28_store_for_t29(
                root, store_root, expected=expected)
            historical, index_root, inputs_rows, gold_rows = \
                derive_t28_historical_fingerprints(
                    payload["blind_inputs_bytes"],
                    payload["blind_gold_bytes"],
                    blind_inputs_sha256=authentication[
                        "t28_blind_inputs_sha256"],
                    blind_gold_sha256=authentication[
                        "t28_blind_gold_sha256"])
            authentication["t28_blind_rows_deserialized_in_boundary"] = \
                inputs_rows
            authentication["t28_gold_rows_deserialized_in_boundary"] = \
                gold_rows
            keys = ("t28_store_identity", "t28_namespace",
                    "t28_private_holdout_root",
                    "t28_construction_ledger_sha256",
                    "t28_construction_ledger_root",
                    "t28_private_manifest_sha256",
                    "t28_construction_seal_sha256",
                    "t28_public_construction_commit", "t28_candidate_commit",
                    "t28_candidate_runtime_root", "t28_construction_state",
                    "t28_construction_attempt",
                    "t28_official_evaluation_state",
                    "t28_official_evaluation_attempt",
                    "t28_official_evaluation_eligibility",
                    "t28_construction_marker_sha256",
                    "t28_machine_only_blind_boundary",
                    "t28_blind_inputs_sha256", "t28_blind_gold_sha256",
                    "t28_blind_rows_deserialized_in_boundary",
                    "t28_gold_rows_deserialized_in_boundary",
                    "t28_access_journal_records",
                    "t28_journal_evaluation_surface_operations",
                    "t28_access_journal_sha256")
            bindings = {key: authentication[key] for key in keys}
            scope = "DISPOSABLE_STANDIN"
            index_origin = "DERIVED_MACHINE_ONLY_FROM_SEALED_BLIND_BYTES"
        return build_oracle_result(
            predecessor=predecessor, prospective_root=prospective_root,
            prospective=prospective, historical=historical,
            bindings=bindings, mode="REAL_SEALED", scope=scope,
            implementation=_SEALED_ORACLE[predecessor],
            store_authenticated=True, index_root=index_root,
            index_origin=index_origin,
            timestamp=f"2026-09-29T02:00:0{variant % 10}+00:00")


def real_mode_oracle_rehearsal(root: Path) -> dict[str, Any]:
    """Dual REAL_REHEARSAL oracle exercise on disposable sealed stand-ins."""
    prospective = {name: [sha256_json(("prospective-t29-standin", name))]
                   for name in DIMENSIONS}
    prospective_root = sha256_json(
        {name: sorted(set(prospective[name])) for name in DIMENSIONS})
    results = {}
    for predecessor in PREDECESSORS:
        result = disposable_real_mode_oracle_result(
            predecessor=predecessor, root=root,
            prospective_root=prospective_root, prospective=prospective,
            variant=0)
        verification = verify_oracle_result(
            result, predecessor=predecessor, mode="REAL_REHEARSAL",
            expected_t29_root=prospective_root)
        results[predecessor] = verification
    return {
        "schema_version": "t29-real-mode-dual-oracle-rehearsal-v1",
        "artifact": "T29_REAL_MODE_DUAL_ORACLE_REHEARSAL",
        "classification": "PUBLIC_SAFE", "status": "PASS",
        "predecessors": PREDECESSORS,
        "t27_rehearsal": results["t27"], "t28_rehearsal": results["t28"],
        "overall_prohibited_overlap": 0,
        "outside_boundary_private_rows_exposed": 0,
    }