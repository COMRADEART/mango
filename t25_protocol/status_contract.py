"""T25 capability-status contract (authorization §6, §21).

Loads the machine-readable status taxonomy established by the T25
remediation authorization (evaluations/t25/remediation/
T25_STATUS_TAXONOMY_CONTRACT.json) and exposes the fail-closed boundary
validation used by the T25 evaluation layer: a capability status must be
a member of that capability's closed status set. UNKNOWN, empty,
missing, and non-string statuses are rejected; any value outside the
closed set is an invalid enum and fails closed. The frozen dispatch
evaluator's UNKNOWN=>unmatched rule (t23_protocol.evaluation) remains
the matching backstop and is not modified by this module.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = _ROOT / "evaluations" / "t25" / "remediation" / \
    "T25_STATUS_TAXONOMY_CONTRACT.json"

UNKNOWN_STATUS = "UNKNOWN"


@lru_cache(maxsize=1)
def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def status_set(capability: str) -> frozenset[str]:
    sets = load_contract()["closed_status_sets"]
    if capability not in sets:
        raise KeyError(f"capability {capability!r} not in the T25 status contract")
    return frozenset(sets[capability]["statuses"])


def validate_status(capability: str, status: object) -> tuple[bool, str]:
    """Fail-closed boundary validation. Returns (ok, reason)."""
    if not isinstance(status, str):
        return False, "status_not_a_string"
    if not status.strip():
        return False, "status_empty"
    if status == UNKNOWN_STATUS:
        return False, "unknown_status_must_not_terminate_a_dispatch"
    if status not in status_set(capability):
        return False, "status_outside_closed_set"
    return True, ""


def assert_status_valid(capability: str, status: object) -> None:
    ok, reason = validate_status(capability, status)
    if not ok:
        raise ValueError(f"T25 status contract violation ({reason}): "
                         f"{capability}[{status!r}]")


def validate_dispatch_rows(rows: list[dict]) -> dict:
    """Validate a full capability-evaluator row list (dispatch_match rows
    as produced by t23_protocol.evaluation.evaluate_capability). A row
    whose status is not a member of its selected capability's closed set
    fails closed regardless of the frozen match rule."""
    violations = []
    for row in rows:
        capability = row.get("selected_capability")
        status = row.get("status")
        ok, reason = validate_status(capability, status)
        if not ok:
            violations.append({"case_id": row.get("case_id"),
                               "capability": capability,
                               "status": status, "reason": reason})
    return {"rows": len(rows), "violations": violations,
            "status": "PASS" if not violations else "FAIL"}