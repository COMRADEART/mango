"""T19.18–T19.28 replanning, recovery, loops, completion, checkpoints."""
from __future__ import annotations

import hashlib
import json

from sciencemath.planning.contract import (
    FAILURE_CLASSES, PLAN_ABORT, PLAN_BLOCK, PLAN_BUDGET_EXCEEDED,
    PLAN_COMPLETE, PLAN_INSUFFICIENT_CAPABILITY, PLAN_POLICY_BLOCKED,
    PLAN_RECOVER, PLAN_REPLAN,
)
from sciencemath.planning.graph import descendants, dep_map, ready_tasks, task_list
from sciencemath.planning.models import Observation, Plan, Task, snapshot_best, utc_now

REPLAN_TRIGGERS = (
    "dependency_fail", "assumption_invalidated", "tool_unavailable",
    "artifact_changed", "constraint_changed", "goal_changed",
    "evidence_blocks",
)
NON_REPLAN = ("task_succeeded", "metadata", "wording")
NON_PROGRESS_LIMIT = 3


def classify_failure(obs: Observation | dict) -> str:
    d = obs.to_dict() if isinstance(obs, Observation) else dict(obs)
    fc = d.get("failure_class")
    if fc in FAILURE_CLASSES:
        return fc
    blob = " ".join(str(x) for x in (d.get("errors") or [])).lower()
    blob += " " + str(d.get("result_status") or "").lower()
    if "policy" in blob or "permission" in blob:
        return "POLICY_BLOCK"
    if "timeout" in blob or "transient" in blob or "unavailable temporarily" in blob:
        return "TRANSIENT"
    if "missing" in blob or "not found" in blob:
        return "MISSING_INPUT"
    if "assumption" in blob:
        return "INVALID_ASSUMPTION"
    if "capability" in blob or "unsupported" in blob:
        return "CAPABILITY_UNAVAILABLE"
    if "budget" in blob:
        return "BUDGET_EXCEEDED"
    if d.get("result_status") in ("FAILED", "ERROR"):
        return "PERMANENT"
    return "UNKNOWN"


def evidence_set(plan: Plan) -> set[str]:
    ev: set[str] = set()
    for obs in plan.observations or []:
        d = obs if isinstance(obs, dict) else obs.to_dict()
        for a in d.get("artifacts") or []:
            ev.add(str(a))
        for f in d.get("facts") or []:
            ev.add(str(f))
    for t in task_list(plan):
        if t.result_reference:
            ev.add(str(t.result_reference))
        if t.status == "SUCCEEDED":
            ev.update(str(x) for x in (t.expected_outputs or []))
    return ev


def _criterion_met(crit: str, plan: Plan, ev: set[str]) -> bool:
    c = (crit or "").lower()
    blob = " ".join(ev).lower() + " " + plan.status.lower()
    if "all mandatory tasks succeeded" in c:
        return all(t.status in ("SUCCEEDED", "SKIPPED") or t.optional
                   for t in task_list(plan))
    if "required artifacts exist" in c:
        return all(bool(t.result_reference) or t.optional or t.status == "SKIPPED"
                   for t in task_list(plan)
                   if t.status == "SUCCEEDED" or not t.optional)
    if "no unresolved mandatory blocker" in c:
        return not any(t.status == "BLOCKED" and not t.optional
                       for t in task_list(plan))
    if "artifact" in c:
        return any(tok.lower() in blob for tok in c.replace("artifact", "").split()
                   if len(tok) > 3) or any("artifact" in x.lower() for x in ev)
    return any(c in x.lower() for x in ev) or c in blob


def task_satisfied(task: Task, plan: Plan) -> bool:
    if task.optional:
        return True
    if task.status in ("SUCCEEDED", "SKIPPED"):
        return True
    alt_id = f"{task.task_id}-alt"
    for t in task_list(plan):
        if t.task_id == alt_id and t.status in ("SUCCEEDED", "SKIPPED"):
            return True
    return False


def verification_missing(plan: Plan) -> bool:
    for t in task_list(plan):
        if t.optional or str(t.task_id).endswith("-alt"):
            continue
        if t.task_type in ("verify", "test", "freshness") or \
                "verif" in (t.title or "").lower():
            if t.status == "SUCCEEDED" and t.result_reference:
                continue
            alt_ok = any(
                x.task_id == f"{t.task_id}-alt"
                and x.status == "SUCCEEDED" and x.result_reference
                for x in task_list(plan))
            if alt_ok:
                continue
            return True
    return False


