"""Focused T21R13 preconstruction tests."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r13"
OUT12 = ROOT / "evaluations" / "t21r12"

def _j(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))

def test_r13_qualification_pass():
    q = _j("preconstruction_qualification.json")
    assert q["verdict"] == "T21R13_PRECONSTRUCTION_AUDIT_PASS"

def test_contract_schema_blind_namespace_string():
    schema = _j("contract_schema.json")
    fields = {f["field_path"]: f for f in schema["fields"]}
    assert fields["blind_namespace"]["json_type"] == "string"
    assert fields["case_id_prefix"]["json_type"] == "string"
    contract = _j("holdout_construction_contract.json")
    assert isinstance(contract["blind_namespace"], str)
    assert isinstance(contract["case_id_prefix"], str)

def test_no_nested_blind_namespace_access():
    audit = _j("contract_access_audit.json")
    assert audit["status"] == "PASS"
    assert audit["violations"] == 0

def test_r12_namespace_shape_regression():
    neg = _j("schema_negative_controls.json")
    reg = neg["R12_NAMESPACE_SHAPE_REGRESSION"]
    assert reg["canonical_blind_namespace_shape"] == "PASS"
    assert reg["legacy_incompatible_namespace_shape"] == "rejected"

def test_synthetic_suite_materializer_completed():
    synth = _j("synthetic_protocol_report.json")
    assert synth["suite_materializer_invoked"] is True
    assert synth["suite_materializer_completed"] is True
    assert synth["status"] == "PASS"

def test_historical_milestones_13():
    prior = _j("prior_exclusion.json")
    assert prior["historical_milestone_count"] == 13
    assert "T21R12_FAILED_PARTIAL_BLIND" in prior["milestones"]

def test_real_r13_paths_absent():
    assert not (ROOT / "rag" / "gk_holdout_t21r13").exists()
    assert not (OUT / "suites").exists()
    assert not (OUT / "construction_run_ledger.json").exists()
    assert not (OUT / "HOLDOUT_FROZEN").exists()

def test_r12_closure_present_and_forensics_preserved():
    closure = json.loads((OUT12 / "T21R12_CLOSURE.json").read_text(encoding="utf-8"))
    assert "CONSTRUCTION_INFRASTRUCTURE_FAILURE" in closure["status"]
    assert (OUT12 / "construction_run_ledger.json").is_file()
    assert (ROOT / "rag" / "gk_holdout_t21r12").is_dir()

def test_exact_design_38():
    cov = _j("contract_gate_coverage.json")
    assert cov["contract_leaves"] == 38
    assert cov["unhandled"] == 0
