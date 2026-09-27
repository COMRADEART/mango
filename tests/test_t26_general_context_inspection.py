"""Public/no-store tests for bounded T26 GENERAL-context inspection."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sciencemath.executive.runner import ExecContext
from t26_protocol import official_runner as runner
from t26_protocol.evaluation_v4 import (
    ADDENDUM_PATH, FREEZE_PATH, REHEARSAL_PATH,
    verify_addendum_document_v3, verify_addendum_freeze_v3,
)

ROOT = Path(__file__).resolve().parents[1]


class OpaqueModel:
    def __init__(self):
        self.Gold = 1


class OpaqueTokenizer:
    def __init__(self):
        self._vocab = {"Gold": 42}


class ConfiguredDependency:
    def __init__(self, config):
        self.config = config


def _context() -> ExecContext:
    return ExecContext(
        model=OpaqueModel(), tokenizer=OpaqueTokenizer(),
        generation={"do_sample": False, "max_new_tokens": 32, "seed": 42})


@pytest.fixture
def provenance_stubs(monkeypatch):
    monkeypatch.setattr(runner, "_inspect_model_provenance", lambda _r, model: {
        "module": type(model).__module__, "class": type(model).__qualname__,
        "base_model_id": runner.EXPECTED_BASE_MODEL,
        "base_revision": runner.EXPECTED_BASE_REVISION,
        "adapter": {"path": runner.EXPECTED_ADAPTER,
                    "sha256": runner.EXPECTED_ADAPTER_SHA256,
                    "bytes": runner.EXPECTED_ADAPTER_BYTES,
                    "name": "t3", "active": True},
        "eval_mode": True, "inference_mode": True,
        "initialized_from_public_artifacts": True})
    monkeypatch.setattr(runner, "_inspect_tokenizer_identity", lambda tokenizer: {
        "module": type(tokenizer).__module__,
        "class": type(tokenizer).__qualname__,
        "source_id": runner.EXPECTED_BASE_MODEL,
        "source_revision": runner.EXPECTED_BASE_REVISION,
        "public_files": [], "public_file_root": "0" * 64,
        "chat_template_root": "1" * 64,
        "chat_template_included": False,
        "is_fast": True, "initialized_from_public_artifacts": True})


def test_opaque_model_and_tokenizer_marker_is_not_a_gold_channel(provenance_stubs):
    identity = runner.build_general_context_identity(ROOT, _context())
    assert identity["candidate_gold_access"] is False
    assert identity["gold_channel_count"] == 0
    assert identity["opaque_dependency_boundary"] == {
        "model_recursive_introspection": False,
        "tokenizer_recursive_introspection": False,
        "bounded_control_plane_recursive_inspection": True,
    }


@pytest.mark.parametrize("name", ["gold", "expected_answer"])
def test_unexpected_top_level_gold_fields_fail(name, provenance_stubs):
    context = _context()
    setattr(context, name, "forbidden")
    with pytest.raises(ValueError, match="unexpected ExecContext attributes"):
        runner.build_general_context_identity(ROOT, context)


@pytest.mark.parametrize("key", ["gold", "expected_answer"])
def test_gold_generation_settings_fail(key, provenance_stubs):
    context = _context()
    context.generation[key] = "forbidden"
    with pytest.raises(ValueError, match="gold marker"):
        runner.build_general_context_identity(ROOT, context)


def test_gold_registry_configuration_fails(provenance_stubs):
    context = _context()
    context.registry = ConfiguredDependency({"gold": "forbidden"})
    with pytest.raises(ValueError, match="gold marker"):
        runner.build_general_context_identity(ROOT, context)


def test_gold_retriever_configuration_fails(provenance_stubs):
    context = _context()
    context.retriever = ConfiguredDependency(
        {"corpus_identity": "public", "expected_answer": "forbidden"})
    with pytest.raises(ValueError, match="gold marker"):
        runner.build_general_context_identity(ROOT, context)


def test_gold_bearing_checkpointer_fails(provenance_stubs):
    context = _context()
    context.checkpointer = ConfiguredDependency(
        {"path": ROOT / "construction" / "gold"})
    with pytest.raises(ValueError, match="checkpointer"):
        runner.build_general_context_identity(ROOT, context)


@pytest.mark.parametrize("value", [
    "C:/T26_PRIVATE_EVALUATION/T26-STORE-01/t26/evaluation/raw_outputs.json",
    "C:/workspace/construction/gold/answers.json",
])
def test_private_path_injection_fails(value, provenance_stubs):
    context = _context()
    context.generation["cache_path"] = value
    with pytest.raises(ValueError, match="private path"):
        runner.build_general_context_identity(ROOT, context)


def test_callable_generation_injection_fails(provenance_stubs):
    context = _context()
    context.generation["hook"] = lambda: None
    with pytest.raises(ValueError, match="callable"):
        runner.build_general_context_identity(ROOT, context)


def test_frozen_exec_context_field_contract_is_complete():
    identity = json.loads((ROOT / runner.GENERAL_CONTEXT_IDENTITY_PATH)
                          .read_text(encoding="utf-8"))
    assert identity["context"]["field_contract"] == list(runner.EXEC_CONTEXT_FIELDS)
    assert set(identity["context"]["field_contract"]) == {
        "model", "tokenizer", "registry", "retriever", "generation",
        "usage", "budgets", "features", "trajectory", "checkpointer",
        "retrieval_k",
    }
    assert identity["candidate_gold_access"] is False
    assert identity["private_store_dependency"] is False


def test_two_fresh_loaded_context_preflights_are_identical_and_pass():
    report = json.loads((ROOT / REHEARSAL_PATH).read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["run_count"] == 2
    assert report["semantic_reproducibility"] is True
    assert report["candidate_executions"] == 0
    assert report["web_searches"] == 0
    assert report["sealed_store_rows_read"] == 0
    assert report["official_evaluator_invocations"] == 0
    assert all(run["status"] == "PASS" for run in report["runs"])


def test_successor_addendum_and_freeze_reproduce():
    addendum = verify_addendum_document_v3(ROOT)
    freeze = verify_addendum_freeze_v3(ROOT)
    assert addendum["root_cause"] == (
        "PRE_EVALUATION_GENERAL_CONTEXT_INSPECTION_OVERBROAD")
    assert addendum["replacement_evaluation_entrypoint"] == (
        "t26_protocol.evaluation_v4:run_real_evaluation")
    assert freeze["status"] == "PASS"
    for relative in (ADDENDUM_PATH, FREEZE_PATH, REHEARSAL_PATH,
                     runner.GENERAL_CONTEXT_IDENTITY_PATH):
        document = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        assert document["classification"] == "PUBLIC_SAFE"


def test_scorer_metrics_and_authority_are_unchanged():
    addendum = verify_addendum_document_v3(ROOT)
    assert addendum["scorer_sha256"] == (
        "c0185f150c8d52d0c3b451a9e7a076de82cd48c3cd0a3e36ab309a28e9aefa15")
    assert addendum["metric_registry_sha256"] == (
        "3cc8b0b5e09ebd29b809a6fe50e5ff27854778c2b749b787746a0509cf3b67b4")
    assert addendum["authority_graph_sha256"] == (
        "2c1400d8d42795bcab30ceb2f651c0c9d54f90add0230614c51eff5f6b154e36")
