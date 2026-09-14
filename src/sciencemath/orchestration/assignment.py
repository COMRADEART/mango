"""T20.24–T20.30 deterministic task assignment and bounded parallelism.

Assignment uses task.required_skill, preconditions, dependency state, agent
availability, capability manifests, budgets, concurrency limits, and
verification separation. No free-form role guessing (T20.24). Conflicting
tasks serialize; independent tasks may run in the same bounded batch
(T20.25/T20.26). Duplicate exclusive execution is prevented (T20.30).
"""
from __future__ import annotations

from sciencemath.orchestration.contract import (
    MAX_CONCURRENT_VERIFIERS, MAX_CONCURRENT_WORKERS, MAX_WORKER_AGENTS,
)
from sciencemath.orchestration.locks import resources_for_task
from sciencemath.orchestration.manifests import (
    SKILL_TO_ROLE, skill_permitted, worker_role_for_skill,
)


def worker_role_for_task(task: dict) -> str | None:
    return worker_role_for_skill(task.get("required_skill") or "")


def agents_for_role(agents: dict[str, dict], role: str) -> list[dict]:
    return sorted(
        (a for a in agents.values() if a["role"] == role
         and a.get("status") in ("READY", "BUSY", "WAITING")),
        key=lambda a: a["agent_id"],
    )


def agent_for_skill(agents: dict[str, dict], skill_id: str,
                    exclude: set[str] | None = None) -> dict | None:
    """Deterministic manifest-based pick (T20.24): the skill's mapped role
    first, then any agent whose manifest permits the skill."""
    role = SKILL_TO_ROLE.get(skill_id or "")
    candidates = agents_for_role(agents, role or "")
    for a in candidates:
        if a["agent_id"] in (exclude or set()):
            continue
        if skill_permitted_agent(a, skill_id):
            return a
    return None


def skill_permitted_agent(agent: dict, skill_id: str) -> bool:
    if skill_id in (agent.get("denied_skills") or []):
        return False
    return skill_id in (agent.get("allowed_skills") or [])


def ready_plan_tasks(plan: dict) -> list[dict]:
    """Dependency-satisfied plan tasks in deterministic order.

    A task is ready when every dependency is SUCCEEDED and the task itself
    is PENDING. Uses the plan's dependency edges (from -> to).
    """
    tasks = plan.get("tasks") or []
    deps = plan.get("dependencies") or []
    by_id = {t["task_id"]: t for t in tasks}
    ok_deps: dict[str, set[str]] = {}
    for d in deps:
        ok_deps.setdefault(d.get("to") or "", set()).add(d.get("from") or "")
    out = []
    for t in sorted(tasks, key=lambda x: x.get("task_id") or ""):
        # planner marks dependency-satisfied tasks READY after observation
        if t.get("status") not in ("PENDING", "READY"):
            continue
        if t.get("optional"):
            continue
        blockers = [d for d in ok_deps.get(t["task_id"], ())
                    if by_id.get(d, {}).get("status") != "SUCCEEDED"]
        if blockers:
            continue
        out.append(t)
    return out


def assignable_batch(plan: dict, agents: dict[str, dict],
                     run: dict, lock_held: dict[str, dict],
                     max_concurrent: int = MAX_CONCURRENT_WORKERS
                     ) -> tuple[list[dict], list[dict]]:
    """Pick the next bounded, resource-safe assignment batch.

    Returns (batch, deferred) where batch items are
    {"task", "agent", "resources"} and deferred items are
    {"task", "reason"}.

    Rules:
    - concurrency cap (T20.25)
    - WRITE/WRITE and READ/WRITE conflicts serialize (T20.26)
    - an exclusive task already assigned is not duplicated (T20.30)
    """
    ready = ready_plan_tasks(plan)
    in_flight = [tid for tid, st in (run.get("tasks") or {}).items()
                 if st in ("ASSIGNED", "RUNNING", "REVISION_REQUESTED")]
    slots = max(0, max_concurrent - len(in_flight))
    batch: list[dict] = []
    deferred: list[dict] = []
    taken_writes: set[str] = set()
    batch_task_ids = set(in_flight)
    for t in ready:
        if t["task_id"] in batch_task_ids:
            deferred.append({"task": t, "reason": "already_assigned"})
            continue
        if slots <= 0:
            deferred.append({"task": t, "reason": "concurrency_limit"})
            continue
        agent = agent_for_skill(agents, t.get("required_skill") or "")
        if agent is None:
            deferred.append({"task": t, "reason": "no_compatible_agent"})
            continue
        if int(agent.get("budget", {}).get("max_tasks") or 0) <= 0:
            deferred.append({"task": t, "reason": "agent_budget_exhausted"})
            continue
        resources = resources_for_task(t)
        conflict = None
        for r in resources:
            rid = r["resource_id"]
            holders = lock_held.get(rid) or {}
            for holder, hkind in holders.items():
                if hkind == "WRITE" or r["kind"] == "WRITE":
                    conflict = f"resource_conflict:{rid}:{holder}"
                    break
            if conflict:
                break
        if conflict:
            deferred.append({"task": t, "reason": conflict})
            continue
        batch_writes = {
            r["resource_id"] for r in resources if r["kind"] == "WRITE"
        }
        if batch_writes & taken_writes:
            deferred.append({"task": t, "reason": "batch_write_conflict"})
            continue
        batch.append({"task": t, "agent": agent, "resources": resources})
        batch_task_ids.add(t["task_id"])
        taken_writes |= batch_writes
        for r in resources:
            lock_held.setdefault(r["resource_id"], {})[t["task_id"]] = \
                r["kind"]
        slots -= 1
    return batch, deferred


def verification_required_for(task: dict) -> bool:
    """Mandatory verification categories (T20.9)."""
    from sciencemath.orchestration.contract import (
        MANDATORY_VERIFICATION_SKILLS, MANDATORY_VERIFICATION_TASK_TYPES,
    )
    if (task.get("task_type") or "") in MANDATORY_VERIFICATION_TASK_TYPES:
        return True
    return (task.get("required_skill") or "") in MANDATORY_VERIFICATION_SKILLS


def pick_verifier(agents: dict[str, dict], producer_agent_id: str,
                  used: list[str]) -> dict | None:
    """An independent verifier: never the producer (T20.9).

    `used` are verifier agent ids already loaded this step
    (max_concurrent_verifiers cap).
    """
    if len(used) >= MAX_CONCURRENT_VERIFIERS:
        return None
    verifiers = agents_for_role(agents, "VERIFIER")
    for v in verifiers:
        if v["agent_id"] == producer_agent_id:
            continue
        if v["agent_id"] in used:
            continue
        if v.get("status") in ("READY", "WAITING"):
            return v
    return None


def reassignment_target(agents: dict[str, dict], skill_id: str,
                        exclude: set[str]) -> dict | None:
    """Selective reassignment (T20.47): a fresh agent of the same role,
    preserving precision — never a different-skill worker."""
    role = SKILL_TO_ROLE.get(skill_id or "")
    for a in agents_for_role(agents, role or ""):
        if a["agent_id"] in exclude:
            continue
        if a.get("status") in ("READY", "WAITING"):
            if skill_permitted_agent(a, skill_id or ""):
                return a
    return None