def can_complete(plan: Plan) -> bool:
    if plan.status in ("ABORTED", "FAILED"):
        return False
    tasks = task_list(plan)
    if not tasks:
        return False
    if verification_missing(plan):
        return False
    for t in tasks:
        if t.optional:
            continue
        if t.status == "INVALIDATED":
            return False
        if t.status == "BLOCKED":
            return False
        if not task_satisfied(t, plan):
            return False
        if t.status == "SUCCEEDED" and not t.result_reference:
            alt_ok = any(
                x.task_id == f"{t.task_id}-alt" and x.result_reference
                for x in task_list(plan))
            if not alt_ok:
                return False
    ev = evidence_set(plan)
    for crit in plan.success_criteria or []:
        if not _criterion_met(str(crit), plan, ev):
            # Structural criteria already checked via task statuses.
            if "mandatory" in str(crit).lower() or "blocker" in str(crit).lower() \
                    or "artifact" in str(crit).lower():
                continue
            if not ev:
                return False
    return True


def completion_decision(plan: Plan) -> tuple[str, list[str]]:
    if can_complete(plan):
        evidence = sorted(evidence_set(plan))
        return PLAN_COMPLETE, evidence
    return "", []


def should_replan(trigger: str | None) -> bool:
    if not trigger:
        return False
    if trigger in NON_REPLAN:
        return False
    return trigger in REPLAN_TRIGGERS


def infer_trigger(obs: Observation | dict, req: dict | None = None) -> str | None:
    req = req or {}
    if req.get("goal_changed"):
        return "goal_changed"
    if req.get("constraint_changed"):
        return "constraint_changed"
    d = obs.to_dict() if isinstance(obs, Observation) else dict(obs or {})
    fc = classify_failure(d) if d.get("result_status") in ("FAILED", "ERROR") else None
    if fc == "INVALID_ASSUMPTION":
        return "assumption_invalidated"
    if fc == "CAPABILITY_UNAVAILABLE":
        return "tool_unavailable"
    if fc in ("PERMANENT", "MISSING_INPUT"):
        return "dependency_fail"
    if d.get("artifact_changed"):
        return "artifact_changed"
    if d.get("blocks_path") or fc == "POLICY_BLOCK":
        return "evidence_blocks"
    if d.get("result_status") == "SUCCEEDED":
        return None
    return None


def state_fingerprint(plan: Plan) -> str:
    rows = []
    for t in task_list(plan):
        rows.append((t.task_id, t.status, t.attempt_count, t.result_reference))
    blob = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def loop_detected(plan: Plan) -> bool:
    hist = [r.get("fingerprint") for r in (plan.history or [])
            if isinstance(r, dict) and r.get("fingerprint")]
    fp = state_fingerprint(plan)
    if hist.count(fp) >= 2:
        return True
    triggers = [r.get("replan_trigger") for r in (plan.history or [])
                if r.get("replan_trigger")]
    if len(triggers) >= 4:
        a, b = triggers[-2], triggers[-1]
        if a and b and a != b and triggers[-4:-2] == [a, b]:
            return True
    for t in task_list(plan):
        if t.attempt_count > t.max_attempts:
            return True
    return False


def progress_signal(before: dict, plan: Plan) -> bool:
    after = {
        "completed": {t.task_id for t in task_list(plan) if t.status == "SUCCEEDED"},
        "artifacts": evidence_set(plan),
        "blockers": {t.task_id for t in task_list(plan) if t.status == "BLOCKED"},
        "verified_assumptions": {
            a.get("assumption_id") if isinstance(a, dict) else a.assumption_id
            for a in (plan.assumptions or [])
            if (a.get("status") if isinstance(a, dict) else a.status) == "VERIFIED"
        },
    }
    if len(after["completed"]) > len(before.get("completed") or []):
        return True
    if len(after["artifacts"]) > len(before.get("artifacts") or []):
        return True
    if len(after["verified_assumptions"]) > len(before.get("verified_assumptions") or []):
        return True
    if len(after["blockers"]) < len(before.get("blockers") or set()):
        return True
    return False


