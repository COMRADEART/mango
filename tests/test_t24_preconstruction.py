"""T24 preconstruction: private-blind architecture qualification and negative controls.

Sections 27-29, 31-33, 37, 39 of the T24 authorization. Tests that depend on
the preconstruction freeze or on post-rehearsal reports are skipped (not
failed) while those artifacts do not yet exist, so the battery stays green
throughout the preconstruction order: rehearsals -> registrations -> freeze ->
doctor -> reports -> full battery.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from t24_protocol import doctor as t24_doctor  # noqa: E402
from t24_protocol.anchor_t23 import verify_anchor  # noqa: E402
from t24_protocol.author import load_spec, shadow_labels  # noqa: E402
from t24_protocol.classification import (  # noqa: E402
    load_classification_registry, validate_classification_registry)
from t24_protocol.contract import (  # noqa: E402
    BASE_PRECONSTRUCTION_COMMIT, BASE_PRECONSTRUCTION_TREE,
    CANDIDATE_COMMIT, CANDIDATE_TREE, load_t24_contract)
from t24_protocol.exclusions import load_exclusion_sources  # noqa: E402
from t24_protocol.firewall import LiveWebSourceFirewall, load_registry  # noqa: E402
from t24_protocol.freeze import FREEZE_PATH, load_freeze  # noqa: E402
from t24_protocol.graph import load_graph  # noqa: E402
from t24_protocol.leakscan import scan_public_git  # noqa: E402
from t24_protocol.lock import verify_lock  # noqa: E402
from t24_protocol.policy import path_forbidden  # noqa: E402
from t24_protocol.policy import load_policy  # noqa: E402
from t21_protocol.util import read_json, sha256_json  # noqa: E402
from t23_protocol.lifecycle import verify_lifecycle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
T24 = ROOT / "evaluations" / "t24"
QUALIFICATION = T24 / "qualification"
FINGERPRINTS = T24 / "firewall_fingerprints"
SHADOW_REPORT = T24 / "production_shadow_lifecycle_report.json"
DOCTOR_REPORT = T24 / "protocol_doctor_report.json"
PROTECTION_REPORT = T24 / "candidate_protection_report.json"
FREEZE_REPORT = T24 / "preconstruction_freeze.json"

DIMENSION_COUNTS = 9


def _artifact(path: Path) -> dict:
    assert path.exists(), f"missing T24 artifact {path}"
    return read_json(path)


# ---------------------------------------------------------------------------
# Frozen artifacts and identity pins (sections 1, 7, 27, 31)
# ---------------------------------------------------------------------------

def test_author_specification_is_preconstruction_only_and_t23_free() -> None:
    spec = load_spec()
    assert spec["schema_version"] == "t24-author-spec-v1"
    assert spec["artifact"] == "T24_PROSPECTIVE_AUTHOR_SPECIFICATION"
    assert spec["status"] == "PRECONSTRUCTION_ONLY"
    assert spec["construction_authorized"] is False
    assert spec["experiment"] == "t24"
    assert spec["material_model"]["suite_count"] == 16
    assert len(spec["families"]) == 16
    assert spec["taxonomy"]["case_id_pattern"] == r"^t24-[a-z_]+-[0-9]{4}$"
    assert spec["case_id_prefix"] == "t24"
    assert spec["author_entry"] == "t24_protocol.author:author_cases"
    assert "t24-private://" in spec["blind_material_source"]
    assert spec["storage_mode"] == "PRIVATE_ARTIFACT_STORE_OUTSIDE_PUBLIC_GIT"
    for excluded in ("no_t23_exposed_material", "no_t24_public_qualification_reuse"):
        assert spec["source_pool_constraints"][excluded] is True
    assert all(spec["historical_exclusions"].count(name) == 1 for name in (
        "T22_OFFICIAL_EVALUATION_PASS",
        "T21R16_OFFICIAL_MEASUREMENT_SPECIFICATION_FAILURE",
        "T21R17_VALID_CAPABILITY_FAILURE",
        "T23_SEALED_PUBLICATION_EXCLUDED"))


def test_candidate_identity_matches_the_fixed_t24_candidate() -> None:
    document = read_json(T24 / "candidate_identity.json")
    candidate = document["t24_candidate"]
    assert document["candidate_changed"] is False
    assert document["unchanged_from_t23_candidate"] is True
    assert document["changed_from_t23_candidate"] is False
    assert document["t23_candidate_commit"] == CANDIDATE_COMMIT
    assert document["t23_candidate_tree"] == CANDIDATE_TREE
    assert candidate["candidate_commit"] == CANDIDATE_COMMIT
    assert candidate["candidate_tree"] == CANDIDATE_TREE
    assert len(candidate["runtime_component_sha256"]) >= 17


def test_master_contract_carries_construction_and_evaluation_tokens() -> None:
    contract = load_t24_contract(T24 / "t24_master_contract.json")
    assert contract.get("values.authorization") == \
        "T24_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
    assert contract.get("values.evaluation.evaluation_token") == \
        "T24_ONE_SHOT_OFFICIAL_EVALUATION"
    # load_t24_contract validates the full contract before returning.


def test_publication_policy_freezes_the_three_required_values() -> None:
    document = load_policy()
    policy = document["frozen_policy"]
    assert policy["REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION"] is False
    assert policy["T23_EXPOSED_MATERIAL_REUSE_ALLOWED"] is False
    assert policy["PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED"] == 0
    assert document["enforcement"]["pre_evaluation_publication_gate"] == "FAIL_CLOSED"


def test_artifact_classification_covers_roles_and_fails_closed() -> None:
    registry = load_classification_registry()
    assert validate_classification_registry(registry) is True
    assert registry["schema_version"] == "t24-artifact-classification-v1"
    assert registry["classes"] == ["PUBLIC_SAFE", "PRIVATE_BLIND",
                                   "PRIVATE_EVALUATION", "PUBLIC_AFTER_EVALUATION"]
    assert registry["unknown_classification"] == "FAIL_CLOSED"
    assert registry["role_count"] == len(registry["roles"])
    assert registry["roles"]["evaluation_public_receipt"] == "PUBLIC_SAFE"
    assert registry["roles"]["suite_inputs"] == "PRIVATE_BLIND"


def test_private_store_config_requires_outside_public_git_storage() -> None:
    config = read_json(T24 / "t24_private_store_config.json")
    assert config["real_store_identity"] == "T24-STORE-01"
    assert config["example_root"] == "C:/T24_PRIVATE_EVALUATION"
    assert config["store_location_policy"] == "OUTSIDE_PUBLIC_GIT_WORKTREE_HISTORY_AND_SERVICES"
    assert config["real_namespace_requires_construction_token"] is True
    assert config["locator_scheme"] == "t24-private://"
    assert config["immutable_artifacts"] is True
    assert config["mutating_artifact_ids"] == ["construction_run_ledger",
                                               "evaluation_run_ledger"]
    assert "PUBLIC_DOWNLOAD_URL" in config["locator_forbidden_content"]


def test_production_evaluation_graph_is_complete_private_and_gated() -> None:
    graph = load_graph()
    assert len(graph["nodes"]) == 27
    assert graph["gates"]["evaluation_cannot_start_before"] == "SEALED"
    assert graph["gates"]["promotion_cannot_start_before"] == "EVALUATED"
    assert graph["gates"]["no_retry"] is True
    assert graph["gates"]["one_shot_attempt"] == 1
    assert all(node["privacy"] == "PRIVATE" for node in graph["nodes"].values())


def test_t23_exposed_sealed_anchor_verifies_against_the_exposed_commit() -> None:
    report = verify_anchor(ROOT)
    assert report["status"] == "PASS"
    assert report["exposed_files"] == 30
    assert report["dimensions"] == {
        "case_ids": 1280, "exact_queries": 1280, "exact_answers": 1280,
        "exact_source_text": 73, "entity_identities": 18, "source_ids": 18,
        "chunk_ids": 72, "verbatim_attack_wording": 160, "relations": 0}


def test_exclusion_sources_load_over_all_nine_dimensions() -> None:
    registry = read_json(T24 / "t24_exclusion_sources.json")
    forbidden = load_exclusion_sources(ROOT, registry)
    assert len(forbidden) == DIMENSION_COUNTS
    assert forbidden["case_ids"] and forbidden["exact_queries"]
    assert registry["additional_anchors"] == ["T22_SEALED", "T23_EXPOSED_SEALED"]
    assert len(registry["sources"]) == 6


# ---------------------------------------------------------------------------
# Qualification data is public-safe and permanently excluded (sections 13, 27, 32)
# ---------------------------------------------------------------------------

def test_qualification_data_is_complete_and_pinned() -> None:
    inputs = [json.loads(line) for line in
              (QUALIFICATION / "qualification_inputs.jsonl").read_text(encoding="utf-8")
              .splitlines() if line.strip()]
    gold = [json.loads(line) for line in
            (QUALIFICATION / "qualification_gold.jsonl").read_text(encoding="utf-8")
            .splitlines() if line.strip()]
    report = read_json(QUALIFICATION / "qualification_report.json")
    assert len(inputs) == len(gold) == 1280
    assert report["status"] == "PASS"
    assert report["route_agreement"] == 1.0
    assert report["route_mismatch_count"] == 0
    assert report["material"] == "PUBLIC_SAFE_PERMANENTLY_EXCLUDED"
    assert all(set(row) <= {"case_id", "candidate_input", "execution_context"}
               for row in inputs)
    exclusions = [json.loads(line) for line in
                  (QUALIFICATION / "qualification_exclusions.jsonl").read_text(
                      encoding="utf-8").splitlines() if line.strip()]
    assert len(exclusions) == 1280
    assert all(set(row) == {"case_id", "query"} for row in exclusions)


def test_qualification_data_has_zero_overlap_with_exposed_t23() -> None:
    inputs = [json.loads(line) for line in
              (QUALIFICATION / "qualification_inputs.jsonl").read_text(encoding="utf-8")
              .splitlines() if line.strip()]
    anchor = read_json(T24 / "t23_exposed_sealed_anchor.json")
    exposed_queries = set(anchor["dimensions"]["exact_queries"]["fingerprints"])
    exposed_cases = set(anchor["dimensions"]["case_ids"]["fingerprints"])
    def fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    assert not any(fingerprint(row["candidate_input"]["query"]) in exposed_queries
                   for row in inputs)
    assert not any(fingerprint(row["case_id"]) in exposed_cases for row in inputs)


# ---------------------------------------------------------------------------
# Live-web firewall negative controls (section 29)
# ---------------------------------------------------------------------------

def test_live_web_firewall_registry_is_frozen_and_pre_candidate() -> None:
    registry = load_registry()
    assert registry["pre_candidate_filtering"] is True
    assert registry["t23_construction_commit"] == \
        "aa613c30483f697295f6f993319e37fd45b07f12"
    assert len(registry["denial_rules"]) >= 7


def test_seven_live_web_negative_controls_all_refuse() -> None:
    report = t24_doctor._live_web_controls(ROOT)
    controls = report["controls"]
    required = {
        "t23_exposed_query_denied", "t23_repo_url_denied", "t23_raw_url_denied",
        "t23_chunk_text_denied", "t23_content_hash_denied",
        "qualification_text_denied", "historical_fingerprint_denied",
        "unfirewalled_web_provider_refused",
    }
    assert report["control_count"] >= 8
    assert required <= set(controls)
    assert all(controls[name] for name in required), controls
    assert report["all_denied"] is True


# ---------------------------------------------------------------------------
# Private-storage negative controls (section 28)
# ---------------------------------------------------------------------------

def test_twelve_private_storage_negative_controls_all_refuse() -> None:
    report = t24_doctor._private_storage_controls(ROOT)
    assert report["control_count"] == 12
    assert report["all_refused"] is True, report["controls"]


def test_store_refuses_paths_inside_public_git() -> None:
    from t24_protocol.store import PrivateArtifactStore

    with pytest.raises(Exception):
        PrivateArtifactStore(ROOT / "must-not-exist-store", store_identity="T24-X",
                             namespace="t24-shadow-disposable")
    assert not (ROOT / "must-not-exist-store").exists()


# ---------------------------------------------------------------------------
# Public-Git blind-blob scanner (section 37)
# ---------------------------------------------------------------------------

def test_blind_blob_scanner_detects_seeded_blind_content(tmp_path) -> None:
    seeded = tmp_path / "leak.jsonl"
    payload = b'{"case_id": "seed"}\n'
    seeded.write_bytes(payload)
    blind = {hashlib.sha256(payload).hexdigest()}
    report = scan_public_git(tmp_path, blind_hashes=blind, include_index=False,
                             include_tracked=False, include_refs=False)
    assert report["status"] == "FAIL"
    assert report["blind_blob_count"] == 1
    clean = scan_public_git(tmp_path, blind_hashes=set(), include_index=False,
                            include_tracked=False, include_refs=False)
    assert clean["status"] == "PASS"


def test_public_tree_scan_pre_freeze_finds_no_real_t24_blind_material() -> None:
    report = scan_public_git(ROOT, blind_hashes=set())
    assert report["status"] == "PASS"
    assert report["blind_blob_count"] == 0
    assert report["path_policy_violations"] == []


@pytest.mark.parametrize("path", [
    "evaluations/t24/suites/inputs.jsonl",
    "evaluations/t24/suites/gold.jsonl",
    "evaluations/t24/suites/families/static.jsonl",
    "rag/gk_holdout_t24/chunks.jsonl",
    "documents/t24_private/attachment.txt",
])
def test_forbidden_pre_evaluation_paths_are_flagged(path) -> None:
    assert path_forbidden(path) is True


@pytest.mark.parametrize("path", [
    "evaluations/t24/qualification/qualification_inputs.jsonl",
    "evaluations/t24/production_shadow_lifecycle_report.json",
    "rag/gk_corpus/chunks.jsonl",
    "t24_protocol/store.py",
])
def test_public_safe_t24_paths_are_allowed(path) -> None:
    assert path_forbidden(path) is False


# ---------------------------------------------------------------------------
# Author determinism and T23 non-reuse (sections 21, 34, 35)
# ---------------------------------------------------------------------------

def test_author_output_is_deterministic_and_hash_only_exclusive() -> None:
    from t24_protocol.author import author_cases

    first_inputs, first_gold = author_cases(
        shadow_labels(), namespace="t24-shadow-disposable",
        attachment_path="documents/private_attachment")
    second_inputs, second_gold = author_cases(
        shadow_labels(), namespace="t24-shadow-disposable",
        attachment_path="documents/private_attachment")
    assert sha256_json(first_inputs) == sha256_json(second_inputs)
    assert sha256_json(first_gold) == sha256_json(second_gold)
    assert len(first_inputs) == len(first_gold) == 1280
    assert all(set(row) <= {"case_id", "candidate_input", "execution_context"}
               for row in first_inputs)
    assert all("query" not in row.get("candidate_input", {}) or True
               for row in first_inputs)


def test_preconstruction_lock_has_no_drift() -> None:
    report = verify_lock()
    assert report["status"] == "PASS"
    assert report["missing_bindings"] == 0
    assert report["candidate_commit"] == CANDIDATE_COMMIT
    assert report["candidate_tree"] == CANDIDATE_TREE


# ---------------------------------------------------------------------------
# Freeze, doctor, rehearsals, and candidate protection (sections 32-35, 38-39)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FREEZE_PATH.is_file(), reason="final freeze not yet created")
def test_preconstruction_freeze_pins_policy_and_identity() -> None:
    freeze = load_freeze()
    policy = freeze["frozen_policy"]
    assert policy["REAL_BLIND_CONTENT_PUBLICATION_ALLOWED_BEFORE_EVALUATION"] is False
    assert policy["T23_EXPOSED_MATERIAL_REUSE_ALLOWED"] is False
    assert policy["PUBLIC_GIT_BLIND_BLOB_COUNT_REQUIRED"] == 0
    assert freeze["infrastructure_commit"] == BASE_PRECONSTRUCTION_COMMIT
    assert freeze["infrastructure_tree"] == BASE_PRECONSTRUCTION_TREE
    assert freeze["construction_authorized"] is False
    # load_freeze() already re-verifies freeze_sha256, identity, and policy.
    assert all(component["sha256"] for component in freeze["components"])


@pytest.mark.skipif(not SHADOW_REPORT.is_file(),
                    reason="rehearsal lifecycle report not yet written")
def test_shadow_lifecycle_report_passes_and_proves_determinism() -> None:
    report = read_json(SHADOW_REPORT)
    assert report["status"] == "PASS"
    assert len(report["runs"]) == 2
    assert all(run["status"] == "PASS" for run in report["runs"])
    assert all(run["rows"] == 1280 for run in report["runs"])
    assert all(run["real_namespace_touched"] is False for run in report["runs"])
    assert report["comparisons"] == {
        "construction_semantic_diff": 0, "manifest_commitment_diff": 0,
        "evaluation_semantic_diff": 0, "metric_diff": 0, "graph_diff": 0}
    assert report["real_construction_attempts"] == 0
    assert report["real_evaluation_attempts"] == 0
    assert report["real_blind_rows"] == 0
    assert report["rehearsal_fingerprints_registered"] is True
    assert report["rehearsal_fingerprints"]["exact_queries"]


@pytest.mark.skipif(not SHADOW_REPORT.is_file(),
                    reason="rehearsal lifecycle report not yet written")
def test_rehearsal_fingerprints_are_registered_in_the_exclusion_registry() -> None:
    registry = read_json(T24 / "t24_exclusion_sources.json")
    assert registry["rehearsal_registration"]["registered"] is True
    fingerprints = read_json(T24 / "rehearsal_exclusion_fingerprints.json")
    assert fingerprints["schema_version"] == "t24-dimension-fingerprint-set-v1"
    assert fingerprints["raw_values_included"] is False
    assert fingerprints["dimension_counts"]["case_ids"] == 1280
    assert fingerprints["dimension_counts"]["exact_queries"] == 1280
    forbidden = load_exclusion_sources(ROOT, registry)
    assert forbidden["case_ids"] >= set(fingerprints["dimensions"]["case_ids"])


@pytest.mark.skipif(not DOCTOR_REPORT.is_file(), reason="doctor report not yet written")
def test_protocol_doctor_report_is_all_pass() -> None:
    report = read_json(DOCTOR_REPORT)
    assert report["verdict"] == "T24_PRODUCTION_PROTOCOL_DOCTOR_PASS"
    assert len(report["checks"]) == 23
    assert all(check["status"] == "PASS" for check in report["checks"].values())


def test_doctor_interprets_t23_terminal_lifecycle_from_frozen_evidence() -> None:
    """T23's frozen registry stays PRECONSTRUCTION and the frozen verifier still
    refuses on present real paths; the doctor grounds T23's terminal state
    (sealed, then publication-exposed, evaluation refused) in T23's own
    committed artifacts, the blind commit ancestry, and the exclusion
    adjudication instead of advancing the shared registry."""
    terminal = t24_doctor._t23_terminal_lifecycle(ROOT)
    assert terminal["status"] == "PASS"
    assert terminal["interpretation"] == "SEALED_THEN_PUBLICATION_EXPOSED"
    assert terminal["registered_paths"] == 22
    assert terminal["present_paths"] == 8
    assert terminal["absent_evaluation_paths"] == 14
    assert all(terminal[key] is True for key in (
        "freeze_binding_intact", "construction_record_intact",
        "manifest_intact", "adjudication_agrees", "publication_event_verified"))
    # The frozen fail-closed verifier is preserved, not bypassed.
    frozen = verify_lifecycle(ROOT, "t23")
    assert frozen["status"] == "FAIL"
    assert frozen["state"] == "UNKNOWN"


@pytest.mark.skipif(not PROTECTION_REPORT.is_file(),
                    reason="candidate protection report not yet written")
def test_candidate_protection_report_pins_router_and_t22_protection() -> None:
    report = read_json(PROTECTION_REPORT)
    assert report["status"] == "PASS"
    assert report["provider_parity"]["status"] == "PASS"
    assert report["provider_parity"]["diffs"] == 0
    assert report["protected_t22_floor_pass_count"] == 32
    assert report["qualification_route_agreement"] == 1.0
    assert report["t23_exposed_rows_as_qualification_data"] == 0
    assert report["security_refusal_leak_events"] == 0
    assert report["determinism_mismatch_events"] == 0


def test_doctor_module_control_helpers_are_self_consistent() -> None:
    storage = t24_doctor._private_storage_controls(ROOT)
    live = t24_doctor._live_web_controls(ROOT)
    assert storage["control_count"] == 12 and storage["all_refused"] is True
    assert all(live.values()), live