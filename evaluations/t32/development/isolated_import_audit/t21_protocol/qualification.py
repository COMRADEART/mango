"""Deterministic author qualification lock."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .author import shadow_author
from .errors import ValidationError
from .util import read_json, sha256_file, sha256_json


def build_qualification_lock(root: Path, contract: Any) -> dict[str, Any]:
    run_1 = shadow_author(contract, root)["fingerprint_root"]
    run_2 = shadow_author(contract, root)["fingerprint_root"]
    if run_1 != run_2:
        raise ValidationError("shadow author is not deterministic")
    experiment_path = root / contract.get("artifacts.experiment_config")
    taxonomy_path = root / contract.get("artifacts.domain_taxonomy")
    exclusion_path = root / contract.get("artifacts.historical_exclusion")
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "0" * 40
    roots = contract.get("roots")
    try:
        runtime_native = contract.get("runtime_native")
    except KeyError:
        runtime_native = None
    lock = {
        "schema_version": "t21-qualification-lock-v2",
        "artifact": "T21_QUALIFICATION_LOCK",
        "experiment": contract.experiment,
        "preconstruction_commit": commit,
        "author_hash": sha256_file(root / "t21_protocol" / "author.py"),
        "production_construction_runner_hash": sha256_file(root / "t21_protocol" / "construction.py"),
        "production_evaluation_runner_hash": sha256_file(root / "t21_protocol" / "evaluate.py"),
        "master_contract_hash": sha256_file(root / "evaluations" / contract.experiment / "t21_master_contract.json"),
        "artifact_graph_hash": sha256_file(root / "evaluations" / contract.experiment / "artifact_graph.json"),
        "doctor_hash": sha256_file(root / "t21_protocol" / "doctor.py"),
        "authoring_profile_hash": sha256_file(experiment_path),
        "contract_hash": contract.hash,
        "shadow_fingerprint_root": run_1,
        "expected_suite_counts": {name: spec["count"] for name, spec in contract.get("suites").items()},
        "expected_taxonomy_root": sha256_json(read_json(taxonomy_path)),
        "expected_exclusion_root": sha256_file(exclusion_path),
        "runtime_root": roots["runtime_root"],
        "evaluator_root": roots["evaluator_root"],
        "floor_hash": roots["floor_hash"],
        "immutable_after": f"{contract.experiment.upper()}_PRODUCTION_PHASE_REQUALIFICATION_PASS",
    }
    if runtime_native is not None:
        # Runtime-native experiments additionally bind the frozen candidate
        # runtime modules and the runtime-contract digests they are derived from.
        lock["runtime_native"] = {
            "schema_module_sha256": sha256_file(root / "src" / "sciencemath" / "knowledge" / "schema.py"),
            "corpus_module_sha256": sha256_file(root / "src" / "sciencemath" / "knowledge" / "corpus.py"),
            "runtime_data_contract_root": roots["runtime_data_contract_root"],
            "runtime_corpus_contract_sha256": roots["runtime_corpus_contract_sha256"],
            "runtime_field_provenance_sha256": roots["runtime_field_provenance_sha256"],
            "candidate_provider_sha256": roots["candidate_provider_sha256"],
        }
    return lock


def validate_qualification_lock(root: Path, contract: Any, lock: dict[str, Any]) -> dict[str, Any]:
    expected = build_qualification_lock(root, contract)
    # The source commit can legitimately differ after the lock is committed;
    # all semantic/code bytes are bound independently below.
    comparable = set(expected) - {"preconstruction_commit"}
    mismatches = sorted(key for key in comparable if lock.get(key) != expected[key])
    commit = lock.get("preconstruction_commit")
    if not isinstance(commit, str) or len(commit) != 40:
        mismatches.append("preconstruction_commit")
    if mismatches:
        raise ValidationError(f"qualification lock mismatch: {sorted(set(mismatches))}")
    return {
        "status": "PASS",
        "author_root_run_1": expected["shadow_fingerprint_root"],
        "author_root_run_2": shadow_author(contract, root)["fingerprint_root"],
        "committed_qualification_root": lock["shadow_fingerprint_root"],
        "all_equal": True,
    }
