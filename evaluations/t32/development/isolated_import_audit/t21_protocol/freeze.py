"""Runtime/evaluator freeze creation and verification."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .util import read_json, sha256_file, sha256_json


def component_map(root: Path, paths: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in sorted(set(paths)):
        path = root / relative
        if not path.is_file():
            raise ValidationError(f"freeze component missing: {relative}")
        result[Path(relative).as_posix()] = sha256_file(path)
    if not result:
        raise ValidationError("freeze component set is empty")
    return result


def component_root(components: dict[str, str]) -> str:
    return sha256_json(components)


def build_freeze(
    root: Path,
    paths: Iterable[str],
    *,
    artifact: str,
    experiment: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    components = component_map(root, paths)
    return {
        "schema_version": "t21-component-freeze-v1",
        "artifact": artifact,
        "experiment": experiment,
        "status": "FROZEN",
        "runtime_execution_count": 0,
        "component_sha256": components,
        "component_root_sha256": component_root(components),
        **(extra or {}),
    }


def verify_freeze(root: Path, freeze_or_path: dict[str, Any] | Path, *, artifact: str | None = None) -> dict[str, Any]:
    freeze = read_json(freeze_or_path) if isinstance(freeze_or_path, Path) else freeze_or_path
    if artifact is not None and freeze.get("artifact") != artifact:
        raise ValidationError("freeze artifact identity mismatch")
    if freeze.get("status") != "FROZEN" or freeze.get("runtime_execution_count") != 0:
        raise ValidationError("component freeze is not pristine")
    components = freeze.get("component_sha256")
    if not isinstance(components, dict) or not components:
        raise ValidationError("component freeze has no components")
    for relative, expected in components.items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise ValidationError(f"frozen component mismatch: {relative}")
    actual_root = component_root(components)
    expected_root = freeze.get("component_root_sha256", freeze.get("root_sha256"))
    if actual_root != expected_root:
        raise ValidationError("component freeze root mismatch")
    return {"status": "VERIFIED", "components": len(components), "root": actual_root}
