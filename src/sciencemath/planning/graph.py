"""T19.5 dependency DAG: reject self-deps, unknown IDs, and cycles."""
from __future__ import annotations

from collections import defaultdict, deque

from sciencemath.planning.models import Plan, Task


def task_list(plan: Plan) -> list[Task]:
    out = []
    for t in plan.tasks:
        out.append(t if isinstance(t, Task) else Task.from_dict(t))
    return out


def dep_map(plan: Plan) -> dict[str, list[str]]:
    ids = {t.task_id for t in task_list(plan)}
    deps: dict[str, list[str]] = {i: [] for i in ids}
    for t in task_list(plan):
        deps[t.task_id] = list(t.dependencies or [])
    for edge in plan.dependencies or []:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            src, dst = edge
            if dst in deps and src not in deps[dst]:
                deps[dst].append(src)
        elif isinstance(edge, dict):
            src, dst = edge.get("from"), edge.get("to")
            if dst in deps and src not in deps[dst]:
                deps[dst].append(src)
    return deps


def validate_graph(plan: Plan) -> list[str]:
    errors: list[str] = []
    tasks = task_list(plan)
    ids = [t.task_id for t in tasks]
    if len(ids) != len(set(ids)):
        errors.append("duplicate task id")
    known = set(ids)
    deps = dep_map(plan)
    for tid, parents in deps.items():
        for p in parents:
            if p == tid:
                errors.append(f"self-dependency {tid}")
            elif p not in known:
                errors.append(f"unknown dependency {p} on {tid}")
    cyc = cycles(deps)
    if cyc:
        errors.append("cycle:" + "->".join(cyc))
    return errors


def cycles(deps: dict[str, list[str]]) -> list[str]:
    nodes = set(deps) | {p for ps in deps.values() for p in ps}
    indeg = {n: 0 for n in nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for n, ps in deps.items():
        for p in ps:
            children[p].append(n)
            indeg[n] = indeg.get(n, 0) + 1
            indeg.setdefault(p, 0)
    q = deque([n for n, d in indeg.items() if d == 0])
    seen = 0
    while q:
        n = q.popleft()
        seen += 1
        for c in children.get(n, []):
            indeg[c] -= 1
            if indeg[c] == 0:
                q.append(c)
    if seen == len(nodes):
        return []
    leftover = [n for n, d in indeg.items() if d > 0]
    return leftover[:8] or ["cycle"]


def children_of(deps: dict[str, list[str]]) -> dict[str, list[str]]:
    ch: dict[str, list[str]] = defaultdict(list)
    for n, ps in deps.items():
        for p in ps:
            ch[p].append(n)
    return dict(ch)


def descendants(tid: str, deps: dict[str, list[str]]) -> set[str]:
    ch = children_of(deps)
    out: set[str] = set()
    stack = list(ch.get(tid, []))
    while stack:
        n = stack.pop()
        if n in out:
            continue
        out.add(n)
        stack.extend(ch.get(n, []))
    return out


def ready_tasks(plan: Plan) -> list[Task]:
    deps = dep_map(plan)
    by = {t.task_id: t for t in task_list(plan)}
    ready = []
    for t in task_list(plan):
        if t.status not in ("PENDING", "READY"):
            continue
        ok = True
        for p in deps.get(t.task_id, []):
            parent = by.get(p)
            if parent is None or parent.status not in ("SUCCEEDED", "SKIPPED"):
                ok = False
                break
        if ok:
            t.status = "READY"
            ready.append(t)
    return ready


def depth_of(tid: str, deps: dict[str, list[str]], memo: dict | None = None) -> int:
    memo = memo if memo is not None else {}
    if tid in memo:
        return memo[tid]
    ps = deps.get(tid) or []
    d = 0 if not ps else 1 + max(depth_of(p, deps, memo) for p in ps)
    memo[tid] = d
    return d


def critical_path(plan: Plan) -> list[str]:
    deps = dep_map(plan)
    tasks = task_list(plan)
    if not tasks:
        return []
    memo: dict[str, int] = {}
    best = max(tasks, key=lambda t: depth_of(t.task_id, deps, memo))
    path = [best.task_id]
    cur = best.task_id
    while deps.get(cur):
        parent = max(deps[cur], key=lambda p: depth_of(p, deps, memo))
        path.append(parent)
        cur = parent
    path.reverse()
    return path


def graph_metadata(plan: Plan) -> dict:
    deps = dep_map(plan)
    ch = children_of(deps)
    tasks = task_list(plan)
    memo: dict[str, int] = {}
    depths = {t.task_id: depth_of(t.task_id, deps, memo) for t in tasks}
    by_depth: dict[int, list[str]] = defaultdict(list)
    for tid, d in depths.items():
        by_depth[d].append(tid)
    parallel = [ids for ids in by_depth.values() if len(ids) > 1]
    fan_out = {t.task_id: len(ch.get(t.task_id, [])) for t in tasks}
    fan_in = {t.task_id: len(deps.get(t.task_id, [])) for t in tasks}
    return {
        "fan_out": fan_out,
        "fan_in": fan_in,
        "parallel_safe_groups": parallel,
        "critical_path": critical_path(plan),
        "depths": depths,
        "acyclic": not cycles(deps),
    }


def add_dependency(plan: Plan, src: str, dst: str) -> list[str]:
    by = {t.task_id: t for t in task_list(plan)}
    if src not in by or dst not in by:
        return ["unknown dependency IDs"]
    if src == dst:
        return ["self-dependency"]
    t = by[dst]
    if src not in t.dependencies:
        t.dependencies.append(src)
    plan.tasks = list(by.values())
    edge = {"from": src, "to": dst, "reason": "explicit"}
    if edge not in (plan.dependencies or []):
        plan.dependencies = list(plan.dependencies or []) + [edge]
    err = validate_graph(plan)
    if err:
        t.dependencies = [d for d in t.dependencies if d != src]
        plan.dependencies = [e for e in plan.dependencies if e != edge]
        return err
    return []
