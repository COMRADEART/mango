"""T21R14 remediation-regression + quarantine + registry integrity tests."""
from __future__ import annotations
import copy, json, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import t21r14_uniqueness as uniqueness
import t21r13_uniqueness as u13
OUT = ROOT / "evaluations" / "t21r14"
OUT13 = ROOT / "evaluations" / "t21r13"

def test_remediation_exclusion_valid_and_extended():
    rem = json.loads((OUT / "remediation_exclusion.json").read_text(encoding="utf-8"))
    decoded = uniqueness.validate_remediation_artifact(rem)
    assert rem["class"] == "OPEN_REMEDIATION_MATERIAL"
    assert rem["raw_values_included"] is False
    # taxonomy-remediation fixture extension present (section 35)
    assert len(decoded["exact_answers"]) > 0

def test_remediation_covers_taxonomy_fixtures():
    rem = json.loads((OUT / "remediation_exclusion.json").read_text(encoding="utf-8"))
    fp = set(rem["dimensions"]["exact_queries"]["fingerprints"])
    for fixture in ("preflight reject __unknown_domain__ fixture",
                    "R13 mismatch reproduction fixture natural_philosophy"):
        assert u13._fingerprint("exact_queries", fixture) in fp

def test_remediation_tampering_rejected():
    rem = json.loads((OUT / "remediation_exclusion.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(rem)
    bad["dimensions"]["exact_queries"]["fingerprints"] = ["deadbeef"]
    with pytest.raises(ValueError):
        uniqueness.validate_remediation_artifact(bad)

def test_r13_quarantine_intact():
    q = json.loads((OUT13 / "OFFICIAL_PARTIAL_RESULTS_QUARANTINE.json").read_text(encoding="utf-8"))
    pointer = json.loads((OUT / "r13_partial_results_quarantine.json").read_text(encoding="utf-8"))
    assert q["rows"] == 1955 and pointer["rows"] == 1955
    assert pointer["raw_results_sha256"] == q["raw_results_sha256"]

def test_r13_closure_status():
    closure = json.loads((OUT13 / "T21R13_CLOSURE.json").read_text(encoding="utf-8"))
    assert closure["status"] == "CLOSED / OFFICIAL_EVALUATION_INFRASTRUCTURE_FAILURE"
    assert closure["one_shot"]["official_evaluation"] == "PERMANENTLY_CONSUMED"

def test_registry_raw_values_never_included():
    prior = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    assert prior["raw_values_included"] is False
    decoded = uniqueness.validate_artifact(prior)
    for milestone, dims in decoded.items():
        for dimension, fps in dims.items():
            for fp in fps:
                assert len(fp) == 64
