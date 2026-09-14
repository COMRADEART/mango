"""T19.7–T19.10 goal/constraint split, clarification, skill-aware decompose."""
from __future__ import annotations

import re

from sciencemath.executive.skills import SkillRegistry
from sciencemath.planning.contract import COST_FREE, COST_PAID
from sciencemath.planning.models import Assumption, Task
from sciencemath.planning.safety import (
    approval_for, network_required, side_effect_for, skill_allowed,
)

_HARD = re.compile(
    r"\b(must|required|hard constraint|do not|never|forbidden|offline only|"
    r"no network|no paid)\b", re.I)
_SOFT = re.compile(
    r"\b(prefer|preferably|nice to have|if possible|soft preference)\b", re.I)
_ASSUME = re.compile(r"\b(assum(?:e|ing)|assumption:)\b", re.I)

TEMPLATES: dict[str, list[dict]] = {
    "CODE_BUGFIX": [
        {"type": "inspect", "skill": "CODE",
         "title": "Inspect repository for the defect",
         "out": ["inspection_notes"]},
        {"type": "diagnose", "skill": "CODE",
         "title": "Diagnose root cause",
         "out": ["root_cause"]},
        {"type": "change", "skill": "CODE",
         "title": "Propose the code change",
         "out": ["patch_proposal"]},
        {"type": "test", "skill": "CODE",
         "title": "Run tests for the change",
         "out": ["test_report"]},
        {"type": "verify", "skill": "CODE",
         "title": "Verify the fix against success criteria",
         "out": ["verification_report"]},
    ],
    "CODE_CHANGE": [
        {"type": "inspect", "skill": "CODE",
         "title": "Inspect current implementation",
         "out": ["inspection_notes"]},
        {"type": "change", "skill": "CODE",
         "title": "Propose the implementation change",
         "out": ["patch_proposal"]},
        {"type": "test", "skill": "CODE",
         "title": "Test the proposed change",
         "out": ["test_report"]},
        {"type": "verify", "skill": "CODE",
         "title": "Verify change completeness",
         "out": ["verification_report"]},
    ],
    "WEB_RESEARCH": [
        {"type": "search", "skill": "WEB_RESEARCH",
         "title": "Search for current evidence",
         "out": ["search_hits"]},
        {"type": "extract", "skill": "WEB_RESEARCH",
         "title": "Extract claims with citations",
         "out": ["cited_claims"]},
        {"type": "freshness", "skill": "WEB_RESEARCH",
         "title": "Check freshness requirement",
         "out": ["freshness_report"]},
        {"type": "synthesize", "skill": "WEB_RESEARCH",
         "title": "Synthesize cited answer",
         "out": ["research_brief"]},
    ],
    "DOCUMENT_ANALYSIS": [
        {"type": "identify", "skill": "DOCUMENT",
         "title": "Identify the local document",
         "out": ["doc_identity"]},
        {"type": "parse", "skill": "DOCUMENT",
         "title": "Parse and locate required fields",
         "out": ["parsed_fields"]},
        {"type": "extract", "skill": "DOCUMENT",
         "title": "Extract cited evidence",
         "out": ["cited_renewal_date"]},
        {"type": "report", "skill": "DOCUMENT",
         "title": "Report cited findings",
         "out": ["document_report"]},
    ],
    "SCICOMP": [
        {"type": "formulate", "skill": "SCICOMP",
         "title": "Formulate the numeric computation",
         "out": ["numeric_spec"]},
        {"type": "compute", "skill": "SCICOMP",
         "title": "Run deterministic SciComp computation",
         "out": ["numeric_result"]},
        {"type": "verify", "skill": "SCICOMP",
         "title": "Verify numeric envelope",
         "out": ["numeric_verification"]},
    ],
    "MEMORY_RECALL": [
        {"type": "retrieve", "skill": "MEMORY",
         "title": "Retrieve scoped durable project context",
         "out": ["memory_hits"]},
    ],
    "MEMORY_WRITE": [
        {"type": "write", "skill": "MEMORY",
         "title": "Propose explicit durable memory write",
         "out": ["memory_write_proposal"]},
    ],
    "MATH_WORKFLOW": [
        {"type": "formulate", "skill": "SCICOMP",
         "title": "Formulate the math workflow",
         "out": ["numeric_spec"]},
        {"type": "compute", "skill": "SCICOMP",
         "title": "Compute with SciComp, not free-form arithmetic",
         "out": ["numeric_result"]},
        {"type": "verify", "skill": "SCICOMP",
         "title": "Verify the numeric result",
         "out": ["numeric_verification"]},
    ],
    "SCIENTIFIC_ANALYSIS": [
        {"type": "parse", "skill": "DOCUMENT",
         "title": "Parse the local dataset or notes",
         "out": ["parsed_fields"]},
        {"type": "compute", "skill": "SCICOMP",
         "title": "Compute the required statistic",
         "out": ["numeric_result"]},
        {"type": "report", "skill": "DOCUMENT",
         "title": "Report cited numeric findings",
         "out": ["analysis_report"]},
    ],
}


