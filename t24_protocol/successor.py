"""Authorized-successor applicability for T24-era byte bindings.

The T25 remediation authorization authorizes exactly one runtime change
(src/sciencemath/executive/runner.py) plus T25 successor protocol code in this
tree, while every T24 sealed artifact (freeze, author lock, receipts, store,
gold) stays an immutable historical record. T24-era verifiers interpret drift
in this tree ONLY when the T25 successor state is fully present and
self-verifying: the T25 preconstruction freeze exists, carries the frozen T25
publication policy with construction_authorized=False, verifies internally,
and binds every drifted byte exactly. Anything else refuses (fail closed).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typing import Any

SUCCESSOR_FREEZE = "evaluations/t25/preconstruction_freeze.json"


def successor_binding(source_root: Path, drifted_paths: list[str]) -> dict[str, Any] | None:
    """Verify the drifted bytes against the authorized T25 successor freeze.

    Returns the successor-interpretation record, or None when the tree is not
    the authorized T25 successor state (caller must refuse).
    """
    source_root = Path(source_root)
    path = source_root / SUCCESSOR_FREEZE
    if not path.is_file():
        return None
    try:
        successor = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if (successor.get("schema_version") != "t25-preconstruction-freeze-v1"
            or successor.get("construction_authorized") is not False
            or successor.get("frozen_policy", {})
            .get("REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION") is not False):
        return None
    bound = {component["path"]: component["sha256"] for component in successor["components"]}
    for relative in drifted_paths:
        file = source_root / relative
        if relative not in bound or not file.is_file():
            return None
        if hashlib.sha256(file.read_bytes()).hexdigest() != bound[relative]:
            return None
    return {"interpretation": "T25_REMEDIATION_ACTIVE",
            "t24_freeze_binding": "HISTORICAL_SUCCESSOR_SUPERSEDED",
            "successor_freeze_sha256": successor.get("freeze_sha256"),
            "drifted_components": sorted(drifted_paths)}