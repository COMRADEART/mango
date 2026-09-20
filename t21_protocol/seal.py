"""Graph-derived seal construction and typed HOLDOUT_FROZEN markers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_graph import seal_input_nodes
from .errors import SealError
from .util import read_json, sha256_file, sha256_json, sha256_path, write_json

HOLDOUT_FROZEN_FIELDS: dict[str, type] = {
    "schema_version": str,
    "experiment": str,
    "construction_status": str,
    "holdout_manifest_sha256": str,
    "freeze_root_sha256": str,
    "candidate_commit": str,
    "candidate_tree": str,
    "runtime_root": str,
    "evaluator_root": str,
    "floor_hash": str,
    "construction_attempts": int,
    "corpus_materializations": int,
    "suite_materializations": int,
    "candidate_rows_executed": int,
    "runtime_rows_executed": int,
    "official_evaluator_invocations": int,
}
JSON_TYPE_NAMES = {str: "string", int: "integer"}


def validate_holdout_frozen_schema(document: dict[str, Any]) -> dict[str, Any]:
    """Prove the frozen JSON schema and production validator describe one marker."""
    required = document.get("required")
    properties = document.get("properties")
    errors: list[str] = []
    if document.get("type") != "object" or document.get("additionalProperties") is not False:
        errors.append("HOLDOUT_FROZEN schema must be a closed object")
    if not isinstance(required, list) or set(required) != set(HOLDOUT_FROZEN_FIELDS):
        errors.append("HOLDOUT_FROZEN schema required fields differ from production validator")
    if not isinstance(properties, dict) or set(properties) != set(HOLDOUT_FROZEN_FIELDS):
        errors.append("HOLDOUT_FROZEN schema properties differ from production validator")
    if isinstance(properties, dict):
        for name, expected in HOLDOUT_FROZEN_FIELDS.items():
            spec = properties.get(name)
            if not isinstance(spec, dict) or spec.get("type") != JSON_TYPE_NAMES[expected]:
                errors.append(f"HOLDOUT_FROZEN schema type mismatch: {name}")
    if errors:
        raise SealError("; ".join(errors))
    return {"status": "PASS", "required_fields": len(HOLDOUT_FROZEN_FIELDS), "missing": 0}


def validate_holdout_frozen(document: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if set(document) != set(HOLDOUT_FROZEN_FIELDS):
        missing = sorted(set(HOLDOUT_FROZEN_FIELDS) - set(document))
        unknown = sorted(set(document) - set(HOLDOUT_FROZEN_FIELDS))
        errors.append(f"HOLDOUT_FROZEN fields differ: missing={missing}, unknown={unknown}")
    for name, expected in HOLDOUT_FROZEN_FIELDS.items():
        value = document.get(name)
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            errors.append(f"HOLDOUT_FROZEN.{name} has wrong type")
    for name in (
        "holdout_manifest_sha256",
        "freeze_root_sha256",
        "candidate_commit",
        "candidate_tree",
        "runtime_root",
        "evaluator_root",
        "floor_hash",
    ):
        value = document.get(name)
        if not isinstance(value, str) or len(value) not in ({40} if name in {"candidate_commit", "candidate_tree"} else {64}):
            errors.append(f"HOLDOUT_FROZEN.{name} is not a valid digest")
    if document.get("construction_status") != "COMPLETE":
        errors.append("construction_status must be COMPLETE")
    expected_counts = {
        "construction_attempts": 1,
        "corpus_materializations": 1,
        "suite_materializations": 1,
        "candidate_rows_executed": 0,
        "runtime_rows_executed": 0,
        "official_evaluator_invocations": 0,
    }
    for name, expected in expected_counts.items():
        if document.get(name) != expected:
            errors.append(f"HOLDOUT_FROZEN.{name} must equal {expected}")
    if errors:
        raise SealError("; ".join(errors))
    return {"status": "PASS", "required_fields": len(HOLDOUT_FROZEN_FIELDS), "missing": 0}


def _resolve(root: Path, relative: str) -> Path:
    path = root / relative
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SealError(f"artifact path escapes workspace: {relative}") from exc
    return path


def build_manifest(root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    bindings: dict[str, dict[str, Any]] = {}
    for name, node in seal_input_nodes(graph).items():
        path = _resolve(root, node["path"])
        if not path.exists():
            raise SealError(f"seal input not producible/present: {name} ({node['path']})")
        bindings[name] = {
            "path": node["path"],
            "sha256": sha256_path(path),
            "kind": "directory" if path.is_dir() else "file",
        }
    expected = set(seal_input_nodes(graph))
    if set(bindings) != expected:
        raise SealError("seal binding set differs from artifact graph")
    return {
        "schema_version": "t21-holdout-manifest-v1",
        "artifact": "T21_HOLDOUT_MANIFEST",
        "experiment": contract.experiment,
        "contract_sha256": contract.hash,
        "bindings": bindings,
        "binding_count": len(bindings),
        "freeze_root_sha256": sha256_json(bindings),
    }


def seal_holdout(root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    out = root / "evaluations" / contract.experiment
    manifest_path = out / "holdout_manifest.json"
    marker_path = out / "HOLDOUT_FROZEN"
    if manifest_path.exists() or marker_path.exists():
        raise SealError("seal artifacts already exist")
    schema = read_json(root / contract.get("artifacts.holdout_frozen_schema"))
    validate_holdout_frozen_schema(schema)
    manifest = build_manifest(root, contract, graph)
    write_json(manifest_path, manifest, exclusive=True)
    roots = contract.get("roots")
    marker = {
        "schema_version": "t21-holdout-frozen-v1",
        "experiment": contract.experiment,
        "construction_status": "COMPLETE",
        "holdout_manifest_sha256": sha256_file(manifest_path),
        "freeze_root_sha256": manifest["freeze_root_sha256"],
        "candidate_commit": roots["candidate_commit"],
        "candidate_tree": roots["candidate_tree"],
        "runtime_root": roots["runtime_root"],
        "evaluator_root": roots["evaluator_root"],
        "floor_hash": roots["floor_hash"],
        "construction_attempts": 1,
        "corpus_materializations": 1,
        "suite_materializations": 1,
        "candidate_rows_executed": 0,
        "runtime_rows_executed": 0,
        "official_evaluator_invocations": 0,
    }
    validate_holdout_frozen(marker)
    write_json(marker_path, marker, exclusive=True)
    return {"manifest": manifest, "marker": marker, "status": "PASS"}


def verify_seal(root: Path, contract: Any, graph: dict[str, Any]) -> dict[str, Any]:
    out = root / "evaluations" / contract.experiment
    manifest_path = out / "holdout_manifest.json"
    marker_path = out / "HOLDOUT_FROZEN"
    if not manifest_path.is_file() or not marker_path.is_file():
        raise SealError("seal artifact missing")
    manifest = read_json(manifest_path)
    marker = read_json(marker_path)
    validate_holdout_frozen(marker)
    expected_nodes = seal_input_nodes(graph)
    if set(manifest.get("bindings", {})) != set(expected_nodes):
        raise SealError("seal is missing or contains unexpected bindings")
    for name, node in expected_nodes.items():
        binding = manifest["bindings"][name]
        if binding.get("path") != node["path"]:
            raise SealError(f"seal path mismatch: {name}")
        if sha256_path(_resolve(root, node["path"])) != binding.get("sha256"):
            raise SealError(f"seal hash mismatch: {name}")
    if sha256_json(manifest["bindings"]) != manifest.get("freeze_root_sha256"):
        raise SealError("seal freeze root mismatch")
    if marker["holdout_manifest_sha256"] != sha256_file(manifest_path):
        raise SealError("HOLDOUT_FROZEN manifest binding mismatch")
    if marker["freeze_root_sha256"] != manifest["freeze_root_sha256"]:
        raise SealError("HOLDOUT_FROZEN freeze-root binding mismatch")
    return {
        "status": "PASS",
        "bound": len(manifest["bindings"]),
        "missing_required_bindings": 0,
        "unexpected_bindings": 0,
    }
