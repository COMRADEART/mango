"""T7.6/T7.7/T7.8 — Plan schema, validation, and construction.

Plans contain ONLY the five allowed actions. Validation is strict:
unique IDs, DAG (acyclic dependencies), bounded steps, exactly one
terminal SYNTHESIZE. A malformed model-proposed plan gets ONE retry
with structured error feedback; after that a deterministic fallback
plan is constructed and the fallback is recorded separately
(T7.23: first-attempt validity / retry validity / fallback rate are
reported apart — malformed plans are never silently repaired and
called model-valid).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict

from sciencemath.executive.budgets import MAX_PLAN_STEPS

ACTIONS = ("REASON", "RETRIEVE", "MATH_TOOL", "CHECK", "SYNTHESIZE")

PLAN_SCHEMA_DOC = """{
  "steps": [
    {"id": "s1", "action": "REASON|MATH_TOOL|RETRIEVE|CHECK|SYNTHESIZE",
     "description": "<= 200 chars, what this step does",
     "depends_on": ["ids of prerequisite steps", "..."],
     "input": "<expression / query / claim to check — optional>"}
  ]
}
Rules: 1-6 steps; unique ids; dependencies must reference EARLIER ids
(no cycles); exactly one SYNTHESIZE and it must be LAST; use MATH_TOOL
for arithmetic (input = expression), RETRIEVE for factual lookup
(input = search query), CHECK to verify an intermediate claim,
REASON for reasoning steps that need no tool."""


# -- validation ---------------------------------------------------------------
@dataclass
class PlanValidation:
    ok: bool
    errors: list = field(default_factory=list)
    feedback: str = ""          # structured feedback for the retry prompt

    def to_dict(self) -> dict:
        return asdict(self)


def validate_plan(plan: dict, max_steps: int = MAX_PLAN_STEPS) -> PlanValidation:
    errors: list[str] = []

    if not isinstance(plan, dict):
        return PlanValidation(False, ["plan is not a JSON object"],
                              "The plan must be a JSON object.")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return PlanValidation(False, ["plan.steps missing or empty"],
                              "Provide a non-empty 'steps' array.")
    if len(steps) > max_steps:
        errors.append(f"too many steps ({len(steps)} > {max_steps})")

    ids: list[str] = []
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            errors.append(f"step {i} is not an object")
            continue
        sid = st.get("id")
        if not isinstance(sid, str) or not sid.strip():
            errors.append(f"step {i} missing string id")
        else:
            if sid in ids:
                errors.append(f"duplicate step id {sid!r}")
            ids.append(sid)
        action = st.get("action")
        if action not in ACTIONS:
            errors.append(f"step {sid or i}: action {action!r} not in "
                          f"{list(ACTIONS)}")
        desc = st.get("description")
        if not isinstance(desc, str) or not desc.strip():
            errors.append(f"step {sid or i}: missing description")
        elif len(desc) > 200:
            errors.append(f"step {sid or i}: description > 200 chars")

    # dependency DAG: unique ids, deps reference earlier ids only
    if len(ids) == len(set(ids)):
        for i, st in enumerate(steps):
            if not isinstance(st, dict):
                continue
            for dep in st.get("depends_on", []) or []:
                if dep not in ids:
                    errors.append(f"step {st.get('id')}: unknown dependency "
                                  f"{dep!r}")
                elif ids.index(dep) >= i:
                    errors.append(f"step {st.get('id')}: dependency {dep!r} "
                                  "must come earlier (cycles forbidden)")

    # terminal synthesis
    if steps and isinstance(steps[-1], dict):
        if steps[-1].get("action") != "SYNTHESIZE":
            errors.append("last step must be SYNTHESIZE")
        synths = [s.get("action") for s in steps if isinstance(s, dict)]
        if synths.count("SYNTHESIZE") > 1:
            errors.append("more than one SYNTHESIZE step")

    if errors:
        feedback = ("Your plan was rejected for these reasons:\n- " +
                    "\n- ".join(errors[:8]) +
                    "\nRe-emit the plan as JSON exactly matching this "
                    "schema:\n" + PLAN_SCHEMA_DOC)
        return PlanValidation(False, errors, feedback)
    return PlanValidation(True)


def plan_fingerprint(plan: dict) -> str:
    """Stable fingerprint for loop detection (T7.13)."""
    canon = json.dumps(plan, sort_keys=True, ensure_ascii=False)
    import hashlib
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


# -- model-proposed plan parsing ----------------------------------------------
def parse_model_plan(raw: str) -> dict | None:
    """Extract the first JSON object from a model response. Returns None
    if unparseable — never guessed into a plan."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# -- deterministic fallback plan (T7.8) ----------------------------------------
def fallback_plan(cls: dict, understanding: dict) -> dict:
    """Deterministic template plan from classification + understanding.
    Guaranteed valid by construction; marked source='deterministic'.
    A MATH_TOOL step is only emitted with a concrete expression — a
    prose placeholder would deterministically fail in the calculator."""
    steps: list[dict] = []
    rtype = cls.get("problem_type", "GENERAL")
    res = cls.get("resources", "NONE")
    expression = (understanding.get("expression") or "").strip()

    if res in ("RETRIEVAL", "BOTH") or rtype == "SCIENCE" or \
            understanding.get("force_retrieval"):
        steps.append({"id": "s1", "action": "RETRIEVE",
                      "description": "Retrieve factual evidence for the "
                                     "question target",
                      "depends_on": [],
                      "input": understanding.get("question_target",
                                                 "")[:200]})
    if res in ("MATH_TOOL", "BOTH") or rtype in ("MATH", "MIXED"):
        if expression:
            steps.append({"id": "s2", "action": "MATH_TOOL",
                          "description": "Compute the required quantity "
                                         "with the deterministic calculator",
                          "depends_on": ([steps[0]["id"]] if steps else []),
                          "input": expression})
        else:
            steps.append({"id": "s2", "action": "REASON",
                          "description": "Work out the required quantity "
                                         "step by step, showing arithmetic",
                          "depends_on": ([steps[0]["id"]] if steps else []),
                          "input": ""})
    if rtype == "SCIENCE" and res not in ("RETRIEVAL", "BOTH"):
        steps.append({"id": "s3", "action": "REASON",
                      "description": "Reason over the question using "
                                     "provided context only",
                      "depends_on": ([steps[-1]["id"]] if steps else []),
                      "input": ""})
    used = {s["id"] for s in steps}
    n = 1
    while f"s{n}" in used:
        n += 1
    steps.append({"id": f"s{n}", "action": "SYNTHESIZE",
                  "description": "Produce the final answer from step "
                                 "observations",
                  "depends_on": ([steps[-1]["id"]] if steps else []),
                  "input": ""})
    plan = {"steps": steps, "source": "deterministic_fallback"}
    v = validate_plan(plan)
    if not v.ok:
        raise AssertionError(f"deterministic fallback plan invalid: "
                             f"{v.errors}")
    return plan