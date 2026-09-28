"""Official T26 marker-layout authentication tests (disposable stand-ins only).

The physical official T26 store is never opened here; its pushed aggregate
metadata preflight artifact is checked for self-consistency instead.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from t26_protocol.t27_private_oracle import (
    OFFICIAL_MARKER_PATH, OFFICIAL_MARKER_SCHEMA,
    T26_STORE_AUTHENTICATION_FIELDS,
    authenticate_official_t26_store_for_t27, disposable_t26_sealed_store,
    official_marker_binding, validate_t26_store_authentication_evidence)
from t27_protocol.construction import (
    CONSTRUCTION_GATE_IDS, CONTRACT_LEAF_IDS, NEGATIVE_CONTROL_IDS,
    construction_contract, official_marker_contract_report,
    run_t26_marker_layout_negative_controls)
from t27_protocol.oracle import verify_oracle_result
from t27_protocol.construction import run_real_mode_oracle_validation_rehearsal

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "evaluations" / "t27"


def read(name: str) -> dict:
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def test_official_marker_binding_is_pinned_to_v4_contract():
    binding = official_marker_binding()
    assert binding["official_marker_path"] == "evaluation/one_shot_spent.json"
    assert binding["official_marker_schema"] == "t26-evaluation-one-shot-marker-v2"
    assert binding["official_marker_artifact"] == "T26_EVALUATION_ONE_SHOT_SPENT"
    assert binding["marker_path_exact"] is True
    assert binding["marker_schema_exact"] is True
    assert binding["legacy_marker_path"] == "markers/evaluation.one-shot"
    assert binding["legacy_marker_path_accepted"] is False


def test_disposable_standin_mirrors_official_layout():
    with TemporaryDirectory(prefix="t27-t26-layout-mirror-") as tmp:
        store, expected = disposable_t26_sealed_store(
            Path(tmp), variant=0, public_repo=ROOT)
        assert store.has(OFFICIAL_MARKER_PATH)
        assert not store.has("markers/evaluation.one-shot")
        marker = store.read(OFFICIAL_MARKER_PATH)
        ledger = store.read("evaluation/ledger.json")
        assert marker["schema_version"] == OFFICIAL_MARKER_SCHEMA
        assert marker["artifact"] == "T26_EVALUATION_ONE_SHOT_SPENT"
        assert marker["experiment"] == "t26"
        assert marker["attempt"] == 1
        assert marker["ledger_genesis_hash"] == ledger["events"][0]["event_hash"]
        assert marker["created_at"] == ledger["created_at"]
        assert ledger["state"] == "COMPLETE" and ledger["attempt"] == 1
        assert ledger["event_count"] == 4
        assert [event["event_type"] for event in ledger["events"]] == [
            "STARTED", "EXECUTED", "SCORED", "COMPLETE"]
        authentication = authenticate_official_t26_store_for_t27(
            ROOT, store, expected=expected)
        assert validate_t26_store_authentication_evidence(
            authentication, real=False)["status"] == "PASS"


def test_metadata_only_authentication_is_row_free():
    with TemporaryDirectory(prefix="t27-t26-row-free-") as tmp:
        store, expected = disposable_t26_sealed_store(
            Path(tmp), variant=1, public_repo=ROOT)
        evidence = authenticate_official_t26_store_for_t27(
            ROOT, store, expected=expected)
        assert set(evidence) == set(T26_STORE_AUTHENTICATION_FIELDS)
        assert evidence["status"] == "PASS"
        assert evidence["official_commitment_scope"] == "DISPOSABLE_STANDIN"
        assert evidence["t26_official_marker_path"] == OFFICIAL_MARKER_PATH
        assert evidence["t26_official_marker_committed"] is True
        assert evidence["t26_official_marker_genesis_matches_ledger"] is True
        assert evidence["t26_legacy_marker_path_present"] is False
        assert all(evidence[key] == 0 for key in (
            "t26_private_rows_read", "t26_gold_rows_read",
            "t26_raw_output_rows_read", "t26_scored_rows_read",
            "t26_candidate_reruns", "outside_boundary_private_rows_exposed"))
        assert evidence["t27_fingerprint_derivation_invoked"] is False
        # The stand-in store contains no input/gold row artifacts at all.
        assert not store.has("construction/inputs.json")
        assert not store.has("construction/gold.json")
        # Exact-equality scope is enforced fail-closed.
        wrong = dict(expected)
        wrong["t26_evaluation_ledger_sha256"] = "0" * 64
        try:
            authenticate_official_t26_store_for_t27(ROOT, store, expected=wrong)
        except ValueError:
            pass
        else:
            raise AssertionError("commitment drift accepted")


def test_real_mode_oracle_rehearsal_passes_with_corrected_layout():
    result = run_real_mode_oracle_validation_rehearsal(ROOT)
    assert result["status"] == "PASS"
    assert result["store_authenticated"] is True
    assert result["commitments_exact"] is True
    assert result["real_mode_not_synthetic"] is True
    assert result["outside_boundary_private_rows_exposed"] == 0


def test_all_fourteen_marker_layout_negative_controls_refuse():
    controls = run_t26_marker_layout_negative_controls(ROOT)
    assert len(controls) == 14
    assert all(item["status"] == "PASS" for item in controls.values()), [
        name for name, item in controls.items() if item["status"] != "PASS"]
    assert all(item["refused"] is True for item in controls.values())


def test_marker_evidence_is_validated_fail_closed():
    with TemporaryDirectory(prefix="t27-t26-fail-closed-") as tmp:
        store, expected = disposable_t26_sealed_store(
            Path(tmp), variant=2, public_repo=ROOT)
        evidence = authenticate_official_t26_store_for_t27(
            ROOT, store, expected=expected)
    real_scope_refused = False
    synthetic_scope_refused = False
    try:
        validate_t26_store_authentication_evidence(
            dict(evidence, official_commitment_scope="OFFICIAL_T26"), real=True)
    except ValueError:
        real_scope_refused = True
    try:
        validate_t26_store_authentication_evidence(evidence, real=True)
    except ValueError:
        synthetic_scope_refused = True
    assert real_scope_refused and synthetic_scope_refused
    tampered = dict(evidence, t26_evaluation_event_count=3)
    try:
        validate_t26_store_authentication_evidence(tampered, real=False)
    except ValueError:
        pass
    else:
        raise AssertionError("event-count drift accepted")


def test_official_marker_contract_artifact_is_authentic():
    contract = read("official_t26_marker_contract.json")
    assert contract == official_marker_contract_report(ROOT)
    assert contract["status"] == "PASS"
    assert contract["marker_path_exact"] is True
    assert contract["marker_schema_exact"] is True
    assert contract["legacy_marker_path_accepted"] is False
    assert contract["disposable_layout_mirrors_official"] is True
    assert contract["real_store_metadata_preflight_required"] is True


def test_real_store_preflight_artifact_is_authentic_and_row_free():
    preflight = read("official_t26_store_preflight.json")
    assert validate_t26_store_authentication_evidence(
        preflight, real=True)["status"] == "PASS"
    assert preflight["official_commitment_scope"] == "OFFICIAL_T26"
    assert preflight["t26_store_identity"] == "T26-STORE-01"
    assert preflight["t26_official_marker_path"] == OFFICIAL_MARKER_PATH
    assert preflight["t26_official_marker_schema"] == OFFICIAL_MARKER_SCHEMA
    assert preflight["t26_official_marker_committed"] is True
    assert preflight["t26_official_marker_genesis_matches_ledger"] is True
    assert preflight["t26_legacy_marker_path_present"] is False
    assert preflight["t26_official_evaluation_state"] == "COMPLETE"
    assert preflight["t26_official_evaluation_attempt"] == 1
    assert preflight["t26_evaluation_event_count"] == 4
    assert all(preflight[key] == 0 for key in (
        "t26_private_rows_read", "t26_gold_rows_read",
        "t26_raw_output_rows_read", "t26_scored_rows_read",
        "t26_candidate_reruns", "outside_boundary_private_rows_exposed"))
    assert preflight["t27_fingerprint_derivation_invoked"] is False


def test_expanded_contract_and_gate_enumerators_match():
    contract = read("construction_contract_v4.json")
    assert contract == construction_contract()
    assert len(CONTRACT_LEAF_IDS) == 60
    assert len(CONSTRUCTION_GATE_IDS) == 52
    assert "oracle.official_marker_path_exact" in CONTRACT_LEAF_IDS
    assert "oracle.real_store_layout_authenticated" in CONTRACT_LEAF_IDS
    assert "G42_T26_OFFICIAL_MARKER_PATH" in CONSTRUCTION_GATE_IDS
    assert "G46_T26_REAL_STORE_LAYOUT_PREFLIGHT" in CONSTRUCTION_GATE_IDS
    negative = read("construction_negative_controls.json")
    assert negative["control_count"] == 72
    assert negative["status"] == "PASS"
    assert set(NEGATIVE_CONTROL_IDS) == set(negative["controls"])
    assert negative["PASS"] == 72


def test_oracle_result_document_and_schema_unchanged():
    from t27_protocol.oracle import ARTIFACT, REAL_SCHEMA, verify_oracle_result

    assert REAL_SCHEMA == "t27-t26-sealed-overlap-oracle-result-v2"
    assert ARTIFACT == "T26_TO_T27_OVERLAP_ORACLE_RESULT"
    # verify_oracle_result enforces the exact frozen field set, so a PASS is
    # the proof that the result document shape did not change.
    rehearsal = run_real_mode_oracle_validation_rehearsal(ROOT)
    assert rehearsal["status"] == "PASS"
    from t26_protocol.t27_private_oracle import disposable_real_mode_oracle_result
    from t27_protocol.construction import fingerprint_root, fingerprint_sets
    from t27_protocol.exclusion import DIMENSIONS
    from t27_protocol.construction import synthetic_private_bundle
    cases, gold, _ = synthetic_private_bundle(6)
    prospective = fingerprint_sets(cases, gold)
    result = disposable_real_mode_oracle_result(
        root=ROOT, prospective_root=fingerprint_root(prospective),
        prospective=prospective, variant=6)
    bindings = {key: result[key] for key in (
        "t26_store_identity", "t26_namespace", "t26_private_holdout_root",
        "t26_private_manifest_sha256", "t26_construction_seal_sha256",
        "t26_evaluation_ledger_sha256", "t26_official_evaluation_state",
        "t26_official_evaluation_attempt")}
    verified = verify_oracle_result(
        result, mode="REAL_REHEARSAL", expected_t27_root=fingerprint_root(
            prospective), expected_t26_bindings=bindings)
    assert verified["status"] == "PASS"
    # The standalone oracle-module rehearsal records the official marker path.
    from t26_protocol.t27_private_oracle import real_mode_oracle_rehearsal
    standalone = real_mode_oracle_rehearsal(ROOT)
    assert standalone["status"] == "PASS"
    assert standalone["official_marker_path"] == OFFICIAL_MARKER_PATH
    assert standalone["official_marker_schema"] == OFFICIAL_MARKER_SCHEMA
    assert standalone["official_marker_authenticated"] is True
    assert standalone["outside_boundary_private_rows_exposed"] == 0