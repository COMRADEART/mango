"""T24_SEALED_EVALUATED anchor: hash-only record of the frozen T24 history.

T24 is SEALED, EVALUATED, and publication-clean: its real blind material never
entered public Git (post-push blind-blob scan 0) and lives only in the private
artifact store, where it stays unread by T25 (authorization §3/§13). The
anchor therefore binds the public-safe T24 receipt/commitment chain, the
candidate identity, the public qualification and rehearsal fingerprint sets,
and the aggregate official result recorded by the T25 authorization — never
raw T24 row content (none is derivable and none may be opened). It drives the
T25 exclusion audit and the live-web source firewall.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

T24_CONSTRUCTION_COMMIT = "71e829d5d7b89298e5c504a0b55278037ec90f28"
T24_CONSTRUCTION_TREE = "30ecf8e69cbb3e7caae118b90fcaad150205a730"
T24_RECEIPT_COMMIT = "d64160bf0ebb715a6a30647d06e420b7dde6b24e"
T24_RECEIPT_TREE = "57199cd464694d4ec32754d40f3360aa9946e811"
T24_CANDIDATE_COMMIT = "e1be88fee99361bfd47dfa054a99637820cadda8"
T24_CANDIDATE_TREE = "c88599484db10c0bcf3eeafa50d84746fa539060"
T24_CONSTRUCTION_LEDGER_SHA256 = (
    "a71da0b7530b654de4a00d431dfa3de1f93f171b4cab957b995d599ee8200501")
T24_EVALUATION_LEDGER_SHA256 = (
    "4d100d2923b78c1a70d353b9750b4afa4b070e9c7340b0b04700c4d72b421ea2")
T24_PRIVATE_ARTIFACT_ROOT = (
    "7be1d7f7aa26b017e983bd69eb484cd6d78a6929f4fb5d4e761f926cc7356a64")

ANCHOR_SCHEMA = "t24-sealed-evaluated-anchor-v1"
ANCHOR_ARTIFACT = "T24_SEALED_EVALUATED_ANCHOR"
# The nine provenance dimensions shared with the T25 exclusion engine, plus the
# artifact-content dimension that hash-excludes every committed T24 artifact.
DIMENSIONS = ("case_ids", "entity_identities", "source_ids", "chunk_ids",
              "exact_queries", "exact_answers", "exact_source_text",
              "verbatim_attack_wording", "relations")
ARTIFACT_DIMENSION = "artifact_content"

# Public-safe T24 artifacts bound by the anchor, read at the pinned receipt
# commit so later T25 additions cannot perturb the anchor.
BOUND_PATHS = (
    "evaluations/t24/construction/T24_CONSTRUCTION_PUBLIC_COMMITMENT.json",
    "evaluations/t24/construction/T24_CONSTRUCTION_PUBLIC_RECEIPT.json",
    "evaluations/t24/evaluation/T24_EVALUATION_PUBLIC_RECEIPT.json",
    "evaluations/t24/preconstruction_freeze.json",
    "evaluations/t24/candidate_identity.json",
    "evaluations/t24/qualification/qualification_report.json",
    "evaluations/t24/qualification/qualification_exclusions.jsonl",
    "evaluations/t24/rehearsal_exclusion_fingerprints.json",
    "evaluations/t24/t24_exclusion_sources.json",
    "evaluations/t24/production_shadow_lifecycle_report.json",
    "evaluations/t24/protocol_doctor_report.json",
    "evaluations/t24/t24_master_contract.json",
    "evaluations/t24/production_provider_config.json",
    "evaluations/t24/T24_PRECONSTRUCTION_VERDICT.json",
)

# Aggregate-only official result recorded by the T25 authorization (§2). The
# T24 private evaluation outputs are never opened; these counts are exactly the
# PUBLIC_SAFE aggregate the authorization itself carried.
OFFICIAL_RESULT = {
    "experiment": "t24",
    "state": "COMPLETE",
    "attempt": 1,
    "verdict": "T24_OFFICIAL_EVALUATION_COMPLETE_CAPABILITY_FAIL",
    "adjudicated_classification": "T24_OFFICIAL_VALID_CAPABILITY_FAILURE",
    "remediation_target": {
        "selected_capability": "GENERAL",
        "terminal_status": "UNKNOWN",
        "unmatched_rows": 4,
        "allowed_count": 0,
        "aggregate_only": True,
        "row_level_analysis_performed": False,
    },
    "source": "T25 aggregate-only remediation + preconstruction authorization §2",
}

# Aggregate route/capability fit from the public frozen T24 runtime only
# (authorization §4; no T24 row opened): 80 GENERAL rows = 72 fast-path
# PARTIALLY_SUPPORTED + 4 [SYNTH]-only UNCERTAIN + 4 retrieval-cued UNKNOWN.
AGGREGATE_FIT = {"general_rows": 80, "partially_supported": 72, "uncertain": 4,
                 "unknown": 4}


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_bytes(root: Path, commit: str, path: str) -> bytes:
    import subprocess

    return subprocess.run(["git", "show", f"{commit}:{path}"], cwd=root,
                          capture_output=True, check=True).stdout


def _git_jsonl(root: Path, commit: str, path: str) -> list[dict[str, Any]]:
    rows = []
    for line in _git_bytes(root, commit, path).decode("utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _dimension(values: list[str]) -> dict[str, Any]:
    unique = sorted(set(values))
    for value in unique:
        if len(value) != 64:
            raise ValueError("non-fingerprint value in T24 anchor dimension")
    return {"count": len(values), "unique_count": len(unique),
            "fingerprints": unique,
            "dimension_root": sha256_json(unique)}


def build_anchor(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    import subprocess

    construction_tree = subprocess.run(
        ["git", "rev-parse", f"{T24_CONSTRUCTION_COMMIT}^{{tree}}"], cwd=root,
        capture_output=True, check=True, text=True).stdout.strip()
    receipt_tree = subprocess.run(
        ["git", "rev-parse", f"{T24_RECEIPT_COMMIT}^{{tree}}"], cwd=root,
        capture_output=True, check=True, text=True).stdout.strip()
    if construction_tree != T24_CONSTRUCTION_TREE or receipt_tree != T24_RECEIPT_TREE:
        raise ValueError("T24 anchor commit/tree identity mismatch")

    # Bind every public T24 artifact at the frozen receipt commit.
    inventory = []
    for path in BOUND_PATHS:
        data = _git_bytes(root, T24_RECEIPT_COMMIT, path)
        inventory.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                          "byte_size": len(data)})

    # Aggregate-free public qualification rows (T24's permanently excluded set).
    qualification = _git_jsonl(root, T24_RECEIPT_COMMIT,
                               "evaluations/t24/qualification/qualification_exclusions.jsonl")
    if len(qualification) != 1280:
        raise ValueError("unexpected T24 qualification exclusion size in anchor build")

    # Disposable T24 rehearsal fingerprints (hash-only, public-safe).
    rehearsal = json.loads(_git_bytes(
        root, T24_RECEIPT_COMMIT,
        "evaluations/t24/rehearsal_exclusion_fingerprints.json").decode("utf-8"))
    if rehearsal.get("raw_values_included") is not False:
        raise ValueError("T24 rehearsal fingerprint set malformed")

    # Every committed T24 artifact commitment (blind suites included) is
    # already hash-public in the construction commitment; bind those hashes.
    commitment = json.loads(_git_bytes(
        root, T24_RECEIPT_COMMIT,
        "evaluations/t24/construction/T24_CONSTRUCTION_PUBLIC_COMMITMENT.json")
        .decode("utf-8"))
    artifact_hashes = [entry["canonical_sha256"] for entry in commitment["artifacts"]]
    if len(artifact_hashes) < 25:
        raise ValueError("T24 construction commitment carries too few artifacts")

    construction_receipt = json.loads(_git_bytes(
        root, T24_RECEIPT_COMMIT,
        "evaluations/t24/construction/T24_CONSTRUCTION_PUBLIC_RECEIPT.json")
        .decode("utf-8"))
    evaluation_receipt = json.loads(_git_bytes(
        root, T24_RECEIPT_COMMIT,
        "evaluations/t24/evaluation/T24_EVALUATION_PUBLIC_RECEIPT.json")
        .decode("utf-8"))
    if construction_receipt["state"] != "SEALED" \
            or construction_receipt["ledger_sha256"] != T24_CONSTRUCTION_LEDGER_SHA256:
        raise ValueError("T24 construction receipt binding mismatch")
    if evaluation_receipt["state"] != "COMPLETE" \
            or evaluation_receipt["ledger_sha256"] != T24_EVALUATION_LEDGER_SHA256:
        raise ValueError("T24 evaluation receipt binding mismatch")

    dimensions: dict[str, dict[str, Any]] = {
        "case_ids": _dimension([fingerprint(row["case_id"]) for row in qualification]),
        "exact_queries": _dimension([fingerprint(row["query"]) for row in qualification]),
        # T24's real blind rows are private and were never opened: the only
        # derivable answer/attack-text fingerprints come from the disposable
        # rehearsal (synthetic, public-safe).
        "exact_answers": _dimension(rehearsal["dimensions"].get("exact_answers", [])),
        "exact_source_text": _dimension(rehearsal["dimensions"].get("exact_source_text", [])),
        "verbatim_attack_wording": _dimension(
            rehearsal["dimensions"].get("verbatim_attack_wording", [])),
        # T24 real corpus/suite identities are private-store-only; nothing
        # public is derivable, so these dimensions carry no T24 fingerprints.
        "entity_identities": _dimension([]),
        "source_ids": _dimension([]),
        "chunk_ids": _dimension([]),
        "relations": _dimension([]),
        ARTIFACT_DIMENSION: _dimension(artifact_hashes),
    }
    anchor = {"schema_version": ANCHOR_SCHEMA, "artifact": ANCHOR_ARTIFACT,
              "experiment": "t25", "raw_values_included": False,
              "t24_history": {
                  "material": "T24_REAL_BLIND_HOLDOUT_SEALED_EVALUATED_NEVER_PUBLISHED",
                  "construction_commit": T24_CONSTRUCTION_COMMIT,
                  "construction_tree": T24_CONSTRUCTION_TREE,
                  "receipt_commit": T24_RECEIPT_COMMIT,
                  "receipt_tree": T24_RECEIPT_TREE,
                  "candidate_commit": T24_CANDIDATE_COMMIT,
                  "candidate_tree": T24_CANDIDATE_TREE,
                  "construction_ledger_sha256": T24_CONSTRUCTION_LEDGER_SHA256,
                  "evaluation_ledger_sha256": T24_EVALUATION_LEDGER_SHA256,
                  "private_artifact_root": T24_PRIVATE_ARTIFACT_ROOT,
                  "store_identity": "T24-STORE-01"},
              "official_result": dict(OFFICIAL_RESULT),
              "aggregate_fit": dict(AGGREGATE_FIT),
              "inventory": {"file_count": len(inventory), "files": inventory,
                            "inventory_root": sha256_json(inventory)},
              "dimensions": dimensions,
              "excluded_material":
                  "T24_1280_CASES_16_SUITES_PRIVATE_CORPUS_ARTIFACT_COMMITMENTS",
              "t24_must_not_be_rerun": True,
              "t24_private_material_must_not_be_opened": True,
              "t25_candidate_must_not_execute_on_t24_rows": True,
              "anchor_artifact": "evaluations/t25/t24_sealed_evaluated_anchor.json"}
    core = {key: value for key, value in anchor.items() if key != "anchor_root"}
    anchor["anchor_root"] = sha256_json(core)
    return anchor


def verify_anchor(root: Path, path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path is not None else (
        Path(root) / "evaluations/t25/t24_sealed_evaluated_anchor.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored.get("schema_version") != ANCHOR_SCHEMA \
            or stored.get("raw_values_included") is not False:
        raise ValueError("T24 sealed-evaluated anchor schema mismatch")
    recomputed = build_anchor(root)
    if recomputed != stored:
        raise ValueError("T24 sealed-evaluated anchor fingerprint mismatch")
    if stored["t24_history"]["construction_commit"] != T24_CONSTRUCTION_COMMIT \
            or stored["t24_history"]["receipt_commit"] != T24_RECEIPT_COMMIT:
        raise ValueError("T24 anchor not bound to the frozen T24 commits")
    return {"status": "PASS",
            "dimensions": {name: value["count"] for name, value
                           in stored["dimensions"].items()},
            "anchor_root": stored["anchor_root"],
            "bound_files": stored["inventory"]["file_count"]}


def fingerprint_sets(anchor: dict[str, Any]) -> dict[str, set[str]]:
    return {name: set(value["fingerprints"]) for name, value
            in anchor["dimensions"].items()}