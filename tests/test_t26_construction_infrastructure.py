"""T26 construction-infrastructure remediation tests (pre-exposure, no real material)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from t26_protocol.construction import (
    CONSTRUCTION_TOKEN, ConstructionLedgerError, GATE_CHECKS,
    NEGATIVE_CONTROL_IDS, T26ConstructionLedger,
    _synthetic_oracle_result, construct_real, protocol_hashes,
    run_construction_audit, run_negative_gate_controls,
    run_publication_leak_gate, synthetic_author_provenance,
    synthetic_private_bundle,
)
from t26_protocol.exclusion import (DIMENSIONS,
                                    build_historical_exclusion_document)
from t26_protocol.freeze import build_freeze
from t26_protocol.lifecycle import T26PrivateStore
from t26_protocol.oracle import verify_oracle_result

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "T26_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"


def _make_store(tmp_path: Path) -> T26PrivateStore:
    return T26PrivateStore(tmp_path / "T26-STORE-01", ROOT)


def _bindings(frozen, historical, hashes, *, attempt=1, commit="e", tree="f"):
    return {
        "experiment": "t26", "attempt": attempt, "authorization": CONSTRUCTION_TOKEN,
        "material_mode": "REAL_BLIND", "namespace": "t26",
        "store_identity": "T26-STORE-01",
        "execution_checkout_commit": commit * 64,
        "execution_checkout_tree": tree * 64,
        "candidate_commit": frozen["candidate_commit"],
        "candidate_tree": frozen["candidate_tree"],
        "runtime_root": frozen["runtime_root"],
        "preconstruction_freeze_sha256": frozen["freeze_sha256"],
        "freeze_component_count": frozen["component_count"],
        "freeze_component_root": frozen["component_root"],
        "freeze_root": frozen["freeze_root"],
        "execution_contract_sha256": hashes["execution_contract_sha256"],
        "authority_graph_sha256": hashes["authority_graph_sha256"],
        "production_graph_sha256": hashes["production_graph_sha256"],
        "metric_registry_sha256": hashes["metric_registry_sha256"],
        "private_storage_policy_sha256": hashes["private_storage_policy_sha256"],
        "qualification_exclusion_sha256": hashes["qualification_exclusion_sha256"],
        "live_web_firewall_registry_sha256":
            hashes["live_web_firewall_registry_sha256"],
        "historical_exclusion_identity": historical["artifact"],
        "historical_exclusion_root": historical["exclusion_root"],
    }


def test_candidate_identity_is_frozen():
    candidate = json.loads(
        (ROOT / "evaluations/t26/candidate_identity.json").read_text(encoding="utf-8"))
    assert candidate["candidate_commit"] == "6cb029c0f4edb4116c7f9a1f187cdc4671077a1f"
    assert candidate["candidate_tree"] == "6199df3a4537e5af480098a4bd009c357ecc2910"
    assert candidate["runtime_root"] == (
        "28f83990f5382400bac72cb34448ad5854c875d74655f1a571703f50d9cb453c")


def test_freeze_hashes_repository_bytes_not_checkout_line_endings():
    frozen = build_freeze(ROOT)
    relative = "t26_protocol/construction.py"
    entry = next(item for item in frozen["components"]
                 if item["path"] == relative)
    committed = subprocess.run(
        ["git", "show", f":{relative}"], cwd=ROOT,
        capture_output=True, check=True,
    ).stdout
    assert entry["sha256"] == hashlib.sha256(committed).hexdigest()
    assert entry["byte_size"] == len(committed)


def test_reproduction_view_excludes_only_declared_self_referential_roots():
    from scripts.t26_preconstruction import (
        _construction_rehearsal_reproduction_view,
    )

    report = {
        "status": "PASS",
        "runs": [{
            "status": "SEALED", "commitment_root": "timestamp-bound",
            "execution_checkout_commit": "commit-a",
            "execution_checkout_tree": "tree-a", "gate_root": "gate-a",
            "ledger_semantic_digest": "ledger-a",
            "manifest_roots": {"construction_semantic_root": "semantic-a",
                               "private_blind_root": "stable-blind"},
            "commitment_semantic": {"construction_gate_root": "gate-a",
                                    "construction_ledger_root": "ledger-root-a",
                                    "private_manifest_sha256": "manifest-a",
                                    "scenario_count": 512},
        }],
    }
    changed = json.loads(json.dumps(report))
    run = changed["runs"][0]
    run.update({"commitment_root": "timestamp-b", "execution_checkout_commit":
                "commit-b", "execution_checkout_tree": "tree-b",
                "gate_root": "gate-b", "ledger_semantic_digest": "ledger-b"})
    run["manifest_roots"]["construction_semantic_root"] = "semantic-b"
    run["commitment_semantic"]["construction_gate_root"] = "gate-b"
    run["commitment_semantic"]["construction_ledger_root"] = "ledger-root-b"
    run["commitment_semantic"]["private_manifest_sha256"] = "manifest-b"
    assert (_construction_rehearsal_reproduction_view(report) ==
            _construction_rehearsal_reproduction_view(changed))
    changed["runs"][0]["commitment_semantic"]["scenario_count"] = 511
    assert (_construction_rehearsal_reproduction_view(report) !=
            _construction_rehearsal_reproduction_view(changed))


def test_nine_dimension_exclusion_model_covers_all_sources():
    historical = build_historical_exclusion_document(ROOT)
    assert len(historical["dimensions"]) == 9
    assert set(historical["dimensions"]) == set(DIMENSIONS)
    assert historical["t25_private_rows_opened"] == 0
    assert set(historical["sources"]) >= {
        "t21_historical_milestones", "t22_protected", "t23_exposed",
        "t24_sealed_evaluated", "t25_sealed_evaluated_public",
        "t26_public_qualification", "t26_disposable_rehearsals",
        "t26_native_smoke_fixtures"}
    recomputed = build_historical_exclusion_document(ROOT)
    assert recomputed["exclusion_root"] == historical["exclusion_root"]


def test_synthetic_bundle_cardinality_and_steps():
    cases, gold, fixtures = synthetic_private_bundle(2)
    assert len(cases) == len(gold) == 512
    families = {case["family"] for case in cases}
    assert len(families) == 16
    for family in families:
        assert sum(1 for case in cases if case["family"] == family) == 32
    assert all(3 <= len(case["plan"]["steps"]) <= 12 for case in cases)
    audit = run_construction_audit(
        cases, gold, fixtures, build_historical_exclusion_document(ROOT))
    assert audit["status"] == "PASS"


def test_ledger_binds_full_experiment_identity(tmp_path):
    store = _make_store(tmp_path)
    frozen = build_freeze(ROOT)
    historical = build_historical_exclusion_document(ROOT)
    hashes = protocol_hashes(ROOT)
    bindings = _bindings(frozen, historical, hashes)
    ledger = T26ConstructionLedger.create_exclusive(store, bindings, TOKEN)
    chain = ledger.verify_event_chain()
    assert chain["event_chain_valid"] is True
    required_bindings = set(_bindings(frozen, historical, hashes))
    assert required_bindings <= set(ledger.document["bindings"])
    with pytest.raises(ConstructionLedgerError):
        T26ConstructionLedger.create_exclusive(store, bindings, TOKEN)
    ledger.fail("LEDGER_CREATED", "InjectedFailure", {"probe": True})
    assert ledger.state == "FAILED"
    with pytest.raises(ConstructionLedgerError):
        ledger.advance("MATERIALIZED")


def test_missing_binding_fails_closed(tmp_path):
    store = _make_store(tmp_path)
    bindings = {"experiment": "t26", "attempt": 1,
                "authorization": CONSTRUCTION_TOKEN,
                "material_mode": "REAL_BLIND", "namespace": "t26",
                "store_identity": "T26-STORE-01"}
    with pytest.raises(ValueError, match="binding incomplete"):
        T26ConstructionLedger.create_exclusive(store, bindings, TOKEN)


def test_unknown_binding_fails_closed(tmp_path):
    store = _make_store(tmp_path)
    frozen = build_freeze(ROOT)
    historical = build_historical_exclusion_document(ROOT)
    hashes = protocol_hashes(ROOT)
    bindings = _bindings(frozen, historical, hashes)
    bindings["rogue_binding"] = "x"
    with pytest.raises(ValueError, match="unknown bindings"):
        T26ConstructionLedger.create_exclusive(store, bindings, TOKEN)


def test_oracle_rejects_bare_boolean_and_tamper():
    cases, gold, fixtures = synthetic_private_bundle(2)
    result = _synthetic_oracle_result(ROOT, cases, gold, fixtures)
    assert verify_oracle_result(result)["status"] == "PASS"
    assert verify_oracle_result(result)["t25_private_rows_exposed_to_t26"] == 0
    tampered = dict(result)
    tampered["overall_overlap_count"] = 2
    with pytest.raises(ValueError):
        verify_oracle_result(tampered)


def test_author_provenance_is_required_and_verified_before_ledger(tmp_path):
    cases, gold, fixtures = synthetic_private_bundle(2)
    oracle = _synthetic_oracle_result(ROOT, cases, gold, fixtures)
    store = _make_store(tmp_path)
    with pytest.raises(ValueError, match="provenance binding set mismatch"):
        construct_real(ROOT, store, token=TOKEN, cases=cases, gold=gold,
                       fixtures=fixtures, oracle_result=oracle)
    assert not store.has("construction/ledger.json")

    provenance = synthetic_author_provenance(cases, gold, fixtures)
    provenance["t25_private_reads"] = 1
    with pytest.raises(ValueError, match="prohibited reads"):
        construct_real(ROOT, store, token=TOKEN, cases=cases, gold=gold,
                       fixtures=fixtures, oracle_result=oracle,
                       provenance=provenance)
    assert not store.has("construction/ledger.json")

    tampered_fixtures = [dict(fixtures[0])]
    tampered_fixtures[0]["content_base64"] = "QQ=="
    tampered_provenance = synthetic_author_provenance(
        cases, gold, tampered_fixtures)
    with pytest.raises(ValueError, match="fixture hash mismatch"):
        construct_real(ROOT, store, token=TOKEN, cases=cases, gold=gold,
                       fixtures=tampered_fixtures, oracle_result=oracle,
                       provenance=tampered_provenance)
    assert not store.has("construction/ledger.json")


def test_deleted_ledger_cannot_recreate_one_shot(tmp_path):
    store = _make_store(tmp_path)
    frozen = build_freeze(ROOT)
    historical = build_historical_exclusion_document(ROOT)
    bindings = _bindings(frozen, historical, protocol_hashes(ROOT))
    T26ConstructionLedger.create_exclusive(store, bindings, TOKEN)
    store.path("construction/ledger.json").unlink()
    with pytest.raises(ConstructionLedgerError, match="duplicate refused"):
        T26ConstructionLedger.create_exclusive(store, bindings, TOKEN)


def test_publication_gate_scans_deleted_history(tmp_path):
    repo = tmp_path / "public"
    repo.mkdir()
    secret = b"disposable-synthetic-private-blob\n"

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True,
                       capture_output=True)

    git("init")
    git("config", "user.email", "t26-rehearsal@example.invalid")
    git("config", "user.name", "T26 Rehearsal")
    exposed = repo / "evaluations/t26/real_blind/synthetic.bin"
    exposed.parent.mkdir(parents=True)
    exposed.write_bytes(secret)
    git("add", ".")
    git("commit", "-m", "synthetic exposure")
    exposed.unlink()
    git("add", "-u")
    git("commit", "-m", "remove synthetic exposure")
    git("update-ref", "refs/remotes/origin/test", "HEAD")

    content_sha = hashlib.sha256(secret).hexdigest()

    class FakeStore:
        _commitments = {"construction/inputs.json": {"sha256": content_sha}}

        @staticmethod
        def read(_relative):
            return {"artifacts": [{"logical_id": "construction/inputs.json",
                                    "classification": "REAL_BLIND_INPUT",
                                    "sha256": content_sha}]}

        @staticmethod
        def read_bytes(_relative):
            return secret

    report = run_publication_leak_gate(
        FakeStore(), repo, refs=("refs/remotes/origin/test",))
    assert report["status"] == "FAIL"
    assert report["blind_blob_count"] >= 1
    assert any(match["surface"] == "fetched_ref_history"
               for match in report["blind_blob_matches"])


def test_all_negative_gate_controls_refuse():
    report = run_negative_gate_controls(ROOT)
    assert report["status"] == "PASS"
    assert report["control_count"] == len(NEGATIVE_CONTROL_IDS) == 23
    assert report["not_refused"] == []
    assert report["material"] == "DISPOSABLE_SYNTHETIC_PRIVATE"


def test_full_construction_lifecycle_rehearsal(tmp_path):
    store = _make_store(tmp_path)
    cases, gold, fixtures = synthetic_private_bundle(2)
    oracle = _synthetic_oracle_result(ROOT, cases, gold, fixtures)
    provenance = synthetic_author_provenance(cases, gold, fixtures)
    result = construct_real(ROOT, store, token=TOKEN, cases=cases, gold=gold,
                            fixtures=fixtures, oracle_result=oracle,
                            provenance=provenance)
    assert result["status"] == "SEALED"
    assert result["ledger"]["state"] == "SEALED"
    assert result["ledger"]["attempt"] == 1
    assert [event["event_type"] for event in result["ledger"]["events"]] == [
        "LEDGER_CREATED", "MATERIALIZED", "AUDITED", "GATE_PASS", "MANIFESTED",
        "SEALED"]
    assert result["gate"]["state"] == "PASS"
    assert result["gate"]["check_count"] == len(GATE_CHECKS) == 24
    assert result["gate"]["fail_count"] == 0
    assert result["contract_leaf_audit"]["fail_count"] == 0
    assert result["contract_leaf_audit"]["unverifiable_count"] == 0
    assert result["contract_leaf_audit"]["total_leaves"] == 62
    manifest = store.read("construction/manifest.json")
    assert manifest["construction_contract_audit"]["total_leaves"] == 62
    assert (manifest["construction_contract_audit"]["leaf_root"] ==
            result["contract_leaf_audit"]["leaf_root"])
    assert len(manifest["construction_ledger_identity"]["ledger_root"]) == 64
    assert result["seal"]["state"] == "SEALED"
    assert result["seal"]["blind_content_included"] is False
    assert result["receipt"]["blind_content_included"] is False
    assert result["receipt"]["state"] == "SEALED"
    assert len(result["receipt"]["construction_ledger_root"]) == 64
    assert result["commitment"]["contract_leaf_total"] == 62
    assert len(result["commitment"]["contract_leaf_root"]) == 64
    assert result["store_verification"]["status"] == "PASS"
    assert result["store_verification"]["missing_artifacts"] == 0
    assert store.has(fixtures[0]["logical_id"])
    assert (store.commitment(fixtures[0]["logical_id"])["classification"] ==
            "PRIVATE_BLIND")
    assert result["publication_leak_gate"]["status"] == "PASS"
    assert result["publication_leak_gate"]["blind_blob_count"] == 0
    assert len(result["manifest_roots"]) == 4
    assert result["audit"]["candidate_executions"] == 0


def test_failure_rehearsal_semantics(tmp_path):
    store = _make_store(tmp_path)
    cases, gold, fixtures = synthetic_private_bundle(3)
    oracle = _synthetic_oracle_result(ROOT, cases, gold, fixtures)
    provenance = synthetic_author_provenance(cases, gold, fixtures)
    with pytest.raises(RuntimeError):
        construct_real(ROOT, store, token=TOKEN, cases=cases, gold=gold,
                       fixtures=fixtures, oracle_result=oracle,
                       provenance=provenance,
                       inject_failure_after_ledger=True)
    ledger = store.read("construction/ledger.json")
    assert ledger["state"] == "FAILED"
    assert ledger["attempt"] == 1
    assert ledger["failure"]["failure_phase"] == "LEDGER_CREATED"
    assert ledger["failure"]["failure_class"] == "RuntimeError"
    assert len(ledger["failure"]["evidence_hash"]) == 64
    with pytest.raises((ConstructionLedgerError, RuntimeError, ValueError)):
        construct_real(ROOT, store, token=TOKEN, cases=cases, gold=gold,
                       fixtures=fixtures, oracle_result=oracle,
                       provenance=provenance)


def test_store_verify_detects_tamper(tmp_path):
    store = _make_store(tmp_path)
    store.write_once("probe/one.json", {"a": 1})
    assert store.verify()["status"] == "PASS"
    store.path("probe/one.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="verification failed"):
        store.verify()


def test_store_verify_rejects_missing_index_root(tmp_path):
    store = _make_store(tmp_path)
    store.write_once("probe/one.json", {"a": 1})
    index = json.loads(store._index_path.read_text(encoding="utf-8"))
    index.pop("artifact_root")
    store._index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError, match="root_mismatches"):
        store.verify()


def test_private_store_rejects_bare_boolean_attestation():
    from t26_protocol.lifecycle import validate_blind_cases

    with pytest.raises(ValueError, match="oracle result required"):
        validate_blind_cases([], [], {"t25_private_overlap_attested": True},
                             {name: [] for name in DIMENSIONS})