def parse_goal_bundle(req: dict) -> dict:
    goal = (req.get("goal") or "").strip()
    constraints = list(req.get("constraints") or [])
    preferences = list(req.get("preferences") or [])
    assumptions = list(req.get("assumptions") or [])
    success = list(req.get("success_criteria") or [])
    failure = list(req.get("failure_criteria") or [])
    subgoals = list(req.get("subgoals") or [])
    for line in re.split(r"[\n;]+", goal):
        s = line.strip()
        if not s:
            continue
        if _SOFT.search(s) and s not in preferences:
            preferences.append(s)
        elif _HARD.search(s) and s not in constraints and s != goal:
            constraints.append(s)
        elif _ASSUME.search(s) and s not in assumptions:
            assumptions.append(s)
    for extra in req.get("hard_constraints") or []:
        if extra not in constraints:
            constraints.append(extra)
    for extra in req.get("soft_preferences") or []:
        if extra not in preferences and extra not in constraints:
            preferences.append(extra)
    if not success:
        success = ["all mandatory tasks succeeded or safely skipped",
                   "required artifacts exist",
                   "no unresolved mandatory blocker"]
    if not failure:
        failure = ["mandatory verification missing",
                   "budget exceeded",
                   "unresolved contradictory constraints"]
    gtype = infer_goal_type(req, goal)
    return {
        "primary_goal": req.get("primary_goal") or goal,
        "subgoals": subgoals,
        "hard_constraints": constraints,
        "soft_preferences": preferences,
        "assumptions": assumptions,
        "success_criteria": success,
        "failure_criteria": failure,
        "goal_type": gtype,
    }


def infer_goal_type(req: dict, goal: str) -> str:
    if req.get("goal_type"):
        return str(req["goal_type"]).upper()
    skills = [s.upper() for s in (req.get("required_skills") or [])]
    g = goal.lower()
    if len(set(skills)) >= 2:
        return "MIXED"
    mapping = [
        ("WEB_RESEARCH", ("current api", "web research", "today's",
                          "live documentation", "search the web")),
        ("DOCUMENT_ANALYSIS", ("contract", "pdf", "csv", "local document",
                               "renewal date", "dataset")),
        ("CODE_BUGFIX", ("fix the bug", "bug in", "failing test",
                         "repository bug")),
        ("CODE_CHANGE", ("implement", "patch", "refactor", "code change")),
        ("SCICOMP", ("numeric", "integral", "matrix", "ode", "compute the")),
        ("MEMORY_WRITE", ("remember that", "save this", "store in memory")),
        ("MEMORY_RECALL", ("prior decision", "what did we decide",
                           "recall from memory")),
        ("MATH_WORKFLOW", ("calculate", "math workflow")),
        ("SCIENTIFIC_ANALYSIS", ("scientific analysis", "local dataset")),
    ]
    for gtype, keys in mapping:
        if any(k in g for k in keys):
            return gtype
    if skills == ["CODE"]:
        return "CODE_BUGFIX"
    if skills == ["WEB_RESEARCH"]:
        return "WEB_RESEARCH"
    if skills == ["DOCUMENT"]:
        return "DOCUMENT_ANALYSIS"
    if skills == ["SCICOMP"]:
        return "SCICOMP"
    if skills == ["MEMORY"]:
        return "MEMORY_RECALL"
    return "MIXED" if skills else "SOFTWARE_ENGINEERING"


