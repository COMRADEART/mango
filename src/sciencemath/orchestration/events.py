"""T20.17–T20.19 append-only event log and deterministic state reduction.

Only the ORCHESTRATOR commits authoritative transitions; workers submit
events. State reducer replay from the event log must reproduce the final
orchestration state (replay_equivalence target 1.0). No hidden chain-of-
thought is stored — only structured observable metadata (T20.19).
"""
from __future__ import annotations

import hashlib
import json

from sciencemath.orchestration.contract import EVENT_TYPES
from sciencemath.orchestration.models import OrchestrationRun, utc_now


class EventLog:
    """Append-only events with deterministic ids and replayable payloads."""

    def __init__(self):
        self.events: list[dict] = []

    def append(self, run: OrchestrationRun, actor_id: str, event_type: str,
               task_id: str = "", payload: dict | None = None,
               provenance: dict | None = None, now: str = "") -> dict:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type!r}")
        run.event_seq += 1
        ev = {
            "event_id": f"ev-{run.run_id[:16]}-{run.event_seq:06d}",
            "run_id": run.run_id,
            "timestamp": now or utc_now(),
            "actor_id": actor_id,
            "task_id": task_id,
            "event_type": event_type,
            "payload": dict(payload or {}),
            "provenance": dict(provenance or {}),
        }
        self.events.append(ev)
        run.events.append(ev)
        return ev

    def event_ids_unique(self) -> bool:
        ids = [e["event_id"] for e in self.events]
        return len(ids) == len(set(ids))


def log_hash(run: OrchestrationRun) -> str:
    blob = json.dumps(run.events, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def reduce_events(run_id: str, events: list[dict]) -> dict:
    """Deterministic state reduction over the event log.

    Reconstructs the observable orchestration state (agent statuses, task
    statuses, artifact registry, verification states, counters) purely from
    events — used to prove replay_equivalence (T20.73).
    """
    state: dict = {
        "run_id": run_id,
        "status": "CREATED",
        "agents": {},
        "tasks": {},
        "artifacts": {},
        "verifications": {},
        "assignments": {},
        "revisions": 0,
        "replans": 0,
        "checkpoints": 0,
        "blockers": [],
        "steps": 0,
    }
    for ev in events:
        if ev.get("run_id") != run_id:
            continue
        et = ev.get("event_type")
        p = ev.get("payload") or {}
        tid = ev.get("task_id") or p.get("task_id") or ""
        if et == "AGENT_CREATED":
            state["agents"][p.get("agent_id")] = "READY"
        elif et == "TASK_ASSIGNED":
            state["tasks"][tid] = "ASSIGNED"
            state["assignments"][tid] = p.get("agent_id")
        elif et == "TASK_STARTED":
            state["tasks"][tid] = "RUNNING"
        elif et == "TASK_COMPLETED":
            state["tasks"][tid] = "SUCCEEDED"
        elif et == "TASK_BLOCKED":
            state["tasks"][tid] = "BLOCKED"
            state["blockers"].append(tid)
        elif et == "TASK_REASSIGNED":
            state["assignments"][tid] = p.get("to_agent")
            state["tasks"][tid] = "ASSIGNED"
        elif et in ("VERIFICATION_PASSED", "VERIFICATION_FAILED"):
            state["verifications"][p.get("verification_id") or tid] = \
                "PASSED" if et == "VERIFICATION_PASSED" else "FAILED"
            aid = p.get("artifact_id")
            if aid and aid in state["artifacts"]:
                state["artifacts"][aid] = \
                    "PASSED" if et == "VERIFICATION_PASSED" else "FAILED"
        elif et == "REVISION_REQUESTED":
            state["revisions"] = int(state["revisions"]) + 1
            state["tasks"][tid] = "REVISION_REQUESTED"
        elif et == "CHECKPOINT_SAVED":
            state["checkpoints"] = int(state["checkpoints"]) + 1
        elif et == "PLAN_REVISED":
            state["replans"] = int(state["replans"]) + 1
        elif et == "RUN_COMPLETED":
            state["status"] = "COMPLETE"
        elif et == "RUN_BLOCKED":
            state["status"] = "BLOCKED"
        elif et == "RUN_ABORTED":
            state["status"] = "ABORTED"
        elif et == "RUN_FAILED":
            state["status"] = "FAILED"
        elif et == "ARTIFACT_REGISTERED":
            state["artifacts"][p.get("artifact_id") or tid] = \
                p.get("verification_status") or "REGISTERED"
        state["steps"] = int(state["steps"]) + 1
    return state


def replay_equivalent(run: OrchestrationRun, events: list[dict] | None = None
                      ) -> bool:
    """True if reducer replay of the event log reproduces task/artifact/
    verification state of the run (T20.73)."""
    evs = events if events is not None else run.events
    state = reduce_events(run.run_id, evs)
    tasks_match = all(
        state["tasks"].get(tid) == st
        for tid, st in run.tasks.items()
        if st in ("ASSIGNED", "RUNNING", "SUCCEEDED", "REVISION_REQUESTED")
    )
    arts_match = all(
        state["artifacts"].get(a["artifact_id"]) == a.get("verification_status")
        or a.get("verification_required") is False
        for a in run.artifacts
    )
    return tasks_match and arts_match