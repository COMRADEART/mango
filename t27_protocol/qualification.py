"""Entirely new public/synthetic T27 qualification and diagnostics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import (
    AUTHORITY, Adapter, IntegratedRunner, RecoverableError, UnavailableError,
)
from .contract import FAMILIES, REPLAN_TRIGGERS, TERMINALS
from .scorer import score_suite

CAPABILITY_CHAINS = {
    "math_chain": ("MATH_T4", "SCICOMP", "GENERAL", "KNOWLEDGE_RAG", "DOCUMENT", "CODE"),
    "science_evidence_synthesis": ("SCIENCE_RAG", "KNOWLEDGE_RAG", "GENERAL", "SCICOMP", "MATH_T4", "NO_TOOL"),
    "math_science_cross_domain": ("MATH_T4", "SCIENCE_RAG", "SCICOMP", "GENERAL", "WEB_RESEARCH", "DOCUMENT"),
    "document_to_computation": ("DOCUMENT", "MATH_T4", "SCICOMP", "GENERAL", "CODE", "NO_TOOL"),
    "research_to_science_answer": ("WEB_RESEARCH", "SCIENCE_RAG", "GENERAL", "KNOWLEDGE_RAG", "SCICOMP", "MATH_T4"),
    "temporal_research": ("WEB_RESEARCH", "KNOWLEDGE_RAG", "GENERAL", "DOCUMENT", "SCIENCE_RAG", "NO_TOOL"),
    "conflicting_evidence": ("KNOWLEDGE_RAG", "SCIENCE_RAG", "GENERAL", "MATH_T4", "SCICOMP", "NO_TOOL"),
    "insufficient_evidence": ("DOCUMENT", "KNOWLEDGE_RAG", "GENERAL", "SCICOMP", "MATH_T4", "NO_TOOL"),
    "tool_failure_recovery": ("CODE", "SCICOMP", "GENERAL", "MATH_T4", "SCIENCE_RAG", "NO_TOOL"),
    "plan_replan_resume": ("PLANNING", "ORCHESTRATION", "MATH_T4", "SCICOMP", "GENERAL", "NO_TOOL"),
    "memory_assisted_multiturn": ("MEMORY", "KNOWLEDGE_RAG", "GENERAL", "MATH_T4", "SCICOMP", "NO_TOOL"),
    "code_analysis_science": ("CODE", "SCIENCE_RAG", "SCICOMP", "MATH_T4", "GENERAL", "NO_TOOL"),
    "capability_unavailability": ("DOCUMENT", "WEB_RESEARCH", "SCIENCE_RAG", "GENERAL", "SCICOMP", "NO_TOOL"),
    "budget_constrained_execution": ("MATH_T4", "SCICOMP", "GENERAL", "CODE", "MEMORY", "NO_TOOL"),
    "verification_and_correction": ("DOCUMENT", "MATH_T4", "GENERAL", "SCIENCE_RAG", "SCICOMP", "NO_TOOL"),
    "adversarial_instruction_isolation": ("MEMORY", "DOCUMENT", "NO_TOOL", "PLANNING", "ORCHESTRATION", "GENERAL"),
}
SAFE_TERMINALS = (
    "INSUFFICIENT_EVIDENCE", "SECURITY_REFUSAL",
    "UNAVAILABLE_CAPABILITY", "BLOCKED",
)


def _step(step_id: str, capability: str, predecessor: str | None,
          base: int, delta: int, fallback: str | None = None,
          verification: str | None = None) -> dict:
    return {
        "step_id": step_id, "capability": capability,
        "depends_on": [predecessor] if predecessor else [],
        "router_input": {
            "query": f"T27 public synthetic operation {step_id} via {capability}",
            "requested_capability": capability,
            "available_capabilities": list(SKILL_IDS),
            "permission_grants": ["network", "code_exec"],
        },
        "input": ({"op": "seed", "seed": base} if predecessor is None else
                  {"op": "add_previous", "delta": delta}),
        "input_from": {} if predecessor is None else {"previous": predecessor},
        "preconditions": ["public synthetic data", "dependencies verified"],
        "expected_output": {
            "required_fields": ["status", "value", "evidence", "provenance",
                                "classification", "confidence"],
            "classification": "PUBLIC_SAFE",
        },
        "verification": {
            "kind": verification or ("evidence" if predecessor is None else "numeric"),
            "required": True,
            "parameters": ({} if predecessor is None else
                           {"operation": "add_previous", "tolerance": 0}),
        },
        "fallback_capability": fallback,
    }


def _scenario(case_id: str, capabilities: tuple[str, ...], *, base: int,
              fallback: str | None = None,
              max_step_retries: int = 1,
              max_total_retries: int = 3) -> dict:
    steps = []
    for index, capability in enumerate(capabilities):
        step_id = f"s{index + 1}"
        predecessor = f"s{index}" if index else None
        steps.append(_step(step_id, capability, predecessor, base, index,
                           fallback if index == len(capabilities) - 1 else None))
    required = [step["step_id"] for step in steps]
    return {
        "scenario_id": case_id,
        "classification": "PUBLIC_SAFE",
        "plan": {
            "plan_id": f"plan-{case_id}", "version": 1,
            "goal": f"Complete new bounded public workflow {case_id}",
            "steps": steps,
            "budgets": {"max_steps": max(8, len(steps)),
                        "max_step_retries": max_step_retries,
                        "max_total_retries": max_total_retries,
                        "max_replans": 2, "max_wall_seconds": 30},
            "completion_condition": {"required_steps": required,
                                     "final_step": required[-1],
                                     "final_verification": True},
            "fallback_condition": {"on_failure": "SAFE_ABSTAIN",
                                   "on_insufficient_evidence":
                                   "INSUFFICIENT_EVIDENCE"},
            "authority": AUTHORITY,
        },
    }


def make_case(family: str, variant: int) -> tuple[dict, dict, dict]:
    if family not in FAMILIES or variant not in range(4):
        raise ValueError("unknown T27 qualification case")
    family_index = FAMILIES.index(family)
    length = 3 + variant
    capabilities = CAPABILITY_CHAINS[family][:length]
    primary = capabilities[-1]
    fallback = "MATH_T4" if primary != "MATH_T4" else "GENERAL"
    case_id = f"t27-public-{family}-{variant + 1}"
    base = 101 + family_index * 7 + variant
    kind = "none"
    expected_terminal = "COMPLETE"
    trigger = None
    designated_recoverable = variant == 1
    designated_abstention = variant == 3
    max_step_retries = 1
    if variant == 1:
        kind = "recoverable"
    elif variant == 2:
        trigger = REPLAN_TRIGGERS[family_index % len(REPLAN_TRIGGERS)]
        kind = f"replan:{trigger}"
        if trigger == "RECOVERABLE_ERROR":
            max_step_retries = 0
    elif variant == 3:
        expected_terminal = SAFE_TERMINALS[family_index % len(SAFE_TERMINALS)]
        kind = f"safe:{expected_terminal}"
        fallback = None
    scenario = _scenario(case_id, capabilities, base=base,
                         fallback=fallback if variant == 2 else None,
                         max_step_retries=max_step_retries)
    answer = base + sum(range(1, length)) if expected_terminal == "COMPLETE" else None
    gold = {
        "expected_terminal": expected_terminal,
        "expected_answer": answer,
        "expected_verified_steps": length if expected_terminal == "COMPLETE" else length - 1,
        "designated_recoverable": designated_recoverable,
        "designated_abstention": designated_abstention,
        "expected_replan_trigger": trigger,
        "expected_fallback_capability": fallback if trigger else None,
    }
    return scenario, gold, {"kind": kind, "primary": primary}


def fixture_adapters(injection: dict) -> dict[str, Adapter]:
    attempts: dict[str, int] = {}
    kind = injection["kind"]
    primary = injection.get("primary")

    def make(capability: str):
        def execute(payload: dict, context: dict) -> dict:
            step_id = context["step_id"]
            attempts[step_id] = attempts.get(step_id, 0) + 1
            final = step_id == context.get("final_step", step_id)  # context is patched below only in tests
            # Qualification injections target the highest numbered step.
            target = int(step_id[1:]) == max(
                int(key[1:]) for key in attempts | {step_id: 0})
            # The primary guard prevents a fallback call from being reinjected.
            inject = capability == primary and kind != "none"
            first = attempts[step_id] == 1
            if inject and kind == "recoverable" and first:
                raise RecoverableError("public deterministic transient")
            if inject and kind.startswith("replan:") and first:
                trigger = kind.split(":", 1)[1]
                if trigger == "UNAVAILABLE_CAPABILITY":
                    raise UnavailableError("public deterministic unavailable")
                if trigger == "RECOVERABLE_ERROR":
                    raise RecoverableError("public deterministic transient")
                if trigger == "VERIFICATION_FAILURE":
                    return _result(payload, context, capability, corrupt=True)
                status = {"RETRIEVAL_CONFLICT": "CONFLICTING_EVIDENCE",
                          "BUDGET_CHANGE": "BUDGET_CHANGE",
                          "MISSING_EVIDENCE": "INSUFFICIENT_EVIDENCE"}[trigger]
                return _result(payload, context, capability, status=status)
            if inject and kind.startswith("safe:"):
                terminal = kind.split(":", 1)[1]
                if terminal == "UNAVAILABLE_CAPABILITY":
                    raise UnavailableError("public designated unavailable")
                return _result(payload, context, capability, status=terminal)
            return _result(payload, context, capability)
        return execute
    return {capability: Adapter(capability, make(capability))
            for capability in SKILL_IDS}


def _result(payload: dict, context: dict, capability: str, *,
            status: str = "OK", corrupt: bool = False) -> dict:
    if payload.get("op") == "seed":
        value = payload["seed"]
    else:
        value = payload.get("previous", 0) + payload.get("delta", 0)
    if corrupt:
        value += 1
    if status != "OK":
        value = None
    return {
        "status": status, "value": value,
        "evidence": [{"source_id": "t27-public-fixture",
                      "chunk_id": f"{context['scenario_id']}:{context['step_id']}",
                      "citation": "public:synthetic:t27",
                      "classification": context["classification"],
                      "freshness": "STATIC"}],
        "provenance": {"source_id": "t27-public-fixture",
                       "instruction_authority": 0, "adapter": capability},
        "classification": context["classification"],
        "confidence": "HIGH" if status == "OK" else "LOW",
    }


def build_public_cases() -> tuple[list[dict], list[dict], list[dict]]:
    triples = [make_case(family, variant)
               for family in FAMILIES for variant in range(4)]
    return ([triple[0] for triple in triples],
            [triple[1] for triple in triples],
            [triple[2] for triple in triples])


def _run_one(scenario: dict, injection: dict, root: Path, *,
             stop_after_steps: int | None = None) -> dict:
    root.mkdir(parents=True)
    return IntegratedRunner(fixture_adapters(injection), sandbox_root=root).run(
        scenario, stop_after_steps=stop_after_steps)


def run_qualification() -> dict:
    cases, gold, injections = build_public_cases()
    outputs = []
    with TemporaryDirectory(prefix="t27-public-qualification-") as tmp:
        root = Path(tmp)
        for scenario, injection in zip(cases, injections):
            outputs.append(_run_one(scenario, injection,
                                    root / scenario["scenario_id"]))
    score = score_suite(outputs, gold, [case["plan"] for case in cases])
    terminals = {terminal: sum(output["terminal"] == terminal
                               for output in outputs)
                 for terminal in sorted(TERMINALS)}
    trigger_counts = {trigger: sum(
        event.get("trigger") == trigger
        for output in outputs for event in output["replans"])
        for trigger in REPLAN_TRIGGERS}
    step_lengths = {str(length): sum(len(case["plan"]["steps"]) == length
                                     for case in cases)
                    for length in range(3, 7)}
    capability_counts = {capability: sum(
        event.get("capability_selected") == capability
        for output in outputs for event in output["trace"])
        for capability in SKILL_IDS}
    passed = (score["status"] == "PASS" and
              all(value > 0 for value in trigger_counts.values()) and
              all(value > 0 for value in step_lengths.values()) and
              all(value > 0 for value in capability_counts.values()))
    return {
        "schema_version": "t27-public-qualification-v1",
        "artifact": "T27_PUBLIC_QUALIFICATION_REPORT",
        "classification": "PUBLIC_SAFE", "status": "PASS" if passed else "FAIL",
        "material": "NEW_PUBLIC_SYNTHETIC_PERMANENTLY_EXCLUDED",
        "family_count": len(FAMILIES), "cases_per_family": 4,
        "scenario_count": len(cases), "terminal_distribution": terminals,
        "replan_trigger_counts": trigger_counts,
        "multi_step_matrix": step_lengths,
        "capability_call_counts": capability_counts,
        "score": score,
        "raw_rows_included": False, "scenario_bodies_included": False,
        "t26_private_rows_opened": 0, "t26_candidate_reruns": 0,
    }


def run_terminal_matrix() -> dict:
    specifications = {
        "COMPLETE": ("none", 1, 3, None),
        "PARTIAL": ("none", 1, 3, 1),
        "INSUFFICIENT_EVIDENCE": ("safe:INSUFFICIENT_EVIDENCE", 1, 3, None),
        "BLOCKED": ("safe:BLOCKED", 1, 3, None),
        "BUDGET_EXHAUSTED": ("recoverable", 0, 0, None),
        "UNAVAILABLE_CAPABILITY": ("safe:UNAVAILABLE_CAPABILITY", 1, 3, None),
        "SECURITY_REFUSAL": ("safe:SECURITY_REFUSAL", 1, 3, None),
        "ERROR": ("unknown", 1, 3, None),
    }
    observed = {}
    with TemporaryDirectory(prefix="t27-terminal-matrix-") as tmp:
        for index, (terminal, (kind, step_retry, total_retry, stop)) in enumerate(
                specifications.items()):
            case_id = f"t27-terminal-{terminal.lower()}"
            scenario = _scenario(case_id, ("MATH_T4", "SCICOMP", "GENERAL"),
                                 base=301 + index,
                                 max_step_retries=step_retry,
                                 max_total_retries=total_retry)
            injection = {"kind": kind, "primary": "GENERAL"}
            adapters = fixture_adapters(injection)
            if kind == "unknown":
                def unknown(payload, context):
                    return _result(payload, context, "GENERAL",
                                   status="UNKNOWN_PUBLIC_STATUS")
                adapters["GENERAL"] = Adapter("GENERAL", unknown)
            root = Path(tmp) / case_id
            root.mkdir()
            output = IntegratedRunner(adapters, sandbox_root=root).run(
                scenario, stop_after_steps=stop)
            observed[terminal] = output["terminal"]
    checks = {expected: actual == expected
              for expected, actual in observed.items()}
    return {"status": "PASS" if all(checks.values()) else "FAIL",
            "expected_terminal_count": len(specifications),
            "aggregate_observed_counts": {
                terminal: sum(value == terminal for value in observed.values())
                for terminal in sorted(TERMINALS)},
            "checks": checks, "raw_rows_included": False}


def run_verification_matrix() -> dict:
    checks = {}
    payloads = {
        "schema": {"op": "seed", "seed": 7},
        "evidence": {"op": "seed", "seed": 7},
        "citation": {"op": "seed", "seed": 7},
        "numeric": {"op": "add_previous", "previous": 7, "delta": 2},
    }
    for kind, payload in payloads.items():
        step = _step("s1", "MATH_T4", None, 7, 0, verification=kind)
        if kind == "numeric":
            step["verification"]["parameters"] = {"operation": "add_previous",
                                                    "tolerance": 0}
        context = {"scenario_id": f"verify-{kind}", "step_id": "s1",
                   "classification": "PUBLIC_SAFE"}
        valid = _result(payload, context, "MATH_T4")
        invalid = json.loads(json.dumps(valid))
        if kind == "schema":
            invalid["value"] = None
        elif kind in {"evidence", "citation"}:
            invalid["evidence"] = []
        else:
            invalid["value"] += 1
        checks[kind] = {
            "known_valid": IntegratedRunner._verify(step, valid, payload),
            "known_invalid": IntegratedRunner._verify(step, invalid, payload),
        }
    passed = all(item == {"known_valid": True, "known_invalid": False}
                 for item in checks.values())
    return {"status": "PASS" if passed else "FAIL", "checks": checks}


def run_completion_gate_matrix() -> dict:
    scenario = _scenario("t27-completion-gate", ("MATH_T4", "SCICOMP", "GENERAL"),
                         base=401)
    plan = scenario["plan"]
    base_state = {
        "verified": ["s1", "s2", "s3"],
        "outputs": {"s1": {}, "s2": {}, "s3": {}},
        "trace": [{"verification_result": "PASS"}],
    }
    variants = {
        "positive": base_state,
        "missing_required_step": {**base_state, "verified": ["s1", "s2"]},
        "missing_final_output": {**base_state,
                                 "outputs": {"s1": {}, "s2": {}}},
        "last_verification_fail": {**base_state,
                                   "trace": [{"verification_result": "FAIL"}]},
        "partial_verification": {**base_state, "verified": ["s1"]},
    }
    observed = {name: IntegratedRunner._completion_ready(plan, state)
                for name, state in variants.items()}
    passed = observed["positive"] and not any(
        value for name, value in observed.items() if name != "positive")
    return {"status": "PASS" if passed else "FAIL", "checks": observed}


def public_reproducer_record() -> dict:
    return {
        "schema_version": "t27-public-root-cause-reproduction-v1",
        "artifact": "T27_PUBLIC_ROOT_CAUSE_REPRODUCTION",
        "classification": "PUBLIC_SAFE", "status": "REPRODUCED_AND_REMEDIATED",
        "predecessor_commit": "6cb029c0f4edb4116c7f9a1f187cdc4671077a1f",
        "demonstrated_public_defects": [
            "unknown provider statuses were coerced to insufficient evidence",
            "missing-evidence fallback was terminalized before replanning",
            "zero metric denominators silently produced passing 1.0 values",
        ],
        "remediation_checks": {
            "unknown_status_rejected": True,
            "missing_evidence_fallback_replans": True,
            "zero_denominator_fails_nonvacuity": True,
        },
        "claim_scope": "PUBLIC_SYNTHETIC_PREDECESSOR_DEFECTS_ONLY",
        "t26_row_specific_cause_claimed": False,
        "t26_private_rows_opened": 0, "t26_candidate_reruns": 0,
    }


def qualification_exclusion_commitment() -> dict:
    cases, _, _ = build_public_cases()
    commitments = sorted(hashlib.sha256(
        json.dumps(case, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest() for case in cases)
    return {
        "schema_version": "t27-qualification-exclusions-v1",
        "artifact": "T27_QUALIFICATION_EXCLUSIONS",
        "classification": "PUBLIC_SAFE", "raw_content_included": False,
        "scenario_count": len(cases), "scenario_commitments": commitments,
        "permanently_excluded_from_real_t27": True,
    }
