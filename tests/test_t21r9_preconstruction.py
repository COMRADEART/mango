"""T21R9 preconstruction gate: synthetic data only, zero runtime rows."""
from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r9_preconstruction as qualification  # noqa: E402
import t21r9_static_semantics as semantics  # noqa: E402


CONTRACT_PATH = (ROOT / "evaluations" / "t21r9" /
                 "preconstruction_contract.json")


def _fixture() -> tuple[list[dict], list[dict], list[dict]]:
    sources, chunks = qualification.build_synthetic_world()
    return sources, chunks, qualification.build_synthetic_suites()


def test_contract_forbids_blind_data_and_runtime_execution() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert contract["blind_data_allowed"] is False
    assert contract["runtime_execution_maximum"] == 0
    assert contract["canonical_parent"] == \
        "7a63ec637ed3b756053e8ea4972af6b983d6dc50"
    assert contract["synthetic_fixture"] == {
        "namespace_prefix": "pre9q-",
        "future_blind_reuse_forbidden": True,
        "source_count": 5,
        "chunk_count": 7,
        "world_rows": 12,
        "suite_rows": 6,
    }


def test_contract_preregisters_all_eight_independence_dimensions() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert contract["independence_dimensions"] == list(
        semantics.INDEPENDENCE_DIMENSIONS)
    assert len(contract["independence_dimensions"]) == 8


def test_synthetic_material_uses_only_disposable_namespace() -> None:
    sources, chunks, rows = _fixture()
    assert (len(sources), len(chunks), len(rows)) == (5, 7, 6)
    assert all(source["source_id"].startswith("pre9q-") for source in sources)
    assert all(chunk["chunk_id"].startswith("pre9q-") for chunk in chunks)
    assert all(row["case_id"].startswith("pre9q-") for row in rows)


def test_historical_absent_entity_transformation_removes_stale_metadata() \
        -> None:
    _sources, chunks, rows = _fixture()
    absent = rows[4]
    assert absent["category"] == "injection_absent_entity"
    assert "construction" not in absent
    assert "construction_tags" not in absent
    assert semantics.scan_annotations(rows, chunks)["status"] == "PASS"


def test_equivalent_first_edge_passes_without_nominated_chunk_in_window() \
        -> None:
    sources, chunks, rows = _fixture()
    row = rows[0]
    initial = row["construction"]["initial_window_chunk_ids"]
    nominated = row["construction"]["gold_path"]["hop1_edge"]["chunk_id"]
    assert nominated not in initial
    result = semantics.audit_path_row(row, sources, chunks)
    assert result["status"] == "PASS"
    assert result["selected_initial_chunk_id"] == \
        "pre9q-chunk-hop1-equivalent"
    assert result["runtime_execution_count"] == 0


def test_all_six_path_controls_have_expected_outcome() -> None:
    sources, chunks, rows = _fixture()
    controls = qualification.path_achievability_controls(
        sources, chunks, rows[0])
    assert len(controls) == 6
    assert all(control["passed"] for control in controls)
    assert {control["name"] for control in controls} == {
        "nominated_absent_equivalent_edge",
        "missing_first_hop_evidence",
        "wrong_relation",
        "wrong_bridge",
        "equal_rank_contradictory_edges",
        "unsafe_nonprojectable_edge",
    }


def test_path_audit_rejects_wrong_source_identity() -> None:
    sources, chunks, rows = _fixture()
    row = copy.deepcopy(rows[0])
    row["construction"]["gold_path"]["hop2_edge"]["source_id"] = \
        "pre9q-src-alpha"
    result = semantics.audit_path_row(row, sources, chunks)
    assert result["status"] == "FAIL"
    assert any("source identity" in defect for defect in result["defects"])


def test_fresh_spoof_fixture_is_structural_only_and_nonresolving() -> None:
    sources, chunks, rows = _fixture()
    result = semantics.audit_spoof_row(rows[1], sources, chunks)
    assert result["status"] == "PASS"
    assert result["locator"] == "r9qz-4e91adbc7032f685"
    assert result["runtime_execution_count"] == 0


def test_all_seven_spoof_controls_have_expected_outcome() -> None:
    sources, chunks, rows = _fixture()
    controls = qualification.spoof_controls(sources, chunks, rows[1])
    assert len(controls) == 7
    assert all(control["passed"] for control in controls)
    assert {control["name"] for control in controls} >= {
        "malformed_provenance",
        "spoof_resolves_real_source",
        "spoof_resolves_real_chunk",
    }


def test_all_ten_annotation_controls_have_expected_outcome() -> None:
    _sources, chunks, rows = _fixture()
    controls = qualification.annotation_controls(rows, chunks)
    assert len(controls) == 10
    assert all(control["passed"] for control in controls)
    assert {control["name"] for control in controls} >= {
        "stale_attack_metadata",
        "missing_required_source",
        "corroboration_path_source_overlap",
    }


def test_each_independence_dimension_has_a_negative_control() -> None:
    sources, chunks, rows = _fixture()
    controls = qualification.independence_controls(sources, chunks, rows)
    assert len(controls) == 9
    assert all(control["passed"] for control in controls)
    names = {control["name"] for control in controls}
    assert {f"reused_{dimension}"
            for dimension in semantics.INDEPENDENCE_DIMENSIONS} <= names


def test_static_scanner_uniqueness_and_blindness_all_pass() -> None:
    sources, chunks, rows = _fixture()
    assert qualification.run_static_audit(rows, sources, chunks)["status"] == \
        "PASS"
    assert semantics.scan_annotations(rows, chunks)["status"] == "PASS"
    assert semantics.audit_independence(
        sources, chunks, rows,
        qualification.synthetic_prior_material())["status"] == "UNIQUE"
    assert qualification.run_blindness_audit()["status"] == "PASS"


def test_qualification_sources_have_no_runtime_evaluator_call() -> None:
    forbidden = {"answer_knowledge", "resolve_path", "run_evaluation",
                 "evaluate_holdout", "official_evaluation"}
    for path in (qualification.BUILDER_PATH, qualification.STATIC_AUDIT_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(
                node.func, (ast.Name, ast.Attribute))
        }
        assert called.isdisjoint(forbidden)


def test_end_to_end_nonblind_miniature_and_seal_controls_pass() -> None:
    report = qualification.run_qualification(write_report=False)
    assert report["status"] == "PASS"
    assert report["counts"] == {
        "sources": 5, "chunks": 7, "world_rows": 12, "suite_rows": 6}
    assert all(status == "PASS" for status in report["stages"].values())
    assert report["runtime_rows_executed"] == 0
    assert report["controls"]["seal_preflight"]["passed"] == 6
    assert report["controls"]["seal_preflight"]["total"] == 6


def test_every_real_r9_holdout_and_exposure_path_remains_absent() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert qualification.prohibited_real_paths() == []
    assert len(contract["prohibited_real_r9_paths"]) == 7
    for relative in contract["prohibited_real_r9_paths"]:
        assert not (ROOT / relative).exists()
