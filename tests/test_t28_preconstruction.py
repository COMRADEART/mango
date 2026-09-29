"""Deterministic T28 preconstruction invariants (no staged artifacts required)."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from sciencemath.executive.skills import SKILL_IDS
from t28_protocol.contract import (CONSTRUCTION_TOKEN, CRITICAL_COUNTERS,
                                   EVALUATION_TOKEN, FAMILIES, FLOORS,
                                   NONVACUITY_MINIMUMS, REPLAN_TRIGGERS,
                                   T27_CONSTRUCTION_STATE,
                                   T27_OFFICIAL_EVALUATION_ATTEMPT,
                                   T27_OFFICIAL_EVALUATION_ELIGIBILITY,
                                   T27_OFFICIAL_EVALUATION_STATE,
                                   T27_PREDECESSOR_VERDICT, design,
                                   execution_contract, production_graph)
from t28_protocol.evaluation import (EvaluationLedgerError,
                                     T28EvaluationLedger,
                                     evaluate_official,
                                     materialize_rehearsal_blind,
                                     run_evaluation_absence_preflight,
                                     run_sealed_store_preflight)
from t28_protocol.exclusion import (DIMENSIONS, GENERATED_PUBLIC_POLICY_SCHEMA,
                                    build_synthetic_historical_index,
                                    generated_public_dimension_policy,
                                    validate_generated_public_dimension_policy,
                                    verify_historical_index)
from t28_protocol.freeze import verify_inherited_runtime
from t28_protocol.qualification import build_public_cases, run_verification_matrix
from t28_protocol.scorer import ZERO_DENOMINATOR_POLICY, score_suite
from t28_protocol.store import T28PrivateStore

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_contract_constants():
    assert CONSTRUCTION_TOKEN == (
        "T28_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION")
    assert EVALUATION_TOKEN == "T28_ONE_SHOT_OFFICIAL_EVALUATION"
    assert CONSTRUCTION_TOKEN != EVALUATION_TOKEN
    assert len(FAMILIES) == 16 and len(REPLAN_TRIGGERS) == 6
    assert len(CRITICAL_COUNTERS) == 9 and len(FLOORS) == 11
    assert FLOORS["scenario_completion_rate"] == 0.70
    assert all(floor == 1.0 for name, floor in FLOORS.items()
               if name != "scenario_completion_rate")
    assert dict(NONVACUITY_MINIMUMS) == {
        "successful_completion_cases": 96, "recoverable_cases": 32,
        "replan_required_cases": 32, "safe_abstention_cases": 32,
        "handoff_cases": 128, "verification_cases": 512}
    assert T27_CONSTRUCTION_STATE == "SEALED"
    assert T27_OFFICIAL_EVALUATION_STATE == (
        "UNSPENT_BUT_PERMANENTLY_INELIGIBLE")
    assert T27_OFFICIAL_EVALUATION_ATTEMPT == 0
    assert T27_OFFICIAL_EVALUATION_ELIGIBILITY == (
        "PERMANENTLY_NOT_AUTHORIZED_FOR_T27")


def test_execution_contract_and_design_frozen():
    contract = execution_contract()
    assert set(contract["terminals"]) == {
        "COMPLETE", "PARTIAL", "INSUFFICIENT_EVIDENCE", "BLOCKED",
        "BUDGET_EXHAUSTED", "UNAVAILABLE_CAPABILITY", "SECURITY_REFUSAL",
        "ERROR"}
    data = design()
    assert (data["family_count"], data["cases_per_family"],
            data["total_real_blind_cases"]) == (16, 32, 512)
    assert data["t27_evaluation_ever_run"] is False
    assert data["t27_official_evaluation_permitted_again"] is False
    assert "UNSPENT_BUT_PERMANENTLY_INELIGIBLE" in data["t27_token_binding"]


def test_production_graph_evaluation_ledger_first():
    graph = production_graph()
    order = graph["ordered_components"]
    assert order.index("evaluation_ledger") < order.index("blind_reader")
    assert order.index("evaluation_ledger") < order.index("workspace_factory")
    assert order.index("evaluation_ledger") < order.index("official_runner")
    assert graph["evaluation_ledger_precedes"] == [
        "blind_reader", "workspace_factory", "official_runner"]
    assert graph["nodes"]["environment_builder"]["producer"] == (
        "t28_protocol.official_environment:"
        "build_official_evaluation_environment")
    assert graph["nodes"]["official_runner"]["producer"] == (
        "t28_protocol.official_environment:T28OfficialRunnerFactory")
    assert graph["missing_producers"] == 0 and graph["dangling_edges"] == 0
    assert graph["production_stubs"] == 0


def test_scorer_fail_nonvacuity():
    cases, gold, injections = build_public_cases()
    plans = [case["plan"] for case in cases]
    outputs = [{
        "terminal": expected["expected_terminal"],
        "verified_steps": list(range(expected["expected_verified_steps"])),
        "final_answer": None if expected["designated_abstention"] else "a",
        "final_answer_commitment": None if expected["designated_abstention"] else "b",
        "trace": [],
        "replans": [], "handoffs": [], "budget_state": {"total_retries": 0},
        "authority": "ORCHESTRATOR",
    } for expected in gold]
    score = score_suite(outputs, gold, plans)
    assert score["zero_denominator_policy"] == "FAIL_NONVACUITY"
    zero_denominator = {
        name for name, metric in score["metrics"].items()
        if metric["denominator"] == 0}
    assert zero_denominator == {"capability_selection_accuracy",
                                "handoff_validity_rate"}
    for name in zero_denominator:
        metric = score["metrics"][name]
        assert metric["observed"] is None
        assert metric["pass"] is False
    nonzero = {name: metric for name, metric in score["metrics"].items()
               if name not in zero_denominator}
    assert all(metric["denominator"] > 0 for metric in nonzero.values())
    assert ZERO_DENOMINATOR_POLICY == "FAIL_NONVACUITY"
    assert score["status"] == "FAIL"


def test_generated_public_dimension_policy_frozen():
    document = generated_public_dimension_policy()
    assert document["schema_version"] == GENERATED_PUBLIC_POLICY_SCHEMA
    validate_generated_public_dimension_policy(document)
    structural = document["dimension_classifications"]
    assert set(structural) == set(DIMENSIONS)
    from t28_protocol.exclusion import GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS
    assert set(GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS) == {
        "entity_identities", "source_ids", "verbatim_attack_wording",
        "relations"}
    assert set(structural) - set(GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS) == {
        "case_ids", "chunk_ids", "exact_queries", "exact_answers",
        "exact_source_text"}


def test_synthetic_index_verifies():
    index = build_synthetic_historical_index(5)
    assert verify_historical_index(index, root=None, mode="SYNTHETIC") is not None


def test_real_index_authenticates():
    from t28_protocol.exclusion import (
        build_authenticated_public_historical_index)
    if not (ROOT / "evaluations/t28/qualification_report.json").is_file():
        pytest.skip("qualification report staged later by the driver")
    index = build_authenticated_public_historical_index(ROOT)
    assert verify_historical_index(index, root=ROOT, mode="REAL") is not None


def test_store_guard_and_disposable_materialization():
    with TemporaryDirectory(prefix="t28-guard-test-") as tmp:
        base = Path(tmp)
        real_store = T28PrivateStore(base / "private", repository_root=ROOT)
        with pytest.raises(Exception):
            materialize_rehearsal_blind(real_store, [{"a": 1}], [{"b": 2}])
        with pytest.raises(Exception):
            real_store.read_json("blind/inputs.json")
        disposable = T28PrivateStore(base / "disposable",
                                     repository_root=ROOT, disposable=True)
        materialize_rehearsal_blind(disposable, [{"a": 1}], [{"b": 2}])
        assert disposable.path("blind/inputs.json").is_file()
        assert disposable.path("blind/gold.json").is_file()
        with pytest.raises(Exception):
            disposable.read_json("blind/gold.json")


def test_evaluation_ledger_token_refused_and_absence_preflight():
    with TemporaryDirectory(prefix="t28-ledger-test-") as tmp:
        store = T28PrivateStore(Path(tmp) / "private", repository_root=ROOT,
                                disposable=True)
        with pytest.raises(EvaluationLedgerError):
            T28EvaluationLedger.create_exclusive(store, {}, "wrong-token")
        assert not store.has("markers/evaluation.one-shot")
        empty = run_evaluation_absence_preflight(store)
        assert empty["status"] == "PASS" and empty["attempts"] == 0


def test_sealed_store_preflight_refuses_unsealed():
    with TemporaryDirectory(prefix="t28-sealed-preflight-") as tmp:
        store = T28PrivateStore(Path(tmp) / "private", repository_root=ROOT)
        with pytest.raises(ValueError):
            run_sealed_store_preflight(store)


def test_official_evaluator_refuses_unsealed_store_no_marker():
    with TemporaryDirectory(prefix="t28-official-refusal-") as tmp:
        base = Path(tmp)
        store = T28PrivateStore(base / "private", repository_root=ROOT)
        with pytest.raises(Exception):
            evaluate_official(ROOT, base / "private", "any-token")
        assert not store.has("markers/evaluation.one-shot")
        assert not store.has("evaluation/ledger.json")


def test_inherited_candidate_runtime_frozen():
    report = verify_inherited_runtime(ROOT)
    assert report["status"] == "PASS"
    assert report["candidate_runtime_changes"] == 0


def test_verification_matrix_pass():
    assert run_verification_matrix()["status"] == "PASS"