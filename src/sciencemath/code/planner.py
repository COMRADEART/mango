"""T15.6 — structured planning before editing.

Non-trivial edits require a plan with: task_summary, files_to_inspect,
candidate_files_to_modify, tests_to_run, risk_level, expected_behavior_change,
protected_components, rollback_condition. Concise implementation rationale
only — no hidden chain-of-thought is exposed because none is generated.
"""
from __future__ import annotations

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")

PLAN_SCHEMA = ("task_summary", "files_to_inspect",
               "candidate_files_to_modify", "tests_to_run", "risk_level",
               "expected_behavior_change", "protected_components",
               "rollback_condition")


def make_plan(task_summary: str, *, files_to_inspect=(),
              candidate_files_to_modify=(), tests_to_run=(),
              risk_level: str = "LOW", expected_behavior_change: str = "",
              protected_components=(), rollback_condition: str = "") -> dict:
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"bad risk_level {risk_level!r}")
    if not task_summary or not task_summary.strip():
        raise ValueError("task_summary is required")
    plan = {
        "task_summary": task_summary.strip()[:1000],
        "files_to_inspect": list(files_to_inspect),
        "candidate_files_to_modify": list(candidate_files_to_modify),
        "tests_to_run": list(tests_to_run),
        "risk_level": risk_level,
        "expected_behavior_change": expected_behavior_change[:1000],
        "protected_components": list(protected_components),
        "rollback_condition": rollback_condition[:1000]
        or "revert the patch if any targeted test fails",
    }
    return plan


def plan_valid(plan: dict) -> tuple:
    """Return (valid: bool, problems: list)."""
    problems = []
    for key in PLAN_SCHEMA:
        if key not in plan:
            problems.append(f"missing:{key}")
    if plan.get("risk_level") not in RISK_LEVELS:
        problems.append("bad:risk_level")
    if not (plan.get("task_summary") or "").strip():
        problems.append("empty:task_summary")
    mutating = bool(plan.get("candidate_files_to_modify"))
    if mutating and not plan.get("tests_to_run"):
        problems.append("missing:tests_to_run_for_mutating_plan")
    if mutating and not plan.get("rollback_condition"):
        problems.append("missing:rollback_condition")
    return (not problems, problems)


def needs_plan(op: str, *, files_to_modify=()) -> bool:
    """Trivial single-file low-risk edits may proceed; everything else plans."""
    from sciencemath.code.contract import CODE_EDIT
    if op != CODE_EDIT:
        return False
    return len(list(files_to_modify)) != 1
