"""Fail-closed tests for the T25 remediation + preconstruction state.

Every artifact written by scripts/t25_preconstruction_build.py is re-verified
here, together with the T24-history freeze discipline (§1/§14), the new-candidate
identity (§18), the T24 exclusion firewall (§16), and the disposable-rehearsal
determinism record (§24). Negative controls must refuse.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from t21_protocol.util import read_json, sha256_file  # noqa: E402
from t25_protocol import doctor as t25_doctor  # noqa: E402
from t25_protocol.anchor_t24 import (ANCHOR_SCHEMA,  # noqa: E402
                                     verify_anchor as verify_t24_anchor)
from t25_protocol.author import load_spec  # noqa: E402
from t25_protocol.contract import (CANDIDATE_COMMIT, CANDIDATE_TREE,  # noqa: E402
                                   RUNTIME_ROOT, enumerate_leaf_requirements)
from t25_protocol.contract import load_t25_contract, validate_t25_contract  # noqa: E402
from t25_protocol.exclusions import load_exclusion_sources  # noqa: E402
from t25_protocol.freeze import FREEZE_PATH, FROZEN_POLICY, load_freeze  # noqa: E402
from t25_protocol.graph import load_graph, validate_graph  # noqa: E402
from t25_protocol.leakscan import scan_public_git  # noqa: E402
from t25_protocol.lock import verify_lock  # noqa: E402
from t25_protocol.policy import load_policy, path_forbidden  # noqa: E402
from t25_protocol.status_contract import (assert_status_valid,  # noqa: E402
                                          load_contract, status_set,
                                          validate_dispatch_rows, validate_status)
from t24_protocol.workspace import verify_source_identity as verify_t24_source_identity  # noqa: E402

T25 = ROOT / "evaluations" / "t25"
T24 = ROOT / "evaluations" / "t24"


def _tracked_paths() -> list[str]:
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def test_author_specification_is_preconstruction_only_and_history_free() -> None:
    spec = load_spec()
    assert spec["construction_authorized"] is False
    assert spec["status"] == "PRECONSTRUCTION_ONLY"
    assert spec["case_id_prefix"] == "t25"
    pool = spec["source_pool_constraints"]
    assert pool["no_t23_exposed_material"] is True
    assert pool["no_t24_sealed_material"] is True
    assert pool["no_t24_private_material_opened"] is True
    assert pool["no_t25_public_qualification_reuse"] is True
    assert "T24_SEALED_EVALUATED" in spec["historical_exclusions"]


def test_candidate_identity_is_the_new_authorized_candidate() -> None:
    document = read_json(T25 / "candidate_identity.json")
    candidate = document["t25_candidate"]
    assert document["schema_version"] == "t25-candidate-identity-v1"
    assert document["candidate_changed"] is True
    assert candidate["candidate_commit"] == CANDIDATE_COMMIT
    assert candidate["candidate_tree"] == CANDIDATE_TREE
    assert candidate["runtime_root"] == RUNTIME_ROOT
    assert candidate["candidate_parent"] == "d64160bf0ebb715a6a30647d06e420b7dde6b24e"
    assert candidate["unchanged_from_t23_candidate"] is False
    assert candidate["unchanged_from_t24_candidate"] is False
    assert candidate["changed_runtime_components"] == ["src/sciencemath/executive/runner.py"]
    # The frozen T24 candidate stays untouched.
    t24 = read_json(T24 / "candidate_identity.json")["t24_candidate"]
    assert candidate["candidate_commit"] != t24["candidate_commit"]


def test_master_contract_carries_exact_t25_tokens_and_t24_exclusion() -> None:
    contract = load_t25_contract(T25 / "t25_master_contract.json")
    assert contract.get("values.authorization") == \
        "T25_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
    assert contract.get("values.evaluation.evaluation_token") == \
        "T25_ONE_SHOT_OFFICIAL_EVALUATION"
    policy = contract.get("values.publication_policy")
    assert policy["REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION"] is False
    assert policy["T24_PRIVATE_MATERIAL_OPENING_ALLOWED"] is False
    assert policy["T25_CANDIDATE_EXECUTION_ON_T24_ROWS_ALLOWED"] is False
    exclusion = contract.get("values.t24_exclusion")
    assert exclusion["t24_must_not_be_rerun"] is True
    assert exclusion["t24_private_material_must_not_be_opened"] is True
    assert exclusion["t25_candidate_must_not_execute_on_t24_rows"] is True
    assert contract.get("values.candidate_identity.candidate_commit") == CANDIDATE_COMMIT


def test_master_contract_leaves_are_enumerable() -> None:
    contract = load_t25_contract(T25 / "t25_master_contract.json")
    leaves = enumerate_leaf_requirements(contract.document)
    assert leaves and all(leaf["requirement_id"].startswith("T25-CON-") for leaf in leaves)
    with TemporaryDirectory(prefix="t25-test-") as temp:
        broken = json.loads(json.dumps(contract.document))
        broken["values"]["candidate_identity"]["candidate_commit"] = \
            "e1be88fee99361bfd47dfa054a99637820cadda8"
        with pytest.raises(ValueError):
            validate_t25_contract(broken)


def test_t24_sealed_evaluated_anchor_is_hash_only_and_verifies() -> None:
    stored = read_json(T25 / "t24_sealed_evaluated_anchor.json")
    assert stored["schema_version"] == ANCHOR_SCHEMA
    assert stored["raw_values_included"] is False
    assert stored["t24_must_not_be_rerun"] is True
    assert stored["t24_private_material_must_not_be_opened"] is True
    assert stored["t25_candidate_must_not_execute_on_t24_rows"] is True
    assert stored["official_result"]["remediation_target"]["unmatched_rows"] == 4
    assert stored["official_result"]["remediation_target"]["allowed_count"] == 0
    assert stored["aggregate_fit"] == {"general_rows": 80, "partially_supported": 72,
                                       "uncertain": 4, "unknown": 4}
    report = verify_t24_anchor(ROOT)
    assert report["status"] == "PASS"
    # The anchor must never make T24 row material derivable: provenance dims
    # come only from public qualification rows and the disposable rehearsal.
    assert stored["dimensions"]["entity_identities"]["count"] == 0
    assert stored["dimensions"]["source_ids"]["count"] == 0
    assert stored["dimensions"]["chunk_ids"]["count"] == 0
    assert stored["dimensions"]["case_ids"]["count"] == 1280


def test_exclusion_sources_load_with_the_t24_anchor() -> None:
    registry = read_json(T25 / "t25_exclusion_sources.json")
    assert registry["schema_version"] == "t25-exclusion-sources-v2"
    assert registry["additional_anchors"] == ["T22_SEALED", "T23_EXPOSED_SEALED",
                                              "T24_SEALED_EVALUATED"]
    assert len(registry["sources"]) == 7
    assert registry["sources"]["t24_sealed_evaluated"]["kind"] == "sealed_evaluated_anchor"
    forbidden = load_exclusion_sources(ROOT, registry)
    assert len(forbidden) == 9
    assert sum(len(values) for values in forbidden.values()) > 1000
    broken = json.loads(json.dumps(registry))
    broken["sources"]["unknown_source"] = {
        "kind": "unknown_kind",
        "path": "evaluations/t25/t25_master_contract.json",
        "sha256": sha256_file(ROOT / "evaluations/t25/t25_master_contract.json")}
    with pytest.raises(ValueError):
        load_exclusion_sources(ROOT, broken)


def test_qualification_data_is_complete_and_excluded() -> None:
    report = read_json(T25 / "qualification" / "qualification_report.json")
    assert report["artifact"] == "T25_QUALIFICATION_REPORT"
    assert report["status"] == "PASS"
    assert report["rows"] == 1280
    assert report["route_agreement"] == 1.0
    assert report["reason_agreement"] == 1.0


def test_production_evaluation_graph_is_complete_private_and_gated() -> None:
    report = validate_graph(load_graph(T25 / "production_evaluation_graph.json"))
    assert report["status"] == "PASS"
    assert report["producer_count"] >= 27


def test_publication_policy_freezes_the_required_values() -> None:
    document = load_policy()
    policy = document["frozen_policy"]
    assert {key: policy[key] for key in FROZEN_POLICY} == FROZEN_POLICY
    assert policy["LIVE_WEB_ISOLATION_OPTION"] == \
        "OPTION_B_BLIND_MATERIAL_PRIVATE_UNTIL_EVALUATION_COMPLETES"
    assert policy["PRIVATE_STORE_EXAMPLE_ROOT"] == "C:/T25_PRIVATE_EVALUATION"


def test_author_lock_verifies_from_the_built_artifacts() -> None:
    lock = verify_lock(T25 / "author_lock.json")
    assert lock["status"] == "PASS"
    assert lock["candidate_commit"] == CANDIDATE_COMMIT
    assert lock["binding_count"] >= 40


def test_ten_live_web_negative_controls_all_refuse() -> None:
    live = t25_doctor._live_web_controls(ROOT)
    assert live["control_count"] >= 10
    assert live["all_denied"] is True
    assert live["controls"]["t24_artifact_hash_denied"] is True
    assert live["controls"]["t24_rehearsal_fingerprint_denied"] is True
    assert live["controls"]["t24_qualification_query_denied"] is True


def test_twelve_private_storage_negative_controls_all_refuse() -> None:
    storage = t25_doctor._private_storage_controls(ROOT)
    assert storage["all_refused"]
    assert storage["control_count"] == 12


def test_public_tree_scan_finds_no_real_t25_or_t24_blind_material() -> None:
    scan = scan_public_git(ROOT, blind_hashes=set())
    assert scan["status"] == "PASS"
    assert scan["blind_blob_count"] == 0
    tracked = _tracked_paths()
    assert not any(path_forbidden(path) for path in tracked)
    assert not any(path.startswith("rag/gk_holdout_t24/") for path in tracked)


def test_status_contract_is_fail_closed() -> None:
    contract = load_contract()
    assert contract["schema_version"] == "t25-status-taxonomy-contract-v1"
    for capability, block in contract["closed_status_sets"].items():
        assert frozenset(block["statuses"]) == status_set(capability)
        # UNKNOWN is never a member of any closed set: it must not terminate a
        # dispatch, so the T24 UNKNOWN failure mode is structurally excluded.
        assert "UNKNOWN" not in block["statuses"]
    assert status_set("GENERAL") == frozenset(
        {"VERIFIED", "STRONGLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNCERTAIN",
         "INSUFFICIENT_INFORMATION", "CONFLICTING_EVIDENCE"})
    ok, reason = validate_status("GENERAL", "PARTIALLY_SUPPORTED")
    assert ok and not reason
    for bad in ("MAYBE", None, "", "unknown", "UNKNOWN"):
        ok, reason = validate_status("GENERAL", bad)
        assert not ok and reason
        with pytest.raises(ValueError):
            assert_status_valid("GENERAL", bad)
    with pytest.raises(KeyError):
        status_set("NOT_A_CAPABILITY")
    rows = validate_dispatch_rows([
        {"case_id": "t25-ok", "selected_capability": "GENERAL",
         "status": "PARTIALLY_SUPPORTED"},
        {"case_id": "t25-bad", "selected_capability": "GENERAL",
         "status": "UNKNOWN"},
    ])
    assert rows["status"] == "FAIL"
    assert rows["violations"][0]["case_id"] == "t25-bad"
    assert rows["violations"][0]["reason"] == "unknown_status_must_not_terminate_a_dispatch"


def test_t24_private_material_stays_unread() -> None:
    """Only T24's public commitment chain and hash-only history are referenced;
    the private store itself is never opened by any T25 surface."""
    commitment = read_json(
        ROOT / "evaluations/t24/construction/T24_CONSTRUCTION_PUBLIC_COMMITMENT.json")
    freeze_sha = commitment["preconstruction_freeze_sha256"]
    assert len(freeze_sha) == 64 and all(c in "0123456789abcdef" for c in freeze_sha)
    anchor = read_json(T25 / "t24_sealed_evaluated_anchor.json")
    assert anchor["t24_history"]["material"] == \
        "T24_REAL_BLIND_HOLDOUT_SEALED_EVALUATED_NEVER_PUBLISHED"
    assert anchor["t24_history"]["store_identity"] == "T24-STORE-01"
    assert anchor["raw_values_included"] is False
    assert anchor["t24_private_material_must_not_be_opened"] is True
    assert anchor["t25_candidate_must_not_execute_on_t24_rows"] is True


def test_t24_freeze_bindings_interpret_the_authorized_remediation() -> None:
    """The T24-era source-identity verifier accepts the authorized drift only
    through the T25 successor freeze, once the freeze exists."""
    if not FREEZE_PATH.is_file():
        pytest.skip("T25 preconstruction freeze not yet written")
    identity = verify_t24_source_identity(ROOT)
    assert identity["status"] == "PASS"
    successor = identity.get("successor_interpretation")
    assert successor is not None
    assert successor["interpretation"] == "T25_REMEDIATION_ACTIVE"
    assert "src/sciencemath/executive/runner.py" in successor["drifted_components"]


@pytest.mark.parametrize("path", [
    "evaluations/t25/suites/inputs.jsonl",
    "evaluations/t25/suites/gold.jsonl",
    "evaluations/t25/suites/families/route_override_adversarial.jsonl",
    "rag/gk_holdout_t25/chunks.jsonl",
    "documents/t25_private/x.txt",
    "evaluations/t24/suites/inputs.jsonl",
    "rag/gk_holdout_t24/chunks.jsonl",
    "documents/t24_private/x.txt",
])
def test_forbidden_paths_parametrized(path: str) -> None:
    assert path_forbidden(path)


def test_freeze_policy_and_identity_after_finalize() -> None:
    if not FREEZE_PATH.is_file():
        pytest.skip("preconstruction freeze not yet written")
    freeze = load_freeze()
    assert freeze["frozen_policy"] == FROZEN_POLICY
    assert freeze["infrastructure_commit"] == "d64160bf0ebb715a6a30647d06e420b7dde6b24e"
    drifted = [component["path"] for component in freeze["components"]
               if not (ROOT / component["path"]).is_file()
               or sha256_file(ROOT / component["path"]) != component["sha256"]]
    assert not drifted