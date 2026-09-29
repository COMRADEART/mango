"""Deterministic T30 preconstruction invariants (no staged artifacts required)."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from sciencemath.executive.skills import SKILL_IDS
from t30_protocol.contract import (
    CONSTRUCTION_TOKEN, CRITICAL_COUNTERS, EVALUATION_TOKEN, FAMILIES, FLOORS,
    NONVACUITY_MINIMUMS, REPLAN_TRIGGERS,
    T27_CONSTRUCTION_ATTEMPT, T27_CONSTRUCTION_STATE,
    T27_OFFICIAL_EVALUATION_ATTEMPT, T27_OFFICIAL_EVALUATION_ELIGIBILITY,
    T27_OFFICIAL_EVALUATION_STATE, T27_PREDECESSOR_VERDICT,
    T28_CONSTRUCTION_ATTEMPT, T28_CONSTRUCTION_STATE,
    T28_OFFICIAL_EVALUATION_ATTEMPT, T28_OFFICIAL_EVALUATION_ELIGIBILITY,
    T28_OFFICIAL_EVALUATION_STATE, T28_PREDECESSOR_VERDICT,
    design, execution_contract, production_graph)
from t30_protocol.evaluation import (EVALUATION_READINESS_ITEMS,
                                     EvaluationLedgerError, T30EvaluationLedger,
                                     evaluate_official,
                                     run_evaluation_absence_preflight,
                                     run_sealed_store_preflight)
from t30_protocol.exclusion import (DIMENSIONS, GENERATED_PUBLIC_POLICY_SCHEMA,
                                    GENERATED_PUBLIC_STRUCTURAL_DIMENSIONS,
                                    build_synthetic_historical_index,
                                    generated_public_dimension_policy,
                                    validate_generated_public_dimension_policy,
                                    verify_historical_index)
from t30_protocol.freeze import (PINNED_CANDIDATE_COMMIT, PINNED_CANDIDATE_TREE,
                                 PINNED_RUNTIME_ROOT, verify_inherited_runtime)
from t30_protocol.qualification import build_public_cases
from t30_protocol.scorer import ZERO_DENOMINATOR_POLICY, score_suite
from t30_protocol.store import T30PrivateStore

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_ALIAS = "evaluations/t30/preconstruction_freeze_" + "v" + "1" + ".json"


def test_frozen_contract_constants():
    assert CONSTRUCTION_TOKEN == (
        "T30_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION")
    assert EVALUATION_TOKEN == "T30_ONE_SHOT_OFFICIAL_EVALUATION"
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
    # Frozen predecessor states (T30 authorization §4/§10/§41): both T27 and
    # T28 are SEALED / UNSPENT_BUT_PERMANENTLY_INELIGIBLE; their tokens are
    # never reused by T30.
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
    from t30_protocol.contract import T29_PREDECESSOR_VERDICT
    assert data["successor_of"] == T29_PREDECESSOR_VERDICT
    assert data["predecessor_states"]["t27"] == T27_PREDECESSOR_VERDICT
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
        "t30_protocol.official_environment:"
        "build_official_evaluation_environment")
    assert graph["nodes"]["official_runner"]["producer"] == (
        "t30_protocol.official_environment:T30OfficialRunnerFactory")
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
    from t30_protocol.evaluation import run_evaluation_rehearsals
    source = inspect.getsource(run_evaluation_rehearsals)
    assert "evaluate_official(" in source
    assert "_evaluate_once(" not in source
    assert "score_suite(" not in source


def test_construct_real_wrapper_source_binding():
    from t30_protocol.freeze import FREEZE_LOADER_ID
    from t30_protocol.construction import run_real_entrypoint_rehearsal
    source = inspect.getsource(run_real_entrypoint_rehearsal)
    assert "construct_real(" in source
    assert "construct_once(" not in source
    with (ROOT / "t30_protocol" / "construction.py").open(
            encoding="utf-8") as handle:
        construction_source = handle.read()
    assert "freeze = load_preconstruction_freeze(root)" in construction_source
    assert "construct_real" in construction_source
    assert "construct_once" in construction_source
    with (ROOT / "t30_protocol" / "freeze.py").open(
            encoding="utf-8") as handle:
        assert FREEZE_LOADER_ID in handle.read()


def test_scorer_fail_nonvacuity():
    from t30_protocol.scorer import score_suite
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
    if not (ROOT / "evaluations/t30/qualification_report.json").is_file():
        pytest.skip("qualification report staged later by the driver")
    from t30_protocol.exclusion import build_authenticated_public_historical_index
    index = build_authenticated_public_historical_index(ROOT)
    assert verify_historical_index(index, root=ROOT, mode="REAL") is not None


def test_store_guard_and_disposable_materialization():
    from t30_protocol.construction import materialize_private
    with TemporaryDirectory(prefix="t30-guard-test-") as tmp:
        base = Path(tmp)
        real_store = T30PrivateStore(base / "private", repository_root=ROOT)
        with pytest.raises(Exception):
            real_store.read_json("blind/inputs.json")
        disposable = T30PrivateStore(base / "disposable",
                                     repository_root=ROOT, disposable=True)
        fixture = {"logical_id": "fx-0", "content": b"\x00\x01",
                   "schema_type": "T30_FIXTURE_V1"}
        descriptors = materialize_private(
            disposable, [{"a": 1}], [{"b": 2}], [fixture],
            {"status": "PASS"}, {"author_id": "SYNTHETIC"},
            {"status": "PASS"}, {"status": "PASS"}, {"entries": []})
        assert descriptors
        assert disposable.path("blind/inputs.json").is_file()
        assert disposable.path("blind/gold.json").is_file()
        assert disposable.path("control/recovery_control.json").is_file()
        with pytest.raises(Exception):
            disposable.read_json("blind/gold.json")
        with pytest.raises(Exception):
            disposable.read_bytes("control/recovery_control.json")


def test_evaluation_ledger_token_refused_and_absence_preflight():
    with TemporaryDirectory(prefix="t30-ledger-test-") as tmp:
        store = T30PrivateStore(Path(tmp) / "private", repository_root=ROOT,
                                disposable=True)
        with pytest.raises(EvaluationLedgerError):
            T30EvaluationLedger.create_exclusive(store, {}, "wrong-token")
        assert not store.has("markers/evaluation.one-shot")
        empty = run_evaluation_absence_preflight(store)
        assert empty["status"] == "PASS" and empty["attempts"] == 0


def test_sealed_store_preflight_refuses_unsealed():
    with TemporaryDirectory(prefix="t30-sealed-preflight-") as tmp:
        store = T30PrivateStore(Path(tmp) / "private", repository_root=ROOT)
        with pytest.raises(ValueError):
            run_sealed_store_preflight(store)


def test_official_evaluator_refuses_unsealed_store_no_marker():
    with TemporaryDirectory(prefix="t30-official-refusal-") as tmp:
        base = Path(tmp)
        store = T30PrivateStore(base / "private", repository_root=ROOT)
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
    from t30_protocol.qualification import run_verification_matrix
    assert run_verification_matrix()["status"] == "PASS"


def test_construction_readiness_items_frozen():
    from t30_protocol.evaluation import EVALUATION_STATES
    from t30_protocol.evaluation import T30_RECOVERY_CONTRACT_LEAVES
    assert len(EVALUATION_READINESS_ITEMS) == 12 + 7
    assert "production_stack_recovery_32_pass" in EVALUATION_READINESS_ITEMS
    assert "control_read_postledger" in EVALUATION_READINESS_ITEMS
    assert len(T30_RECOVERY_CONTRACT_LEAVES) == 16
    assert "production_environment_pass" in EVALUATION_READINESS_ITEMS
    assert "model_hydration_pass" in EVALUATION_READINESS_ITEMS
    assert sorted(EVALUATION_STATES) == [
        "COMPLETE", "EXECUTED", "FAILED", "SCORED", "STARTED"]


# ------------------------------------------------------------------
# canonical freeze loader semantics (T30 freeze-path remediation)
# ------------------------------------------------------------------


def _synthetic_freeze_document(**overrides) -> dict:
    from t21_protocol.util import sha256_json
    entries = [
        {"path": f"t30_protocol/mod{i}.py", "sha256": f"{i:064d}",
         "byte_size": 900 + i, "role": "T30_PROTOCOL_RUNTIME"}
        for i in range(3)]
    root_input = {
        "schema_version": "t30-preconstruction-freeze-v1",
        "artifact": "T30_PRECONSTRUCTION_FREEZE",
        "classification": "PUBLIC_SAFE", "experiment": "t30",
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
    from t30_protocol.freeze import (EXCLUDED, FREEZE_LOADER_ID,
                                     T29_PREDECESSOR_STATUS_PATH,
                                     T30_PRECONSTRUCTION_FREEZE_PATH,
                                     load_preconstruction_freeze)
    assert T30_PRECONSTRUCTION_FREEZE_PATH == (
        "evaluations/t30/preconstruction_freeze.json")
    assert FREEZE_LOADER_ID == "t30_protocol.freeze:load_preconstruction_freeze"
    assert T29_PREDECESSOR_STATUS_PATH == (
        "evaluations/t30/t29_predecessor_status.json")
    assert FORBIDDEN_ALIAS not in T30_PRECONSTRUCTION_FREEZE_PATH
    assert FORBIDDEN_ALIAS not in T29_PREDECESSOR_STATUS_PATH
    assert not any(FORBIDDEN_ALIAS in entry for entry in EXCLUDED)
    assert "t30_protocol.freeze:build_freeze:driver-provisional" in (
        __import__("t30_protocol.freeze", fromlist=["PROVISIONAL_FREEZE_BUILDER_ID"])
        .PROVISIONAL_FREEZE_BUILDER_ID)

    def loader_refusal(document, marker, *, write=True):
        with TemporaryDirectory(prefix="t30-loader-refusal-") as tmp:
            sparse = Path(tmp) / "repo"
            (sparse / "evaluations" / "t30").mkdir(parents=True)
            if write:
                (sparse / "evaluations" / "t30" /
                 "preconstruction_freeze.json").write_text(
                    json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
            with pytest.raises(ValueError) as raised:
                load_preconstruction_freeze(sparse)
            assert marker in str(raised.value), str(raised.value)
            assert not list((sparse / "evaluations" / "t30").glob("*_v1*"))

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
    scanned = list((ROOT / "t30_protocol").glob("*.py"))
    scanned.extend((ROOT / "scripts").glob("t30*.py"))
    scanned.extend((ROOT / "tests").glob("test_t30*.py"))
    assert scanned, "T30 production surface must not be empty"
    for path in scanned:
        with path.open(encoding="utf-8") as handle:
            assert FORBIDDEN_ALIAS not in handle.read(), path


def test_real_entrypoint_contract_and_gate_leaves():
    from t30_protocol.construction import (CONSTRUCTION_GATE_IDS,
                                           CONTRACT_LEAF_IDS)
    assert "protocol.canonical_freeze_path_exact" in CONTRACT_LEAF_IDS
    assert "protocol.real_entrypoint_freeze_reproduces" in CONTRACT_LEAF_IDS
    assert len(CONTRACT_LEAF_IDS) == 69 + 9
    assert "recovery.control_gold_designation_derived" in CONTRACT_LEAF_IDS
    assert "exclusion.t29_abandoned_package_excluded" in CONTRACT_LEAF_IDS
    assert "oracle.live_authentication_bound" in CONTRACT_LEAF_IDS
    assert "G53_REAL_ENTRYPOINT_CANONICAL_FREEZE_PATH" in CONSTRUCTION_GATE_IDS
    assert "G54_REAL_ENTRYPOINT_FREEZE_REPRODUCTION" in CONSTRUCTION_GATE_IDS
    assert len(CONSTRUCTION_GATE_IDS) == 63 + 6
    assert "G63_RECOVERY_SCHEDULE_GOLD_CAUSAL_ORDER" in CONSTRUCTION_GATE_IDS
    assert "G64_ADAPTER_IMPLEMENTATION_IDENTITY_EXACT" in CONSTRUCTION_GATE_IDS
    assert "G56_ACTUAL_T28_JOURNAL_POSITIVE_CONTROL" in CONSTRUCTION_GATE_IDS
    assert "G57_DISPOSABLE_T28_JOURNAL_EQUIVALENCE" in CONSTRUCTION_GATE_IDS


def test_dual_sealed_overlap_oracle_rehearsal_binding():
    from t30_protocol.construction import (fingerprint_root, fingerprint_sets,
                                           synthetic_private_bundle)
    from t30_protocol.oracle import (PREDECESSORS,
                                     disposable_real_mode_oracle_result,
                                     verify_oracle_result)
    from t30_protocol.construction import COMMITMENT_FIELDS
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
            root=ROOT, expected_t30_root=root,
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
                expected_t30_root=root,
                expected_predecessor_bindings=bindings)


def test_t29_status_record_and_excluded_surface():
    from t30_protocol.freeze import EXCLUDED, T29_PREDECESSOR_STATUS_PATH
    assert "evaluations/t30/preconstruction_freeze.json" in EXCLUDED
    assert "evaluations/t30/protocol_doctor_report.json" in EXCLUDED
    assert T29_PREDECESSOR_STATUS_PATH not in EXCLUDED
    assert not any("v1" in entry for entry in EXCLUDED)

# ---------------------------------------------------------------------------
# T30 successor tests (§14–§33): journal schema, stand-in, abandoned package.
# ---------------------------------------------------------------------------


def _lifecycle_journal(tmp_path, variant=0):
    # The frozen T28 store refuses any location inside the repository, and
    # pyproject pins pytest's basetemp repo-locally; use the system temp.
    import tempfile
    from t30_protocol.oracle import (disposable_t28_sealed_store,
                                     read_t28_access_journal)
    base = Path(tempfile.mkdtemp(prefix=f"t30-test-t28-{variant}-"))
    store_root, expected = disposable_t28_sealed_store(
        base, variant=variant, public_repo=ROOT)
    records, _ = read_t28_access_journal(store_root)
    return store_root, expected, records


def test_t30_journal_validator_accepts_frozen_lifecycle_journal(tmp_path):
    from t30_protocol.oracle import (T28_REPLACE_LEDGER_STATE_SEQUENCE,
                                     _scan_t28_access_journal)
    _store, _expected, records = _lifecycle_journal(tmp_path)
    counters = _scan_t28_access_journal(records)
    assert counters["replace_ledger_state_sequence"] == list(
        T28_REPLACE_LEDGER_STATE_SEQUENCE)
    assert counters["journal_evaluation_surface_operations"] == 0
    assert any(record["op"] == "replace_ledger" and "state" in record
               for record in records)


def test_t29_frozen_validator_rejects_the_same_journal(tmp_path):
    from t29_protocol.oracle import _scan_t28_access_journal as frozen_scan
    _store, _expected, records = _lifecycle_journal(tmp_path)
    with pytest.raises(ValueError, match="malformed"):
        frozen_scan(records)


def test_t30_journal_schemas_are_operation_specific():
    from t30_protocol.oracle import (T28_JOURNAL_BASE_FIELDS,
                                     T28_JOURNAL_OPERATION_SCHEMAS)
    assert T28_JOURNAL_OPERATION_SCHEMAS["replace_ledger"] == (
        T28_JOURNAL_BASE_FIELDS | {"state"})
    assert T28_JOURNAL_OPERATION_SCHEMAS["has"] == (
        T28_JOURNAL_BASE_FIELDS | {"exists"})
    for op, schema in T28_JOURNAL_OPERATION_SCHEMAS.items():
        if op != "replace_ledger":
            assert "state" not in schema


def test_t30_journal_negative_controls_all_refuse(tmp_path):
    from t30_protocol.oracle import (T28_JOURNAL_NEGATIVE_CONTROL_IDS,
                                     run_t28_journal_negative_controls)
    _store, _expected, records = _lifecycle_journal(tmp_path)
    report = run_t28_journal_negative_controls(records)
    assert report["status"] == "PASS"
    assert set(report["controls"]) == set(T28_JOURNAL_NEGATIVE_CONTROL_IDS)
    assert all(item["refused"] for item in report["controls"].values())


def test_lifecycle_standin_authenticates_and_is_self_equivalent(tmp_path):
    from t30_protocol.oracle import (authenticate_official_t28_store_for_t30,
                                     t28_journal_schema_equivalence)
    store, expected, records = _lifecycle_journal(tmp_path, 0)
    _other, _other_expected, other = _lifecycle_journal(tmp_path, 1)
    report, _ = authenticate_official_t28_store_for_t30(
        ROOT, store, expected=expected)
    assert report["status"] == "PASS"
    assert report["official_commitment_scope"] == "DISPOSABLE_STANDIN"
    assert t28_journal_schema_equivalence(records, other)["SCHEMA_EQUIVALENT"]


def _prospective(tag="t30-test"):
    from t21_protocol.util import sha256_json
    from t30_protocol.exclusion import DIMENSIONS
    sets = {name: [sha256_json((tag, name))] for name in DIMENSIONS}
    return sets, sha256_json({name: sorted(v) for name, v in sets.items()})


def test_abandonment_oracle_never_opens_row_files(tmp_path):
    from t30_protocol.abandonment import (
        disposable_t29_abandoned_package,
        run_sealed_t29_abandoned_to_t30_overlap_oracle,
        verify_abandonment_oracle_result)
    package, commitment = disposable_t29_abandoned_package(tmp_path)
    sets, root = _prospective()
    result = run_sealed_t29_abandoned_to_t30_overlap_oracle(
        root=ROOT, package_dir=package, prospective_root=root,
        prospective=sets, commitment=commitment)
    verified = verify_abandonment_oracle_result(
        result, mode="REAL_REHEARSAL", expected_t30_root=root,
        expected_commitment_root=commitment["commitment_root"])
    assert verified["status"] == "PASS" and result["t29_row_files_opened"] == 0
    # structural dimensions are exempt on the historical side
    assert result["dimensions"]["entity_identities"]["historical_population"] == 0
    assert result["t29_structural_exempt_populations"]["entity_identities"] == 3


def test_abandonment_oracle_refuses_overlap_and_tampering(tmp_path):
    import json as _json
    from t30_protocol.abandonment import (
        disposable_t29_abandoned_package,
        run_sealed_t29_abandoned_to_t30_overlap_oracle,
        verify_abandonment_oracle_result)
    from t21_protocol.util import sha256_json
    package, commitment = disposable_t29_abandoned_package(tmp_path)
    historical = _json.loads((package / "fingerprints.json").read_text())
    sets, _ = _prospective()
    sets["case_ids"] = [historical["case_ids"][0]]
    root = sha256_json({name: sorted(v) for name, v in sets.items()})
    result = run_sealed_t29_abandoned_to_t30_overlap_oracle(
        root=ROOT, package_dir=package, prospective_root=root,
        prospective=sets, commitment=commitment)
    assert result["overall_prohibited_overlap"] == 1
    with pytest.raises(ValueError, match="nonzero"):
        verify_abandonment_oracle_result(result, mode="REAL_REHEARSAL")
    tampered = dict(commitment, prospective_fingerprint_root="0" * 64)
    with pytest.raises(ValueError):
        run_sealed_t29_abandoned_to_t30_overlap_oracle(
            root=ROOT, package_dir=package, prospective_root=root,
            prospective=sets, commitment=tampered)


def test_t29_abandonment_commitment_is_public_roots_only():
    from t30_protocol.abandonment import (COMMITMENT_FIELDS,
                                          t29_abandonment_commitment)
    commitment = t29_abandonment_commitment(ROOT)
    assert commitment["prospective_fingerprint_root"].startswith("8d4ade57")
    assert commitment["reuse_permitted"] is False
    assert commitment["row_data_included"] is False
    assert all(name in commitment for name in COMMITMENT_FIELDS)


def test_construct_real_scope_rules_refuse_before_any_store(tmp_path):
    from t30_protocol.construction import construct_real
    from t30_protocol.contract import CONSTRUCTION_TOKEN
    for mode, kwargs, marker in (
            ("REAL", {"t28_expected": {}}, "caller expectations"),
            ("REAL_REHEARSAL", {"t28_expected": {}, "t29_commitment": None},
             "binding scope mismatch")):
        with pytest.raises(ValueError, match=marker):
            construct_real(
                root=ROOT, private_store_root=tmp_path / "private",
                cases=[], gold=[], fixtures=[], oracle_result={},
                provenance={}, token=CONSTRUCTION_TOKEN, t27_store=None,
                t28_store_root=tmp_path / "T28-STORE-01",
                t29_abandoned_package=tmp_path / "pkg",
                t27_expected={} if mode == "REAL_REHEARSAL" else None,
                oracle_mode=mode, **kwargs)
        assert not (tmp_path / "private").exists()
