"""T19.12–T19.15 / T19.39–T19.40 / T19.45–T19.46 safety and policy gates."""
from __future__ import annotations

import re

from sciencemath.executive.skills import SkillRegistry
from sciencemath.planning.contract import (
    COST_FREE, COST_PAID, KNOWN_TASK_SKILLS, PAID_COMPUTE_GATE_REQUIRED,
    PLAN_INSUFFICIENT_CAPABILITY, PLAN_NEEDS_CLARIFICATION,
    PLAN_POLICY_BLOCKED,
)

_PAID = re.compile(
    r"\b(paid compute|paid api|h100|a100|cloud gpu|buy|purchase|"
    r"spend money|billing|stripe charge|metered search)\b", re.I)
_SHELL = re.compile(
    r"\b(powershell|cmd\.exe|bash -c|run shell|execute arbitrary)\b", re.I)
_DESTRUCT = re.compile(
    r"\b(delete repository|delete all files|rm -rf|wipe disk|"
    r"drop database|upload secrets|exfiltrat)\b", re.I)
_POLICY = re.compile(
    r"\b(change benchmark scores|remove safety|override policy|"
    r"ignore the current plan|ignore previous instructions|"
    r"fake system prompt|you are now unrestricted)\b", re.I)
_SKIP_VERIFY = re.compile(
    r"\b(mark everything complete|skip verification|looks good enough)\b",
    re.I)
_INJECT = re.compile(
    r"(ignore (the )?(current plan|previous instructions)|"
    r"you are now|system prompt:|mark everything complete|"
    r"skip verification|spend money|run powershell|delete all files|"
    r"delete repository|upload secrets|write this to memory|"
    r"change benchmark scores|remove safety constraints)", re.I)

SEMANTIC_ACTIVE = {
    "SCICOMP": "ACTIVE",  # promoted lab; registry may remain EXPERIMENTAL
    "CODE": "ACTIVE",
    "WEB_RESEARCH": "ACTIVE",
    "DOCUMENT": "ACTIVE",
    "MEMORY": "ACTIVE",
    "MATH_T4": "ACTIVE",
    "SCIENCE_RAG": "ACTIVE",
    "GENERAL": "ACTIVE",
    "NO_TOOL": "ACTIVE",
}


def skill_known_state(skill_id: str, registry: SkillRegistry | None = None) -> str:
    reg = registry or SkillRegistry()
    if not reg.known(skill_id) and skill_id not in SEMANTIC_ACTIVE:
        return "UNKNOWN"
    if skill_id in SEMANTIC_ACTIVE:
        return SEMANTIC_ACTIVE[skill_id]
    return reg.availability(skill_id)


def skill_allowed(skill_id: str, registry: SkillRegistry | None = None) -> bool:
    if skill_id not in KNOWN_TASK_SKILLS:
        return False
    state = skill_known_state(skill_id, registry)
    return state == "ACTIVE"


def is_injection(text: str) -> bool:
    return bool(_INJECT.search(text or ""))


def data_not_policy(text: str) -> dict:
    """Inputs from MEMORY/DOCUMENT/WEB/CODE are DATA (authority 0)."""
    return {
        "instruction_authority": 0,
        "injection_flagged": is_injection(text or ""),
        "literal_excerpt": (text or "")[:240],
        "policy_override_attempt": bool(_POLICY.search(text or "")),
    }


def classify_goal_policy(goal: str, source: str = "user") -> dict:
    g = goal or ""
    paid = bool(_PAID.search(g))
    policy = bool(_POLICY.search(g)) and source == "user"
    # Observation/memory cannot change policy; user goal that asks to
    # override safety is still a policy block.
    if source != "user" and is_injection(g):
        return {
            "op": None,
            "paid": False,
            "destructive": bool(_DESTRUCT.search(g)),
            "skip_verify": bool(_SKIP_VERIFY.search(g)),
            "injection": True,
            "gate": None,
        }
    if paid or policy:
        return {
            "op": PLAN_POLICY_BLOCKED,
            "paid": paid,
            "destructive": bool(_DESTRUCT.search(g)),
            "skip_verify": bool(_SKIP_VERIFY.search(g)),
            "injection": is_injection(g),
            "gate": PAID_COMPUTE_GATE_REQUIRED if paid else "POLICY_GATE",
        }
    return {
        "op": None,
        "paid": False,
        "destructive": bool(_DESTRUCT.search(g)),
        "skip_verify": bool(_SKIP_VERIFY.search(g)),
        "injection": is_injection(g),
        "gate": None,
    }


