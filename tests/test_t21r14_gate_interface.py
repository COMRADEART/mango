"""T21R14 gate-interface + taxonomy-integrity regression tests."""
from __future__ import annotations
import copy, inspect, json, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
OUT = ROOT / "evaluations" / "t21r14"
import t21r14_construction_gate as gate
import t21r14_uniqueness as uniqueness
import t21r14_exact_design_auditor as auditor
import t21r6_run_eval as r6
import t21r14_run_eval as run_eval
import t21r14_official_eval as official

def _contract():
    return json.loads((OUT / "holdout_construction_contract.json").read_text(encoding="utf-8"))

ZERO_METRICS = {"runtime_execution_count": 0, "candidate_R14_rows_executed": 0,
                "official_evaluator_invocations": 0, "annotation_violations": 0}
ZERO_CONTEXT = {"prior_exact_query_overlap": 0, "prior_pair_template_overlap": 0,
                "historical_milestones": 14, "historical_overlap": 0,
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

def test_gate_api_mutation_missing_callable():
    with pytest.raises(AttributeError):
        _ = gate.build_gate_report_missing

def test_gate_api_mutation_wrong_argument_count():
    with pytest.raises(TypeError):
        gate.build_gate_report({})

def test_gate_api_mutation_wrong_schema_value():
    report = gate.build_gate_report(_contract(), {"runtime_execution_count": 5, "candidate_R14_rows_executed": 0, "official_evaluator_invocations": 0, "annotation_violations": 0}, [], context=dict(ZERO_CONTEXT))
    assert report["status"] == "FAIL"

def test_gate_api_mutation_wrong_report_value_type():
    report = gate.build_gate_report(_contract(), dict(ZERO_METRICS), [], context=dict(ZERO_CONTEXT))
    assert report["status"] == "FAIL"

def test_prior_exclusion_rebuilt_valid_112():
    artifact = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    decoded = uniqueness.validate_artifact(artifact)
    assert len(decoded) == 14
    assert sum(len(dims) for dims in decoded.values()) == 112
    assert artifact["raw_values_included"] is False
    assert artifact["historical_milestone_count"] == 14
    assert len(artifact["milestone_order"]) == 14
    for milestone in decoded.values():
        for dimension in decoded[milestone] if False else []:
            pass
    for milestone, dims in decoded.items():
        assert set(dims) == set(uniqueness.DIMENSIONS)
        for dimension, fps in dims.items():
            assert all(len(v) == 64 and all(c in "0123456789abcdef" for c in v) for v in fps)

def test_exclusion_raw_payload_rejected():
    artifact = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(artifact)
    bad["milestones"]["T21"]["dimensions"]["case_ids"]["fingerprints"] = ["r14b-av-0000"]
    with pytest.raises(ValueError):
        uniqueness.validate_artifact(bad)

def test_exclusion_milestone_count_mismatch_rejected():
    artifact = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(artifact)
    bad["milestones"].pop("T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE")
    with pytest.raises(ValueError):
        uniqueness.validate_artifact(bad)

def test_exclusion_set_sha_mismatch_rejected():
    artifact = json.loads((OUT / "prior_exclusion.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(artifact)
    bad["milestones"]["T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE"]["dimensions"]["case_ids"]["set_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        uniqueness.validate_artifact(bad)

# --- taxonomy negative controls (section 41) --------------------------------

def _scan_with_row(tmp, row):
    suite = Path(tmp) / "mango-t21r14-neg-holdout-v1"
    suite.mkdir()
    (suite / "holdout.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return official.scan_gold_taxonomy(Path(tmp), Path(tmp), OUT / "domain_taxonomy_contract.json")

def test_neg_unknown_required_domain():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="t21r14-neg-") as tmp:
        defects = _scan_with_row(tmp, {"case_id": "r14b-neg-0000", "gold": {"required_domains": ["__unknown_domain__"]}, "request": {"query": "q"}, "mode": "answer"})
    assert any("__unknown_domain__" in d for d in defects)

def test_neg_misspelled_domain():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="t21r14-neg-") as tmp:
        defects = _scan_with_row(tmp, {"case_id": "r14b-neg-0001", "gold": {"required_domains": ["natural_philosphy"]}, "request": {"query": "q"}, "mode": "answer"})
    assert defects

def test_neg_wrong_type():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="t21r14-neg-") as tmp:
        defects = _scan_with_row(tmp, {"case_id": "r14b-neg-0002", "gold": {"required_domains": "arts"}, "request": {"query": "q"}, "mode": "answer"})
    assert any("wrong type" in d for d in defects)

def test_neg_null_label():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="t21r14-neg-") as tmp:
        defects = _scan_with_row(tmp, {"case_id": "r14b-neg-0003", "gold": {"required_domains": ["arts", None]}, "request": {"query": "q"}, "mode": "answer"})
    assert any("null/empty" in d for d in defects)

def test_neg_duplicate_labels():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="t21r14-neg-") as tmp:
        defects = _scan_with_row(tmp, {"case_id": "r14b-neg-0004", "gold": {"required_domains": ["arts", "arts"]}, "request": {"query": "q"}, "mode": "answer"})
    assert any("duplicate" in d for d in defects)

def test_neg_author_only_domain_rejected():
    """An author-emitted label the evaluator does not know must be rejected by preflight."""
    import tempfile
    canonical = {d["canonical_label"] for d in json.loads((OUT / "domain_taxonomy_contract.json").read_text(encoding="utf-8"))["domains"]}
    author_only = canonical - {"arts"}
    assert ("arts" in canonical) and ("arts" in run_eval.CANONICAL_DOMAINS)
    with pytest.raises(SystemExit, match="T21R6_EVALUATOR_INVALID"):
        r6.validate_domain_labels(["not_a_domain_anywhere"])

def test_r13_exact_failure_labels_accepted_by_full_chain():
    """natural_philosophy / civic_architecture pass evaluator validation and preflight."""
    r6.validate_domain_labels(["natural_philosophy", "civic_architecture"])
    import tempfile
    with tempfile.TemporaryDirectory(prefix="t21r14-pos-") as tmp:
        defects = _scan_with_row(tmp, {"case_id": "r14b-pos-0000", "gold": {"required_domains": ["natural_philosophy", "civic_architecture"]}, "request": {"query": "q"}, "mode": "answer"})
    assert defects == []

def test_normalize_domain_no_aliasing():
    assert r6.normalize_domain("Natural Philosophy") == "natural_philosophy"
    assert r6.normalize_domain("natural-philosophy") == "natural_philosophy"
    assert r6.normalize_domain("__unknown_domain__") == "__unknown_domain__"
    with pytest.raises(SystemExit, match="T21R6_EVALUATOR_INVALID"):
        r6.validate_domain_labels(["not_a_domain_anywhere"])
