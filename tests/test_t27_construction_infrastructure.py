"""T27 construction/evaluation infrastructure without real exposure."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from t27_protocol.construction import (
    CONTRACT_LEAF_IDS, CONSTRUCTION_GATE_IDS, ConstructionLedgerError,
    T27ConstructionLedger, _fixed_clock_factory, author_provenance,
    construction_contract, fingerprint_sets, require_static_design,
    fingerprint_root, run_publication_leak_gate, synthetic_oracle_result,
    synthetic_private_bundle, verify_event_chain,
)
from t27_protocol.contract import CONSTRUCTION_TOKEN, EVALUATION_TOKEN
from t27_protocol.evaluation import EVALUATION_STATES, runner_identity
from t27_protocol.freeze import verify_freeze_v3
from t27_protocol.oracle import verify_oracle_result
from t27_protocol.store import T27PrivateStore, storage_policy_successor

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "evaluations" / "t27"


def read(name: str) -> dict:
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def minimal_bindings() -> dict:
    return {
        "experiment": "t27", "attempt": 1, "mode": "REAL_BLIND",
        "authorization_token": CONSTRUCTION_TOKEN, "store_id": "T27-STORE-01",
        "namespace": "t27", "execution_commit": "1" * 40,
        "execution_tree": "2" * 40, "candidate_commit": "3" * 40,
        "candidate_tree": "4" * 40, "runtime_root": "5" * 64,
        "preconstruction_freeze_sha256": "6" * 64, "component_count": 1,
        "component_root": "7" * 64, "freeze_root": "8" * 64,
        "terminal_contract_sha256": "9" * 64, "metric_registry_sha256": "a" * 64,
        "nonvacuity_policy_sha256": "b" * 64, "authority_graph_sha256": "c" * 64,
        "production_graph_sha256": "d" * 64, "storage_policy_sha256": "e" * 64,
        "historical_exclusion_policy_sha256": "f" * 64,
        "t26_historical_failure_anchor_sha256": "0" * 64,
        "public_historical_index_root": "1" * 64,
        "t26_overlap_oracle_result_sha256": "2" * 64,
        "combined_historical_exclusion_root": "3" * 64,
        "construction_timestamp": "2026-09-27T00:00:00+00:00",
        "state": "LEDGER_CREATED",
    }


def test_exclusive_construction_ledger_spends_once_and_hash_chains():
    with TemporaryDirectory(prefix="t27-ledger-test-") as tmp:
        store = T27PrivateStore(Path(tmp) / "private", repository_root=ROOT,
                                disposable=True)
        ledger = T27ConstructionLedger.create_exclusive(
            store, minimal_bindings(), CONSTRUCTION_TOKEN,
            clock=_fixed_clock_factory(1))
        assert verify_event_chain(ledger.document)
        assert store.has("markers/construction.one-shot")
        with pytest.raises(ConstructionLedgerError):
            T27ConstructionLedger.create_exclusive(
                store, minimal_bindings(), CONSTRUCTION_TOKEN)


def test_deleted_or_recreated_ledger_and_deleted_marker_are_detected():
    with TemporaryDirectory(prefix="t27-ledger-recreation-test-") as tmp:
        store = T27PrivateStore(Path(tmp) / "private", repository_root=ROOT,
                                disposable=True)
        ledger = T27ConstructionLedger.create_exclusive(
            store, minimal_bindings(), CONSTRUCTION_TOKEN,
            clock=_fixed_clock_factory(2))
        genesis = copy.deepcopy(ledger.document)
        ledger.advance("MATERIALIZED", {"synthetic": True},
                       clock=_fixed_clock_factory(3))
        store.path("construction/ledger.json").write_text(
            json.dumps(genesis, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(ConstructionLedgerError, match="integrity"):
            T27ConstructionLedger.load(store)
        store.path("markers/construction.one-shot").unlink()
        with pytest.raises(ConstructionLedgerError, match="deleted"):
            T27ConstructionLedger.load(store)


def test_static_design_oracle_and_fixture_optionality_are_nonvacuous():
    cases, gold, fixtures = synthetic_private_bundle(5)
    oracle = synthetic_oracle_result(cases, gold, variant=5)
    assert verify_oracle_result(
        oracle, mode="SYNTHETIC",
        expected_t27_root=fingerprint_root(fingerprint_sets(cases, gold)),
    )["status"] == "PASS"
    provenance = author_provenance(
        "TEST-DISPOSABLE", "1" * 64, "2026-09-27T00:00:00+00:00")
    audit = require_static_design(cases, gold, fixtures, oracle, provenance)
    assert audit["status"] == "PASS"
    assert audit["scenario_count"] == audit["gold_count"] == 512
    assert audit["minimum_steps"] >= 3 and audit["maximum_steps"] <= 12
    assert set(fingerprint_sets(cases, gold)) == {
        "case_ids", "entity_identities", "source_ids", "chunk_ids",
        "exact_queries", "exact_answers", "exact_source_text",
        "verbatim_attack_wording", "relations"}


def test_public_reports_cover_contract_gate_rehearsals_and_failures():
    contract = read("construction_contract.json")
    construction = read("construction_rehearsal_report.json")
    evaluation = read("evaluation_rehearsal_report.json")
    failures = read("failure_rehearsal_report.json")
    negative = read("construction_negative_controls.json")
    assert contract["leaf_count"] == len(CONTRACT_LEAF_IDS)
    assert construction_contract()["leaf_ids"] == list(CONTRACT_LEAF_IDS)
    assert construction["status"] == evaluation["status"] == "PASS"
    assert len(CONTRACT_LEAF_IDS) == 51
    assert len(CONSTRUCTION_GATE_IDS) == 41
    assert construction["semantic_equivalence"] is True
    assert evaluation["semantic_equivalence"] is True
    assert all(run["gate_check_count"] == len(CONSTRUCTION_GATE_IDS)
               for run in construction["runs"])
    assert failures["status"] == "PASS"
    assert failures["construction"]["retry_refused"] is True
    assert failures["evaluation"]["retry_refused"] is True
    assert negative["status"] == "PASS"


def test_evaluation_identity_scorer_and_freeze_are_frozen():
    assert EVALUATION_STATES == ("STARTED", "EXECUTED", "SCORED", "COMPLETE", "FAILED")
    assert read("official_runner_identity.json") == runner_identity(ROOT)
    for run in read("evaluation_rehearsal_report.json")["runs"]:
        assert run["denominators_nonzero"] is True
        assert run["all_public_qualification_floors_pass"] is True
        assert run["critical_counters_zero"] is True
        assert run["gold_firewall"] == "PASS"
    assert read("preconstruction_freeze_v2.json")["freeze_sha256"] == (
        "163cf013d2c2c5fec20b00824600b3eae09040644bbc8de4ad245dbdd13948b9")
    assert verify_freeze_v3(ROOT, read("preconstruction_freeze_v3.json"))["status"] == "PASS"


def test_storage_policy_leak_gate_and_real_exposure_remain_safe():
    assert read("construction_ready_storage_policy.json") == storage_policy_successor()
    scan = run_publication_leak_gate(ROOT)
    assert scan["status"] == "PASS"
    assert scan["blind_blob_count"] == scan["forbidden_path_count"] == 0
    exposure = read("real_exposure_v3.json")
    assert all(exposure[key] == 0 for key in (
        "t27_real_blind_rows", "t27_real_gold", "construction_attempts",
        "evaluation_attempts", "candidate_real_executions",
        "official_real_evaluator_invocations",
        "t26_private_rows_exposed_outside_sealed_oracle",
        "t26_candidate_reruns"))
    assert CONSTRUCTION_TOKEN == "T27_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
    assert EVALUATION_TOKEN == "T27_ONE_SHOT_OFFICIAL_EVALUATION"
    unrestricted = read("unrestricted_test_report.json")
    assert unrestricted["new_live_failures"] == 0
    assert unrestricted["new_unknown_failures"] == 0
    assert unrestricted["unexplained_skips"] == 0
    assert unrestricted["xfails"] == 0
    assert unrestricted["deselections"] == 0
