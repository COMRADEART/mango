"""T14.10 — typed Skill Registry for the Mango Executive Router.

Availability is honest: PREPARED_ONLY skills are interfaces, not
runtimes. The router must never claim they executed.
"""
from __future__ import annotations

from copy import deepcopy

ACTIVE = "ACTIVE"
EXPERIMENTAL = "EXPERIMENTAL"
QUALIFIED = "QUALIFIED"
PREPARED_ONLY = "PREPARED_ONLY"
DISABLED = "DISABLED"
AVAILABILITIES = (ACTIVE, EXPERIMENTAL, QUALIFIED, PREPARED_ONLY, DISABLED)

LOCAL_FREE = "LOCAL_FREE"
LOCAL_EXPENSIVE = "LOCAL_EXPENSIVE"
ONLINE_FREE = "ONLINE_FREE"
ONLINE_METERED = "ONLINE_METERED"
PAID_COMPUTE = "PAID_COMPUTE"
COST_CLASSES = (LOCAL_FREE, LOCAL_EXPENSIVE, ONLINE_FREE,
                ONLINE_METERED, PAID_COMPUTE)

SKILL_IDS = (
    "GENERAL", "MATH_T4", "SCIENCE_RAG", "SCICOMP", "CODE",
    "WEB_RESEARCH", "DOCUMENT", "MEMORY", "PLANNING", "NO_TOOL",
    "ORCHESTRATION", "KNOWLEDGE_RAG",
)

_SCHEMA_EMPTY = {"type": "object", "properties": {}, "required": []}


def _skill(**kwargs) -> dict:
    base = {
        "skill_id": None,
        "description": "",
        "availability": PREPARED_ONLY,
        "input_schema": _SCHEMA_EMPTY,
        "output_schema": _SCHEMA_EMPTY,
        "preconditions": [],
        "required_permissions": [],
        "cost_class": LOCAL_FREE,
        "latency_class": "LOW",
        "offline": True,
        "online": False,
        "deterministic": True,
        "verification_method": "none",
        "fallback_behavior": "GENERAL",
        "executable": False,
    }
    base.update(kwargs)
    base["executable"] = base["availability"] in (ACTIVE, EXPERIMENTAL,
                                                    QUALIFIED)
    if base["cost_class"] == PAID_COMPUTE:
        base["executable"] = False
    return base


