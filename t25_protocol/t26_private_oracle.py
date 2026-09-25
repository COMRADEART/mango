"""Frozen T25-side private overlap oracle for T26 (runs inside the T25 store).

The engine compares T26's prospective private-input fingerprints (passed in as
hashes only) against the T25 private holdout's own nine-dimensional fingerprint
sets. It never exports a T25 row: the only output is a hash-bound zero-overlap
commitment written back into the T25 private store. The T26 author and the T26
candidate receive the commitment only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from t21_protocol.util import sha256_json

from .exclusions import DIMENSIONS

SCHEMA = "t26-private-overlap-oracle-result-v1"
ARTIFACT = "T25_PRIVATE_OVERLAP_ORACLE_RESULT"
ENGINE_IDENTITY = "t25_protocol.t26_private_oracle:T26_PRIVATE_OVERLAP_ENGINE"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def store_private_fingerprints(store: Any, dimension: str) -> list[str]:
    """Recompute T25 private fingerprint sets from the sealed private suite.

    This function executes strictly inside the T25 store boundary. Its result
    is consumed only by ``build_oracle_result`` and never returned to T26.
    """
    if dimension not in DIMENSIONS:
        raise ValueError("unknown T25 oracle fingerprint dimension")
    inputs = json.loads(store.read_bytes("suites/inputs.jsonl").decode("utf-8"))
    gold = json.loads(store.read_bytes("suites/gold.jsonl").decode("utf-8"))
    if dimension == "case_ids":
        return [_fingerprint(row["case_id"]) for row in inputs]
    if dimension == "exact_queries":
        return [_fingerprint(row["candidate_input"]["query"]) for row in inputs]
    if dimension == "exact_answers":
        return [_fingerprint(_canonical(
            {k: v for k, v in row.items() if k != "case_id"})) for row in gold]
    if dimension == "verbatim_attack_wording":
        return [_fingerprint(row["candidate_input"]["query"]) for row in inputs
                if row.get("family") in ("security_adversarial",
                                         "route_override_adversarial")]
    sources = json.loads(store.read_bytes("corpus/sources.jsonl").decode("utf-8"))
    chunks = json.loads(store.read_bytes("corpus/chunks.jsonl").decode("utf-8"))
    if dimension == "entity_identities":
        return [_fingerprint(row["source_title"]) for row in sources]
    if dimension == "source_ids":
        return [_fingerprint(row["source_id"]) for row in sources]
    if dimension == "chunk_ids":
        return [_fingerprint(row["chunk_id"]) for row in chunks]
    if dimension == "exact_source_text":
        return [_fingerprint(row["text"]) for row in chunks]
    if dimension == "relations":
        return [_fingerprint(_canonical(list(row["relations"]))) for row in sources
                if row.get("relations")]
    raise ValueError("unhandled T25 oracle fingerprint dimension")


def build_oracle_result(*, store: Any, t26_fingerprint_root: str,
                        t26_fingerprints: dict[str, list[str]]) -> dict[str, Any]:
    """Compare T26 hashes against T25 private fingerprint sets; bind everything.

    ``t26_fingerprints`` maps each of the nine dimensions to SHA-256
    fingerprints of T26's prospective private material. No T25 private value
    ever leaves this function; only counts and the commitment do.
    """
    if set(t26_fingerprints) != set(DIMENSIONS):
        raise ValueError("T26 oracle input dimension set mismatch")
    commitments_path = store.root / "commitments.json"
    commitments = json.loads(commitments_path.read_text(encoding="utf-8"))
    index = {entry["artifact_logical_id"]: entry
             for entry in commitments["commitments"]}
    required_ids = ("private_holdout_manifest", "holdout_seal",
                    "construction_run_ledger", "evaluation_run_ledger")
    missing = [key for key in required_ids if key not in index]
    if missing:
        raise ValueError(f"T25 oracle cannot bind the T25 store: missing {missing}")
    recomputed = {}
    for key in required_ids:
        data = store.read_bytes(key)
        recomputed[key] = hashlib.sha256(data).hexdigest()
        if recomputed[key] != index[key]["canonical_sha256"]:
            raise ValueError(f"T25 oracle binding drift on {key}")
    manifest = json.loads(store.read_bytes("private_holdout_manifest")
                          .decode("utf-8"))
    holdout_root = manifest["private_holdout_root"]
    dimensions = {}
    overlap_total = 0
    compared_total = 0
    for name in DIMENSIONS:
        t26_set = set(t26_fingerprints.get(name, ()))
        # Runs over the T25 private store's own fingerprint registry, which is
        # recomputed from the sealed private suite inside the store boundary.
        t25_set = set(store_private_fingerprints(store, name))
        overlap = len(t26_set & t25_set)
        applicable = bool(t26_set or t25_set)
        dimensions[name] = {"applicable": applicable,
                            "compared_population": len(t26_set | t25_set),
                            "overlap_count": overlap}
        compared_total += dimensions[name]["compared_population"]
        overlap_total += overlap
    result = {
        "schema_version": SCHEMA, "artifact": ARTIFACT, "experiment": "t26",
        "oracle_implementation": ENGINE_IDENTITY,
        "t25_private_holdout_root": holdout_root,
        "t25_private_manifest_sha256": recomputed["private_holdout_manifest"],
        "t25_construction_seal_sha256": recomputed["holdout_seal"],
        "t25_official_evaluation_ledger_sha256": recomputed["evaluation_run_ledger"],
        "t26_candidate_private_input_fingerprint_root": t26_fingerprint_root,
        "dimensions": dimensions,
        "overall_overlap_count": overlap_total,
        "overall_overlap": "ZERO_OVERLAP_ATTESTED" if overlap_total == 0
        else "OVERLAP_DETECTED",
        "oracle_execution_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result["result_sha256"] = sha256_json({key: value for key, value in result.items()
                                           if key != "result_sha256"})
    return result


T26_PRIVATE_OVERLAP_ENGINE = build_oracle_result
