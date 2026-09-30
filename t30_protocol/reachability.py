"""T30 real-stack nonvacuity reachability (recovery-reachability remediation).

Everything here is PUBLIC_SAFE / SYNTHETIC_DISPOSABLE / PERMANENTLY_EXCLUDED
material that can never be reused as T30 real material.  The disposable
bundle is executable by the UNCHANGED T30 production adapter registry
(``t30_protocol.production:build_adapters``) — never by the qualification
``fixture_adapters`` — and exercises every nonvacuity designation through
qualified local deterministic capabilities only:

* successful completion — MATH_T4/SCICOMP numeric chains;
* recovery — one frozen transient fault from the recovery-control wrapper;
* replan — CODE unavailable (no code repository in the evaluation
  workspace) -> MATH_T4, MATH_T4 unparseable expression (MISSING_EVIDENCE) ->
  SCICOMP, MATH_T4 wrong value (VERIFICATION_FAILURE) -> SCICOMP;
* safe abstention — NO_TOOL (INSUFFICIENT_EVIDENCE) and CODE without a
  fallback (UNAVAILABLE_CAPABILITY);
* handoff / verification — every multi-step plan.

Causal order (§14): scenarios -> recovery control (scenarios only) ->
``designated_recoverable`` derived from the control -> gold.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from t21_protocol.util import sha256_json

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import AUTHORITY, ExecutionError
from .contract import FAMILIES, NONVACUITY_MINIMUMS
from .recovery_control import (
    FAULT_CLASS, FAULT_MESSAGE, POLICY_ROOT, RecoveryControlError,
    aggregate_audits, build_recovery_control, candidate_control_exposure,
    check_designation_consistency, control_sha256, derive_recoverable_labels,
    recovery_control_policy, validate_control_shape, validate_recovery_control,
    wrap_production_adapters)
from .scorer import score_suite

REACHABILITY_VARIANT = 21
MATERIAL = "SYNTHETIC_DISPOSABLE_PERMANENTLY_EXCLUDED"
KINDS = ("COMPLETE", "RECOVERABLE", "REPLAN", "ABSTAIN")
REPLAN_STIMULI = (
    ("UNAVAILABLE_CAPABILITY", "CODE", "MATH_T4"),
    ("MISSING_EVIDENCE", "MATH_T4", "SCICOMP"),
    ("VERIFICATION_FAILURE", "MATH_T4", "SCICOMP"),
)
ABSTENTION_STIMULI = (
    ("INSUFFICIENT_EVIDENCE", "NO_TOOL"),
    ("UNAVAILABLE_CAPABILITY", "CODE"),
)
REQUIRED_FIELDS = ["status", "value", "evidence", "provenance",
                   "classification", "confidence"]
ADD_PREVIOUS = {"operation": "add_previous", "tolerance": 0}


def _router(step_id: str, capability: str, scenario_id: str) -> dict[str, Any]:
    return {"query": f"disposable reachability {scenario_id} {step_id} {capability}",
            "requested_capability": capability,
            "available_capabilities": list(SKILL_IDS),
            "permission_grants": ["network", "code_exec"]}


def _step(scenario_id: str, step_id: str, capability: str,
          predecessor: str | None, payload: dict[str, Any], kind: str,
          parameters: dict[str, Any], fallback: str | None = None
          ) -> dict[str, Any]:
    return {
        "step_id": step_id, "capability": capability,
        "depends_on": [predecessor] if predecessor else [],
        "router_input": _router(step_id, capability, scenario_id),
        "input": payload,
        "input_from": {"previous": predecessor} if predecessor else {},
        "preconditions": ["synthetic disposable data", "dependencies verified"],
        "expected_output": {"required_fields": list(REQUIRED_FIELDS),
                            "classification": "PUBLIC_SAFE"},
        "verification": {"kind": kind, "required": True,
                         "parameters": parameters},
        "fallback_capability": fallback,
    }


def _design(variant: int, family_index: int, index: int) -> dict[str, Any]:
    kind = KINDS[index % 4]
    rotation = family_index + index // 4
    length = 3 + (index // 4) % 4
    return {"kind": kind, "length": length,
            "replan": REPLAN_STIMULI[rotation % len(REPLAN_STIMULI)],
            "abstain": ABSTENTION_STIMULI[rotation % len(ABSTENTION_STIMULI)],
            "target_step": f"s{1 + rotation % length}",
            "a": 100_000 * (variant + 1) + 1_000 * family_index + 10 * index + 1,
            "b": 7 + family_index + index}


def _scenario(variant: int, family: str, family_index: int, index: int
              ) -> tuple[dict[str, Any], dict[str, Any]]:
    design = _design(variant, family_index, index)
    scenario_id = f"t30-disposable-{variant}-{family}-{index + 1:02d}"
    a, b, length = design["a"], design["b"], design["length"]
    steps = [_step(scenario_id, "s1", "MATH_T4", None,
                   {"expression": f"{a}+{b}", "terms": [a, b]}, "numeric",
                   {"operation": "add", "tolerance": 0})]
    value = a + b
    for number in range(2, length):
        delta = 3 + number + family_index % 5
        step_id, predecessor = f"s{number}", f"s{number - 1}"
        if number % 2 == 0:
            payload = {"op": "describe_previous", "delta": delta,
                       "query": f"disposable mean {scenario_id} {step_id}"}
            capability = "SCICOMP"
        else:
            payload = {"delta": delta}
            capability = "MATH_T4"
        steps.append(_step(scenario_id, step_id, capability, predecessor,
                           payload, "numeric", ADD_PREVIOUS))
        value += delta
    final_id, final_pred = f"s{length}", f"s{length - 1}"
    final_delta = 5 + length + family_index % 3
    kind = design["kind"]
    if kind in {"COMPLETE", "RECOVERABLE"}:
        steps.append(_step(scenario_id, final_id, "MATH_T4", final_pred,
                           {"delta": final_delta}, "numeric", ADD_PREVIOUS))
    elif kind == "REPLAN":
        trigger, capability, fallback = design["replan"]
        if trigger == "UNAVAILABLE_CAPABILITY":
            payload = {"request": f"disposable analysis {scenario_id}",
                       "delta": final_delta}
        elif trigger == "MISSING_EVIDENCE":
            payload = {"expression": "((", "op": "describe_previous",
                       "delta": final_delta,
                       "query": f"disposable mean {scenario_id} {final_id}"}
        else:
            payload = {"expression": "1+1", "op": "describe_previous",
                       "delta": final_delta,
                       "query": f"disposable mean {scenario_id} {final_id}"}
        steps.append(_step(scenario_id, final_id, capability, final_pred,
                           payload, "numeric", ADD_PREVIOUS, fallback))
    else:
        terminal, capability = design["abstain"]
        payload = ({"query": f"disposable unanswerable {scenario_id}"}
                   if capability == "NO_TOOL"
                   else {"request": f"disposable analysis {scenario_id}"})
        steps.append(_step(scenario_id, final_id, capability, final_pred,
                           payload, "evidence", {}))
    required = [step["step_id"] for step in steps]
    scenario = {
        "scenario_id": scenario_id, "classification": "PUBLIC_SAFE",
        "plan": {
            "plan_id": f"plan-{scenario_id}", "version": 1,
            "goal": f"Disposable T30 reachability {variant} {family} {index + 1}",
            "steps": steps,
            "budgets": {"max_steps": max(8, length), "max_step_retries": 1,
                        "max_total_retries": 3, "max_replans": 2,
                        "max_wall_seconds": 30},
            "completion_condition": {"required_steps": required,
                                     "final_step": required[-1],
                                     "final_verification": True},
            "fallback_condition": {"on_failure": "SAFE_ABSTAIN",
                                   "on_insufficient_evidence":
                                   "INSUFFICIENT_EVIDENCE"},
            "authority": AUTHORITY,
        },
    }
    design["final_value"] = value + final_delta
    return scenario, design


def production_disposable_scenarios(variant: int
                                    ) -> tuple[list[dict[str, Any]],
                                               list[dict[str, Any]]]:
    """§14 step 1: candidate-visible scenarios only (no gold exists yet)."""
    cases, designs = [], []
    for family_index, family in enumerate(FAMILIES):
        for index in range(32):
            scenario, design = _scenario(variant, family, family_index, index)
            cases.append(scenario)
            designs.append({**design, "family": family})
    return cases, designs


def production_disposable_control(cases: list[dict[str, Any]], *,
                                  designs: list[dict[str, Any]] | None = None,
                                  variant: int | None = None
                                  ) -> dict[str, Any]:
    """§14 step 2: schedule generated from candidate-visible scenarios only."""
    if designs is None:
        if variant is None:
            raise ValueError("disposable control requires the scenario design")
        _cases, designs = production_disposable_scenarios(variant)
    targets = [(case["scenario_id"], design["target_step"])
               for case, design in zip(cases, designs)
               if design["kind"] == "RECOVERABLE"]
    return build_recovery_control(cases, targets,
                                  classification="SYNTHETIC_DISPOSABLE")


def _gold(cases: list[dict[str, Any]], designs: list[dict[str, Any]],
          control: dict[str, Any]) -> list[dict[str, Any]]:
    """§14 steps 3–4: gold derived AFTER the control; recoverable FROM it."""
    recoverable = derive_recoverable_labels(control)
    gold = []
    for case, design in zip(cases, designs):
        kind, length = design["kind"], design["length"]
        trigger = fallback = None
        if kind == "ABSTAIN":
            terminal = design["abstain"][0]
            answer: Any = f"T30-DISPOSABLE-{terminal}-{case['scenario_id']}"
            verified = length - 1
        else:
            terminal, answer, verified = "COMPLETE", design["final_value"], length
            if kind == "REPLAN":
                trigger, _capability, fallback = design["replan"]
        designated_recoverable = case["scenario_id"] in recoverable
        gold.append({
            "scenario_id": case["scenario_id"], "family": design["family"],
            "expected_terminal": terminal, "expected_answer": answer,
            "expected_verified_steps": verified,
            "designated_recoverable": designated_recoverable,
            "designated_abstention": kind == "ABSTAIN",
            "expected_replan_trigger": trigger,
            "expected_fallback_capability": fallback,
            "metric_designations": {
                "successful_completion": terminal == "COMPLETE",
                "recoverable": designated_recoverable,
                "replan_required": bool(trigger),
                "safe_abstention": kind == "ABSTAIN",
                "handoff": True, "verification": True,
            },
        })
    return gold


def production_disposable_bundle(variant: int = 0, *, with_fixture: bool = False
                                 ) -> tuple[list[dict[str, Any]],
                                            list[dict[str, Any]],
                                            list[dict[str, Any]],
                                            dict[str, Any]]:
    """Deterministic disposable 512/512 bundle + recovery control, in §14 order."""
    cases, designs = production_disposable_scenarios(variant)
    control = production_disposable_control(cases, designs=designs)
    gold = _gold(cases, designs, control)
    fixtures: list[dict[str, Any]] = []
    if with_fixture:
        content = f"disposable-t30-private-fixture-{variant}".encode("utf-8")
        fixtures.append({
            "logical_id": f"rehearsal-{variant}.bin",
            "classification": "PRIVATE_FIXTURE",
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
            "schema_type": "application/octet-stream", "content": content,
        })
    return cases, gold, fixtures, control


# ---------------------------------------------------------------------------
# §27/§29–§35 real-stack nonvacuity reachability gate
# ---------------------------------------------------------------------------


def _recovery_case_evidence(output: dict[str, Any],
                            entry: dict[str, Any]) -> dict[str, bool]:
    target_events = [event for event in output.get("trace", [])
                     if event.get("step_id") == entry["step_id"]]
    return {
        "first_designated_attempt_recoverable_error": bool(target_events)
        and target_events[0].get("status") == "RECOVERABLE_ERROR",
        "retry_count_at_least_one":
            output.get("budget_state", {}).get("total_retries", 0) >= 1,
        "terminal_complete": output.get("terminal") == "COMPLETE",
        "verification_pass": bool(output.get("trace"))
        and output["trace"][-1].get("verification_result") == "PASS",
    }


def execute_production_stack(root: Path, cases: list[dict[str, Any]],
                             control: dict[str, Any]) -> dict[str, Any]:
    """Run disposable scenarios through the frozen official factory in its
    tagged rehearsal mode: production adapter registry + recovery wrapper."""
    from .construction import candidate_input_projection
    from .official_environment import build_official_evaluation_environment
    environment = build_official_evaluation_environment(root, real=False)
    stack = environment.preflight()
    environment.factory.bind_recovery_control(control)
    projected = [candidate_input_projection(case) for case in cases]
    outputs = []
    with TemporaryDirectory(prefix="t30-reachability-") as tmp:
        base = Path(tmp)
        for item in projected:
            workspace = base / item["scenario_id"]
            workspace.mkdir()
            outputs.append(environment.factory(workspace).run(item))
    return {"outputs": outputs, "stack": stack,
            "audits": list(environment.factory.recovery_audits),
            "candidate_control_exposure": candidate_control_exposure(projected)}


def run_real_stack_nonvacuity_reachability(root: Path, *,
                                           variant: int = REACHABILITY_VARIANT
                                           ) -> dict[str, Any]:
    root = Path(root).resolve()
    cases, gold, _fixtures, control = production_disposable_bundle(variant)
    validate_recovery_control(control, cases)
    consistency = check_designation_consistency(control, gold)
    run = execute_production_stack(root, cases, control)
    outputs, stack = run["outputs"], run["stack"]
    plans = [case["plan"] for case in cases]
    score = score_suite(outputs, gold, plans)
    metrics = score["metrics"]
    entries = {entry["scenario_id"]: entry for entry in control["entries"]}
    recovery_rows = [_recovery_case_evidence(output, entries[output["scenario_id"]])
                     for output in outputs if output["scenario_id"] in entries]
    injection = aggregate_audits(run["audits"], control)
    replan_triggers = sorted({event["trigger"] for output in outputs
                              for event in output.get("replans", [])})
    safe_terminals = sorted({output["terminal"] for output, expected
                             in zip(outputs, gold)
                             if expected["designated_abstention"]})
    handoffs = [handoff for output in outputs for handoff in output["handoffs"]]

    def metric(name: str) -> dict[str, Any]:
        return {key: metrics[name][key] for key in (
            "numerator", "denominator", "observed", "floor", "pass")}

    designations = [
        {"designation": "successful_completion",
         "stimulus": "MATH_T4/SCICOMP numeric dependency chain",
         "real_execution_mechanism":
             "t30 production MATH_T4 calculator + SCICOMP describe",
         "expected_observable": "COMPLETE, all required steps verified, "
                                "final answer commitment, last verification PASS",
         "scorer_predicate": "verified_completion_rate",
         "evidence": metric("verified_completion_rate")},
        {"designation": "recovery",
         "stimulus": "one frozen transient fault (" + FAULT_MESSAGE + ")",
         "real_execution_mechanism":
             "recovery-control wrapper around the production adapter; "
             "IntegratedRunner bounded retry",
         "expected_observable": "RECOVERABLE_ERROR then retry, COMPLETE",
         "scorer_predicate":
             "recovery_success_rate (COMPLETE and total_retries >= 1)",
         "evidence": metric("recovery_success_rate")},
        {"designation": "replan",
         "stimulus": "CODE unavailable / MATH_T4 missing evidence / "
                     "MATH_T4 verification failure",
         "real_execution_mechanism":
             "production UnavailableError / INSUFFICIENT_EVIDENCE / numeric "
             "verification failure -> fallback capability",
         "expected_observable": "exactly one replan, version 2, expected "
                                "trigger and fallback, COMPLETE",
         "scorer_predicate": "replan_correctness_rate",
         "evidence": metric("replan_correctness_rate")},
        {"designation": "safe_abstention",
         "stimulus": "NO_TOOL / CODE without fallback",
         "real_execution_mechanism":
             "production NO_TOOL INSUFFICIENT_EVIDENCE / CODE UnavailableError",
         "expected_observable": "designated safe terminal, final_answer null, "
                                "final_answer_commitment null",
         "scorer_predicate": "safe_abstention_accuracy",
         "evidence": metric("safe_abstention_accuracy")},
        {"designation": "handoff",
         "stimulus": "input_from dependency handoffs",
         "real_execution_mechanism": "IntegratedRunner handoff validation",
         "expected_observable": "VALID handoffs, internal authority, registered "
                                "capabilities, provenance commitment",
         "scorer_predicate": "handoff_validity_rate",
         "evidence": metric("handoff_validity_rate")},
        {"designation": "verification",
         "stimulus": "numeric add / add_previous and evidence verification",
         "real_execution_mechanism": "IntegratedRunner._verify on production "
                                     "adapter results",
         "expected_observable": "verified steps meet expected verified steps",
         "scorer_predicate": "verification_success_rate",
         "evidence": metric("verification_success_rate")},
    ]
    for item in designations:
        evidence = item["evidence"]
        item["reachable"] = (evidence["denominator"] > 0
                             and evidence["pass"] is True)
    recovery_proof = {
        "scenario_count": len(cases),
        "scheduled_recoverable_cases": len(entries),
        "injected_first_failures": injection["injected_first_failures"],
        "retries_observed": sum(row["retry_count_at_least_one"]
                                for row in recovery_rows),
        "complete_count": sum(row["terminal_complete"] for row in recovery_rows),
        "verification_pass_count": sum(row["verification_pass"]
                                       for row in recovery_rows),
        "first_attempt_recoverable_error_count": sum(
            row["first_designated_attempt_recoverable_error"]
            for row in recovery_rows),
        "all_cases_pass": bool(recovery_rows) and all(
            all(row.values()) for row in recovery_rows),
        "recovery_numerator": metrics["recovery_success_rate"]["numerator"],
        "recovery_denominator": metrics["recovery_success_rate"]["denominator"],
        "recovery_observed": metrics["recovery_success_rate"]["observed"],
        "recovery_pass": metrics["recovery_success_rate"]["pass"],
        **injection,
    }
    checks = {
        "production_adapter_registry_used":
            stack.get("production_adapter_registry_used") is True
            and stack.get("adapter_builder_actual")
            == "t30_protocol.production:build_adapters",
        "fixture_adapters_not_used":
            "fixture_adapters" not in str(stack.get("adapter_substitute_source")),
        "recovery_minimum_32": len(entries) >= NONVACUITY_MINIMUMS[
            "recoverable_cases"],
        "recovery_proof_all_cases": recovery_proof["all_cases_pass"],
        "recovery_exactly_one_injection_per_scheduled_case":
            injection["injected_first_failures"] == len(entries)
            and injection["max_injections_observed"] == 1
            and injection["unscheduled_injections"] == 0
            and injection["scheduled_but_not_injected"] == 0,
        "all_designations_reachable": all(item["reachable"]
                                          for item in designations),
        "replan_triggers_observed": replan_triggers == sorted(
            trigger for trigger, _c, _f in REPLAN_STIMULI),
        "safe_terminals_observed": safe_terminals == sorted(
            terminal for terminal, _c in ABSTENTION_STIMULI),
        "abstention_answers_null": all(
            output["final_answer"] is None
            and output["final_answer_commitment"] is None
            for output, expected in zip(outputs, gold)
            if expected["designated_abstention"]),
        "handoffs_valid_and_bound": bool(handoffs) and all(
            handoff["status"] == "VALID" and handoff["authority"] == AUTHORITY
            and handoff["producer_capability"] in SKILL_IDS
            and handoff["consumer_capability"] in SKILL_IDS
            and bool(handoff["provenance_commitment"])
            for handoff in handoffs),
        "score_suite_pass": score["status"] == "PASS",
        "critical_counters_zero": all(value == 0 for value
                                      in score["critical_counters"].values()),
        "candidate_control_exposure_zero": run["candidate_control_exposure"] == 0,
        "designation_consistency": consistency["status"] == "PASS",
    }
    status = "GATE_GREEN" if all(checks.values()) else "GATE_RED"
    core = {
        "schema_version": "t30-real-stack-nonvacuity-reachability-v1",
        "artifact": "T30_REAL_STACK_NONVACUITY_REACHABILITY_GATE",
        "classification": "PUBLIC_SAFE", "material": MATERIAL,
        "reusable_as_real_material": False,
        "status": status, "checks": checks,
        "failed_checks": sorted(name for name, value in checks.items()
                                if not value),
        "adapter_stack": {key: stack.get(key) for key in (
            "factory_id", "production_adapter_registry_used",
            "adapter_substitute_source", "adapter_builder_actual",
            "recovery_control_wrapper", "recovery_control_policy_root",
            "explicitly_tagged_disposable_substitute")},
        "designations": designations,
        "recovery_proof": recovery_proof,
        "replan_triggers_observed": replan_triggers,
        "safe_terminals_observed": safe_terminals,
        "handoff_count": len(handoffs),
        "score_status": score["status"],
        "designated_counts": score["designated_counts"],
        "critical_counters": score["critical_counters"],
        "scenario_count": len(cases),
        "recovery_control_policy_root": POLICY_ROOT,
        "disposable_control_sha256": control_sha256(control),
        "scorer_unchanged": True,
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_recovery_control_entries": 0,
        "candidate_real_executions": 0,
    }
    return {**core, "reachability_root": sha256_json(core)}


# ---------------------------------------------------------------------------
# §36/§37 negative recovery-control controls
# ---------------------------------------------------------------------------


def _refused(function, *exceptions: type[BaseException]) -> tuple[bool, str]:
    try:
        function()
    except exceptions as exc:
        return True, type(exc).__name__
    except Exception as exc:  # wrong failure class is NOT a refusal
        return False, f"UNEXPECTED:{type(exc).__name__}"
    return False, "ACCEPTED"


def run_recovery_control_negative_controls(root: Path) -> dict[str, Any]:
    from .construction import candidate_input_projection
    from .store import PreLedgerViolation, T30PrivateStore
    from .recovery_control import CONTROL_PATH, adapter_identity_report
    root = Path(root).resolve()
    variant = REACHABILITY_VARIANT + 1
    cases, gold, _fixtures, control = production_disposable_bundle(variant)
    small_cases = cases[:8]
    first = control["entries"][0]

    def mutated(mutation) -> dict[str, Any]:
        document = copy.deepcopy(control)
        mutation(document)
        return document

    def entry_edit(key, value):
        return lambda document: document["entries"][0].__setitem__(key, value)

    controls: dict[str, tuple[bool, str]] = {}
    controls["missing_control_schedule"] = _refused(
        lambda: validate_control_shape(None), RecoveryControlError)
    controls["malformed_schema"] = _refused(
        lambda: validate_control_shape(mutated(
            lambda document: document.pop("entry_count"))),
        RecoveryControlError)
    controls["unknown_scenario"] = _refused(
        lambda: validate_recovery_control(mutated(
            entry_edit("scenario_id", "t30-disposable-unknown")), cases),
        RecoveryControlError)
    controls["unknown_step"] = _refused(
        lambda: validate_recovery_control(mutated(
            entry_edit("step_id", "s99")), cases), RecoveryControlError)
    controls["capability_mismatch"] = _refused(
        lambda: validate_recovery_control(mutated(
            entry_edit("capability", "SCICOMP" if first["capability"]
                       == "MATH_T4" else "MATH_T4")), cases),
        RecoveryControlError)

    def duplicate(document):
        document["entries"].append(copy.deepcopy(document["entries"][0]))
        document["entry_count"] += 1
    controls["duplicate_schedule_entry"] = _refused(
        lambda: validate_control_shape(mutated(duplicate)), RecoveryControlError)
    controls["max_injections_not_one"] = _refused(
        lambda: validate_control_shape(mutated(entry_edit("max_injections", 2))),
        RecoveryControlError)
    controls["unsupported_fault_class"] = _refused(
        lambda: validate_control_shape(mutated(
            entry_edit("fault_class", "PERMANENT_ERROR"))), RecoveryControlError)
    controls["gold_field_in_control"] = _refused(
        lambda: validate_control_shape(mutated(
            lambda document: document.__setitem__("gold", []))),
        RecoveryControlError)
    controls["expected_answer_in_control"] = _refused(
        lambda: validate_control_shape(mutated(
            entry_edit("expected_answer", 1))), RecoveryControlError)
    controls["expected_terminal_in_control"] = _refused(
        lambda: validate_control_shape(mutated(
            entry_edit("expected_terminal", "COMPLETE"))), RecoveryControlError)

    def exposed():
        scenario = copy.deepcopy(cases[0])
        scenario["plan"]["steps"][0]["input"]["fault_class"] = FAULT_CLASS
        candidate_input_projection(scenario)
    controls["control_field_exposed_to_candidate"] = _refused(exposed, ValueError)

    # Wrapper-level controls on a stub delegate (no scenario execution).
    from sciencemath.integrated.runner import Adapter, RecoverableError
    calls = {"n": 0}

    def delegate(payload, context):
        calls["n"] += 1
        return {"status": "OK"}
    base = {capability: Adapter(capability, delegate) for capability in SKILL_IDS}
    entry = {**first}

    def foreign():
        wrapped, _audit = wrap_production_adapters(
            base, scenario_id=entry["scenario_id"], entry=entry)
        wrapped[entry["capability"]].execute(
            {}, {"scenario_id": "t30-disposable-other", "step_id": entry["step_id"]})
    controls["fault_injected_into_unscheduled_scenario"] = _refused(
        foreign, ExecutionError)
    controls["entry_bound_to_other_scenario"] = _refused(
        lambda: wrap_production_adapters(base, scenario_id="t30-other",
                                          entry=entry), RecoveryControlError)

    def more_than_once():
        wrapped, audit = wrap_production_adapters(
            base, scenario_id=entry["scenario_id"], entry=entry)
        context = {"scenario_id": entry["scenario_id"],
                   "step_id": entry["step_id"]}
        outcomes = []
        for _ in range(3):
            try:
                wrapped[entry["capability"]].execute({}, context)
                outcomes.append("DELEGATED")
            except RecoverableError:
                outcomes.append("INJECTED")
        if outcomes != ["INJECTED", "DELEGATED", "DELEGATED"] or audit.injections != 1:
            return
        raise RecoveryControlError("second and third invocations delegated")
    controls["fault_injected_more_than_once"] = _refused(
        more_than_once, RecoveryControlError)

    def leak():
        one, audit_one = wrap_production_adapters(
            base, scenario_id=entry["scenario_id"], entry=entry)
        unscheduled, audit_two = wrap_production_adapters(
            base, scenario_id="t30-disposable-unscheduled", entry=None)
        try:
            one[entry["capability"]].execute(
                {}, {"scenario_id": entry["scenario_id"],
                     "step_id": entry["step_id"]})
        except RecoverableError:
            pass
        identity_preserved = all(unscheduled[name] is base[name] for name in base)
        if identity_preserved and audit_two.injections == 0 and \
                audit_one.injections == 1:
            raise RecoveryControlError("fault state isolated per scenario")
    controls["fault_state_leaks_across_scenarios"] = _refused(
        leak, RecoveryControlError)

    def preledger_read():
        with TemporaryDirectory(prefix="t30-control-preledger-") as tmp:
            store = T30PrivateStore(Path(tmp) / "private", repository_root=root,
                                    disposable=True)
            store.write_once_json(CONTROL_PATH, control)
            store.read_bytes(CONTROL_PATH)
    controls["control_parsed_before_started"] = _refused(
        preledger_read, PreLedgerViolation)

    def set_mismatch_missing():
        tampered = copy.deepcopy(gold)
        index = next(i for i, row in enumerate(tampered)
                     if row["designated_recoverable"])
        tampered[index]["designated_recoverable"] = False
        check_designation_consistency(control, tampered)

    def set_mismatch_extra():
        tampered = copy.deepcopy(gold)
        index = next(i for i, row in enumerate(tampered)
                     if not row["designated_recoverable"])
        tampered[index]["designated_recoverable"] = True
        check_designation_consistency(control, tampered)
    controls["recoverable_gold_missing_control_entry"] = _refused(
        set_mismatch_missing, RecoveryControlError)
    controls["control_entry_without_gold_designation"] = _refused(
        set_mismatch_extra, RecoveryControlError)

    def unqualified_target():
        scenario = copy.deepcopy(small_cases[0])
        scenario["plan"]["steps"][0]["capability"] = "GENERAL"
        build_recovery_control([scenario] + small_cases[1:],
                               [(scenario["scenario_id"], "s1")])
    controls["nonlocal_unqualified_target"] = _refused(
        unqualified_target, RecoveryControlError)

    def no_retry_budget():
        scenario = copy.deepcopy(small_cases[0])
        scenario["plan"]["budgets"]["max_step_retries"] = 0
        build_recovery_control([scenario] + small_cases[1:],
                               [(scenario["scenario_id"], "s1")])
    controls["target_without_retry_budget"] = _refused(
        no_retry_budget, RecoveryControlError)
    controls["control_generator_accepts_no_gold"] = (
        "gold" not in inspect.signature(build_recovery_control).parameters,
        "SIGNATURE")

    # §37: substituting the t26 registry must fail the identity control and
    # the official factory itself.
    from . import official_environment
    import t26_protocol.production as t26_production
    original = official_environment.build_adapters
    try:
        official_environment.build_adapters = t26_production.build_adapters
        report = adapter_identity_report(root)
        mismatch_detected = report["identity_exact"] is False
        environment = official_environment.build_official_evaluation_environment(
            root, real=False)
        environment.factory.bind_recovery_control(control)
        with TemporaryDirectory(prefix="t30-identity-control-") as tmp:
            workspace = Path(tmp) / cases[0]["scenario_id"]
            workspace.mkdir()
            factory_refused, _kind = _refused(
                lambda: environment.factory(workspace), ValueError)
    finally:
        official_environment.build_adapters = original
    controls["t26_adapter_substitution_detected"] = (
        mismatch_detected and factory_refused, "IDENTITY")
    restored = adapter_identity_report(root)
    controls["attested_adapter_identity_restored"] = (
        restored["identity_exact"] is True, "IDENTITY")

    def factory_without_control():
        environment = official_environment.build_official_evaluation_environment(
            root, real=False)
        with TemporaryDirectory(prefix="t30-unbound-control-") as tmp:
            workspace = Path(tmp) / cases[0]["scenario_id"]
            workspace.mkdir()
            environment.factory(workspace)
    controls["runner_without_postledger_control"] = _refused(
        factory_without_control, ValueError)

    results = {name: {"refused": passed, "failure_class": kind}
               for name, (passed, kind) in sorted(controls.items())}
    failed = sorted(name for name, item in results.items() if not item["refused"])
    return {
        "schema_version": "t30-recovery-control-negative-controls-v1",
        "artifact": "T30_RECOVERY_CONTROL_NEGATIVE_CONTROLS",
        "classification": "PUBLIC_SAFE", "material": MATERIAL,
        "control_count": len(results), "PASS": len(results) - len(failed),
        "FAIL": len(failed), "failed_controls": failed,
        "status": "PASS" if not failed else "FAIL", "controls": results,
        "real_blind_rows": 0, "real_recovery_control_entries": 0,
    }


def recovery_policy_document() -> dict[str, Any]:
    return recovery_control_policy()


__all__ = [
    "MATERIAL", "REACHABILITY_VARIANT", "execute_production_stack",
    "production_disposable_bundle", "production_disposable_control",
    "production_disposable_scenarios", "recovery_policy_document",
    "run_real_stack_nonvacuity_reachability",
    "run_recovery_control_negative_controls",
]
