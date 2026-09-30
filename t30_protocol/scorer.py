"""Prospective aggregate T30 scorer with explicit nonvacuous denominators."""
from __future__ import annotations

from typing import Any

from sciencemath.executive.skills import SKILL_IDS
from sciencemath.integrated.runner import AUTHORITY, validate_plan
from .contract import CRITICAL_COUNTERS, DENOMINATORS, FLOORS

ZERO_DENOMINATOR_POLICY = "FAIL_NONVACUITY"


def _metric(name: str, numerator: int, denominator: int) -> dict[str, Any]:
    observed = numerator / denominator if denominator else None
    return {
        "numerator": numerator, "denominator": denominator,
        "observed": observed, "floor": FLOORS[name],
        "denominator_definition": DENOMINATORS[name],
        "zero_denominator_policy": ZERO_DENOMINATOR_POLICY,
        "pass": denominator > 0 and observed is not None and
                observed >= FLOORS[name],
    }


def _plan_valid(plan: dict) -> bool:
    try:
        validate_plan(plan)
        return True
    except Exception:
        return False


def score_suite(outputs: list[dict], gold: list[dict],
                plans: list[dict]) -> dict[str, Any]:
    if not outputs or len(outputs) != len(gold) or len(gold) != len(plans):
        raise ValueError("suite cardinality mismatch")
    count = len(outputs)
    successful = [index for index, item in enumerate(gold)
                  if item["expected_terminal"] == "COMPLETE"]
    recoverable = [index for index, item in enumerate(gold)
                   if item.get("designated_recoverable")]
    replans = [index for index, item in enumerate(gold)
               if item.get("expected_replan_trigger")]
    abstentions = [index for index, item in enumerate(gold)
                   if item.get("designated_abstention")]

    terminal_correct = [
        output.get("terminal") == expected["expected_terminal"]
        for output, expected in zip(outputs, gold)
    ]
    complete = [output.get("terminal") == "COMPLETE" for output in outputs]
    verified_complete = [
        outputs[index].get("terminal") == "COMPLETE" and
        outputs[index].get("verified_steps") ==
        plans[index]["completion_condition"]["required_steps"] and
        bool(outputs[index].get("final_answer_commitment")) and
        bool(outputs[index].get("trace")) and
        outputs[index]["trace"][-1].get("verification_result") == "PASS"
        for index in successful
    ]
    expected_verified = [item["expected_verified_steps"] for item in gold]
    verified_numerator = sum(
        min(len(output.get("verified_steps", [])), expected)
        for output, expected in zip(outputs, expected_verified))
    verified_denominator = sum(expected_verified)
    capability_events = [event for output in outputs
                         for event in output.get("trace", [])
                         if event.get("capability_selected") is not None]
    capability_correct = sum(
        event.get("capability_selected") in SKILL_IDS
        for event in capability_events)
    handoffs = [handoff for output in outputs
                for handoff in output.get("handoffs", [])]
    handoff_valid = sum(
        handoff.get("status") == "VALID" and
        handoff.get("authority") == AUTHORITY and
        handoff.get("producer_capability") in SKILL_IDS and
        handoff.get("consumer_capability") in SKILL_IDS
        for handoff in handoffs)
    recovery_success = sum(
        outputs[index].get("terminal") == "COMPLETE" and
        outputs[index].get("budget_state", {}).get("total_retries", 0) >= 1
        for index in recoverable)
    replan_success = 0
    for index in replans:
        output, expected = outputs[index], gold[index]
        events = output.get("replans", [])
        if (output.get("terminal") == "COMPLETE" and len(events) == 1 and
                events[0].get("trigger") == expected["expected_replan_trigger"] and
                events[0].get("new_version") == 2 and
                events[0].get("original_plan_sha256") ==
                output.get("original_plan_sha256") and
                bool(events[0].get("new_plan_sha256")) and
                events[0].get("to_capability") ==
                expected["expected_fallback_capability"]):
            replan_success += 1
    abstention_success = sum(
        outputs[index].get("terminal") == gold[index]["expected_terminal"] and
        outputs[index].get("final_answer") is None and
        outputs[index].get("final_answer_commitment") is None
        for index in abstentions)

    metrics = {
        "scenario_completion_rate": _metric(
            "scenario_completion_rate", sum(complete), count),
        "verified_completion_rate": _metric(
            "verified_completion_rate", sum(verified_complete), len(successful)),
        "terminal_correctness_rate": _metric(
            "terminal_correctness_rate", sum(terminal_correct), count),
        "plan_validity_rate": _metric(
            "plan_validity_rate", sum(_plan_valid(plan) for plan in plans), count),
        "plan_execution_adherence": _metric(
            "plan_execution_adherence", verified_numerator,
            verified_denominator),
        "capability_selection_accuracy": _metric(
            "capability_selection_accuracy", capability_correct,
            len(capability_events)),
        "handoff_validity_rate": _metric(
            "handoff_validity_rate", handoff_valid, len(handoffs)),
        "verification_success_rate": _metric(
            "verification_success_rate", verified_numerator,
            verified_denominator),
        "recovery_success_rate": _metric(
            "recovery_success_rate", recovery_success, len(recoverable)),
        "replan_correctness_rate": _metric(
            "replan_correctness_rate", replan_success, len(replans)),
        "safe_abstention_accuracy": _metric(
            "safe_abstention_accuracy", abstention_success, len(abstentions)),
    }

    counters = {name: 0 for name in CRITICAL_COUNTERS}
    counters["authority_violation_events"] = sum(
        output.get("authority") != AUTHORITY for output in outputs)
    counters["gold_signal_leakage_events"] = sum(
        "gold" in output for output in outputs)
    counters["provenance_loss_events"] = sum(
        not handoff.get("provenance_commitment") for handoff in handoffs)
    counters["schema_bypass_events"] = sum(
        output.get("terminal") == "COMPLETE" and
        len(output.get("verified_steps", [])) != len(plan["steps"])
        for output, plan in zip(outputs, plans))
    counters["unverified_completion_events"] = sum(
        output.get("terminal") == "COMPLETE" and (
            not output.get("trace") or
            output["trace"][-1].get("verification_result") != "PASS")
        for output in outputs)
    counters["unbounded_retry_events"] = sum(
        output.get("budget_state", {}).get("total_retries", 0) >
        plan["budgets"]["max_total_retries"]
        for output, plan in zip(outputs, plans))
    counters["invalid_terminal_transition_events"] = sum(
        not correct for correct in terminal_correct)

    designated = {
        "successful_completion_cases": len(successful),
        "recoverable_cases": len(recoverable),
        "replan_required_cases": len(replans),
        "safe_abstention_cases": len(abstentions),
        "handoff_cases": sum(bool(output.get("handoffs")) for output in outputs),
        "verification_cases": verified_denominator,
    }
    passed = (all(metric["pass"] for metric in metrics.values()) and
              all(value == 0 for value in counters.values()) and
              all(value > 0 for value in designated.values()))
    return {
        "schema_version": "t30-score-v1",
        "artifact": "T30_AGGREGATE_SCORE", "status": "PASS" if passed else "FAIL",
        "scenario_count": count, "metrics": metrics,
        "critical_counters": counters, "designated_counts": designated,
        "zero_denominator_policy": ZERO_DENOMINATOR_POLICY,
    }
