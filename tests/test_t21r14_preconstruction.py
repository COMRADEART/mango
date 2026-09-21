"""Focused T21R14 preconstruction tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r14"
OUT13 = ROOT / "evaluations" / "t21r13"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import t21r6_run_eval as r6  # noqa: E402
import t21r14_run_eval as run_eval  # noqa: E402
import t21r14_official_eval as official  # noqa: E402
import t21r14_blind_author as author  # noqa: E402

def _j(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))

def test_r14_qualification_pass():
    q = _j("preconstruction_qualification.json")
    assert q["verdict"] == "T21R14_PRECONSTRUCTION_AUDIT_PASS"

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

def test_historical_milestones_14():
    prior = _j("prior_exclusion.json")
    assert prior["historical_milestone_count"] == 14
    assert "T21R12_FAILED_PARTIAL_BLIND" in prior["milestones"]
    assert "T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE" in prior["milestones"]

def test_r13_closure_present_and_forensics_preserved():
    closure = json.loads((OUT13 / "T21R13_CLOSURE.json").read_text(encoding="utf-8"))
    assert "OFFICIAL_EVALUATION_INFRASTRUCTURE_FAILURE" in closure["status"]
    assert closure["evaluation"]["rows_scored"] == 0
    assert (OUT13 / "evaluation_run_ledger.json").is_file()
    assert (OUT13 / "raw_results.jsonl").is_file()
    assert (OUT13 / "holdout_manifest.json").is_file()
    assert (OUT13 / "HOLDOUT_FROZEN").is_file()

def test_r13_official_evaluation_permanently_refused():
    """The retained R13 one-shot ledger fails every future R13 preflight closed."""
    report = official.__dict__  # module imported
    import t21r13_official_eval as r13eval
    paths = r13eval.build_paths(ROOT)
    result = r13eval._preflight(paths)
    assert result["status"] == "FAIL"
    assert any("one-shot exposure artifact exists" in d for d in result["defects"])

def test_r13_quarantine_policy():
    q = json.loads((OUT13 / "OFFICIAL_PARTIAL_RESULTS_QUARANTINE.json").read_text(encoding="utf-8"))
    assert q["rows"] == 1955
    assert q["official_scoring"] is False
    policy = q["access_policy"]
    for key in ("candidate_tuning", "training_data", "r14_authoring", "r14_construction_tooling_reads"):
        assert policy[key] == "FORBIDDEN"
    q14 = _j("r13_partial_results_quarantine.json")
    assert q14["raw_results_sha256"] == q["raw_results_sha256"]

def test_canonical_taxonomy_contract():
    tax = _j("domain_taxonomy_contract.json")
    labels = [d["canonical_label"] for d in tax["domains"]]
    assert len(labels) == 14
    assert labels == sorted(set(labels))
    assert "natural_philosophy" in labels and "civic_architecture" in labels
    for entry in tax["domains"]:
        assert entry["aliases"] == []
        assert entry["allowed_in_gold_required_domains"] is True

def test_evaluator_rebound_to_canonical_taxonomy():
    tax = _j("domain_taxonomy_contract.json")
    canonical = {d["canonical_label"] for d in tax["domains"]}
    assert run_eval.CANONICAL_DOMAINS == canonical
    assert r6.DOMAIN_TAXONOMY == canonical
    assert run_eval._qualified.DOMAIN_TAXONOMY == canonical

def test_r13_domain_taxonomy_abort_regression():
    """The exact R13 failure labels are now canonically registered and accepted."""
    r6.validate_domain_labels(["natural_philosophy", "civic_architecture"])

def test_unknown_domain_loud_failure():
    with pytest.raises(SystemExit, match="T21R6_EVALUATOR_INVALID"):
        r6.validate_domain_labels(["__unknown_domain__"])

def test_gold_taxonomy_scan_rejects_unknown_before_evaluation():
    import tempfile
    tax = OUT / "domain_taxonomy_contract.json"
    with tempfile.TemporaryDirectory(prefix="t21r14-goldscan-") as tmp:
        suite = Path(tmp) / "mango-t21r14-x-holdout-v1"
        suite.mkdir()
        row = {"case_id": "r14b-scan-0000", "gold": {"required_domains": ["__unknown_domain__"], "expect_status": "ANSWER"}, "request": {"query": "q"}, "mode": "answer"}
        (suite / "holdout.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        defects = official.scan_gold_taxonomy(Path(tmp), Path(tmp), tax)
    assert any("outside the canonical" in d and "__unknown_domain__" in d for d in defects)

def test_gold_taxonomy_scan_accepts_registered_labels():
    import tempfile
    tax = OUT / "domain_taxonomy_contract.json"
    with tempfile.TemporaryDirectory(prefix="t21r14-goldscan2-") as tmp:
        suite = Path(tmp) / "mango-t21r14-x-holdout-v1"
        suite.mkdir()
        row = {"case_id": "r14b-scan-0001", "gold": {"required_domains": ["natural_philosophy", "civic_architecture", "biography"], "expect_status": "ANSWER"}, "request": {"query": "q"}, "mode": "answer"}
        (suite / "holdout.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        defects = official.scan_gold_taxonomy(Path(tmp), Path(tmp), tax)
    assert defects == []

def test_author_vocabulary_enumerable_and_subset():
    voc = _j("author_domain_vocabulary.json")
    tax = _j("domain_taxonomy_contract.json")
    canonical = {d["canonical_label"] for d in tax["domains"]}
    assert set(voc["possible_gold_labels"]) <= canonical
    assert voc["no_dynamic_label_invention"] is True
    assert author.AUTHOR_DOMAIN_VOCABULARY <= canonical

def test_crossdomain_registry_all_labels_registered():
    reg = _j("crossdomain_pair_registry.json")
    tax = _j("domain_taxonomy_contract.json")
    canonical = {d["canonical_label"] for d in tax["domains"]}
    assert reg["pair_families"] == 7 and reg["rows_per_pair"] == 100 and reg["total_rows"] == 700
    for pair in reg["pairs"]:
        assert pair["domain_a"] in canonical and pair["domain_b"] in canonical

def test_taxonomy_coverage_100():
    cov = _j("domain_taxonomy_coverage.json")
    assert cov["coverage_percent"] == 100.0
    assert cov["canonical_domains"] == cov["evaluator_covered_domains"] == cov["scorer_covered_domains"] == cov["synthetic_tested_domains"] == 14
    assert cov["author_covered_domains"] == 10
    assert cov["author_subset_of_evaluator"] is True
    assert cov["author_coverage_percent"] == 100.0
    assert cov["scorer_equals_evaluator"] is True

def test_consumer_matrix_no_conflicts():
    m = _j("domain_taxonomy_consumer_matrix.json")
    assert m["independent_hardcoded_conflicting_taxonomies"] == 0
    assert m["unknown_consumers"] == 0
    assert m["producer_consumer_disagreements"] == 0

def test_real_r14_paths_absent():
    assert not (ROOT / "rag" / "gk_holdout_t21r14").exists()
    assert not (OUT / "suites").exists()
    assert not (OUT / "construction_run_ledger.json").exists()
    assert not (OUT / "holdout_manifest.json").exists()
    assert not (OUT / "HOLDOUT_FROZEN").exists()
    assert not (OUT / "evaluation_run_ledger.json").exists()
    assert not (OUT / "raw_results.jsonl").exists()
    assert not (OUT / "holdout_results.json").exists()

def test_exact_design_38():
    cov = _j("contract_gate_coverage.json")
    assert cov["contract_leaves"] == 38
    assert cov["unhandled"] == 0
