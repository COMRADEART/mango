"""Public, synthetic 16-family qualification; permanently excluded from blind."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import (AUTHORITY, Adapter, IntegratedRunner,
                                           RecoverableError, UnavailableError)
from .contract import FAMILIES
from .scorer import score_suite

CAPABILITY_CHAINS = {
    "math_chain": ("MATH_T4", "SCICOMP", "GENERAL"),
    "science_evidence_synthesis": ("SCIENCE_RAG", "KNOWLEDGE_RAG", "GENERAL"),
    "math_science_cross_domain": ("SCIENCE_RAG", "MATH_T4", "SCICOMP"),
    "document_to_computation": ("DOCUMENT", "MATH_T4", "SCICOMP"),
    "research_to_science_answer": ("WEB_RESEARCH", "SCIENCE_RAG", "GENERAL"),
    "temporal_research": ("WEB_RESEARCH", "KNOWLEDGE_RAG", "GENERAL"),
    "conflicting_evidence": ("KNOWLEDGE_RAG", "SCIENCE_RAG", "NO_TOOL"),
    "insufficient_evidence": ("DOCUMENT", "KNOWLEDGE_RAG", "NO_TOOL"),
    "tool_failure_recovery": ("MATH_T4", "SCICOMP", "GENERAL"),
    "plan_replan_resume": ("PLANNING", "ORCHESTRATION", "MATH_T4"),
    "memory_assisted_multiturn": ("MEMORY", "KNOWLEDGE_RAG", "GENERAL"),
    "code_analysis_science": ("CODE", "SCIENCE_RAG", "SCICOMP"),
    "capability_unavailability": ("DOCUMENT", "WEB_RESEARCH", "SCIENCE_RAG"),
    "budget_constrained_execution": ("MATH_T4", "SCICOMP", "GENERAL"),
    "verification_and_correction": ("DOCUMENT", "MATH_T4", "GENERAL"),
    "adversarial_instruction_isolation": ("MEMORY", "DOCUMENT", "NO_TOOL"),
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _step(sid: str, capability: str, *, predecessor: str | None,
          base: int, delta: int, fallback: str | None = None) -> dict:
    router_input = {
        "query": f"Perform {capability} internal step for synthetic T26 fixture {sid}",
        "requested_capability": capability,
        "available_capabilities": list(SKILL_IDS),
        "permission_grants": ["network", "code_exec"],
    }
    payload = {"op": "seed", "seed": base} if predecessor is None else {
        "op": "add_previous", "delta": delta}
    return {
        "step_id": sid, "capability": capability,
        "depends_on": [predecessor] if predecessor else [],
        "router_input": router_input,
        "input": payload,
        "input_from": {"previous": predecessor} if predecessor else {},
        "preconditions": ["synthetic fixture data classified",
                          "all dependencies verified"],
        "expected_output": {"required_fields": ["status", "value", "evidence",
                                                "provenance", "classification",
                                                "confidence"],
                            "classification": "PUBLIC_SAFE"},
        "verification": {"kind": "evidence" if predecessor is None else "numeric",
                         "required": True,
                         "parameters": {} if predecessor is None else
                         {"operation": "add_previous", "tolerance": 1e-12}},
        "fallback_capability": fallback,
    }


def make_case(family: str, variant: int) -> tuple[dict, dict, dict]:
    if family not in FAMILIES or variant not in range(4):
        raise ValueError("unknown public qualification case")
    caps = CAPABILITY_CHAINS[family]
    case_id = f"t26q-{family}-{variant:02d}"
    base = 5 + FAMILIES.index(family) * 3 + variant
    fallback = None
    if variant == 0 and family in {
            "document_to_computation", "plan_replan_resume",
            "capability_unavailability", "verification_and_correction"}:
        fallback = "MATH_T4" if caps[2] != "MATH_T4" else "SCICOMP"
    if variant == 1 and family == "document_to_computation":
        fallback = "GENERAL"
    steps = [_step("s1", caps[0], predecessor=None, base=base, delta=0),
             _step("s2", caps[1], predecessor="s1", base=base, delta=2),
             _step("s3", caps[2], predecessor="s2", base=base, delta=3,
                   fallback=fallback)]
    budget = {"max_steps": 5, "max_step_retries": 1,
              "max_total_retries": 3, "max_replans": 2,
              "max_wall_seconds": 30}
    if variant == 0 and family == "budget_constrained_execution":
        budget["max_total_retries"] = 0
    plan = {
        "plan_id": f"plan-{case_id}", "version": 1,
        "goal": f"Use three dependent registered internal capabilities for {family}",
        "steps": steps, "budgets": budget,
        "completion_condition": {"required_steps": ["s1", "s2", "s3"],
                                 "final_step": "s3", "final_verification": True},
        "fallback_condition": {"on_failure": "SAFE_ABSTAIN",
                               "on_insufficient_evidence": "INSUFFICIENT_EVIDENCE"},
        "authority": AUTHORITY,
    }
    scenario = {"scenario_id": case_id, "plan": plan,
                "classification": "PUBLIC_SAFE"}
    expected_terminal = "COMPLETE"
    if variant == 0 and family in {"conflicting_evidence", "insufficient_evidence"}:
        expected_terminal = "INSUFFICIENT_EVIDENCE"
    if variant == 0 and family == "budget_constrained_execution":
        expected_terminal = "BUDGET_EXHAUSTED"
    if variant == 0 and family == "adversarial_instruction_isolation":
        expected_terminal = "SECURITY_REFUSAL"
    replan_trigger = None
    if variant == 0 and family == "document_to_computation":
        replan_trigger = "SCHEMA_MISMATCH"
    if variant == 1 and family == "document_to_computation":
        replan_trigger = "VERIFICATION_FAILURE"
    if variant == 0 and family == "plan_replan_resume":
        replan_trigger = "VERIFICATION_FAILURE"
    if variant == 0 and family == "capability_unavailability":
        replan_trigger = "UNAVAILABLE_CAPABILITY"
    if variant == 0 and family == "verification_and_correction":
        replan_trigger = "VERIFICATION_FAILURE"
    recoverable = (variant == 0 and family in {
        "tool_failure_recovery", "plan_replan_resume",
        "capability_unavailability", "verification_and_correction",
        "document_to_computation", "research_to_science_answer",
        "temporal_research"}) or (variant == 1 and family == "document_to_computation")
    gold = {
        "scenario_id": case_id, "expected_terminal": expected_terminal,
        "expected_answer": base + 5 if expected_terminal == "COMPLETE" else None,
        "expected_replan_trigger": replan_trigger,
        "recoverable_failure": recoverable,
        "safe_abstention": expected_terminal != "COMPLETE",
    }
    injection = {"family": family, "variant": variant,
                 "kind": _injection_kind(family, variant)}
    return scenario, gold, injection


def _injection_kind(family: str, variant: int) -> str:
    if variant == 0:
        return {
            "conflicting_evidence": "conflicting_evidence",
            "insufficient_evidence": "missing_evidence",
            "tool_failure_recovery": "tool_error",
            "plan_replan_resume": "verification_failure_resume",
            "capability_unavailability": "tool_unavailable",
            "budget_constrained_execution": "budget_exhaustion",
            "verification_and_correction": "verification_failure",
            "adversarial_instruction_isolation": "external_action_request",
            "research_to_science_answer": "retriever_error",
            "temporal_research": "provider_exception",
            "document_to_computation": "invalid_capability_response",
        }.get(family, "none")
    if variant == 1 and family == "document_to_computation":
        return "schema_mismatch"
    return "none"


def fixture_adapters(injection: dict) -> dict[str, Adapter]:
    attempts: dict[str, int] = {}
    kind = injection["kind"]

    def make(capability: str):
        def execute(payload: dict, context: dict) -> dict:
            step = context["step_id"]
            attempts[step] = attempts.get(step, 0) + 1
            first = attempts[step] == 1
            if kind in {"tool_error", "retriever_error", "provider_exception",
                        "budget_exhaustion"} and step == "s3" and first:
                raise RecoverableError(kind)
            if kind == "tool_unavailable" and step == "s3" and capability == "SCIENCE_RAG":
                raise UnavailableError(kind)
            if kind == "invalid_capability_response" and step == "s3" and first:
                return {"status": "OK", "value": 42, "unregistered_field": True}
            if kind == "external_action_request" and step == "s3":
                return {"requested_action": "send email"}
            if kind in {"conflicting_evidence", "missing_evidence"} and step == "s3":
                status = "CONFLICTING_EVIDENCE" if kind == "conflicting_evidence" else "INSUFFICIENT_EVIDENCE"
                return {"status": status, "value": None, "evidence": [],
                        "provenance": {"source_id": "fixture"},
                        "classification": context["classification"],
                        "confidence": "LOW"}
            if payload["op"] == "seed":
                value = payload["seed"]
            elif payload["op"] == "add_previous":
                value = payload["previous"] + payload["delta"]
            else:
                raise ValueError("unknown fixture operation")
            if kind in {"verification_failure", "verification_failure_resume",
                        "schema_mismatch"} and step == "s3" and first:
                if kind == "schema_mismatch":
                    classification = "PRIVATE_BLIND"
                else:
                    value += 1
                    classification = context["classification"]
            else:
                classification = context["classification"]
            return {"status": "OK", "value": value,
                    "evidence": [{"source_id": "t26-public-fixture",
                                  "chunk_id": f"{context['scenario_id']}-{step}",
                                  "citation": f"fixture:{context['scenario_id']}:{step}",
                                  "classification": classification,
                                  "freshness": "STATIC"}],
                    "provenance": {"source_id": "t26-public-fixture",
                                   "step_id": step, "adapter": capability,
                                   "instruction_authority": 0},
                    "classification": classification,
                    "confidence": "HIGH"}
        return execute
    return {cap: Adapter(cap, make(cap)) for cap in SKILL_IDS}


def build_public_cases() -> tuple[list[dict], list[dict], list[dict]]:
    triples = [make_case(family, variant)
               for family in FAMILIES for variant in range(4)]
    return ([x[0] for x in triples], [x[1] for x in triples],
            [x[2] for x in triples])


def run_qualification() -> dict:
    cases, gold, injections = build_public_cases()
    outputs = []
    with TemporaryDirectory(prefix="t26-public-qualification-") as tmp:
        for scenario, injection in zip(cases, injections):
            case_root = Path(tmp) / scenario["scenario_id"]
            case_root.mkdir()
            runner = IntegratedRunner(fixture_adapters(injection),
                                      sandbox_root=case_root)
            if injection["kind"] == "verification_failure_resume":
                partial = runner.run(scenario, stop_after_steps=1)
                if partial["terminal"] != "PARTIAL" or partial["verified_steps"] != ["s1"]:
                    raise ValueError("checkpoint interruption did not preserve first step")
                output = runner.run(scenario, resume=True)
            else:
                output = runner.run(scenario)
            outputs.append(output)
    score = score_suite(outputs, gold, [c["plan"] for c in cases])
    score.pop("rows")  # public report: aggregates only
    dispatch_unmatched = sum(
        event.get("status") == "ERROR" and event.get("output_commitment") is None
        for output in outputs for event in output["trace"])
    unexpected_unknown = sum(output["terminal"] not in {
        "COMPLETE", "PARTIAL", "INSUFFICIENT_EVIDENCE", "BLOCKED",
        "BUDGET_EXHAUSTED", "UNAVAILABLE_CAPABILITY", "SECURITY_REFUSAL", "ERROR"}
        for output in outputs)
    status = "PASS" if (score["status"] == "PASS" and dispatch_unmatched == 0
                        and unexpected_unknown == 0) else "FAIL"
    return {"schema_version": "t26-public-qualification-v1",
            "artifact": "T26_PUBLIC_QUALIFICATION_REPORT", "status": status,
            "family_count": len(FAMILIES), "scenario_count": len(cases),
            "cases_per_family": 4, "minimum_steps": 3,
            "material": "PUBLIC_SAFE_PERMANENTLY_EXCLUDED",
            "injection_counts": {kind: sum(i["kind"] == kind for i in injections)
                                 for kind in sorted({i["kind"] for i in injections})},
            "dispatch_unmatched": dispatch_unmatched,
            "unexpected_unknown_terminal": unexpected_unknown,
            "score": score,
            "trace_commitments": {o["scenario_id"]: _sha(json.dumps(
                [{k: v for k, v in event.items() if k not in
                  {"start_timestamp", "end_timestamp"}}
                 for event in o["trace"]], sort_keys=True))
                                  for o in outputs}}


def exclusion_fingerprints(cases: list[dict]) -> dict:
    return {"schema_version": "t26-qualification-exclusions-v1",
            "artifact": "T26_QUALIFICATION_EXCLUSIONS",
            "raw_content_included": False,
            "case_id_sha256": sorted(_sha(c["scenario_id"]) for c in cases),
            "goal_sha256": sorted(_sha(c["plan"]["goal"]) for c in cases),
            "router_query_sha256": sorted({
                _sha(s["router_input"]["query"])
                for c in cases for s in c["plan"]["steps"]}),
            "permanently_excluded_from_real_t26": True}
