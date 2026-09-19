"""T21R13 gate-interface regression + exclusion-integrity tests."""
from __future__ import annotations
import copy, inspect, json, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
OUT = ROOT / "evaluations" / "t21r13"
import t21r13_construction_gate as gate
import t21r13_preconstruction as pc
import t21r13_uniqueness as uniqueness
import t21r13_exact_design_auditor as auditor

def _contract():
    return json.loads((OUT / "holdout_construction_contract.json").read_text(encoding="utf-8"))

ZERO_METRICS = {"runtime_execution_count": 0, "candidate_R13_rows_executed": 0,
                "official_evaluator_invocations": 0, "annotation_violations": 0}
ZERO_CONTEXT = {"prior_exact_query_overlap": 0, "prior_pair_template_overlap": 0,
                "historical_milestones": 13, "historical_overlap": 0,
                "remediation_overlap": 0, "candidate_leakage": 0,
                "historical_leakage": 0, "remediation_leakage": 0}

def test_build_gate_report_callable_and_signature_compatible():
    assert callable(gate.build_gate_report)
    params = list(inspect.signature(gate.build_gate_report).parameters)
    assert params == ["contract", "metrics", "rows", "context", "miniature"]

def test_gate_path_used_by_static_gold_audit_and_prevalidate():
    contract = _contract()
    rows = auditor.make_valid_fixture(contract)
    report = gate.build_gate_report(contract, dict(ZERO_METRICS), rows, context=dict(ZERO_CONTEXT))
    assert report["status"] == "PASS"
    assert report["exact_design"]["passed"] == 38
    assert report["exact_design"]["failed"] == 0

def test_gate_cli_api_equivalence():
    contract = _contract()
    rows = auditor.make_valid_fixture(contract)
    assert gate.build_gate_report(contract, dict(ZERO_METRICS), rows, context=dict(ZERO_CONTEXT)) == gate.evaluate_levels(contract, dict(ZERO_METRICS), rows, dict(ZERO_CONTEXT))

def test_cross_module_interface_audit_pass():
    result = pc.audit_cross_module_interfaces()
    assert result["status"] == "PASS", json.dumps(result["findings"], indent=1)[:2000]
    assert result["missing_call_targets"] == 0
    assert result["signature_mismatches"] == 0

def test_gate_api_mutation_missing_callable():
    with pytest.raises(AttributeError):
        _ = gate.build_gate_report_missing

def test_gate_api_mutation_wrong_argument_count():
    with pytest.raises(TypeError):
        gate.build_gate_report({})

def test_gate_api_mutation_wrong_schema_value():
    report = gate.build_gate_report(_contract(), {"runtime_execution_count": 5, "candidate_R13_rows_executed": 0, "official_evaluator_invocations": 0, "annotation_violations": 0}, [], context=dict(ZERO_CONTEXT))
    assert report["status"] == "FAIL"

def test_gate_api_mutation_wrong_report_value_type():
    report = gate.build_gate_report(_contract(), dict(ZERO_METRICS), [], context=dict(ZERO_CONTEXT))
    assert report["status"] == "FAIL"

def test_prior_exclusion_rebuilt_valid_104():
    artifact = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    result = uniqueness.validate_exclusion_artifact(artifact)
    assert result["status"] == "VALID"
    assert result["valid_sets"] == 104
    assert artifact["raw_values_included"] is False
    assert artifact["historical_milestone_count"] == 13
    assert len(artifact["milestone_order"]) == 13

def test_exclusion_raw_payload_rejected():
    artifact = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(artifact)
    bad["milestones"]["T21"]["dimensions"]["case_ids"]["fingerprints"] = ["r11b-av-0000"]
    with pytest.raises(ValueError):
        uniqueness.validate_exclusion_artifact(bad)

def test_exclusion_r12_noncanonical_dimension_rejected():
    artifact = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(artifact)
    bad["milestones"]["T21R12_FAILED_PARTIAL_BLIND"]["dimensions"] = {"answer": None, "query": None}
    with pytest.raises(ValueError):
        uniqueness.validate_exclusion_artifact(bad)

def test_exclusion_milestone_count_order_rejected():
    artifact = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(artifact)
    bad["historical_milestone_count"] = 12
    with pytest.raises(ValueError):
        uniqueness.validate_exclusion_artifact(bad)
    bad2 = copy.deepcopy(artifact)
    bad2["milestone_order"] = [m for m in bad2["milestone_order"] if m != "T21R12_FAILED_PARTIAL_BLIND"]
    with pytest.raises(ValueError):
        uniqueness.validate_exclusion_artifact(bad2)
