"""T22 final adjudication and capability-promotion pins."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sciencemath.executive.skills import QUALIFIED, SkillRegistry, registry_sha256
from t21_protocol.freeze import verify_freeze
from t21_protocol.metric_semantics import semantics_root
from t21_protocol.util import read_json, sha256_file, sha256_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t22"
RECORD = OUT / "T22_FINAL_PROMOTION_RECORD.json"
RECORD_SUM = OUT / "T22_FINAL_PROMOTION_RECORD.sha256"
VERDICT = "MANGO_KNOWLEDGE_RAG_CAPABILITY_PROMOTED"


def _record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def test_exact_evaluated_candidate_is_promoted_without_identity_substitution() -> None:
    record = _record()
    candidate = record["evaluated_candidate"]
    assert candidate == {
        "candidate_commit": "7d919a255c2df87adcb3dd42011b505b10509713",
        "candidate_tree": "0bbf81b234458a4ac204ff6b035bc59b59078544",
        "current_canonical_qualified_candidate": True,
        "runtime_root": "a9a24e3d8bba5e8b6985493d262f3699cef93cdbdd35cc09a7e4bc073ded7f5f",
    }
    assert record["verdict"] == VERDICT


def test_registry_records_qualified_scope_without_router_promotion() -> None:
    record = _record()
    states = record["capability_states"]
    registry = SkillRegistry()
    assert registry.availability("KNOWLEDGE_RAG") == QUALIFIED
    assert registry.executable("KNOWLEDGE_RAG") is True
    assert states["KNOWLEDGE_RAG"] == QUALIFIED
    assert states["Executive Router"] == "EXPERIMENTAL"
    assert states["registry_sha256_after_promotion"] == registry_sha256()
    assert "no broader deployment or release readiness claim" in \
        states["knowledge_rag_scope"]


def test_official_result_and_temporal_gates_are_pinned() -> None:
    record = _record()
    assert record["status"] == "CLOSED / OFFICIAL_EVALUATION_PASS"
    assert record["execution"] == {
        "automatic_retries": 0,
        "duplicate_ids": 0,
        "errors": 0,
        "evaluation_attempts": 1,
        "invalid_outputs": 0,
        "rows_attempted": 4800,
        "rows_evaluated": 4800,
        "rows_executed": 4800,
        "rows_scored": 4800,
        "timeouts": 0,
    }
    assert record["floor_summary"] == {
        "candidate_capability_pass": True,
        "failed": 0,
        "passed": 32,
        "total": 32,
    }
    assert all(gate["pass"] for gate in record["temporal_capability"].values())


def test_history_privacy_and_next_phase_remain_closed() -> None:
    record = _record()
    assert record["historical_state"]["T21R16"] == \
        "CLOSED / OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE"
    assert record["historical_state"]["T21R17"] == \
        "CLOSED / VALID_CAPABILITY_FAILURE"
    assert not any(record["privacy_and_publication"].values())
    assert record["blind_material_included"] is False
    assert record["next_phase"] == {
        "reserved_identifier": "T23",
        "state": "AWAITING_EXPLICIT_AUTHORIZATION",
        "started": False,
    }


def test_promotion_record_checksum_sidecar() -> None:
    digest = hashlib.sha256(RECORD.read_bytes()).hexdigest()
    expected, filename = RECORD_SUM.read_text(encoding="ascii").strip().split("  ")
    assert filename == RECORD.name
    assert expected == digest


def test_frozen_roots_recompute_without_rerunning_the_evaluation() -> None:
    record = _record()
    sealed = record["sealed_inputs"]
    runtime = read_json(OUT / "runtime_freeze.json")
    evaluator = read_json(OUT / "evaluator_freeze.json")
    runtime_check = verify_freeze(ROOT, runtime)
    evaluator_check = verify_freeze(ROOT, evaluator)
    assert runtime_check["root"] == record["evaluated_candidate"]["runtime_root"]
    assert evaluator_check["root"] == sealed["evaluator_root"]

    manifest = read_json(OUT / "holdout_manifest.json")
    marker = read_json(OUT / "HOLDOUT_FROZEN")
    assert sha256_file(OUT / "holdout_manifest.json") == \
        sealed["holdout_manifest_sha256"]
    assert sha256_file(OUT / "HOLDOUT_FROZEN") == \
        sealed["HOLDOUT_FROZEN_sha256"]
    assert sha256_json(manifest["bindings"]) == sealed["seal_root"]
    assert marker["freeze_root_sha256"] == sealed["seal_root"]

    contract = read_json(OUT / "t21_master_contract.json")
    floors = contract["values"]["promotion_floors"]
    semantics = read_json(OUT / "official_metric_semantics.json")
    assert sha256_json(floors) == sealed["floor_hash"]
    assert semantics_root(semantics) == sealed["scorer_semantic_root"]
