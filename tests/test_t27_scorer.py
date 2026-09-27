"""T27 scorer denominator and nonvacuity tests."""
from __future__ import annotations

from t27_protocol.qualification import make_case
from t27_protocol.scorer import score_suite


def test_zero_denominators_fail_instead_of_becoming_one():
    scenario, _, _ = make_case("math_chain", 0)
    output = {
        "terminal": "ERROR", "verified_steps": [], "final_answer": None,
        "final_answer_commitment": None, "trace": [], "replans": [],
        "handoffs": [], "budget_state": {"total_retries": 0},
        "authority": "COORDINATE_INTERNAL_WORK_ONLY",
    }
    gold = {
        "expected_terminal": "ERROR", "expected_verified_steps": 0,
        "designated_recoverable": False, "designated_abstention": False,
        "expected_replan_trigger": None,
        "expected_fallback_capability": None,
    }
    report = score_suite([output], [gold], [scenario["plan"]])
    assert report["status"] == "FAIL"
    for name in ("verified_completion_rate", "plan_execution_adherence",
                 "capability_selection_accuracy", "handoff_validity_rate",
                 "verification_success_rate", "recovery_success_rate",
                 "replan_correctness_rate", "safe_abstention_accuracy"):
        metric = report["metrics"][name]
        assert metric["denominator"] == 0
        assert metric["observed"] is None
        assert metric["pass"] is False
        assert metric["zero_denominator_policy"] == "FAIL_NONVACUITY"


def test_qualification_rates_publish_full_metric_records():
    from t27_protocol.qualification import run_qualification

    report = run_qualification()["score"]
    assert report["status"] == "PASS"
    assert set(report["metrics"]) == {
        "scenario_completion_rate", "verified_completion_rate",
        "terminal_correctness_rate", "plan_validity_rate",
        "plan_execution_adherence", "capability_selection_accuracy",
        "handoff_validity_rate", "verification_success_rate",
        "recovery_success_rate", "replan_correctness_rate",
        "safe_abstention_accuracy",
    }
    for metric in report["metrics"].values():
        assert {"numerator", "denominator", "observed", "floor",
                "zero_denominator_policy", "pass"} <= set(metric)
        assert metric["denominator"] > 0
        assert metric["pass"] is True