def snapshot_progress(plan: Plan) -> dict:
    return {
        "completed": {t.task_id for t in task_list(plan) if t.status == "SUCCEEDED"},
        "artifacts": evidence_set(plan),
        "blockers": {t.task_id for t in task_list(plan) if t.status == "BLOCKED"},
        "verified_assumptions": {
            a.get("assumption_id") if isinstance(a, dict) else a.assumption_id
            for a in (plan.assumptions or [])
            if (a.get("status") if isinstance(a, dict) else a.status) == "VERIFIED"
        },
    }


def invalidate_downstream(plan: Plan, task_id: str) -> list[str]:
    deps = dep_map(plan)
    down = descendants(task_id, deps)
    changed = []
    by = {t.task_id: t for t in task_list(plan)}
    for tid in down:
        t = by[tid]
        if t.status == "SUCCEEDED":
            t.status = "INVALIDATED"
            t.result_reference = None
            changed.append(tid)
        elif t.status not in ("PENDING", "INVALIDATED"):
            t.status = "INVALIDATED"
            changed.append(tid)
        else:
            t.status = "INVALIDATED"
            changed.append(tid)
    plan.tasks = list(by.values())
    plan.best_verified = snapshot_best(plan)
    return changed


def preserve_unrelated(plan: Plan, changed_id: str) -> None:
    deps = dep_map(plan)
    down = descendants(changed_id, deps) | {changed_id}
    by = {t.task_id: t for t in task_list(plan)}
    kept = []
    for tid, t in by.items():
        if tid in down:
            continue
        if t.status == "SUCCEEDED" and t.result_reference:
            kept.append(tid)
    plan.best_verified = snapshot_best(plan)
    plan.decision_metadata = list(plan.decision_metadata or []) + [{
        "progress_preserved": kept,
        "invalidated": sorted(down),
    }]


def _add_alternate(plan: Plan, task: Task) -> bool:
    """One bounded alternate path; rewire dependents onto it."""
    alt_id = f"{task.task_id}-alt"
    if any(x.task_id == alt_id for x in task_list(plan)):
        return False
    alt = Task(
        task_id=alt_id,
        title="Alternate path: " + task.title,
        objective="Recover via alternate path after permanent failure",
        task_type=task.task_type,
        required_skill=task.required_skill,
        required_inputs=list(task.required_inputs),
        expected_outputs=list(task.expected_outputs),
        preconditions=list(task.preconditions),
        postconditions=list(task.postconditions),
        success_criteria=list(task.success_criteria),
        failure_conditions=list(task.failure_conditions),
        dependencies=list(task.dependencies),
        max_attempts=task.max_attempts,
        estimated_cost_class=task.estimated_cost_class,
        network_required=task.network_required,
        side_effect_class=task.side_effect_class,
        execution_authority=False,
        approval_required=task.approval_required,
        approval_reason=task.approval_reason,
        rationale={"replan_trigger": "dependency_fail",
                   "alternate_of": task.task_id},
    )
    for other in task_list(plan):
        if task.task_id in (other.dependencies or []):
            other.dependencies = [
                alt_id if d == task.task_id else d
                for d in other.dependencies
            ]
    rewritten = []
    for edge in plan.dependencies or []:
        if isinstance(edge, dict):
            src, dst = edge.get("from"), edge.get("to")
            if src == task.task_id:
                rewritten.append({**edge, "from": alt_id})
            else:
                rewritten.append(edge)
        elif isinstance(edge, (list, tuple)) and len(edge) == 2:
            src, dst = edge[0], edge[1]
            rewritten.append([alt_id if src == task.task_id else src, dst])
        else:
            rewritten.append(edge)
    for parent in alt.dependencies or []:
        rewritten.append({"from": parent, "to": alt_id,
                          "reason": "alternate_path"})
    plan.dependencies = rewritten
    plan.tasks = task_list(plan) + [alt]
    task.status = "FAILED"
    return True


