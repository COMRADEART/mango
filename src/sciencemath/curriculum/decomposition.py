"""T6.14 — Task-level problem decomposition schema.

A small internal plan representation: the beginning of Mango's future
executive reasoning system (T7+), but deliberately NOT an agent loop —
the plan is data only, produced and evaluated offline. No hidden
chain-of-thought is stored; only task-level decomposition.
"""
from __future__ import annotations

import json
import re

PROBLEM_TYPES = ("math", "science", "mixed", "insufficient")
VALID_SUBPROBLEM_KEYS = {"id", "goal", "needs_math_tool", "needs_retrieval"}

_PLAN_EXAMPLE = """{
  "problem_type": "mixed",
  "subproblems": [
    {"id": 1, "goal": "...", "needs_math_tool": false, "needs_retrieval": true},
    {"id": 2, "goal": "...", "needs_math_tool": true, "needs_retrieval": false}
  ]
}"""


def validate_plan(plan: dict | str) -> list[str]:
    """Validate a decomposition plan. Accepts a dict or a JSON string.
    Empty list means valid."""
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError as e:
            return [f"plan is not valid JSON: {e}"]
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["plan must be a JSON object"]
    pt = plan.get("problem_type")
    if pt not in PROBLEM_TYPES:
        errors.append(f"problem_type {pt!r} not in {PROBLEM_TYPES}")
    subs = plan.get("subproblems")
    if not isinstance(subs, list) or not subs:
        errors.append("subproblems: must be a non-empty list")
        return errors
    seen_ids = set()
    for i, sp in enumerate(subs):
        if not isinstance(sp, dict):
            errors.append(f"subproblems[{i}]: must be an object")
            continue
        unknown = set(sp) - VALID_SUBPROBLEM_KEYS
        if unknown:
            errors.append(f"subproblems[{i}]: unknown keys {sorted(unknown)}")
        sid = sp.get("id")
        if not isinstance(sid, int) or sid in seen_ids:
            errors.append(f"subproblems[{i}]: id must be a unique integer")
        seen_ids.add(sid)
        goal = sp.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            errors.append(f"subproblems[{i}]: goal must be non-empty text")
        for flag in ("needs_math_tool", "needs_retrieval"):
            if flag in sp and not isinstance(sp[flag], bool):
                errors.append(f"subproblems[{i}]: {flag} must be boolean")
        if len(json.dumps(goal or "")) > 400:
            errors.append(f"subproblems[{i}]: goal too long for task-level "
                          "decomposition (no chain-of-thought storage)")
    return errors


def routing_label_from_plan(plan: dict) -> str:
    """Derive the coarse routing label (routing.py labels) from a plan."""
    subs = plan.get("subproblems") or []
    any_tool = any(sp.get("needs_math_tool") for sp in subs
                   if isinstance(sp, dict))
    any_ret = any(sp.get("needs_retrieval") for sp in subs
                  if isinstance(sp, dict))
    if any_tool and any_ret:
        return "BOTH"
    if any_tool:
        return "TOOL"
    if any_ret:
        return "RETRIEVAL"
    return "NONE"


PLAN_TEMPLATE = _PLAN_EXAMPLE


def parse_plan_from_output(raw: str) -> dict | None:
    """Extract the first JSON object that looks like a plan from model
    output; None when none is present. Deliberately strict: only a JSON
    object carrying problem_type + subproblems counts."""
    if not raw:
        return None
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw):
        try:
            candidate = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "problem_type" in candidate \
                and "subproblems" in candidate:
            return candidate
    return None