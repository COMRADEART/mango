"""Evidence-checked lifecycle assertions for current and historical experiments.

This is additive: the T22-frozen protocol doctor and artifacts remain byte-for-byte
unchanged. A declared state grants no path exception unless its immutable evidence
and the phase ledgers validate independently.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


REGISTRY = "evaluations/t23/experiment_lifecycle_registry.json"
STATES = {"PRECONSTRUCTION", "CONSTRUCTED", "SEALED", "EVALUATED", "PROMOTED"}


def _read(root: Path, relative: str) -> dict[str, Any]:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"missing or escaping lifecycle evidence: {relative}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid lifecycle evidence: {relative}")
    return value


def _sha256(root: Path, relative: str) -> str:
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"missing or escaping lifecycle component: {relative}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ledger(root: Path, relative: str, experiment: str, kind: str) -> None:
    ledger = _read(root, relative)
    if not (ledger.get("experiment") == experiment and ledger.get("kind") == kind
            and ledger.get("state") == "COMPLETE" and ledger.get("attempt") == 1
            and ledger.get("metadata", {}).get("workspace_mode") == "REAL_EXPERIMENT"):
        raise ValueError(f"inconsistent {kind} ledger for {experiment}")


def verify_lifecycle(root: Path, experiment: str) -> dict[str, Any]:
    """Apply phase-specific real-path rules; unknown/inconsistent states fail closed."""
    root = Path(root).resolve()
    try:
        registry = _read(root, REGISTRY)
        if registry.get("schema_version") != "t23-experiment-lifecycle-registry-v1":
            raise ValueError("unknown lifecycle registry schema")
        entry = registry.get("experiments", {}).get(experiment)
        if not isinstance(entry, dict) or entry.get("state") not in STATES:
            raise ValueError(f"unknown or unsupported lifecycle state: {experiment}")
        state = entry["state"]
        contract = _read(root, entry["contract"])
        values = contract.get("values", {})
        key = f"real_{experiment}_paths"
        real_paths = values.get(key)
        if not isinstance(real_paths, list) or not real_paths or not all(isinstance(p, str) for p in real_paths):
            raise ValueError("real-path registry missing or malformed")
        if "evaluation_graph" in entry:
            graph = _read(root, entry["evaluation_graph"])
            nodes = graph.get("nodes")
            if graph.get("experiment") != experiment or not isinstance(nodes, dict):
                raise ValueError("lifecycle evaluation graph is invalid")
            graph_paths = [node.get("path") for node in nodes.values() if isinstance(node, dict)]
            if len(graph_paths) != len(nodes) or not all(isinstance(p, str) for p in graph_paths):
                raise ValueError("lifecycle evaluation paths are invalid")
            real_paths = sorted(set(real_paths) | set(graph_paths))
        present: list[str] = []
        for relative in real_paths:
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("real path escapes repository")
            if path.exists():
                present.append(relative)

        if state == "PRECONSTRUCTION":
            freeze = _read(root, entry["preconstruction_freeze"])
            if (freeze.get("artifact") != f"{experiment.upper()}_PRECONSTRUCTION_FREEZE"
                    or freeze.get("real_t23_exposure") != 0 or present):
                raise ValueError("preconstruction state has invalid freeze or real paths")
        elif state == "PROMOTED":
            record = _read(root, entry["promotion_record"])
            checksum_path = (root / entry["promotion_checksum"]).resolve()
            if not checksum_path.is_relative_to(root) or not checksum_path.is_file():
                raise ValueError("promotion checksum missing")
            expected = checksum_path.read_text(encoding="ascii").split()[0].lower()
            if _sha256(root, entry["promotion_record"]) != expected:
                raise ValueError("promotion record checksum mismatch")
            if (record.get("verdict") != entry["expected_verdict"]
                    or record.get("floor_summary", {}).get("passed") != entry["protected_floor_count"]
                    or record.get("floor_summary", {}).get("failed") != 0
                    or record.get("immutability_audit", {}).get("status") != "PASS"):
                raise ValueError("promotion evidence is not a passing promotion")
            _ledger(root, entry["construction_ledger"], experiment, "construction")
            _ledger(root, entry["evaluation_ledger"], experiment, "evaluation")
            seal = f"evaluations/{experiment}/HOLDOUT_FROZEN"
            manifest = f"evaluations/{experiment}/holdout_manifest.json"
            sealed = record.get("sealed_inputs", {})
            if (_sha256(root, seal) != sealed.get("HOLDOUT_FROZEN_sha256")
                    or _sha256(root, manifest) != sealed.get("holdout_manifest_sha256")
                    or set(present) != set(real_paths)):
                raise ValueError("promotion artifacts are missing or inconsistent")
            # Public preconstruction files may coexist with the registered
            # private promotion paths, but no unregistered top-level output may
            # silently appear under the promoted experiment directory.
            output = root / "evaluations" / experiment
            tracked = subprocess.run(["git", "ls-files", "--", f"evaluations/{experiment}"],
                                     cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
            allowed = {path.split("/")[2] for path in tracked if path.startswith(f"evaluations/{experiment}/")}
            allowed.update(path.split("/")[2] for path in real_paths
                           if path.startswith(f"evaluations/{experiment}/"))
            unexpected = sorted(path.name for path in output.iterdir() if path.name not in allowed)
            if unexpected:
                raise ValueError(f"unregistered promoted artifacts: {unexpected}")
        else:
            # No intermediate experiment is currently registered. Adding one
            # requires explicit evidence rules, never a permissive default.
            raise ValueError(f"state {state} lacks registered evidence rules")
        return {"status": "PASS", "experiment": experiment, "state": state,
                "registered_paths": len(real_paths), "present_paths": len(present),
                "evidence_valid": True}
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError,
            subprocess.CalledProcessError) as exc:
        return {"status": "FAIL", "experiment": experiment, "state": "UNKNOWN",
                "evidence_valid": False, "reason": str(exc)}


def verify_historical_transition(root: Path, experiment: str) -> dict[str, Any]:
    """Authenticate an older phase from the explicit registry and its ledger.

    Failed one-shot attempts are distinct states: merely finding a corpus does
    not imply successful construction or evaluation.
    """
    root = Path(root).resolve()
    try:
        registry = _read(root, REGISTRY)
        if registry.get("schema_version") != "t23-experiment-lifecycle-registry-v1":
            raise ValueError("unknown lifecycle registry schema")
        entry = registry.get("historical_transitions", {}).get(experiment)
        if not isinstance(entry, dict) or set(entry) != {
            "state", "evidence", "field", "value", "required_paths", "forbidden_paths"
        }:
            raise ValueError(f"unregistered historical transition: {experiment}")
        if entry["state"] not in {"CONSTRUCTION_FAILED", "SEALED", "EVALUATION_FAILED", "EVALUATED"}:
            raise ValueError("unsupported historical transition state")
        evidence = _read(root, entry["evidence"])
        if evidence.get(entry["field"]) != entry["value"]:
            raise ValueError("historical ledger state contradicts registry")
        for relative in entry["required_paths"]:
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.exists():
                raise ValueError(f"missing required historical artifact: {relative}")
        for relative in entry["forbidden_paths"]:
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or path.exists():
                raise ValueError(f"forbidden historical artifact exists: {relative}")
        return {"status": "PASS", "experiment": experiment,
                "state": entry["state"], "evidence": entry["evidence"],
                "evidence_sha256": _sha256(root, entry["evidence"]),
                "required_paths": len(entry["required_paths"]),
                "forbidden_paths": len(entry["forbidden_paths"])}
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "experiment": experiment,
                "state": "UNKNOWN", "reason": str(exc)}
