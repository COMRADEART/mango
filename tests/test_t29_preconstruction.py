"""Deterministic T29 preconstruction invariants (no staged artifacts required)."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from sciencemath.executive.skills import SKILL_IDS
from t29_protocol.contract import (
    CONSTRUCTION_TOKEN, CRITICAL_COUNTERS, EVALUATION_TOKEN, FAMILIES, FLOORS,
    NONVACUITY_MINIMUMS, REPLAN_TRIGGERS,
    T27_CONSTRUCTION_ATTEMPT, T27_CONSTRUCTION_STATE,
    T27_OFFICIAL_EVALUATION_ATTEMPT, T27_OFFICIAL_EVALUATION_ELIGIBILITY,
    T27_OFFICIAL_EVALUATION_STATE, T27_PREDECESSOR_VERDICT,
    T28_CONSTRUCTION_ATTEMPT, T28_CONSTRUCTION_STATE,
    T28_OFFICIAL_EVALUATION_ATTEMPT, T28_OFFICIAL_EVALUATION_ELIGIBILITY,
    T28_OFFICIAL_EVALUATION_STATE, T28_PREDECESSOR_VERDICT,
    design, execution_contract, production_graph)
from t29_protocol.evaluation import (EVALUATION_READINESS_ITEMS,
                                     EvaluationLedgerError, T29EvaluationLedger,
                                     evaluate_official,
                                     run_evaluation_absence_preflight,
                                     run_sealed_store_preflight)
from t29_protocol.exclusion import (DIMENSIONS, GENERATED_PUBLIC_POLICY_SCHEMA,
                                    GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS,
                                    build_synthetic_historical_index,
                                    generated_public_dimension_policy,
                                    validate_generated_public_dimension_policy,
                                    verify_historical_index)
from t29_protocol.freeze import (PINNED_CANDIDATE_COMMIT, PINNED_CANDIDATE_TREE,
                                 PINNED_RUNTIME_ROOT, verify_inherited_runtime)
from t29_protocol.qualification import build_public_cases
from t29_protocol.scorer import ZERO_DENOMINATOR_POLICY, score_suite
from t29_protocol.store import T29PrivateStore

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_ALIAS = "evaluations/t29/preconstruction_freeze_" + "v" + "1" + ".json"


def test_frozen_contract_constants():
    assert CONSTRUCTION_TOKEN == (
        "T29_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION")
    assert EVALUATION_TOKEN == "T29_ONE_SHOT_OFFICIAL_EVALUATION"
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
    # Frozen predecessor states (T29 authorization §4/§10/§41): both T27 and
    # T28 are SEALED / UNSPENT_BUT_PERMANENTLY_INELIGIBLE; their tokens are
    # never reused by T29.
    assert T27_CONSTRUCTION_STATE == "SEALED"
    assert T27_CONSTRUCTION_ATTEMPT == 1
    assert T27_OFFICIAL_EVALUATION_STATE == (
        "UNSPENT_BUT_PERMANENTLY_INELIGIBLE")
    assert T27_OFFICIAL_EVALUATION_ATTEMPT == 0
    assert T27_OFFICIAL_EVALUATION_ELIGIBILITY == (
        "PERMANENTLY_NOT_AUTHORIZED_FOR_T27")
    assert T28_CONSTRUCTION_STATE == "SEALED"
    assert T28_CONSTRUCTION_ATTEMPT == 1
    assert T28_OFFICIAL_EVALUATION_STATE == (
        "UNSPENT_BUT_PERMANENTLY_INELIGIBLE")
    assert T28_OFFICIAL_EVALUATION_ATTEMPT == 0
    assert T28_OFFICIAL_EVALUATION_ELIGIBILITY == "PERMANENTLY_INELIGIBLE"


def test_predecessor_tokens_never_reused():
    from t27_protocol.contract import (
        CONSTRUCTION_TOKEN as T27_CONSTRUCTION,
        EVALUATION_TOKEN as T27_EVALUATION)
    from t28_protocol.contract import (
        CONSTRUCTION_TOKEN as T28_CONSTRUCTION,
        EVALUATION_TOKEN as T28_EVALUATION)
    official_tokens = {CONSTRUCTION_TOKEN, EVALUATION_TOKEN}
    assert T27_CONSTRUCTION and T27_EVALUATION and T28_CONSTRUCTION \
        and T28_EVALUATION
    assert official_tokens.isdisjoint(
        {T27_CONSTRUCTION, T27_EVALUATION, T28_CONSTRUCTION, T28_EVALUATION})


def test_execution_contract_and_design_frozen():
    contract = execution_contract()
    assert set(contract["terminals"]) == set(
        sorted({"COMPLETE", "PARTIAL", "INSUFFICIENT_EVIDENCE", "BLOCKED",
                "BUDGET_EXHAUSTED", "UNAVAILABLE_CAPABILITY", "SECURITY_REFUSAL",
                "ERROR"}))
    data = design()
    assert (data["family_count"], data["cases_per_family"],
            data["total_real_blind_cases"]) == (16, 32, 512)
    assert data["minimum_steps"] == 3 and data["maximum_steps"] == 12
    assert data["t27_evaluation_ever_run"] is False
    assert data["t27_official_evaluation_permitted_again"] is False
    assert "UNSPENT_BUT_PERMANENTLY_INELIGIBLE" in data["t27_token_binding"]
    assert data["successor_of"] == T27_PREDECESSOR_VERDICT
    assert data["real_construction_attempts"] == 0
    assert data["real_evaluation_attempts"] == 0
    assert data["t27_private_rows_opened"] == 0
    assert data["t27_candidate_reruns"] == 0


def test_production_graph_evaluation_ledger_first():
    graph = production_graph()
    order = graph["ordered_components"]
    assert order.index("evaluation_ledger") < order.index("blind_reader")
    assert order.index("evaluation_ledger") < order.index("workspace_factory")
    assert order.index("evaluation_ledger") < order.index("official_runner")
    assert graph["evaluation_ledger_precedes"] == [
        "blind_reader", "workspace_factory", "official_runner"]
    assert graph["nodes"]["environment_builder"]["producer"] == (
        "t29_protocol.official_environment:"
        "build_official_evaluation_environment")
    assert graph["nodes"]["official_runner"]["producer"] == (
        "t29_protocol.official_environment:T29OfficialRunnerFactory")
    assert graph["missing_producers"] == 0 and graph["dangling_edges"] == 0
    assert graph["production_stubs"] == 0


def test_official_entrypoint_closed_signature():
    # §24: evaluate_official(root, private_store_root, token) — no caller
    # injection of runner / provider / context / corpus / document roots /
    # model / adapter registry.  The single keyword-only parameter is the
    # frozen mode guard with its safe REAL default.
    parameters = inspect.signature(evaluate_official).parameters
    assert list(parameters)[:3] == ["root", "private_store_root", "token"]
    assert all(parameters[name].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
               for name in ("root", "private_store_root", "token"))
    assert all(name == "mode" and parameter.kind is
               inspect.Parameter.KEYWORD_ONLY and parameter.default == "REAL"
               for name, parameter in parameters.items()
               if name not in {"root", "private_store_root", "token"})


def test_wrapper_only_rehearsal_source_binding():
    from t29_protocol.evaluation import run_evaluation_rehearsals
    source = inspect.getsource(run_evaluation_rehearsals)
    assert "evaluate_official(" in source
    assert "_evaluate_once(" not in source
    assert "score_suite(" not in source


def test_construct_real_wrapper_source_binding():
    from t29_protocol.freeze import FREEZE_LOADER_ID
    from t29_protocol.construction import run_real_entrypoint_rehearsal
    source = inspect.getsource(run_real_entrypoint_rehearsal)
    assert "construct_real(" in source
    assert "construct_once(" not in source
    with (ROOT / "t29_protocol" / "construction.py").open(
            encoding="utf-8") as handle:
        construction_source = handle.read()
    assert "freeze = load_preconstruction_freeze(root)" in construction_source
    assert "construct_real" in construction_source
    assert "construct_once" in construction_source
    with (ROOT / "t29_protocol" / "freeze.py").open(
            encoding="utf-8") as handle:
        assert FREEZE_LOADER_ID in handle.read()


def test_scorer_fail_nonvacuity():
    from t29_protocol.scorer import score_suite
    cases, gold, injections = build_public_cases()
    plans = [case["plan"] for case in cases]
    outputs = [{
        "terminal": expected["expected_terminal"],
        "verified_steps": list(range(expected["expected_verified_steps"])),
        "final_answer": None if expected["designated_abstention"] else "a",
        "final_answer_commitment":
            None if expected["designated_abstention"] else "b",
        "trace": [],
        "replans": [], "handoffs": [], "budget_state": {"total_retries": 0},
        "authority": "ORCHESTRATOR",
    } for expected in gold]
    score = score_suite(outputs, gold, plans)
    assert score["zero_denominator_policy"] == "FAIL_NONVACUITY"
    zero_denominator = {
        name for name, metric in score["metrics"].items()
        if metric["denominator"] == 0}
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
    assert len(DIMENSIONS) == 9
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
    if not (ROOT / "evaluations/t29/qualification_report.json").is_file():
        pytest.skip("qualification report staged later by the driver")
    from t29_protocol.exclusion import build_authenticated_public_historical_index
    index = build_authenticated_public_historical_index(ROOT)
    assert verify_historical_index(index, root=ROOT, mode="REAL") is not None


def test_store_guard_and_disposable_materialization():
    from t29_protocol.construction import materialize_private
    with TemporaryDirectory(prefix="t29-guard-test-") as tmp:
        base = Path(tmp)
        real_store = T29PrivateStore(base / "private", repository_root=ROOT)
        with pytest.raises(Exception):
            real_store.read_json("blind/inputs.json")
        disposable = T29PrivateStore(base / "disposable",
                                     repository_root=ROOT, disposable=True)
        fixture = {"logical_id": "fx-0", "content": b"\x00\x01",
                   "schema_type": "T29_FIXTURE_V1"}
        descriptors = materialize_private(
            disposable, [{"a": 1}], [{"b": 2}], [fixture],
            {"status": "PASS"}, {"author_id": "SYNTHETIC"},
            {"status": "PASS"}, {"status": "PASS"})
        assert descriptors
        assert disposable.path("blind/inputs.json").is_file()
        assert disposable.path("blind/gold.json").is_file()
        with pytest.raises(Exception):
            disposable.read_json("blind/gold.json")


def test_evaluation_ledger_token_refused_and_absence_preflight():
    with TemporaryDirectory(prefix="t29-ledger-test-") as tmp:
        store = T29PrivateStore(Path(tmp) / "private", repository_root=ROOT,
                                disposable=True)
        with pytest.raises(EvaluationLedgerError):
            T29EvaluationLedger.create_exclusive(store, {}, "wrong-token")
        assert not store.has("markers/evaluation.one-shot")
        empty = run_evaluation_absence_preflight(store)
        assert empty["status"] == "PASS" and empty["attempts"] == 0


def test_sealed_store_preflight_refuses_unsealed():
    with TemporaryDirectory(prefix="t29-sealed-preflight-") as tmp:
        store = T29PrivateStore(Path(tmp) / "private", repository_root=ROOT)
        with pytest.raises(ValueError):
            run_sealed_store_preflight(store)


def test_official_evaluator_refuses_unsealed_store_no_marker():
    with TemporaryDirectory(prefix="t29-official-refusal-") as tmp:
        base = Path(tmp)
        store = T29PrivateStore(base / "private", repository_root=ROOT)
        with pytest.raises(Exception):
            evaluate_official(ROOT, base / "private", "any-token")
        assert not store.has("markers/evaluation.one-shot")
        assert not store.has("evaluation/ledger.json")


def test_inherited_candidate_runtime_frozen():
    report = verify_inherited_runtime(ROOT)
    assert report["status"] == "PASS"
    assert report["candidate_runtime_changes"] == 0
    assert report["pinned_candidate_commit"] == PINNED_CANDIDATE_COMMIT
    assert report["computed_runtime_root"] == PINNED_RUNTIME_ROOT


def test_verification_matrix_pass():
    from t29_protocol.qualification import run_verification_matrix
    assert run_verification_matrix()["status"] == "PASS"


def test_construction_readiness_items_frozen():
    from t29_protocol.evaluation import EVALUATION_STATES
    assert len(EVALUATION_READINESS_ITEMS) == 12
    assert "production_environment_pass" in EVALUATION_READINESS_ITEMS
    assert "model_hydration_pass" in EVALUATION_READINESS_ITEMS
    assert sorted(EVALUATION_STATES) == [
        "COMPLETE", "EXECUTED", "FAILED", "SCORED", "STARTED"]


# ------------------------------------------------------------------
# canonical freeze loader semantics (T29 freeze-path remediation)
# ------------------------------------------------------------------


def _synthetic_freeze_document(**overrides) -> dict:
    from t21_protocol.util import sha256_json
    entries = [
        {"path": f"t29_protocol/mod{i}.py", "sha256": f"{i:064d}",
         "byte_size": 900 + i, "role": "T29_PROTOCOL_RUNTIME"}
        for i in range(3)]
    root_input = {
        "schema_version": "t29-preconstruction-freeze-v1",
        "artifact": "T29_PRECONSTRUCTION_FREEZE",
        "classification": "PUBLIC_SAFE", "experiment": "t29",
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
    from t29_protocol.freeze import (EXCLUDED, FREEZE_LOADER_ID,
                                     SUPERSEDED_PRE_EXPOSURE_PATH,
                                     T29_PRECONSTRUCTION_FREEZE_PATH,
                                     load_preconstruction_freeze)
    assert T29_PRECONSTRUCTION_FREEZE_PATH == (
        "evaluations/t29/preconstruction_freeze.json")
    assert FREEZE_LOADER_ID == "t29_protocol.freeze:load_preconstruction_freeze"
    assert SUPERSEDED_PRE_EXPOSURE_PATH == (
        "evaluations/t29/preconstruction_freeze_superseded_pre_exposure.json")
    assert FORBIDDEN_ALIAS not in T29_PRECONSTRUCTION_FREEZE_PATH
    assert FORBIDDEN_ALIAS not in SUPERSEDED_PRE_EXPOSURE_PATH
    assert not any(FORBIDDEN_ALIAS in entry for entry in EXCLUDED)
    assert "t29_protocol.freeze:build_freeze:driver-provisional" in (
        __import__("t29_protocol.freeze", fromlist=["PROVISIONAL_FREEZE_BUILDER_ID"])
        .PROVISIONAL_FREEZE_BUILDER_ID)

    def loader_refusal(document, marker, *, write=True):
        with TemporaryDirectory(prefix="t29-loader-refusal-") as tmp:
            sparse = Path(tmp) / "repo"
            (sparse / "evaluations" / "t29").mkdir(parents=True)
            if write:
                (sparse / "evaluations" / "t29" /
                 "preconstruction_freeze.json").write_text(
                    json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
            with pytest.raises(ValueError) as raised:
                load_preconstruction_freeze(sparse)
            assert marker in str(raised.value), str(raised.value)
            assert not list((sparse / "evaluations" / "t29").glob("*_v1*"))

    loader_refusal(None, "absent", write=False)
    # a doc-internally coherent freeze survives the loader's internal
    # recomputation and is refused only by repository re-verification,
    # which is impossible inside the sparse temporary root
    loader_refusal(_synthetic_freeze_document(), "repository")
    # tampered freeze identity is refused by field name before any
    # repository access
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
    loader_refusal(_synthetic_freeze_document(real_construction_authorized=True),
                   "authorization state")
    loader_refusal(_synthetic_freeze_document(experiment="t28"),
                   "schema invalid")


def test_real_entrypoint_forbidden_scans_clean():
    scanned = list((ROOT / "t29_protocol").glob("*.py"))
    scanned.extend((ROOT / "scripts").glob("t29*.py"))
    scanned.extend((ROOT / "tests").glob("test_t29*.py"))
    assert scanned, "T29 production surface must not be empty"
    for path in scanned:
        with path.open(encoding="utf-8") as handle:
            assert FORBIDDEN_ALIAS not in handle.read(), path


def test_real_entrypoint_contract_and_gate_leaves():
    from t29_protocol.construction import (CONSTRUCTION_GATE_IDS,
                                           CONTRACT_LEAF_IDS)
    assert "protocol.canonical_freeze_path_exact" in CONTRACT_LEAF_IDS
    assert "protocol.real_entrypoint_freeze_reproduces" in CONTRACT_LEAF_IDS
    assert len(CONTRACT_LEAF_IDS) == 65
    assert "G53_REAL_ENTRYPOINT_CANONICAL_FREEZE_PATH" in CONSTRUCTION_GATE_IDS
    assert "G54_REAL_ENTRYPOINT_FREEZE_REPRODUCTION" in CONSTRUCTION_GATE_IDS
    assert len(CONSTRUCTION_GATE_IDS) == 56


def test_dual_sealed_overlap_oracle_rehearsal_binding():
    from t29_protocol.construction import (fingerprint_root, fingerprint_sets,
                                           synthetic_private_bundle)
    from t29_protocol.oracle import (PREDECESSORS,
                                     disposable_real_mode_oracle_result,
                                     verify_oracle_result)
    from t29_protocol.construction import COMMITMENT_FIELDS
    cases, gold, _fixtures = synthetic_private_bundle(13, with_fixture=True)
    prospective = fingerprint_sets(cases, gold)
    root = fingerprint_root(prospective)
    for predecessor in ("t27", "t28"):
        result = disposable_real_mode_oracle_result(
            predecessor=predecessor, root=ROOT, prospective_root=root,
            prospective=prospective, variant=7)
        bindings = {key: result[key] for key in (
            f"{predecessor}_store_identity", f"{predecessor}_namespace",
            *COMMITMENT_FIELDS[predecessor],
            f"{predecessor}_construction_state",
            f"{predecessor}_construction_attempt",
            f"{predecessor}_official_evaluation_state",
            f"{predecessor}_official_evaluation_attempt",
            f"{predecessor}_official_evaluation_eligibility",
            f"{predecessor}_candidate_commit",
            f"{predecessor}_candidate_runtime_root")}
        verdict = verify_oracle_result(
            result, predecessor=predecessor, mode="REAL_REHEARSAL",
            root=ROOT, expected_t29_root=root,
            expected_predecessor_bindings=bindings)
        assert verdict["status"] == "PASS", verdict
        assert verdict["overall_prohibited_overlap"] == 0
        assert result["outside_boundary_private_rows_exposed"] == 0
        assert verdict[f"{predecessor}_store_authenticated"] is True
        assert verdict[f"{predecessor}_commitments_exact"] is True
        assert result[f"{predecessor}_construction_state"] == "SEALED"
        # tampering the one-shot attempt count is refused by the absence
        # bindings before any store access
        with pytest.raises(ValueError):
            verify_oracle_result(
                dict(result, **{f"{predecessor}_construction_attempt": 2}),
                predecessor=predecessor, mode="REAL_REHEARSAL", root=ROOT,
                expected_t29_root=root,
                expected_predecessor_bindings=bindings)


def test_superseded_record_and_excluded_surface():
    from t29_protocol.freeze import EXCLUDED, SUPERSEDED_PRE_EXPOSURE_PATH
    assert "evaluations/t29/preconstruction_freeze.json" in EXCLUDED
    assert "evaluations/t29/protocol_doctor_report.json" in EXCLUDED
    assert SUPERSEDED_PRE_EXPOSURE_PATH.rsplit("/", 1)[-1] == (
        "preconstruction_freeze_superseded_pre_exposure.json")
    assert not any("v1" in entry for entry in EXCLUDED)