"""T23 productionization contracts without touching real blind paths."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from sciencemath.executive.router_v2 import route_request
from sciencemath.web.fixture_provider import FixtureCorpus, FixtureSearchProvider
from t21_protocol.contract import load_contract
from t21_protocol.errors import AuthorizationError, ContractError, LedgerError
from t21_protocol.ledger import ConstructionLedger
from t21_protocol.util import read_json
from t23_protocol.author import GOLD_ONLY, author_cases, fingerprint_root, load_spec, shadow_labels
from t23_protocol.construction import run_real_construction, run_shadow_construction, verify_seal
from t23_protocol.context import (
    CONSTRUCTION_TOKENS, EVALUATION_TOKENS, load_experiment_contract,
    require_construction_authorization,
)
from t23_protocol.contract import PATHS, load_t23_contract, validate_t23_contract
from t23_protocol.graph import load_graph, validate_graph
from t23_protocol.lock import verify_lock
from t23_protocol.provider import ProductionDispatchError, ProductionRouterProvider, decision_parity
from t23_protocol.evaluation import run_real_evaluation
from t23_protocol.scorer import REGISTRY, score_router, validate_registry

ROOT = Path(__file__).resolve().parents[1]
T23 = ROOT / "evaluations" / "t23"


def test_additive_registry_preserves_frozen_experiments() -> None:
    assert set(CONSTRUCTION_TOKENS) == {"t21r15", "t21r16", "t21r17", "t22", "t23"}
    assert set(EVALUATION_TOKENS) == set(CONSTRUCTION_TOKENS)
    assert load_experiment_contract(T23 / "t23_master_contract.json", experiment="t23").experiment == "t23"
    assert load_experiment_contract(ROOT / "evaluations/t22/t21_master_contract.json", experiment="t22").experiment == "t22"
    assert load_experiment_contract(ROOT / "evaluations/t21r15/t21_master_contract.json", experiment="t21r15").experiment == "t21r15"
    assert load_contract(ROOT / "evaluations/t22/t21_master_contract.json").experiment == "t22"
    with pytest.raises(AuthorizationError):
        load_experiment_contract(T23 / "t23_master_contract.json", experiment="t24")
    with pytest.raises(AuthorizationError):
        require_construction_authorization("invalid", experiment="t23")


def test_t23_contract_paths_are_closed_and_distinct() -> None:
    contract = load_t23_contract(T23 / "t23_master_contract.json")
    assert validate_t23_contract(contract.document)["status"] == "PASS"
    assert contract.get("construction_authorized") is False
    assert set(contract.get("real_t23_paths")) == set(PATHS.values())
    assert all("t22" not in path for path in PATHS.values())
    broken = json.loads(json.dumps(contract.document))
    broken["values"]["artifacts"]["corpus"] = "rag/gk_holdout_t22"
    with pytest.raises(ContractError):
        validate_t23_contract(broken)


def test_author_determinism_and_no_gold_visibility() -> None:
    spec = load_spec()
    first = author_cases(shadow_labels(), namespace="t23-shadow", attachment_path="documents/shadow.txt")
    second = author_cases(shadow_labels(), namespace="t23-shadow", attachment_path="documents/shadow.txt")
    assert first == second
    assert fingerprint_root(spec) == verify_lock()["author_fingerprint_root"]
    assert len(first[0]) == len(first[1]) == 1280
    assert all(not set(row["candidate_input"]) & GOLD_ONLY for row in first[0])
    assert all(route_request(inp["candidate_input"])["route_id"] == gold["expected_route"]
               for inp, gold in zip(*first))
    with pytest.raises(ValueError, match="attachment"):
        author_cases(shadow_labels(), namespace="t23-shadow")


def test_graph_lock_and_router_metric_registry() -> None:
    assert verify_lock()["missing_bindings"] == 0
    graph = validate_graph(load_graph())
    assert graph["status"] == "PASS"
    assert not graph["missing_producers"] and not graph["dangling_inputs"]
    assert not graph["stub_production_nodes"]
    registry = read_json(REGISTRY)
    validate_registry(registry)
    assert len(registry["metrics"]) == 15
    assert registry["generic_fallback_consumers"] == 0
    inputs, gold = author_cases(shadow_labels(), namespace="t23-shadow", attachment_path="documents/shadow.txt")
    rows = [{"candidate_input": i["candidate_input"], "gold": g,
             "decision": route_request(i["candidate_input"]),
             "repeat_decision": route_request(i["candidate_input"])}
            for i, g in zip(inputs, gold)]
    score = score_router(rows, registry)
    assert score["status"] == "PASS"
    assert len(score["metrics"]) == 15


def test_shadow_ledger_seal_and_exclusive_second_create() -> None:
    with TemporaryDirectory(prefix="t23-test-shadow-") as directory:
        root = Path(directory)
        result = run_shadow_construction(ROOT, root)
        assert result["terminal_state"] == "SEALED"
        assert result["audits"]["gold_leakage"] == 0
        assert result["audits"]["referential_failures"] == 0
        assert result["seal"]["status"] == "PASS"
        assert verify_seal(root)["status"] == "PASS"
        ledger = root / "evaluations/t23/construction_run_ledger.json"
        assert read_json(ledger)["state"] == "COMPLETE"
        with pytest.raises(LedgerError):
            ConstructionLedger.create_exclusive(ledger, "t23")
        marker = read_json(root / "evaluations/t23/HOLDOUT_FROZEN")
        manifest = read_json(root / "evaluations/t23/holdout_manifest.json")
        assert marker["schema_version"] == "t23-holdout-frozen-v1"
        assert manifest["schema_version"] == "t23-holdout-manifest-v1"
        assert marker["construction_authorized"] is False


def test_provider_initialization_parity_and_gold_rejection() -> None:
    web = FixtureSearchProvider(FixtureCorpus([], query_time="2026-09-22"))
    provider = ProductionRouterProvider(ROOT / "rag/gk_corpus", web_provider=web,
                                        workspace_mode="SYNTHETIC_DISPOSABLE")
    assert provider.rows_executed == 0
    inputs, _ = author_cases(shadow_labels(), namespace="t23-shadow", attachment_path="documents/shadow.txt")
    sample = [row for row in inputs if row["case_id"].startswith("t23-shadow-insufficient_evidence")][:4]
    outputs = provider.generate(sample)
    assert decision_parity(sample, outputs) == {
        "rows": 4, "mismatches": {"route_id": 0, "reason_code": 0, "selected_capability": 0},
        "status": "PASS",
    }
    with pytest.raises(ProductionDispatchError, match="gold"):
        provider.generate([{**sample[0], "expected_route": "INSUFFICIENT_EVIDENCE"}])
    with pytest.raises(ProductionDispatchError, match="gold"):
        provider.generate([{"case_id": "bad", "candidate_input": {"query": "x", "expected_route": "ANSWER_LOCAL"}}])
    with pytest.raises(ProductionDispatchError, match="live"):
        ProductionRouterProvider(ROOT / "rag/gk_corpus", web_provider=web)


def test_real_t23_paths_remain_absent() -> None:
    assert not any((ROOT / relative).exists() for relative in PATHS.values())
    with pytest.raises(AuthorizationError):
        run_real_construction(ROOT, "not-authorized", private_labels=[],
                              private_corpus=ROOT / "rag/gk_corpus",
                              attachment_path="documents/private.txt")
    with pytest.raises(AuthorizationError):
        run_real_evaluation(ROOT, "not-authorized", general_context=None,
                            live_web_provider=None)
    assert not any((ROOT / relative).exists() for relative in PATHS.values())