def select_skill(task_type: str, goal: str, hint: str | None,
                 registry: SkillRegistry | None = None) -> str:
    if hint and skill_allowed(hint, registry):
        return hint
    g = (goal or "").lower()
    if task_type in ("search", "freshness", "extract") and "document" not in g:
        if "web" in g or "api" in g or "current" in g:
            return "WEB_RESEARCH"
    table = {
        "inspect": "CODE", "diagnose": "CODE", "change": "CODE",
        "test": "CODE", "verify": "CODE", "search": "WEB_RESEARCH",
        "freshness": "WEB_RESEARCH", "synthesize": "WEB_RESEARCH",
        "identify": "DOCUMENT", "parse": "DOCUMENT", "extract": "DOCUMENT",
        "report": "DOCUMENT", "formulate": "SCICOMP", "compute": "SCICOMP",
        "retrieve": "MEMORY", "write": "MEMORY",
    }
    skill = table.get(task_type, hint or "GENERAL")
    if skill == "GENERAL" and "compute" in g:
        skill = "SCICOMP"
    return skill


def _steps_for_type(gtype: str, req: dict) -> list[dict]:
    if gtype in TEMPLATES:
        return list(TEMPLATES[gtype])
    skills = [s.upper() for s in (req.get("required_skills") or [])]
    if not skills:
        if gtype == "SOFTWARE_ENGINEERING":
            skills = ["CODE"]
        elif gtype == "MIXED":
            skills = ["WEB_RESEARCH", "CODE"]
        else:
            skills = ["CODE"]
    order = []
    skill_to_type = {
        "CODE": "CODE_BUGFIX",
        "WEB_RESEARCH": "WEB_RESEARCH",
        "DOCUMENT": "DOCUMENT_ANALYSIS",
        "SCICOMP": "SCICOMP",
        "MEMORY": "MEMORY_RECALL",
        "MATH_T4": "SCICOMP",
        "SCIENCE_RAG": "WEB_RESEARCH",
    }
    for sk in skills:
        order.extend(TEMPLATES.get(skill_to_type.get(sk, "CODE_BUGFIX"), []))
    return order or list(TEMPLATES["CODE_BUGFIX"])


