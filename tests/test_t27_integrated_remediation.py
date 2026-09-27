"""Public-only T27 remediation tests."""
from __future__ import annotations

import pytest

from sciencemath.integrated.runner import ExecutionError
from t27_protocol.contract import REPLAN_TRIGGERS
from t27_protocol.production import PROVIDER_STATUS_MAP, normalize_provider_status
from t27_protocol.qualification import (
    public_reproducer_record, run_completion_gate_matrix, run_qualification,
    run_terminal_matrix, run_verification_matrix,
)


def test_all_eight_terminals_are_reachable_with_exact_semantics():
    report = run_terminal_matrix()
    assert report["status"] == "PASS"
    assert report["expected_terminal_count"] == 8
    assert all(report["checks"].values())
    assert set(report["aggregate_observed_counts"].values()) == {1}


def test_verification_kinds_accept_valid_and_reject_invalid():
    report = run_verification_matrix()
    assert report["status"] == "PASS"
    assert set(report["checks"]) == {"schema", "evidence", "numeric", "citation"}
    assert all(item == {"known_valid": True, "known_invalid": False}
               for item in report["checks"].values())


def test_completion_gate_positive_and_all_negative_controls():
    report = run_completion_gate_matrix()
    assert report == {
        "status": "PASS",
        "checks": {"positive": True, "missing_required_step": False,
                   "missing_final_output": False,
                   "last_verification_fail": False,
                   "partial_verification": False},
    }


def test_provider_normalization_is_explicit_and_unknown_refused():
    assert PROVIDER_STATUS_MAP == {
        "OK": "OK", "ANSWER": "OK", "DOC_ANSWER": "OK",
        "PARTIALLY_SUPPORTED": "INSUFFICIENT_EVIDENCE",
        "CONFLICTING_EVIDENCE": "CONFLICTING_EVIDENCE",
        "SECURITY_REFUSAL": "SECURITY_REFUSAL",
        "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
        "ROUTER_CONFIGURATION_ERROR": "INSUFFICIENT_EVIDENCE",
    }
    assert {status: normalize_provider_status(status)
            for status in PROVIDER_STATUS_MAP} == PROVIDER_STATUS_MAP
    with pytest.raises(ExecutionError, match="unknown production provider status"):
        normalize_provider_status("UNRECOGNIZED_PUBLIC_STATUS")


def test_new_qualification_has_positive_nonvacuous_coverage():
    report = run_qualification()
    assert report["status"] == "PASS"
    assert report["family_count"] == 16
    assert report["scenario_count"] == 64
    assert report["multi_step_matrix"] == {"3": 16, "4": 16, "5": 16, "6": 16}
    assert set(report["replan_trigger_counts"]) == set(REPLAN_TRIGGERS)
    assert all(value > 0 for value in report["replan_trigger_counts"].values())
    assert all(value > 0 for value in report["capability_call_counts"].values())
    assert all(metric["denominator"] > 0 and metric["pass"]
               for metric in report["score"]["metrics"].values())
    assert all(value == 0 for value in report["score"]["critical_counters"].values())


def test_root_cause_claim_stays_public_and_non_row_specific():
    record = public_reproducer_record()
    assert record["status"] == "REPRODUCED_AND_REMEDIATED"
    assert len(record["demonstrated_public_defects"]) == 3
    assert all(record["remediation_checks"].values())
    assert record["t26_row_specific_cause_claimed"] is False
    assert record["t26_private_rows_opened"] == record["t26_candidate_reruns"] == 0
