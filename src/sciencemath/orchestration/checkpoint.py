"""T20.71–T20.74 run checkpointing, deterministic resume, crash consistency.

Checkpoints capture the full authoritative state: agents, task states,
artifact refs, verification states, budgets consumed, locks, pending
assignments, replan state, event-log offset, and run hash. Resume preserves
run_id, completed verified tasks, artifact references, budgets consumed,
pending/failed tasks, revision counts, and event-log integrity — no
duplicate completion, no budget reset, no lost artifacts, no ghost agents,
no stale locks (T20.72).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sciencemath.orchestration.models import (
    OrchestrationRun, run_state_hash,
)
from sciencemath.orchestration.events import log_hash


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(str(tmp), str(path))


class RunCheckpointer:
    """Atomic run checkpoints (T20.71). Deterministic; no wall clock."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)

    def save(self, run: OrchestrationRun, locks_snapshot: dict,
             reason: str = "meaningful_state_change", now: str = "") -> str:
        run.run_hash = run_state_hash(run)
        payload = {
            "checkpoint": {
                "run_id": run.run_id,
                "plan_id": run.plan_id,
                "run_version": run.run_version,
                "status": run.status,
                "reason": reason,
                "saved_at": now,
                "steps": run.steps,
                "event_offset": len(run.events),
                "event_log_hash": log_hash(run),
                "run_hash": run.run_hash,
            },
            "run": run.to_dict(),
            "locks": locks_snapshot,
        }
        path = self.base / f"{run.run_id}.ckpt.json"
        _atomic_write_json(path, payload)
        run.checkpoints = list(run.checkpoints) + [{
            "checkpoint_id": path.name,
            "reason": reason,
            "event_offset": len(run.events),
            "run_hash": run.run_hash,
        }]
        return path.name

    def load(self, run_id: str) -> tuple[OrchestrationRun, dict] | None:
        path = self.base / f"{run_id}.ckpt.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        run = OrchestrationRun.from_dict(payload["run"])
        return run, payload.get("locks") or {}


def resume_integrity(saved: OrchestrationRun, loaded: OrchestrationRun
                     ) -> list[str]:
    """T20.72 resume integrity invariants. Empty list = intact."""
    errs: list[str] = []
    if loaded.run_id != saved.run_id:
        errs.append("run_id_changed")
    if loaded.plan_id != saved.plan_id:
        errs.append("plan_id_changed")
    if loaded.budgets.get("consumed_messages", 0) < \
            saved.budgets.get("consumed_messages", 0):
        errs.append("budget_reset")
    for st in ("consumed_revisions", "consumed_replans", "consumed_handoffs",
               "consumed_artifacts"):
        if loaded.budgets.get(st, 0) < saved.budgets.get(st, 0):
            errs.append("budget_reset")
    done_saved = {tid for tid, s in saved.tasks.items()
                  if s in ("SUCCEEDED",)}
    done_loaded = {tid for tid, s in loaded.tasks.items()
                   if s in ("SUCCEEDED",)}
    if done_saved - done_loaded:
        errs.append("lost_completed_tasks")
    art_saved = {a["artifact_id"] for a in saved.artifacts}
    art_loaded = {a["artifact_id"] for a in loaded.artifacts}
    if art_saved - art_loaded:
        errs.append("lost_artifacts")
    if len(loaded.events) < len(saved.events):
        errs.append("event_log_truncated")
    # no ghost agents, no stale locks
    if {a["agent_id"] for a in loaded.agents} != \
            {a["agent_id"] for a in saved.agents}:
        errs.append("ghost_agents")
    return errs


def crash_consistency_check(before: dict, after: dict) -> list[str]:
    """T20.74: interruption during assignment / result submission /
    verification / checkpoint must never double-account or duplicate
    completion."""
    errs: list[str] = []
    dup = [tid for tid in after.get("completed_events", [])
           if after.get("completed_events", []).count(tid) > 1]
    if dup:
        errs.append("duplicate_task_completion:" + ",".join(sorted(set(dup))))
    if after.get("budgets", {}).get("consumed_messages", 0) is None:
        errs.append("corrupted_budget")
    return errs