def decompose(req: dict, parsed: dict,
              registry: SkillRegistry | None = None) -> list[Task]:
    gtype = parsed["goal_type"]
    steps = _steps_for_type(gtype, req)
    if req.get("subgoals"):
        extra = []
        for i, sg in enumerate(req["subgoals"]):
            if isinstance(sg, dict):
                extra.append({
                    "type": sg.get("task_type") or "custom",
                    "skill": sg.get("required_skill") or select_skill(
                        sg.get("task_type") or "custom", parsed["primary_goal"],
                        sg.get("required_skill"), registry),
                    "title": sg.get("title") or sg.get("objective") or str(sg),
                    "out": sg.get("expected_outputs") or [f"subgoal_{i}_out"],
                })
            else:
                extra.append({
                    "type": "custom",
                    "skill": select_skill("custom", str(sg), None, registry),
                    "title": str(sg)[:120],
                    "out": [f"subgoal_{i}_out"],
                })
        # Keep templates then extra subgoals, still actionable (not
        # solve/verify/finish only).
        if extra:
            steps = steps + extra
    horizon = (req.get("horizon") or "short").lower()
    if horizon == "long" and len(steps) < 15:
        pad = []
        base = steps or list(TEMPLATES["CODE_BUGFIX"])
        n = 0
        while len(steps) + len(pad) < int(req.get("target_tasks") or 16):
            src = base[n % len(base)]
            pad.append({
                **src,
                "title": src["title"] + f" (horizon stage {n + 1})",
                "out": [f"{o}_h{n}" for o in src.get("out") or ["artifact"]],
            })
            n += 1
        steps = steps + pad
    destructive = bool(req.get("destructive") or req.get("irreversible"))
    shell = bool(req.get("shell"))
    paid = bool(req.get("paid"))
    memory_write_ok = bool(req.get("user_explicit_memory_write")
                           or req.get("durable_plan_requested"))
    max_attempts = int((req.get("budget") or {}).get(
        "max_attempts_per_task", 3))
    tasks: list[Task] = []
    prev = None
    fan_root = None
    for i, step in enumerate(steps, start=1):
        tid = f"t{i:02d}"
        skill = select_skill(step["type"], parsed["primary_goal"],
                             step.get("skill"), registry)
        if skill == "MEMORY" and step["type"] == "write" and not memory_write_ok:
            continue
        se = "PAID" if paid else side_effect_for(skill, step["type"], destructive)
        appr, reason = approval_for(se, destructive, shell)
        if se in ("LOCAL_MUTATION", "EXTERNAL_IRREVERSIBLE"):
            appr, reason = True, reason or "mutation requires approval"
        deps = []
        if prev and not req.get("parallel_first"):
            deps = [prev]
        if req.get("fan_out") and i > 1 and fan_root:
            if step.get("skill") != steps[0].get("skill"):
                deps = [fan_root]
        crit = list(step.get("success") or []) or [
            f"artifact {o} produced" for o in step.get("out") or ["artifact"]
        ]
        if step["type"] == "verify" or step["type"] == "test":
            crit.append("verification evidence exists")
        if skill == "WEB_RESEARCH":
            crit.append("freshness requirement met")
            crit.append("required evidence class present")
        if skill == "DOCUMENT" and "renewal" in parsed["primary_goal"].lower():
            crit.append("cited renewal date extracted")
        t = Task(
            task_id=tid,
            title=step["title"][:160],
            objective=step["title"],
            task_type=step["type"],
            required_skill=skill,
            required_inputs=list(step.get("inputs") or (deps and ["prior_artifact"]) or []),
            expected_outputs=list(step.get("out") or ["artifact"]),
            preconditions=[f"deps_succeeded:{d}" for d in deps],
            postconditions=[f"produced:{o}" for o in step.get("out") or ["artifact"]],
            success_criteria=crit,
            failure_conditions=["tool error", "missing artifact"],
            dependencies=deps,
            max_attempts=max_attempts,
            estimated_cost_class=COST_PAID if paid else COST_FREE,
            network_required=network_required(skill),
            persistent_write_requested=(
                skill == "MEMORY" and step["type"] == "write" and memory_write_ok),
            side_effect_class=se,
            execution_authority=False,
            approval_required=appr,
            approval_reason=reason,
            optional=bool(step.get("optional")),
            parallel_safe=bool(req.get("parallel_first") and i > 1),
            rationale={
                "selected_skill": skill,
                "dependency_reason": (
                    f"depends on {deps[0]}" if deps else "no predecessor"),
            },
        )
        tasks.append(t)
        if i == 1:
            fan_root = tid
        prev = tid
        if req.get("fan_in") and i == len(steps) and len(tasks) >= 3:
            # last task depends on all middle parallel tasks
            mid = [x.task_id for x in tasks[1:-1]]
            t.dependencies = mid or t.dependencies
    if req.get("include_optional_unfinished"):
        tasks.append(Task(
            task_id=f"t{len(tasks)+1:02d}",
            title="Optional polish pass",
            objective="Optional non-blocking polish",
            task_type="polish",
            required_skill="GENERAL",
            success_criteria=["optional polish recorded"],
            optional=True,
            execution_authority=False,
            side_effect_class="NONE",
        ))
    # Never emit the forbidden 3-step solve/verify/finish shape alone.
    titles = [t.title.lower() for t in tasks]
    if titles == ["solve problem", "verify problem", "finish"]:
        return decompose({**req, "goal_type": "CODE_BUGFIX", "subgoals": []},
                         {**parsed, "goal_type": "CODE_BUGFIX"}, registry)
    return tasks


def assumptions_from(parsed: dict) -> list[Assumption]:
    out = []
    for i, stmt in enumerate(parsed.get("assumptions") or [], start=1):
        text = stmt if isinstance(stmt, str) else str(
            (stmt or {}).get("statement") or stmt)
        out.append(Assumption(
            assumption_id=f"a{i:02d}",
            statement=text,
            confidence=(stmt.get("confidence") if isinstance(stmt, dict)
                        else "MEDIUM"),
            status="UNVERIFIED",
        ))
    return out
