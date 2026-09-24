"""T23_EXPOSED_SEALED anchor: hash-only fingerprints of every published T23 blind artifact.

Built from the pinned public construction commit (aa613c3). Contains hashes,
fingerprints, and structural counts only — never raw T23 blind text. The anchor
drives both the exclusion audit and the live-web source firewall.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from t21_protocol.util import sha256_json

from .contract import T23_CONSTRUCTION_COMMIT, T23_CONSTRUCTION_TREE

ANCHOR_SCHEMA = "t23-exposed-sealed-anchor-v1"
ANCHOR_ARTIFACT = "T23_EXPOSED_SEALED_ANCHOR"
DIMENSIONS = ("case_ids", "entity_identities", "source_ids", "chunk_ids",
              "exact_queries", "exact_answers", "exact_source_text",
              "verbatim_attack_wording", "relations")
T23_SUITES = "evaluations/t23/suites"
T23_CORPUS = "rag/gk_holdout_t23"
ATTACHMENT_PATH = "documents/private_pool_attachment.txt"
FAMILY_FILES = (
    "ambiguous_route", "citation_sensitive", "conflicting_evidence", "cross_domain_local",
    "explicit_current", "historical_as_of", "insufficient_evidence", "malformed_router_state",
    "mixed_intent", "multi_hop_local", "recency_sensitive", "route_override_adversarial",
    "security_adversarial", "static_local_factual", "tool_required", "unsupported_tool_request",
)
ATTACK_FAMILIES = ("security_adversarial", "route_override_adversarial")
T23_INVENTORY = (
    ATTACHMENT_PATH,
    "evaluations/t23/HOLDOUT_FROZEN",
    "evaluations/t23/construction_audits.json",
    "evaluations/t23/construction_run_ledger.json",
    "evaluations/t23/holdout_manifest.json",
    "evaluations/t23/suites/blindness_audit.json",
    "evaluations/t23/suites/construction_gate.json",
    "evaluations/t23/suites/static_audit.json",
    "evaluations/t23/suites/uniqueness_audit.json",
    f"{T23_SUITES}/families/ambiguous_route.jsonl",
    f"{T23_SUITES}/families/citation_sensitive.jsonl",
    f"{T23_SUITES}/families/conflicting_evidence.jsonl",
    f"{T23_SUITES}/families/cross_domain_local.jsonl",
    f"{T23_SUITES}/families/explicit_current.jsonl",
    f"{T23_SUITES}/families/historical_as_of.jsonl",
    f"{T23_SUITES}/families/insufficient_evidence.jsonl",
    f"{T23_SUITES}/families/malformed_router_state.jsonl",
    f"{T23_SUITES}/families/mixed_intent.jsonl",
    f"{T23_SUITES}/families/multi_hop_local.jsonl",
    f"{T23_SUITES}/families/recency_sensitive.jsonl",
    f"{T23_SUITES}/families/route_override_adversarial.jsonl",
    f"{T23_SUITES}/families/security_adversarial.jsonl",
    f"{T23_SUITES}/families/static_local_factual.jsonl",
    f"{T23_SUITES}/families/tool_required.jsonl",
    f"{T23_SUITES}/families/unsupported_tool_request.jsonl",
    f"{T23_SUITES}/gold.jsonl",
    f"{T23_SUITES}/inputs.jsonl",
    f"{T23_CORPUS}/chunks.jsonl",
    f"{T23_CORPUS}/corpus_manifest.json",
    f"{T23_CORPUS}/sources.jsonl",
)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git_bytes(root: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=root,
                            capture_output=True, check=True)
    return result.stdout


def _git_jsonl(root: Path, commit: str, path: str) -> list[dict[str, Any]]:
    rows = []
    for line in _git_bytes(root, commit, path).decode("utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _dimension(values: list[str]) -> dict[str, Any]:
    unique = sorted(set(values))
    return {"count": len(values), "unique_count": len(unique),
            "fingerprints": [fingerprint(value) for value in unique],
            "dimension_root": sha256_json(unique)}


def build_anchor(root: Path, *, commit: str = T23_CONSTRUCTION_COMMIT) -> dict[str, Any]:
    root = Path(root).resolve()
    tree = subprocess.run(["git", "rev-parse", f"{commit}^{{tree}}"], cwd=root,
                          capture_output=True, check=True, text=True).stdout.strip()
    if tree != T23_CONSTRUCTION_TREE:
        raise ValueError("T23 anchor commit/tree identity mismatch")
    parent = subprocess.run(["git", "rev-parse", f"{commit}^"], cwd=root,
                            capture_output=True, check=True).stdout.decode().strip()
    inventory = []
    for path in T23_INVENTORY:
        data = _git_bytes(root, commit, path)
        inventory.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                          "byte_size": len(data)})
    inputs = _git_jsonl(root, commit, f"{T23_SUITES}/inputs.jsonl")
    gold = _git_jsonl(root, commit, f"{T23_SUITES}/gold.jsonl")
    if len(inputs) != 1280 or len(gold) != 1280:
        raise ValueError("unexpected T23 holdout size in anchor build")
    family_by_case = {row["case_id"]: row["family"] for row in gold}
    source_rows = _git_jsonl(root, commit, f"{T23_CORPUS}/sources.jsonl")
    chunk_rows = _git_jsonl(root, commit, f"{T23_CORPUS}/chunks.jsonl")
    attachment = _git_bytes(root, commit, ATTACHMENT_PATH).decode("utf-8")
    dimensions: dict[str, dict[str, Any]] = {
        "case_ids": _dimension([row["case_id"] for row in inputs]),
        "exact_queries": _dimension([row["candidate_input"]["query"] for row in inputs]),
        "exact_answers": _dimension([
            json.dumps({"expected_route": row["expected_route"],
                        "expected_reason": row["expected_reason"], "family": row["family"]},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            for row in gold]),
        "exact_source_text": _dimension([row["text"] for row in chunk_rows] + [attachment]),
        "entity_identities": _dimension([row["source_title"] for row in source_rows]),
        "source_ids": _dimension([row["source_id"] for row in source_rows]),
        "chunk_ids": _dimension([row["chunk_id"] for row in chunk_rows]),
        "verbatim_attack_wording": _dimension([
            row["candidate_input"]["query"] for row in inputs
            if family_by_case[row["case_id"]] in ATTACK_FAMILIES]),
        # The exposed T23 corpus schema carries no relations field; the relation
        # dimension is carried by exact_source_text and entity_identities.
        "relations": _dimension([]),
    }
    suite_identities = {family: entry["sha256"] for family, entry in
                        ((item["path"].rsplit("/", 1)[-1].removesuffix(".jsonl"), item)
                         for item in inventory if "/families/" in item["path"])}
    anchor = {"schema_version": ANCHOR_SCHEMA, "artifact": ANCHOR_ARTIFACT,
              "experiment": "t24", "raw_values_included": False,
              "t23_construction": {"commit": commit, "tree": tree, "parent": parent,
                                   "material": "T23_REAL_BLIND_HOLDOUT_ALL_DIMENSIONS_EXPOSED"},
              "inventory": {"file_count": len(inventory), "files": inventory,
                            "inventory_root": sha256_json(inventory)},
              "suite_identities": {"family_file_count": len(suite_identities),
                                   "families": suite_identities,
                                   "suite_root": sha256_json(suite_identities)},
              "corpus": {"source_count": len(source_rows), "chunk_count": len(chunk_rows),
                         "manifest_sha256": next(item["sha256"] for item in inventory
                                                 if item["path"] == f"{T23_CORPUS}/corpus_manifest.json"),
                         "attachment": {"path": ATTACHMENT_PATH,
                                        "sha256": next(item["sha256"] for item in inventory
                                                       if item["path"] == ATTACHMENT_PATH)}},
              "dimensions": dimensions,
              "excluded_material": "T23_1280_CASES_16_SUITES_18_SOURCES_72_CHUNKS_ATTACHMENT",
              "anchor_artifact": "evaluations/t24/t23_exposed_sealed_anchor.json"}
    core = {key: value for key, value in anchor.items() if key != "anchor_root"}
    anchor["anchor_root"] = sha256_json(core)
    return anchor


def verify_anchor(root: Path, path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path is not None else (Path(root) / "evaluations/t24/t23_exposed_sealed_anchor.json")
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored.get("schema_version") != ANCHOR_SCHEMA or stored.get("raw_values_included") is not False:
        raise ValueError("T23 exposed-sealed anchor schema mismatch")
    recomputed = build_anchor(root, commit=stored["t23_construction"]["commit"])
    if recomputed != stored:
        raise ValueError("T23 exposed-sealed anchor fingerprint mismatch")
    if stored["t23_construction"]["commit"] != T23_CONSTRUCTION_COMMIT:
        raise ValueError("T23 anchor not bound to the frozen exposed commit")
    return {"status": "PASS", "dimensions": {name: value["count"] for name, value in
                                             stored["dimensions"].items()},
            "anchor_root": stored["anchor_root"],
            "exposed_files": stored["inventory"]["file_count"]}


def fingerprint_sets(anchor: dict[str, Any]) -> dict[str, set[str]]:
    return {name: set(value["fingerprints"]) for name, value in anchor["dimensions"].items()}