"""Full T21R9 preregistration infrastructure tests; no blind data."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import t21r9_blindness_audit as blindness  # noqa: E402
import t21r9_build_suites as suite_builder  # noqa: E402
import t21r9_construction_gate as gate  # noqa: E402
import t21r9_freeze_holdout as seal  # noqa: E402
import t21r9_official_eval as official  # noqa: E402
import t21r9_preconstruction as qualification  # noqa: E402
import t21r9_static_semantics as semantics  # noqa: E402
import t21r9_uniqueness as uniqueness  # noqa: E402
import t21r9_world as world_builder  # noqa: E402


OUT = ROOT / "evaluations" / "t21r9"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _material():
    sources, chunks = qualification.build_synthetic_world()
    rows = qualification.build_synthetic_suites()
    return sources, chunks, rows


def test_all_32_promotion_floors_are_byte_for_value_preserved() -> None:
    r8 = _json(ROOT / "evaluations" / "t21r8" / "validation_contract.json")
    r9 = _json(OUT / "validation_contract.json")
    assert r9["floors"] == r8["floors"]
    assert sum(len(group) for group in r9["floors"].values()) == 32
    assert r9["promotion_floor_count"] == 32


def test_real_contract_restores_all_eleven_partial_path_configurations() -> None:
    contract = _json(OUT / "holdout_construction_contract.json")
    expected = {
        "missing_start_entity", "missing_hop1", "missing_hop2",
        "wrong_bridge_identity", "near_name_start_entity",
        "near_name_bridge_entity", "wrong_relation",
        "same_entity_wrong_attribute", "partial_path_only",
        "unrelated_conflict", "relevant_unresolved_conflict",
    }
    assert set(contract["partial_path_configurations"]) == expected
    assert semantics.PARTIAL_PATH_COMPONENTS == expected


def test_identity_confusion_annotation_controls_are_positive_and_negative() \
        -> None:
    _sources, chunks, rows = _material()
    controls = {control["name"]: control for control in
                qualification.annotation_controls(rows, chunks)}
    for component in ("near_name_start_entity", "near_name_bridge_entity",
                      "same_entity_wrong_attribute"):
        assert controls[f"{component}_valid"]["passed"] is True
        assert controls[f"{component}_malformed"]["passed"] is True


def test_retrieval_mirror_matches_production_on_every_preregistered_stage() \
        -> None:
    _sources, chunks, rows = _material()
    controls = qualification.retrieval_parity_controls(chunks, rows[0])
    assert len(controls) == 7
    assert all(control["passed"] for control in controls)
    assert {control["name"] for control in controls} == {
        "ranking_parity", "reranking_parity", "same_source_dedup_parity",
        "top8_truncation_parity", "source_reservation_parity",
        "entity_relation_first_edge_selection",
        "retrieval_mirror_parity_drift",
    }


def test_path_window_is_derived_and_fake_annotation_is_ignored() -> None:
    sources, chunks, rows = _material()
    row = copy.deepcopy(rows[0])
    row["construction"]["initial_window_chunk_ids"] = [
        "pre9q-chunk-wrong-relation"]
    result = semantics.audit_path_row(row, sources, chunks)
    assert result["status"] == "PASS"
    assert result["annotation_initial_window_ignored"] is True
    assert result["selected_initial_chunk_id"] == \
        "pre9q-chunk-hop1-equivalent"
    assert "pre9q-chunk-hop1-nominated" not in result[
        "derived_initial_window_chunk_ids"]


def test_real_builders_reject_disposable_ids_and_declared_windows() -> None:
    with pytest.raises(ValueError, match="pre9q"):
        world_builder.validate_world_spec({
            "world": [{"entity_id": "pre9q-forbidden"}],
            "sources": [{"source_id": "source-real"}],
            "chunks": [{"chunk_id": "chunk-real", "source_id": "source-real",
                        "metadata": {"fact_entity": "x",
                                     "fact_attribute": "creator",
                                     "fact_value": "y"}}],
        })
    contract = copy.deepcopy(_json(OUT / "holdout_construction_contract.json"))
    contract["suite_target_exact"] = {
        official.evaluator.SUITES[0]: 1,
        **{suite_id: 0 for suite_id in official.evaluator.SUITES[1:]},
    }
    row = qualification.build_synthetic_suites()[0]
    row["case_id"] = "r9-control-real-case"
    row["suite_id"] = official.evaluator.SUITES[0]
    row["construction"]["initial_window_chunk_ids"] = ["fake"]
    with pytest.raises(ValueError, match="initial retrieval windows"):
        suite_builder.validate_suite_spec({"rows": [row]}, contract)


def test_builder_and_static_firewall_has_no_production_runtime_dependency() \
        -> None:
    result = blindness.audit_scripts(ROOT)
    assert result["status"] == "PASS"
    assert result["violations"] == []
    for name in blindness.SCRIPTS:
        tree = ast.parse((ROOT / "scripts" / name).read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names]
        assert not any(value.startswith("sciencemath") for value in imports)


def test_hash_only_prior_exclusion_covers_t21_through_t21r8() -> None:
    artifact = _json(uniqueness.FINGERPRINT_PATH)
    decoded = uniqueness.validate_artifact(artifact)
    assert tuple(decoded) == uniqueness.MILESTONES
    assert artifact["raw_values_included"] is False
    assert set(decoded) == {
        "T21", "T21R", "T21R2", "T21R3", "T21R4", "T21R5", "T21R6",
        "T21R7", "T21R8_DIAGNOSTIC",
    }
    assert all(decoded[milestone][dimension]
               for milestone in decoded for dimension in
               uniqueness.DIMENSIONS[:-1])
    assert decoded["T21R7"]["verbatim_attack_wording"]
    assert decoded["T21R8_DIAGNOSTIC"]["verbatim_attack_wording"]
    assert artifact["milestones"]["T21R8_DIAGNOSTIC"][
        "raw_material_committed"] is False


def test_t21r8_fingerprint_reuse_and_artifact_tamper_fail_closed() -> None:
    sources, chunks, rows = _material()
    controls = qualification.prior_exclusion_controls(sources, chunks, rows)
    assert len(controls) == 3
    assert all(control["passed"] for control in controls)
    assert {control["name"] for control in controls} >= {
        "t21r8_fingerprint_reuse", "prior_exclusion_fingerprint_tamper"}


def test_full_construction_gate_enforces_counts_stress_and_all_ie_classes() \
        -> None:
    contract = _json(OUT / "holdout_construction_contract.json")
    requirements = contract["stress_requirements"]
    metrics = {
        "runtime_execution_count": 0, "annotation_violations": 0,
        "declared_initial_windows": 0,
        "partial_path_configurations": contract[
            "partial_path_configurations"],
        "suite_rows": contract["suite_target_exact"],
        "total_rows": contract["total_rows_exact"],
        "stress": {
            "multihop_rows": 800, "multihop_chain_families": 12,
            "multihop_largest_family_share": 0.20,
            "multihop_relation_surface_mismatch_fraction": 0.50,
            "crossdomain_rows": 700,
            "crossdomain_two_source_two_domain": 700,
            "domain_pair_families": 4, "largest_domain_pair_share": 0.35,
            "multisource_path_rows": 1200, "partial_path_rows": 300,
            "partial_path_configuration_counts": {
                component: requirements["partial_path_configuration_minimum"]
                for component in contract["partial_path_configurations"]},
            "relation_surface_rows": 700,
            "canonical_relations": [f"REL-{index}" for index in range(16)],
            "relation_surface_mismatch_fraction": 0.50,
            "source_injection_rows": 300,
            "query_injection_or_spoof_rows": 250,
            "safe_fact_with_directive_rows": 150,
        },
    }
    report = gate.build_gate_report(contract, metrics)
    assert report["status"] == "PASS"
    broken = copy.deepcopy(metrics)
    broken["stress"]["partial_path_configuration_counts"][
        "near_name_bridge_entity"] = 4
    assert gate.build_gate_report(contract, broken)["status"] == "FAIL"


def test_exact_official_preflight_passes_without_writing_ledger(tmp_path) \
        -> None:
    sources, chunks, rows = _material()
    root = tmp_path / "synthetic-repository"
    stages = qualification.materialize_real_protocol_candidate(
        root, sources, chunks, rows)
    assert all(value in {"PASS", "UNIQUE", 0} for value in stages.values())
    assert seal.seal(root)["status"] == "PASS"
    report = official.preflight(root)
    assert report["status"] == "PASS"
    assert report["runtime_execution_count"] == 0
    assert report["ledger_written"] is False
    assert not (root / "evaluations" / "t21r9" /
                "evaluation_run_ledger.json").exists()


def test_real_preflight_negative_controls_cover_new_audit_gaps(tmp_path) \
        -> None:
    sources, chunks, rows = _material()
    root = tmp_path / "synthetic-repository"
    qualification.materialize_real_protocol_candidate(root, sources, chunks,
                                                      rows)
    seal.seal(root)
    controls = qualification.real_protocol_seal_controls(root)
    assert len(controls) == 12
    assert all(control["passed"] for control in controls)
    assert {control["name"] for control in controls} >= {
        "official_runner_schema_mismatch", "suite_id_mismatch",
        "evaluator_hash_mismatch", "runtime_component_hash_drift",
        "evaluator_component_hash_drift", "freeze_file_component_map_tamper"}


def test_frozen_component_verifier_refuses_drift_and_missing_components(
        tmp_path) -> None:
    freeze_path = OUT / "runtime_freeze.json"
    freeze = _json(freeze_path)
    assert seal.verify_component_freeze(
        ROOT, freeze_path, "T21R9_RUNTIME_FREEZE")["status"] == "VERIFIED"

    with pytest.raises(ValueError, match="frozen component hash mismatch"):
        drifted = copy.deepcopy(freeze)
        drifted["component_sha256"][next(iter(drifted[
            "component_sha256"]))] = "0" * 64
        drifted_path = tmp_path / "drifted-runtime_freeze.json"
        drifted_path.write_text(json.dumps(drifted), encoding="utf-8")
        seal.verify_component_freeze(ROOT, drifted_path,
                                     "T21R9_RUNTIME_FREEZE")

    for mutation, message in (
            ({"artifact": "WRONG"}, "identity mismatch"),
            ({"status": "UNFROZEN"}, "not FROZEN"),
            ({"runtime_execution_count": 1}, "runtime execution"),
            ({"component_sha256": {}}, "no component_sha256 map"),
            ({"component_sha256": {"src/missing.py": "0" * 64}},
             "frozen component missing")):
        bad = copy.deepcopy(freeze)
        bad.update(mutation)
        bad_path = tmp_path / f"bad-{mutation['artifact'] if 'artifact' in mutation else message.replace(' ', '-')}.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError, match=message.replace(
                " ", chr(92) + " ")):
            seal.verify_component_freeze(ROOT, bad_path,
                                         "T21R9_RUNTIME_FREEZE")


def test_runtime_and_evaluator_freezes_bind_current_components() -> None:
    for name, artifact in (("runtime_freeze.json", "T21R9_RUNTIME_FREEZE"),
                           ("evaluator_freeze.json",
                            "T21R9_EVALUATOR_FREEZE")):
        freeze = _json(OUT / name)
        assert freeze["artifact"] == artifact
        assert freeze["status"] == "FROZEN"
        assert freeze["runtime_execution_count"] == 0
        for relative, expected in freeze["component_sha256"].items():
            assert _sha(ROOT / relative) == expected


def _sealed_official_paths(tmp_path):
    sources, chunks, rows = _material()
    root = tmp_path / "synthetic-repository"
    qualification.materialize_real_protocol_candidate(root, sources, chunks,
                                                      rows)
    assert seal.seal(root)["status"] == "PASS"
    return root, official.build_paths(root)


def test_started_ledger_creation_is_exclusive_and_second_attempt_refused(
        tmp_path) -> None:
    _root, paths = _sealed_official_paths(tmp_path)
    assert not paths.ledger.exists()
    official._write_ledger(paths, "started")
    first = paths.ledger.read_text(encoding="utf-8")
    assert json.loads(first)["phase"] == "started"
    with pytest.raises(FileExistsError):
        official._write_ledger(paths, "started")
    assert paths.ledger.read_text(encoding="utf-8") == first
    assert json.loads(paths.ledger.read_text(
        encoding="utf-8"))["phase"] == "started"


@pytest.mark.parametrize("phase,error", [
    ("started", None), ("failed", "synthetic failure"), ("complete", None)])
def test_existing_ledger_refuses_official_preflight(
        tmp_path, phase, error) -> None:
    _root, paths = _sealed_official_paths(tmp_path)
    official._write_ledger(paths, phase, error)
    report = official._preflight(paths)
    assert report["status"] == "FAIL"
    assert any("evaluation_run_ledger.json" in defect
               for defect in report["defects"])
    assert report["runtime_execution_count"] == 0


@pytest.mark.parametrize("name", ["raw_results.jsonl", "holdout_results.json"])
def test_existing_results_artifact_refuses_official_preflight(
        tmp_path, name) -> None:
    _root, paths = _sealed_official_paths(tmp_path)
    (paths.out / name).write_text("", encoding="utf-8")
    report = official._preflight(paths)
    assert report["status"] == "FAIL"
    assert any(name in defect for defect in report["defects"])


def test_failed_evaluation_keeps_ledger_and_blocks_rerun(
        tmp_path, monkeypatch) -> None:
    _root, paths = _sealed_official_paths(tmp_path)

    def forced_failure(*_args, **_kwargs):
        raise RuntimeError("synthetic forced failure")

    monkeypatch.setattr(official.evaluator, "evaluate", forced_failure)
    monkeypatch.setattr("sciencemath.knowledge.corpus.load_corpus",
                        lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="synthetic forced failure"):
        official.execute(paths)
    assert paths.ledger.exists()
    ledger = json.loads(paths.ledger.read_text(encoding="utf-8"))
    assert ledger["phase"] == "failed"
    assert "synthetic forced failure" in ledger["error"]
    assert official._preflight(paths)["status"] == "FAIL"
    with pytest.raises(SystemExit):
        official.execute(paths)


def test_qualification_binds_all_real_tooling_contracts_and_fingerprints() \
        -> None:
    report = qualification.run_qualification(write_report=False)
    assert report["status"] == "PASS"
    bindings = report["bindings"]
    assert len(bindings["tooling_sha256"]) == 12
    assert set(bindings["contract_sha256"]) == {
        "preconstruction", "validation", "construction", "scoring_semantics"}
    assert bindings["prior_exclusion_fingerprint_sha256"] == _sha(
        uniqueness.FINGERPRINT_PATH)
    assert report["runtime_rows_executed"] == 0


def test_no_real_r9_blind_or_exposure_path_exists() -> None:
    assert qualification.prohibited_real_paths() == []
