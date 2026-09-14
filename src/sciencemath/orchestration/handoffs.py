"""T20.21/T20.22 handoff contract and validation.

A handoff cannot silently drop constraints, required evidence, success
criteria, budget, or provenance. Invalid handoffs are rejected.
"""
from __future__ import annotations

from sciencemath.orchestration.contract import MAX_HANDOFF_CYCLE
from sciencemath.orchestration.assignment import skill_permitted_agent
from sciencemath.orchestration.models import Handoff, deterministic_id


def build_handoff(run: dict, task: dict, from_agent: dict, to_agent: dict,
                  artifact_refs: list | None = None,
                  now: str = "") -> Handoff:
    """Build the full handoff contract (T20.21). Budget and provenance are
    carried explicitly so they can never be silently dropped."""
    remaining_budget = dict(run.get("budgets") or {})
    agent_budget = (to_agent.get("budget") or {})
    remaining_budget["agent"] = {
        "max_tasks": agent_budget.get("max_tasks"),
        "max_revisions": agent_budget.get("max_revisions"),
        "max_messages": agent_budget.get("max_messages"),
    }
    return Handoff(
        handoff_id=deterministic_id("hnd_", run.get("run_id"),
                                    task.get("task_id"),
                                    to_agent.get("agent_id"), now),
        from_agent=from_agent.get("agent_id"),
        to_agent=to_agent.get("agent_id"),
        task_id=task.get("task_id") or "",
        objective=task.get("objective") or task.get("title") or "",
        inputs=list(task.get("required_inputs") or []),
        artifact_refs=list(artifact_refs or []),
        constraints=list(run.get("plan", {}).get("constraints") or []),
        success_criteria=list(task.get("success_criteria") or []),
        remaining_budget=remaining_budget,
        expected_output_schema=task.get("expected_outputs") and {
            "expected_outputs": list(task["expected_outputs"])} or {},
        provenance={
            "plan_id": run.get("plan_id"),
            "plan_version": (run.get("plan") or {}).get("plan_version"),
            "assigned_at": now,
            "from_role": from_agent.get("role"),
            "to_role": to_agent.get("role"),
        },
    )


def validate_handoff(run: dict, handoff: Handoff, task: dict,
                     agents: dict[str, dict]) -> list[str]:
    """T20.22 rejection rules. Empty list = valid."""
    errs: list[str] = []
    target = agents.get(handoff.to_agent)
    if target is None:
        return ["unknown_target_agent"]
    if agents.get(handoff.from_agent) is None:
        errs.append("unknown_from_agent")
    task_status = (run.get("tasks") or {}).get(task.get("task_id"))
    if task_status in ("SUCCEEDED", "INVALIDATED", "SKIPPED"):
        errs.append(f"task_already_{str(task_status).lower()}")
    skill = task.get("required_skill") or ""
    if not skill_permitted_agent(target, skill):
        errs.append(f"target_lacks_skill:{skill}")
    if target.get("paid_compute_access"):
        errs.append("target_paid_access_forbidden")
    if handoff.remaining_budget.get("max_cost_class", "FREE") != "FREE":
        errs.append("budget_invalid")
    for ref in handoff.artifact_refs:
        known = {a.get("artifact_id") for a in (run.get("artifacts") or [])}
        if ref not in known:
            errs.append(f"required_artifact_missing:{ref}")
    if not handoff.constraints and (run.get("plan") or {}).get("constraints"):
        errs.append("constraint_set_incomplete")
    if not handoff.success_criteria and task.get("success_criteria"):
        errs.append("success_criteria_incomplete")
    if not handoff.provenance.get("plan_id"):
        errs.append("provenance_incomplete")
    cycle = handoff_cycle_depth(run, handoff.to_agent)
    if cycle > MAX_HANDOFF_CYCLE:
        errs.append("handoff_cycle_exceeds_limit")
    return errs


def handoff_cycle_depth(run: dict, agent_id: str) -> int:
    """Longest handoff chain ending at agent_id (bounded by MAX_HANDOFF_CYCLE)."""
    edges: dict[str, list[str]] = {}
    for h in run.get("handoffs") or []:
        edges.setdefault(h.get("from_agent"), []).append(h.get("to_agent"))
    depth = 0
    stack = [agent_id]
    best: dict[str, int] = {agent_id: 0}
    while stack and depth <= MAX_HANDOFF_CYCLE + 1:
        cur = stack.pop()
        for nxt in edges.get(cur, ()):
            if best.get(nxt, -1) < best.get(cur, 0) + 1:
                best[nxt] = best.get(cur, 0) + 1
                depth = max(depth, best[nxt])
                stack.append(nxt)
    return depth