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


# --- real-entrypoint freeze-path remediation (§7/§8/§9/§14–§16) ---


def _synthetic_freeze_document(**overrides) -> dict:
    from t21_protocol.util import sha256_json
    from t28_protocol.freeze import (PINNED_CANDIDATE_COMMIT,
                                     PINNED_CANDIDATE_TREE,
                                     PINNED_RUNTIME_ROOT)
    entries = [
        {"path": f"t28_protocol/mod{i}.py", "sha256": f"{i:064d}",
         "byte_size": 900 + i, "role": "T28_PROTOCOL_RUNTIME"}
        for i in range(3)]
    root_input = {
        "schema_version": "t28-preconstruction-freeze-v1",
        "artifact": "T28_PRECONSTRUCTION_FREEZE",
        "classification": "PUBLIC_SAFE", "experiment": "t28",
        "candidate_commit": PINNED_CANDIDATE_COMMIT,
        "candidate_tree": PINNED_CANDIDATE_TREE,
        "runtime_root": PINNED_RUNTIME_ROOT,
        "candidate_runtime_changes": 0,
        "component_root": sha256_json(entries),
        "terminal_semantics_frozen": True,
        "completion_recovery_replan_abstention_frozen": True,
        "provider_and_scorer_bindings_frozen": True,
        "real_construction_authorized": False,
        "real_evaluation_authorized": False,
        "real_blind_rows": 0, "real_gold_rows": 0,
        "real_construction_attempts": 0, "real_evaluation_attempts": 0,
    }
    document = {**root_input, "component_count": len(entries),
                "components": entries, "freeze_root": sha256_json(root_input)}
    document["freeze_sha256"] = sha256_json(document)
    document.update(overrides)
    return document


def test_canonical_freeze_path_and_loader_semantics():
    from t28_protocol.freeze import (EXCLUDED, FREEZE_LOADER_ID,
                                     SUPERSEDED_PRE_EXPOSURE_PATH,
                                     T28_PRECONSTRUCTION_FREEZE_PATH,
                                     load_preconstruction_freeze)
    forbidden = "evaluations/t28/preconstruction_freeze_" + "v1" + ".json"
    assert T28_PRECONSTRUCTION_FREEZE_PATH == (
        "evaluations/t28/preconstruction_freeze.json")
    assert FREEZE_LOADER_ID == "t28_protocol.freeze:load_preconstruction_freeze"
    assert SUPERSEDED_PRE_EXPOSURE_PATH == (
        "evaluations/t28/preconstruction_freeze_superseded_pre_exposure.json")
    assert forbidden not in T28_PRECONSTRUCTION_FREEZE_PATH
    assert forbidden not in SUPERSEDED_PRE_EXPOSURE_PATH
    assert not any(forbidden in entry for entry in EXCLUDED)

    def loader_refusal(document, marker, *, write=True):
        with TemporaryDirectory(prefix="t28-loader-refusal-") as tmp:
            sparse = Path(tmp) / "repo"
            (sparse / "evaluations" / "t28").mkdir(parents=True)
            if write:
                (sparse / "evaluations" / "t28" /
                 "preconstruction_freeze.json").write_text(
                    json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
            with pytest.raises(ValueError) as raised:
                load_preconstruction_freeze(sparse)
            assert marker in str(raised.value), str(raised.value)
            assert not list((sparse / "evaluations" / "t28").glob("*_v1*"))

    loader_refusal(None, "absent", write=False)
    # a doc-internally coherent freeze survives the loader's internal
    # recomputation and is refused only by repository re-verification,
    # which is impossible inside the sparse temporary root
    loader_refusal(_synthetic_freeze_document(), "repository")
    # tampered freeze identity is refused by field name before any
    # repository access (§16)
    loader_refusal(_synthetic_freeze_document(freeze_sha256="1" * 64),
                   "freeze_sha256")
    loader_refusal(_synthetic_freeze_document(component_count=99),
                   "component_count")
    loader_refusal(_synthetic_freeze_document(component_root="2" * 64),
                   "component_root")
    loader_refusal(_synthetic_freeze_document(freeze_root="3" * 64),
                   "freeze_root")
    loader_refusal(_synthetic_freeze_document(candidate_commit="b" * 40),
                   "candidate identity")


def test_real_entrypoint_loader_bound_and_forbidden_scans_clean():
    from t28_protocol.freeze import FREEZE_LOADER_ID
    with (ROOT / "t28_protocol" / "construction.py").open(
            encoding="utf-8") as handle:
        construction_source = handle.read()
    assert "freeze = load_preconstruction_freeze(root)" in construction_source
    assert "construct_real" in construction_source
    with (ROOT / "t28_protocol" / "freeze.py").open(
            encoding="utf-8") as handle:
        assert FREEZE_LOADER_ID in handle.read()
    forbidden = "evaluations/t28/preconstruction_freeze_" + "v1" + ".json"
    scanned = list((ROOT / "t28_protocol").glob("*.py"))
    scanned.extend((ROOT / "scripts").glob("t28*.py"))
    scanned.extend((ROOT / "tests").glob("test_t28*.py"))
    assert scanned, "T28 production surface must not be empty"
    for path in scanned:
        with path.open(encoding="utf-8") as handle:
            assert forbidden not in handle.read(), path


def test_real_entrypoint_contract_and_gate_leaves():
    from t28_protocol.construction import (CONSTRUCTION_GATE_IDS,
                                           CONTRACT_LEAF_IDS,
                                           construction_contract)
    assert "protocol.canonical_freeze_path_exact" in CONTRACT_LEAF_IDS
    assert "protocol.real_entrypoint_freeze_reproduces" in CONTRACT_LEAF_IDS
    assert construction_contract()["leaf_count"] == len(CONTRACT_LEAF_IDS)
    assert len(CONTRACT_LEAF_IDS) == 62
    assert "G53_REAL_ENTRYPOINT_CANONICAL_FREEZE_PATH" in CONSTRUCTION_GATE_IDS
    assert "G54_REAL_ENTRYPOINT_FREEZE_REPRODUCTION" in CONSTRUCTION_GATE_IDS
    assert len(CONSTRUCTION_GATE_IDS) == 54


def test_real_rehearsal_oracle_binding():
    from t21_protocol.util import sha256_json
    from t28_protocol.construction import (fingerprint_root, fingerprint_sets,
                                           synthetic_private_bundle)
    from t28_protocol.oracle import verify_oracle_result
    from t27_protocol.t28_private_oracle import (
        disposable_real_mode_oracle_result)
    cases, gold, _fixtures = synthetic_private_bundle(13, with_fixture=True)
    prospective = fingerprint_sets(cases, gold)
    result = disposable_real_mode_oracle_result(
        root=ROOT, prospective_root=fingerprint_root(prospective),
        # single-digit variant: the disposable candidate commit embeds the
        # variant digit and must stay a 40-hex identifier
        prospective=prospective, variant=7)
    verdict = verify_oracle_result(result, mode="REAL_REHEARSAL")
    assert verdict["real_mode_not_synthetic"] is True
    assert verdict["t27_store_authenticated"] is True
    assert verdict["overall_prohibited_overlap"] == 0
    # promoting the disposable stand-in scope to OFFICIAL_T27 is refused —
    # a rehearsal oracle can never impersonate the official T27 scope
    tampered = dict(result, official_commitment_scope="OFFICIAL_T27")
    tampered["result_sha256"] = sha256_json(
        {key: value for key, value in tampered.items()
         if key != "result_sha256"})
    with pytest.raises(ValueError):
        verify_oracle_result(tampered, mode="REAL_REHEARSAL")