def default_registry() -> dict[str, dict]:
    """Closed catalogue. Unknown skill_ids are rejected, never invented."""
    return {
        "GENERAL": _skill(
            skill_id="GENERAL",
            description="General conversation and explanation without tools.",
            availability=ACTIVE,
            verification_method="none",
            fallback_behavior="NO_TOOL",
        ),
        "MATH_T4": _skill(
            skill_id="MATH_T4",
            description="Deterministic T4 math tools (calculator, symbolic, "
                        "units, numerical_math, equation_solver).",
            availability=ACTIVE,
            input_schema={"type": "object",
                          "properties": {"question": {"type": "string"}},
                          "required": ["question"]},
            output_schema={"type": "object",
                           "properties": {"value": {"type": "number"}}},
            preconditions=["question_is_t4_sufficient_or_helpful"],
            verification_method="t4_verifier",
            fallback_behavior="GENERAL",
        ),
        "SCIENCE_RAG": _skill(
            skill_id="SCIENCE_RAG",
            description="T5R scientific retrieval with citation discipline.",
            availability=ACTIVE,
            preconditions=["external_scientific_fact_needed"],
            verification_method="t5r_citation_gate",
            fallback_behavior="GENERAL",
            latency_class="MEDIUM",
        ),
        "SCICOMP": _skill(
            skill_id="SCICOMP",
            description="Scientific computing laboratory for bounded numerical "
                        "and symbolic computation. Promoted ACTIVE at T14R2.",
            availability=ACTIVE,
            preconditions=["compute_necessity_COMPUTE_REQUIRED",
                           "parameter_fidelity_gate",
                           "correction_firewall"],
            verification_method="scicomp_envelope",
            fallback_behavior="MATH_T4",
            latency_class="MEDIUM",
        ),
        "CODE": _skill(
            skill_id="CODE",
            description="Bounded repository-level coding intelligence "
                        "(CODE skill runtime). Promoted ACTIVE at T15R.",
            availability=ACTIVE,
            required_permissions=["code_exec"],
            cost_class=LOCAL_EXPENSIVE,
            deterministic=False,
            verification_method="none",
            fallback_behavior="GENERAL",
            latency_class="HIGH",
        ),
        "WEB_RESEARCH": _skill(
            skill_id="WEB_RESEARCH",
            description="Bounded web research: search, fetch, evaluate, "
                        "extract, verify, synthesize, cite. Fixture-first; "
                        "optional free live providers. T16 runtime.",
            availability=ACTIVE,
            required_permissions=["network"],
            cost_class=ONLINE_FREE,
            offline=True,
            online=True,
            deterministic=True,
            verification_method="web_evidence_graph",
            fallback_behavior="SCIENCE_RAG",
            latency_class="HIGH",
            input_schema={"type": "object",
                          "properties": {"question": {"type": "string"}},
                          "required": ["question"]},
            output_schema={"type": "object",
                           "properties": {
                               "answer": {"type": "string"},
                               "status": {"type": "string"},
                               "citations": {"type": "array"}}},
        ),
        "DOCUMENT": _skill(
            skill_id="DOCUMENT",
            description="Local document and structured-data intelligence: "
                        "identify, parse, search, QA, summarize, compare, "
                        "tables, schema, profile, filter, aggregate, join, "
                        "cite. Fixture-sandbox; no OCR; T17 runtime.",
            availability=ACTIVE,
            fallback_behavior="GENERAL",
            latency_class="MEDIUM",
        ),
        "MEMORY": _skill(
            skill_id="MEMORY",
            description="Persistent local memory: explicit write, scoped retrieval, provenance, conflict, expiry, deletion. Stored text is DATA (instruction authority 0). T18 runtime.",
            availability=ACTIVE,
            fallback_behavior="GENERAL",
        ),
        "PLANNING": _skill(
            skill_id="PLANNING",
            description="Long-horizon planner: decompose, sequence, monitor, "
                        "replan, resume, and completion-gate across registered "
                        "skills. Propose-only; no autonomous execution. T19 runtime.",
            availability=ACTIVE,
            verification_method="plan_schema",
            fallback_behavior="GENERAL",
            latency_class="MEDIUM",
        ),
        "NO_TOOL": _skill(
            skill_id="NO_TOOL",
            description="Explicit no-tool / needs-information terminal.",
            availability=ACTIVE,
            fallback_behavior="GENERAL",
        ),
        "ORCHESTRATION": _skill(
            skill_id="ORCHESTRATION",
            description="Bounded multi-agent orchestration: coordinates "
                        "specialist agents over validated T19 plans with "
                        "role manifests, handoff contracts, independent "
                        "verification, budgets, checkpoint/resume, and "
                        "recovery. COORDINATE_INTERNAL_WORK_ONLY; no "
                        "external action authority. T20 runtime. "
                        "Promoted ACTIVE at T20.",
            availability=ACTIVE,
            cost_class=LOCAL_EXPENSIVE,
            deterministic=True,
            verification_method="orchestration_run_audit",
            fallback_behavior="PLANNING",
            latency_class="MEDIUM",
        ),
        "KNOWLEDGE_RAG": _skill(
            skill_id="KNOWLEDGE_RAG",
            description="Local-first general knowledge retrieval with "
                        "source provenance, citation-grounded synthesis, "
                        "conflict handling, freshness boundaries, and "
                        "evidence-based abstention. Qualified for the exact "
                        "frozen T22 capability scope after the official "
                        "one-shot evaluation passed all 32 floors; this does "
                        "not imply a broader deployment or release gate.",
            availability=QUALIFIED,
            offline=True,
            online=False,
            cost_class=LOCAL_FREE,
            verification_method="knowledge_evidence_gate",
            fallback_behavior="GENERAL",
            latency_class="MEDIUM",
        ),
    }


class SkillRegistry:
    """Typed, closed skill catalogue (T14.10 / T14.11)."""

    def __init__(self, skills: dict[str, dict] | None = None):
        self._skills = deepcopy(skills or default_registry())
        for sid, rec in self._skills.items():
            if sid not in SKILL_IDS:
                raise ValueError(f"invented skill_id {sid!r}")
            if rec.get("skill_id") != sid:
                raise ValueError(f"skill_id mismatch {sid}")
            if rec.get("availability") not in AVAILABILITIES:
                raise ValueError(f"bad availability for {sid}")
            if rec.get("cost_class") not in COST_CLASSES:
                raise ValueError(f"bad cost_class for {sid}")

    def get(self, skill_id: str) -> dict | None:
        rec = self._skills.get(skill_id)
        return deepcopy(rec) if rec else None

    def known(self, skill_id: str) -> bool:
        return skill_id in self._skills

    def availability(self, skill_id: str) -> str:
        rec = self._skills.get(skill_id)
        return rec["availability"] if rec else DISABLED

    def executable(self, skill_id: str) -> bool:
        rec = self._skills.get(skill_id)
        if rec is None:
            return False
        if rec["cost_class"] == PAID_COMPUTE:
            return False
        return rec["availability"] in (ACTIVE, EXPERIMENTAL, QUALIFIED)

    def ids(self) -> tuple[str, ...]:
        return tuple(self._skills)

    def as_dict(self) -> dict:
        return deepcopy(self._skills)

    def counts(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(s["availability"] for s in self._skills.values()))


def registry_sha256(registry: SkillRegistry | None = None) -> str:
    import hashlib
    import json
    reg = registry or SkillRegistry()
    blob = json.dumps(reg.as_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
