"""Public/synthetic tests for the additive T26 evaluation protocol."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from t26_protocol.evaluation_v2 import (
    ADDENDUM_SCHEMA, EVALUATION_IMPLEMENTATION, EVALUATION_TOKEN,
    LEGACY_IMPLEMENTATION, LEDGER_BINDING_FIELDS, SCORER_SHA256,
    T26EvaluationLedger, build_addendum_document, candidate_view,
    run_negative_controls, validate_candidate_payload,
    verify_addendum_document, verify_addendum_freeze,
    verify_original_v3_components,
)
from t26_protocol.lifecycle import T26PrivateStore

ROOT = Path(__file__).resolve().parents[1]


def _bindings() -> dict:
    values = {name: "1" * 64 for name in LEDGER_BINDING_FIELDS}
    values.update({"experiment": "t26", "attempt": 1,
                   "authorization": "T26_DISPOSABLE_SYNTHETIC_EVALUATION",
                   "material_mode": "DISPOSABLE_SYNTHETIC",
                   "candidate_commit": "2" * 40,
                   "candidate_tree": "3" * 40})
    return values


def test_root_cause_and_entrypoint_supersession_are_explicit():
    legacy = (ROOT / "t26_protocol/lifecycle.py").read_text(encoding="utf-8")
    assert 'seal.get("manifest_sha256")' in legacy
    assert 'manifest["inputs"]' in legacy
    addendum = build_addendum_document(ROOT)
    assert addendum["schema_version"] == ADDENDUM_SCHEMA
    assert addendum["root_cause"] == (
        "PRE_EVALUATION_INFRASTRUCTURE_SCHEMA_COMPATIBILITY_DEFECT")
    assert addendum["legacy_evaluation_entrypoint"] == LEGACY_IMPLEMENTATION
    assert addendum["replacement_evaluation_entrypoint"] == EVALUATION_IMPLEMENTATION
    assert addendum["construction_superseded"] is False
    assert addendum["real_evaluation_authorized"] is False


def test_original_v3_explicit_component_set_remains_exact():
    report = verify_original_v3_components(ROOT)
    assert report["status"] == "PASS"
    assert report["component_count"] == 244
    assert report["freeze_root"] == (
        "7ec02173e02fb498ebe487aa01e225fa1e6c0c8600672aeec0b107e363efa5da")


def test_addendum_and_freeze_reproduce_exactly():
    assert verify_addendum_document(ROOT)["evaluation_authorization_token"] == EVALUATION_TOKEN
    frozen = verify_addendum_freeze(ROOT)
    assert frozen["status"] == "PASS"
    assert frozen["component_count"] >= 18


def test_scorer_and_public_dependency_identities_are_unchanged():
    addendum = verify_addendum_document(ROOT)
    assert addendum["scorer_sha256"] == SCORER_SHA256
    assert addendum["metric_registry_sha256"] == (
        "3cc8b0b5e09ebd29b809a6fe50e5ff27854778c2b749b787746a0509cf3b67b4")
    assert addendum["production_runtime_sha256"] == (
        "594a481fcbf1ea4ad04fe8ce7fae4a9c01a07a2a83563689347b7fae32088697")
    assert addendum["authority_graph_sha256"] == (
        "2c1400d8d42795bcab30ceb2f651c0c9d54f90add0230614c51eff5f6b154e36")


def test_gold_firewall_strips_family_and_rejects_gold_fields():
    scenario = {"scenario_id": "synthetic", "plan": {},
                "classification": "PRIVATE_BLIND", "family": "math_chain"}
    visible = candidate_view(scenario)
    assert set(visible) == {"scenario_id", "plan", "classification"}
    assert "family" not in visible
    with pytest.raises(ValueError):
        validate_candidate_payload({**visible, "expected_answer": "forbidden"})


def test_evaluation_ledger_is_exclusive_hash_chained_and_terminal():
    with TemporaryDirectory(prefix="t26-eval-ledger-test-") as tmp:
        store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
        ledger = T26EvaluationLedger.create_exclusive(store, _bindings())
        ledger.advance("EXECUTED", {"candidate_execution_count": 512})
        ledger.advance("SCORED", {"scenario_count": 512})
        ledger.advance("COMPLETE", {"scenario_count": 512})
        report = ledger.verify()
        assert report["status"] == "PASS"
        assert report["state"] == "COMPLETE"
        assert report["event_count"] == 4
        with pytest.raises(Exception):
            T26EvaluationLedger.create_exclusive(store, _bindings())


def test_failure_state_is_durable_and_second_attempt_refused():
    with TemporaryDirectory(prefix="t26-eval-failure-test-") as tmp:
        store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
        ledger = T26EvaluationLedger.create_exclusive(store, _bindings())
        ledger.fail("STARTED", "InjectedFailure", {"synthetic": True})
        assert ledger.verify()["state"] == "FAILED"
        assert ledger.document["attempt"] == 1
        with pytest.raises(Exception):
            T26EvaluationLedger.create_exclusive(store, _bindings())


def test_ledger_verification_rejects_terminal_envelope_tamper():
    with TemporaryDirectory(prefix="t26-eval-ledger-tamper-") as tmp:
        store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
        ledger = T26EvaluationLedger.create_exclusive(store, _bindings())
        ledger.document["event_count"] = 2
        store.replace("evaluation/ledger.json", ledger.document)
        with pytest.raises(Exception):
            ledger.verify()


def test_negative_control_matrix_is_complete():
    report = run_negative_controls(ROOT)
    assert report["status"] == "PASS"
    assert report["control_count"] == report["refused_count"] == 14
    assert report["not_refused"] == []
    assert report["real_private_rows_read"] == 0


def test_public_rehearsal_reports_are_complete_and_real_absence_is_explicit():
    rehearsal = json.loads((ROOT / "evaluations/t26/T26_EVALUATION_REHEARSAL_REPORT.json")
                           .read_text(encoding="utf-8"))
    negative = json.loads((ROOT / "evaluations/t26/T26_EVALUATION_NEGATIVE_CONTROLS.json")
                          .read_text(encoding="utf-8"))
    assert rehearsal["status"] == "PASS"
    assert rehearsal["pair"]["run_count"] == 2
    assert rehearsal["pair"]["scenario_count_per_run"] == 512
    assert rehearsal["pair"]["semantic_reproducibility"] is True
    assert rehearsal["failure"]["state"] == "FAILED"
    assert rehearsal["failure"]["second_evaluation_refused"] is True
    assert rehearsal["real_evaluation_ledger_created"] is False
    assert negative["status"] == "PASS"
