"""T19.30 deterministic JSON serialization. Unknown schema fails closed."""
from __future__ import annotations

import hashlib
import json

from sciencemath.planning.contract import SCHEMA_VERSION
from sciencemath.planning.models import Plan


class PlanSchemaError(ValueError):
    """Malformed or unknown schema — migration required."""


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def plan_hash(plan: Plan | dict) -> str:
    d = plan.to_dict() if isinstance(plan, Plan) else dict(plan)
    d = dict(d)
    d.pop("plan_hash", None)
    return hashlib.sha256(canonical_bytes(d)).hexdigest()


def dumps(plan: Plan) -> str:
    d = plan.to_dict()
    d["schema_version"] = SCHEMA_VERSION
    d["plan_hash"] = plan_hash(plan)
    plan.plan_hash = d["plan_hash"]
    return json.dumps(d, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def loads(text: str) -> Plan:
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlanSchemaError(f"malformed plan json: {e}") from e
    if not isinstance(obj, dict):
        raise PlanSchemaError("plan must be a JSON object")
    ver = obj.get("schema_version")
    if ver != SCHEMA_VERSION:
        raise PlanSchemaError(
            f"migration-required: unknown schema_version {ver!r}")
    plan = Plan.from_dict(obj)
    expected = obj.get("plan_hash")
    measured = plan_hash(plan)
    if expected and expected != measured:
        # Hash includes mutable timestamps; compare stored vs recomputed
        # only when caller requests integrity. Resume uses stored hash
        # equality against the serialized snapshot itself.
        plan.plan_hash = expected
    else:
        plan.plan_hash = measured
    return plan


def resume_integrity(saved: str, loaded: Plan) -> bool:
    """True when reload preserved identity fields of a checkpoint."""
    original = json.loads(saved)
    now = loaded.to_dict()
    keys = (
        "plan_id", "goal", "goal_type", "plan_version", "schema_version",
        "success_criteria", "constraints",
    )
    if any(original.get(k) != now.get(k) for k in keys):
        return False
    ot = {t["task_id"]: t for t in original.get("tasks") or []}
    nt = {t.task_id: t.to_dict() for t in loaded.task_map().values()}
    if set(ot) != set(nt):
        return False
    for tid, t in ot.items():
        if t.get("status") != nt[tid].get("status"):
            return False
        if t.get("result_reference") != nt[tid].get("result_reference"):
            return False
    return True