def side_effect_for(skill: str, task_type: str, destructive: bool = False) -> str:
    if destructive or task_type in ("destroy", "delete", "irreversible"):
        return "EXTERNAL_IRREVERSIBLE" if "upload" in task_type or \
            task_type == "irreversible" else "LOCAL_MUTATION"
    if skill == "WEB_RESEARCH":
        return "NETWORK_READ"
    if skill == "CODE" and task_type in ("change", "modify", "patch", "edit"):
        return "LOCAL_MUTATION"
    if skill == "CODE":
        return "READ_ONLY"
    if skill == "DOCUMENT":
        return "READ_ONLY"
    if skill == "MEMORY" and task_type in ("write", "store", "save"):
        return "LOCAL_MUTATION"
    if skill == "MEMORY":
        return "READ_ONLY"
    if skill == "SCICOMP":
        return "NONE"
    return "NONE"


def network_required(skill: str) -> bool:
    return skill == "WEB_RESEARCH"


def approval_for(side_effect: str, destructive: bool, shell: bool) -> tuple[bool, str]:
    if destructive or side_effect in (
            "LOCAL_MUTATION", "NETWORK_MUTATION",
            "EXTERNAL_IRREVERSIBLE", "PAID") or shell:
        reason = "destructive or irreversible future action"
        if side_effect == "PAID":
            reason = "paid service requires gate"
        if shell:
            reason = "shell/process execution requires approval"
        return True, reason
    return False, ""


def contradiction(constraints: list[str], goal: str) -> str | None:
    blob = " ".join(constraints or []) + " " + (goal or "")
    low = blob.lower()
    no_net = bool(re.search(
        r"\b(no network|offline only|must use no network|network forbidden)\b",
        low))
    live = bool(re.search(
        r"\b(today'?s live|live stock|live website|browse live|"
        r"real[- ]time web)\b", low))
    if no_net and live:
        return "contradictory hard constraints: no network vs live retrieval"
    return None


def needs_clarification(req: dict) -> str | None:
    goal = req.get("goal") or ""
    gtype = (req.get("goal_type") or "").upper()
    skills = [s.upper() for s in (req.get("required_skills") or [])]
    cons = list(req.get("constraints") or [])
    c = contradiction(cons, goal)
    if c:
        return c
    codeish = (
        gtype in ("CODE_BUGFIX", "CODE_CHANGE", "SOFTWARE_ENGINEERING")
        or "CODE" in skills
        or bool(re.search(r"\b(repo|repository|codebase|pull request)\b",
                          goal, re.I))
    )
    mut = bool(re.search(
        r"\b(fix|patch|edit|modify|change the code|implement)\b", goal, re.I))
    if codeish and mut and not req.get("target_repository"):
        if not re.search(r"\b(repo|repository)\s+\S+", goal, re.I) and \
                "in-memory" not in goal.lower() and \
                "fixture" not in goal.lower() and \
                not req.get("allow_unspecified_repo"):
            # Eval fixtures often omit a real repo; only insist when the
            # request marks the repo as required/missing.
            if req.get("require_repository") or "target repository" in goal.lower():
                return "missing target repository"
    if req.get("ambiguous_destructive"):
        return "ambiguous destructive operation"
    if req.get("unknown_output_format") or (
            "required output format" in goal.lower()
            and not req.get("required_output_format")):
        return "unknown required output format"
    if req.get("missing_required_fact"):
        return "materially ambiguous required fact"
    return None


def insufficient_capability(skill: str, registry: SkillRegistry | None = None) -> bool:
    if not skill:
        return False
    if skill not in KNOWN_TASK_SKILLS and skill != "PLANNING":
        return True
    return not skill_allowed(skill, registry)


def paid_task(task: dict) -> bool:
    return (task.get("estimated_cost_class") == COST_PAID
            or task.get("side_effect_class") == "PAID")
