"""T20.71 run serialization: canonical run JSON + integrity hash.

Same conventions as planning/serialize.py: LF-normalized canonical bytes,
sha256 identity, resume integrity by canonical comparison.
"""
from __future__ import annotations

import hashlib
import json

from sciencemath.orchestration.models import OrchestrationRun


class RunSchemaError(ValueError):
    """Run serialization schema violation."""


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def run_hash(run: OrchestrationRun | dict) -> str:
    d = run.to_dict() if isinstance(run, OrchestrationRun) else dict(run)
    d.pop("run_hash", None)
    return hashlib.sha256(canonical_bytes(d)).hexdigest()


def dumps(run: OrchestrationRun) -> str:
    return json.dumps(run.to_dict(), sort_keys=True, ensure_ascii=False,
                      indent=2)


def loads(text: str) -> OrchestrationRun:
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        raise RunSchemaError(f"invalid run json: {e}") from e
    if not isinstance(d, dict) or "run_id" not in d or "plan_id" not in d:
        raise RunSchemaError("run payload missing run_id/plan_id")
    return OrchestrationRun.from_dict(d)


def resume_integrity(saved: OrchestrationRun, loaded: OrchestrationRun
                     ) -> list[str]:
    """T20.72 invariants as serialization-level checks. Empty = intact."""
    errs: list[str] = []
    if run_hash(saved) != run_hash(loaded) and \
            loaded.steps < saved.steps:
        errs.append("run_state_regressed")
    if loaded.budgets.get("consumed_revisions", 0) < \
            saved.budgets.get("consumed_revisions", 0):
        errs.append("budget_reset")
    if len(loaded.events) < len(saved.events):
        errs.append("event_log_truncated")
    return errs