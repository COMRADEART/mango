"""T20.29/T20.31–T20.34/T20.47 recovery: livelock detection, failure
classification, bounded revisions, agent-failure recovery, selective
reassignment.

One worker failure must not reset the whole run (T20.33). Recovery actions
depend on the failure class (T20.32). Completed verified work is retained
on replan or worker failure (T20.46).
"""
from __future__ import annotations

from sciencemath.orchestration.contract import (
    FAILURE_CLASSES, LIVELOCK_FINGERPRINT_LIMIT,
)
from sciencemath.orchestration.models import deterministic_id


def classify_failure(worker_result: dict, context: dict | None = None
                     ) -> str:
    """T20.32 failure classification. Recovery depends on the class."""
    ctx = context or {}
    errors = [str(e).lower() for e in (worker_result.get("errors") or [])]
    fc = worker_result.get("failure_class")
    blob = " ".join(errors)
    if ctx.get("class"):
        c = ctx["class"]
        return c if c in FAILURE_CLASSES else "UNKNOWN"
    if fc in FAILURE_CLASSES:
        return fc
    if "timeout" in blob or "crashed" in blob:
        return "AGENT_CRASH"
    if "verification" in blob:
        return "VERIFICATION_FAIL"
    if "policy" in blob:
        return "POLICY_BLOCK"
    if "budget" in blob:
        return "BUDGET_EXCEEDED"
    if "artifact" in blob:
        return "MISSING_ARTIFACT"
    if "conflict" in blob:
        return "RESOURCE_CONFLICT"
    if "capability" in blob or "skill" in blob:
        return "CAPABILITY_MISMATCH"
    if "invalid" in blob or "schema" in blob:
        return "INVALID_INPUT"
    if worker_result.get("result_status") == "FAILED":
        return ctx.get("default") or "TRANSIENT"
    return "UNKNOWN"


RECOVERY_ACTIONS = {
    "TRANSIENT": "retry_or_reassign",
    "PERMANENT": "replan_or_block",
    "INVALID_INPUT": "revise_or_block",
    "MISSING_ARTIFACT": "recover_dependency",
    "CAPABILITY_MISMATCH": "reassign_same_role_or_block",
    "VERIFICATION_FAIL": "bounded_revision",
    "POLICY_BLOCK": "block",
    "DEPENDENCY_FAIL": "replan_or_block",
    "RESOURCE_CONFLICT": "serialize_retry",
    "BUDGET_EXCEEDED": "block",
    "AGENT_CRASH": "reassign_or_recover",
    "UNKNOWN": "block_or_replan",
}


def recovery_action(failure_class: str) -> str:
    return RECOVERY_ACTIONS.get(failure_class, "block_or_replan")


def bounded_revision_ok(run: dict, task_id: str, max_per_task: int = 2
                        ) -> bool:
    """T20.31 bounded revisions: no unlimited try-again."""
    used = sum(1 for r in (run.get("revisions") or [])
               if r.get("task_id") == task_id)
    if used >= max_per_task:
        return False
    if int((run.get("budgets") or {}).get("consumed_revisions") or 0) >= \
            int((run.get("budgets") or {}).get("max_revisions") or 12):
        return False
    return True


def livelock_fingerprint(run: dict) -> str:
    """Semantic state fingerprint for livelock detection (T20.29).

    Repeated identical fingerprints with no progress indicate livelock;
    unbounded livelock tolerance is 0.
    """
    import json
    plan = run.get("plan") or {}
    fp = {
        "statuses": {t.get("task_id"): t.get("status")
                     for t in (plan.get("tasks") or [])},
        "plan_version": plan.get("plan_version"),
        "revisions": len(run.get("revisions") or []),
        "replans": (run.get("budgets") or {}).get("consumed_replans", 0),
    }
    blob = json.dumps(fp, sort_keys=True)
    return deterministic_id("lfp_", blob)


def livelock_detected(run: dict, limit: int = LIVELOCK_FINGERPRINT_LIMIT
                      ) -> bool:
    """Track fingerprint history; the same fingerprint repeated `limit`
    times means repeated state transitions with no progress."""
    fp = livelock_fingerprint(run)
    history = list(run.get("fingerprints") or []) + [fp]
    tail = history[-limit:]
    return len(tail) == limit and len(set(tail)) == 1


def agent_failed_ok_to_recover(run: dict, agent_id: str,
                               max_failed: int = 3) -> bool:
    """Per-agent failure bound (T20.31): max_failed_tasks bounded."""
    fails = sum(1 for a in (run.get("assignments") or [])
                if a.get("agent_id") == agent_id
                and a.get("status") == "FAILED")
    return fails < max_failed


def recoverable_tasks(plan: dict, exclude: set[str] | None = None) -> list:
    """Completed verified tasks that must be preserved (T20.46)."""
    keep = []
    for t in (plan.get("tasks") or []):
        if t.get("status") == "SUCCEEDED" and \
                t.get("task_id") not in (exclude or set()):
            keep.append(t)
    return keep


def unrelated_completed_work_loss(plan_before: dict, plan_after: dict,
                                  changed_id: str | None) -> int:
    """T20.46: unrelated completed work loss must be 0."""
    before = {t.get("task_id") for t in (plan_before.get("tasks") or [])
              if t.get("status") == "SUCCEEDED"}
    after = {t.get("task_id") for t in (plan_after.get("tasks") or [])
             if t.get("status") == "SUCCEEDED"}
    if changed_id:
        after |= descendants_of(plan_after, changed_id) | {changed_id}
    return len(before - after)


def descendants_of(plan: dict, task_id: str) -> set[str]:
    deps: dict[str, list[str]] = {}
    for d in plan.get("dependencies") or []:
        deps.setdefault(d.get("from") or "", []).append(d.get("to") or "")
    out: set[str] = set()
    stack = [task_id]
    while stack:
        cur = stack.pop()
        for nxt in deps.get(cur, ()):
            if nxt not in out:
                out.add(nxt)
                stack.append(nxt)
    return out