def recover(plan: Plan, task: Task, failure_class: str, now: str | None = None) -> str:
    """Apply class-specific recovery. Returns planner op."""
    if failure_class == "TRANSIENT":
        if task.attempt_count < task.max_attempts:
            task.status = "PENDING"
            return PLAN_RECOVER
        plan.status = "BLOCKED"
        plan.blocked_reason = "transient retries exhausted"
        return PLAN_BLOCK
    if failure_class == "POLICY_BLOCK":
        task.status = "BLOCKED"
        plan.status = "BLOCKED"
        plan.blocked_reason = "policy block cannot be bypassed"
        return PLAN_POLICY_BLOCKED
    if failure_class == "CAPABILITY_UNAVAILABLE":
        task.status = "BLOCKED"
        plan.status = "BLOCKED"
        plan.blocked_reason = "required capability unavailable"
        return PLAN_INSUFFICIENT_CAPABILITY
    if failure_class == "BUDGET_EXCEEDED":
        task.status = "BLOCKED"
        plan.status = "FAILED"
        plan.blocked_reason = "budget exceeded"
        return PLAN_BUDGET_EXCEEDED
    if failure_class == "INVALID_ASSUMPTION":
        invalidate_downstream(plan, task.task_id)
        preserve_unrelated(plan, task.task_id)
        if _add_alternate(plan, task):
            plan.status = "NEEDS_REPLAN"
            return PLAN_REPLAN
        task.status = "BLOCKED"
        plan.status = "BLOCKED"
        plan.blocked_reason = "assumption invalidated; no remaining alternate"
        return PLAN_BLOCK
    if failure_class == "UNKNOWN":
        if task.attempt_count < min(2, task.max_attempts):
            task.status = "PENDING"
            return PLAN_RECOVER
        plan.status = "BLOCKED"
        plan.blocked_reason = "non-progress"
        return PLAN_BLOCK
    if failure_class in ("PERMANENT", "MISSING_INPUT"):
        if _add_alternate(plan, task):
            plan.status = "NEEDS_REPLAN"
            return PLAN_REPLAN
        task.status = "BLOCKED"
        plan.status = "BLOCKED"
        plan.blocked_reason = "permanent failure; no remaining alternate"
        return PLAN_BLOCK
    task.status = "BLOCKED"
    plan.status = "BLOCKED"
    return PLAN_BLOCK


def maybe_checkpoint(plan: Plan, now: str | None = None) -> dict | None:
    tasks = task_list(plan)
    if len(tasks) < 4:
        return None
    completed = [t.task_id for t in tasks if t.status == "SUCCEEDED"]
    if not completed:
        return None
    interval = 4
    if len(completed) % interval != 0 and plan.status not in (
            "BLOCKED", "COMPLETE", "ABORTED"):
        if not (plan.status == "IN_PROGRESS" and len(completed) >= 3
                and not plan.checkpoints):
            return None
    rec = {
        "checkpoint_id": f"cp{len(plan.checkpoints)+1:02d}",
        "timestamp": utc_now(now),
        "completed_tasks": completed,
        "remaining_tasks": [t.task_id for t in tasks
                            if t.status not in ("SUCCEEDED", "SKIPPED")],
        "constraints": list(plan.constraints),
        "budget_consumed": {
            k: plan.budget.get(k) for k in plan.budget
            if k.startswith("consumed")
        },
        "open_blockers": [t.task_id for t in tasks if t.status == "BLOCKED"],
        "verified_artifacts": sorted(evidence_set(plan)),
        "assumptions": list(plan.assumptions),
        "plan_hash": plan.plan_hash,
        "plan_version": plan.plan_version,
    }
    plan.checkpoints = list(plan.checkpoints or []) + [rec]
    return rec


def apply_observation(plan: Plan, obs: Observation, now: str | None = None) -> str:
    by = {t.task_id: t for t in task_list(plan)}
    task = by.get(obs.task_id)
    if task is None:
        plan.blocked_reason = "observation for unknown task"
        return PLAN_BLOCK
    task.attempt_count += 1
    task.observations = list(task.observations or []) + [obs.to_dict()]
    plan.observations = list(plan.observations or []) + [obs.to_dict()]
    if task.attempt_count > task.max_attempts and obs.result_status != "SUCCEEDED":
        plan.status = "BLOCKED"
        plan.blocked_reason = "unbounded retry refused"
        task.status = "FAILED"
        return PLAN_BLOCK
    if obs.result_status in ("SUCCEEDED", "SUCCESS", "OK"):
        task.status = "SUCCEEDED"
        arts = list(obs.artifacts or [])
        task.result_reference = arts[0] if arts else f"{task.task_id}.artifact"
        plan.best_verified = snapshot_best(plan)
        plan.status = "IN_PROGRESS"
        return "OBSERVED_SUCCESS"
    fc = classify_failure(obs)
    task.status = "FAILED"
    return recover(plan, task, fc, now)


def note_history(plan: Plan, **kwargs) -> None:
    rec = {"fingerprint": state_fingerprint(plan), **kwargs}
    plan.history = list(plan.history or []) + [rec]
