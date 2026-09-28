"""Authenticated historical-exclusion provenance regression gate."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from t27_protocol.construction import (
    CONTRACT_LEAF_IDS, CONSTRUCTION_GATE_IDS, fingerprint_root,
    fingerprint_sets, historical_exclusion_audit,
    run_real_mode_oracle_validation_rehearsal, synthetic_oracle_result,
    synthetic_private_bundle,
)
from t27_protocol.exclusion import (
    DIMENSIONS, PUBLIC_HISTORY_BUILDER, REQUIRED_HISTORICAL_SOURCES,
    build_authenticated_public_historical_index, verify_historical_index,
)
from t27_protocol.oracle import verify_oracle_result

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "evaluations" / "t27"


def read(name: str) -> dict:
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def test_public_history_builder_is_complete_and_authenticated():
    index = build_authenticated_public_historical_index(ROOT)
    verified = verify_historical_index(index, root=ROOT, mode="REAL")
    assert verified["status"] == "PASS"
    assert index["builder_implementation_identity"] == PUBLIC_HISTORY_BUILDER
    assert [source["source_class"] for source in index["sources"]] == list(
        REQUIRED_HISTORICAL_SOURCES)
    assert set(index["aggregate_dimensions"]) == set(DIMENSIONS)
    for source in index["sources"]:
        assert len(source["source_commitment"]) == 64
        assert len(source["overall_source_root"]) == 64
        assert set(source["dimensions"]) == set(DIMENSIONS)


def test_empty_or_unauthenticated_public_history_fails_closed():
    cases, gold, _ = synthetic_private_bundle(9)
    oracle = synthetic_oracle_result(cases, gold, variant=9)
    with pytest.raises(ValueError, match="required"):
        historical_exclusion_audit(cases, gold, None, oracle)
    index = build_authenticated_public_historical_index(ROOT)
    tampered = copy.deepcopy(index)
    tampered["sources"][0]["source_commitment"] = "f" * 64
    with pytest.raises(ValueError):
        verify_historical_index(tampered, root=ROOT, mode="REAL")


def test_real_mode_oracle_rehearsal_authenticates_store_and_exact_bindings():
    result = run_real_mode_oracle_validation_rehearsal(ROOT)
    assert result["status"] == "PASS"
    assert result["store_authenticated"] is True
    assert result["commitments_exact"] is True
    assert result["real_mode_not_synthetic"] is True
    assert result["outside_boundary_private_rows_exposed"] == 0


def test_synthetic_oracle_cannot_verify_as_real():
    cases, gold, _ = synthetic_private_bundle(10)
    oracle = synthetic_oracle_result(cases, gold, variant=10)
    root = fingerprint_root(fingerprint_sets(cases, gold))
    with pytest.raises(ValueError):
        verify_oracle_result(
            oracle, mode="REAL_REHEARSAL", expected_t27_root=root,
            expected_t26_bindings={})


def test_expanded_contract_gate_and_all_negative_controls_pass():
    controls = read("construction_negative_controls.json")
    assert len(CONTRACT_LEAF_IDS) == 51
    assert len(CONSTRUCTION_GATE_IDS) == 41
    assert controls["status"] == "PASS"
    assert controls["control_count"] >= 41
    assert controls["PASS"] == controls["control_count"]
    assert controls["FAIL"] == 0
