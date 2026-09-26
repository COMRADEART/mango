"""Public/synthetic tests for T26 production-runner identity binding."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from t26_protocol.evaluation_v2 import (
    verify_addendum_freeze, verify_original_v3_components,
)
from t26_protocol.evaluation_v3 import (
    ADDENDUM_PATH, FREEZE_PATH, NEGATIVE_PATH, REHEARSAL_PATH,
    LEDGER_BINDING_FIELDS, PREDECESSOR_COMMIT,
    run_negative_controls, run_real_evaluation,
    verify_addendum_document_v2, verify_addendum_freeze_v2,
)
from t26_protocol.official_runner import (
    FACTORY_ID, DeterministicFixtureSearchProvider,
    DeterministicGeneralContext, build_official_runner_factory,
    validate_corpus_mount, validate_gold_free_mount,
    validate_stack_attestation, verify_runner_identity_document,
)

ROOT = Path(__file__).resolve().parents[1]


def test_predecessor_addendum_and_construction_freeze_are_unchanged():
    original = verify_original_v3_components(ROOT)
    predecessor = verify_addendum_freeze(ROOT)
    assert original["component_count"] == 244
    assert original["freeze_sha256"] == (
        "b0c49c7f6370130420e9881a9312fd87e212c09d5818df9876f0ba28f534e3dd")
    assert predecessor == {
        "status": "PASS", "component_count": 18,
        "component_root":
            "7a6cf07ad64ee037495af9f339150eef2e82281f9087e38db50b752fd8505ca6",
        "freeze_root":
            "b0baf8653add2b34a37261676fbdd5fff566f7d372dedc4c079251c2fce873e1",
        "freeze_sha256":
            "5b39e7a38a8f83b3a52df685e56c83773cef104f73d713aa41d363ac8b12adde",
    }


def test_runner_factory_identity_binds_frozen_production_stack():
    identity = verify_runner_identity_document(ROOT)
    assert identity["factory_id"] == FACTORY_ID
    assert identity["production_runtime_sha256"] == (
        "594a481fcbf1ea4ad04fe8ce7fae4a9c01a07a2a83563689347b7fae32088697")
    assert identity["integrated_runner_runtime_sha256"] == (
        "a097a31c883cd8f93f12576c8ff2a49a945604d7aa3ab194e2df8a8c269b458a")
    registry = identity["production_adapter_registry"]
    assert set(registry["registered_skill_ids"]) == {
        entry["capability"] for entry in registry["entries"]}
    assert all(entry["internal_only"] is True and
               entry["may_perform_external_action"] is False
               for entry in registry["entries"])


def test_canonical_factory_builds_exact_wrapped_production_stack():
    factory = build_official_runner_factory(
        ROOT, live_web_provider=DeterministicFixtureSearchProvider(),
        general_context=DeterministicGeneralContext(), real=False)
    stack = factory.preflight()
    validate_stack_attestation(stack, real=False)
    assert stack["integrated_runner_used"] is True
    assert stack["production_adapter_registry_used"] is True
    assert stack["provider_id"] == (
        "t25_protocol.provider:T25ProductionRouterProvider")
    assert stack["t26_firewall_used"] is True
    assert stack["inner_live_or_fixture"] == "fixture"


def test_real_path_has_no_arbitrary_runner_factory_argument():
    parameters = inspect.signature(run_real_evaluation).parameters
    assert "runner_factory" not in parameters
    assert {"live_web_provider", "general_context"} <= set(parameters)


def test_real_factory_rejects_fixture_provider_before_ledger():
    with pytest.raises(ValueError, match="REAL_BLIND requires"):
        build_official_runner_factory(
            ROOT, live_web_provider=DeterministicFixtureSearchProvider(),
            general_context=DeterministicGeneralContext(), real=True)


def test_mount_policy_rejects_caller_path_and_gold():
    with TemporaryDirectory(prefix="t26-caller-corpus-") as tmp:
        with pytest.raises(ValueError, match="caller-selected"):
            validate_corpus_mount(ROOT, Path(tmp))
    with pytest.raises(ValueError, match="gold-containing"):
        validate_gold_free_mount(ROOT / "construction/gold.json")


def test_successor_addendum_and_ledger_binding_set_are_complete():
    addendum = verify_addendum_document_v2(ROOT)
    assert addendum["predecessor_addendum_commit"] == PREDECESSOR_COMMIT
    assert addendum["real_path_accepts_runner_factory"] is False
    assert addendum["official_runner_factory_id"] == FACTORY_ID
    for field in (
        "official_runner_factory_id", "official_runner_factory_sha256",
        "production_runtime_sha256", "production_provider_id",
        "production_provider_sha256", "production_adapter_registry_root",
        "official_runner_policy_root"):
        assert field in LEDGER_BINDING_FIELDS


def test_production_rehearsals_are_complete_and_semantically_equal():
    report = json.loads((ROOT / REHEARSAL_PATH).read_text(encoding="utf-8"))
    pair = report["pair"]
    assert report["status"] == "PASS"
    assert pair["run_count"] == 2
    assert pair["scenario_count_per_run"] == 512
    assert pair["total_synthetic_candidate_executions"] == 1024
    assert pair["semantic_reproducibility"] is True
    assert pair["production_adapter_registry_used"] is True
    assert pair["t25_production_router_provider_used"] is True
    assert pair["t26_firewall_used"] is True
    assert pair["gold_exposure"] == 0


def test_failure_rehearsal_and_all_negative_controls_pass():
    report = json.loads((ROOT / REHEARSAL_PATH).read_text(encoding="utf-8"))
    failure = report["failure"]
    assert failure["state"] == "FAILED"
    assert failure["attempt"] == 1
    assert failure["retry_count"] == 0
    assert failure["second_evaluation_refused"] is True
    controls = run_negative_controls(ROOT)
    assert controls["status"] == "PASS"
    assert controls["old_control_count"] == 14
    assert controls["new_control_count"] == 13
    assert controls["total_control_count"] == controls["total_refused_count"] == 27
    assert controls["not_refused"] == []


def test_successor_freeze_reproduces_and_artifacts_are_public_safe():
    frozen = verify_addendum_freeze_v2(ROOT)
    assert frozen["status"] == "PASS"
    for relative in (ADDENDUM_PATH, FREEZE_PATH, NEGATIVE_PATH, REHEARSAL_PATH):
        document = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        assert document["classification"] == "PUBLIC_SAFE"
        assert "gold" not in document or document.get("gold_included") is False
