"""T20.26–T20.28 logical resource locks and deadlock detection.

Lightweight logical locks over named scopes (repository_fixture:<id>,
document_fixture:<id>, memory_scope:<id>, artifact:<id>). Frozen benchmark
prefers READ locks or sandboxed WRITE scopes. Deadlock must be detectable.
"""
from __future__ import annotations

from sciencemath.orchestration.contract import LOCK_KINDS


class LockTable:
    """Task-keyed logical locks. Deterministic; no wall-clock waiting."""

    def __init__(self):
        # resource_id -> {task_id: kind}
        self.held: dict[str, dict[str, str]] = {}
        # task_id -> list of resource_ids it waits for
        self.waiting: dict[str, list[str]] = {}

    def acquire(self, task_id: str, resources: list[dict]) -> str:
        """Try to acquire all locks for a task. Returns "" on success or a
        blocked reason naming the conflicting holder."""
        for r in resources:
            rid = r["resource_id"]
            kind = r.get("kind") or "READ"
            if kind not in LOCK_KINDS:
                return f"invalid lock kind {kind!r}"
            holders = self.held.get(rid) or {}
            for holder, hkind in holders.items():
                if holder == task_id:
                    continue
                if hkind == "WRITE" or kind == "WRITE":
                    return f"resource_conflict:{rid}:{holder}"
        # All clear — take the locks.
        for r in resources:
            rid = r["resource_id"]
            kind = r.get("kind") or "READ"
            self.held.setdefault(rid, {})[task_id] = kind
        self.waiting.pop(task_id, None)
        return ""

    def mark_waiting(self, task_id: str, resources: list[dict]) -> None:
        self.waiting[task_id] = [r["resource_id"] for r in resources]

    def release(self, task_id: str, resources: list[dict]) -> None:
        for r in resources:
            rid = r["resource_id"]
            holders = self.held.get(rid)
            if holders and task_id in holders:
                del holders[task_id]
                if not holders:
                    del self.held[rid]
        self.waiting.pop(task_id, None)

    def release_all(self, task_id: str) -> None:
        for rid in list(self.held):
            holders = self.held[rid]
            if task_id in holders:
                del holders[task_id]
                if not holders:
                    del self.held[rid]
        self.waiting.pop(task_id, None)

    def snapshot(self) -> dict:
        return {"held": {k: dict(v) for k, v in self.held.items()},
                "waiting": {k: list(v) for k, v in self.waiting.items()}}

    def load_snapshot(self, snap: dict) -> None:
        self.held = {k: dict(v) for k, v in (snap.get("held") or {}).items()}
        self.waiting = {k: list(v) for k, v in (snap.get("waiting") or {}).items()}


def wait_for_graph(table: LockTable) -> dict[str, set[str]]:
    """waiter_task -> {holder_task} edges from the lock table."""
    edges: dict[str, set[str]] = {}
    for task_id, rids in table.waiting.items():
        for rid in rids:
            for holder in table.held.get(rid, {}):
                if holder != task_id:
                    edges.setdefault(task_id, set()).add(holder)
    return edges


def find_deadlock(edges: dict[str, set[str]]) -> list[str] | None:
    """Return a wait cycle (list of task ids) or None.

    Deadlock tolerance is 0: any A-waits-B, B-waits-A (or larger cycle)
    must be detected, never spun on (T20.28).
    """
    for start in edges:
        path = [start]
        seen = {start}

        def dfs(node: str) -> list[str] | None:
            for nxt in sorted(edges.get(node, ())):
                if nxt == start:
                    return path[:]
                if nxt in seen:
                    continue
                seen.add(nxt)
                path.append(nxt)
                found = dfs(nxt)
                if found:
                    return found
                path.pop()
            return None

        found = dfs(start)
        if found:
            return found
    return None


def resources_for_task(task: dict, default_scope: str = "") -> list[dict]:
    """Deterministic resource set for a task.

    Explicit task["resources"] entries win ({"resource_id", "kind"}).
    Fallback derives one scope from the required skill, so unrelated tasks
    never contend unless the fixture declares shared resources.
    """
    out = []
    for r in task.get("resources") or []:
        if isinstance(r, str):
            out.append({"resource_id": r, "kind": "WRITE"})
        elif isinstance(r, dict) and r.get("resource_id"):
            out.append({"resource_id": str(r["resource_id"]),
                        "kind": r.get("kind") or "READ"})
    if out:
        return out
    skill = task.get("required_skill") or ""
    scope = {
        "CODE": "repository_fixture",
        "SCICOMP": "artifact",
        "WEB_RESEARCH": "web_fixture",
        "SCIENCE_RAG": "web_fixture",
        "DOCUMENT": "document_fixture",
        "MEMORY": "memory_scope",
        "MATH_T4": "artifact",
        "GENERAL": "artifact",
    }.get(skill, "artifact")
    name = default_scope or task.get("task_id") or "default"
    return [{"resource_id": f"{scope}:{name}", "kind": "READ"}]