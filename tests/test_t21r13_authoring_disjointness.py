"""T21R13 private-spec reauthoring: historical-disjointness tests.

Hash-only historical access: every historical comparison uses the
SHA-256 fingerprints of the authoritative prior-exclusion registry.
No raw historical corpus, holdout, or private spec is opened.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import t21r13_blind_author as author  # noqa: E402
import t21r13_uniqueness as uniqueness  # noqa: E402


@pytest.fixture(scope="module")
def material():
    world_spec, suites_spec = author.build_specs()
    return world_spec, suites_spec


@pytest.fixture(scope="module")
def exclusion_index():
    return author._exclusion_index()


def test_registry_identity():
    document = json.loads(
        author.PRIOR_FINGERPRINT_PATH.read_text(encoding="utf-8"))
    assert document["historical_milestone_count"] == 13
    assert len(document["historical_dimensions"]) == 8
    assert document["raw_values_included"] is False
    digest = hashlib.sha256(
        author.PRIOR_FINGERPRINT_PATH.read_bytes()).hexdigest()
    assert digest == (
        "7c65b86e00143a3529c7bd334ca3d6fa085822ccf84833693eb42498749d33f0")


def test_eight_dimension_historical_disjointness(material, exclusion_index):
    world_spec, suites_spec = material
    fingerprints = uniqueness.fingerprint_material(
        world_spec["sources"], world_spec["chunks"],
        suites_spec["rows"], world_spec["world"])
    for dimension in uniqueness.DIMENSIONS:
        overlap = fingerprints[dimension] & exclusion_index[dimension]
        assert overlap == set(), f"{dimension} historical overlap: {len(overlap)}"


def test_case_id_prefix_and_intra_r13_uniqueness(material):
    _, suites_spec = material
    rows = suites_spec["rows"]
    case_ids = [row["case_id"] for row in rows]
    assert len(case_ids) == len(set(case_ids))
    assert all(case_id.startswith("r13b-") for case_id in case_ids)


def test_source_chunk_id_uniqueness(material):
    world_spec, _ = material
    source_ids = [s["source_id"] for s in world_spec["sources"]]
    chunk_ids = [c["chunk_id"] for c in world_spec["chunks"]]
    assert len(source_ids) == len(set(source_ids))
    assert len(chunk_ids) == len(set(chunk_ids))
    assert all(not sid.startswith("gk-r11") and not sid.startswith("gk-r12")
               for sid in source_ids)


def test_authoring_negative_controls_eight_of_eight():
    report = author.authoring_negative_controls()
    assert report["status"] == "PASS"
    assert report["rejections_passed"] == 8
    assert all(report["rejections"].values())
    assert all(report["legacy_regressions"].values())
    assert report["raw_historical_values_used"] is False


def test_per_milestone_critical_isolation(material):
    world_spec, suites_spec = material
    fingerprints = uniqueness.fingerprint_material(
        world_spec["sources"], world_spec["chunks"],
        suites_spec["rows"], world_spec["world"])
    document = json.loads(
        author.PRIOR_FINGERPRINT_PATH.read_text(encoding="utf-8"))
    for milestone in ("T21R10_SEALED", "T21R11_INVALID_SEALED",
                      "T21R12_FAILED_PARTIAL_BLIND"):
        block = document["milestones"][milestone]
        for dimension in uniqueness.DIMENSIONS:
            overlap = (fingerprints[dimension]
                       & set(block["dimensions"][dimension]["fingerprints"]))
            assert overlap == set(), f"{milestone}/{dimension}: {len(overlap)}"


def test_open_remediation_isolation(material):
    world_spec, suites_spec = material
    values = uniqueness.remediation_fingerprint_material(
        world_spec["sources"], world_spec["chunks"], suites_spec["rows"])
    artifact = json.loads(
        author.REMEDIATION_EXCLUSION_PATH.read_text(encoding="utf-8"))
    excluded = uniqueness.validate_remediation_artifact(artifact)
    for dimension in uniqueness.REMEDIATION_DIMENSIONS:
        assert values[dimension] & excluded[dimension] == set()


def test_shadow_authoring_deterministic_and_quarantined():
    with tempfile.TemporaryDirectory(prefix="t21r13-shadow-1-") as first, \
            tempfile.TemporaryDirectory(prefix="t21r13-shadow-2-") as second:
        run_1 = author.shadow_author(Path(first))
        run_2 = author.shadow_author(Path(second))
    assert run_1["status"] == "UNIQUE"
    assert run_1["fingerprint_root"] == run_2["fingerprint_root"]
    assert run_1["historical_overlap_total"] == 0
    assert run_1["counts"]["rows"] == 4800
    for name in ("private_world_spec.json", "private_suites_spec.json"):
        assert not (Path(first) / name).exists()


def test_authoring_profile_frozen():
    profile = json.loads((ROOT / "evaluations" / "t21r13" /
                          "private_spec_authoring_profile.json").read_text(
                              encoding="utf-8"))
    assert profile["artifact"] == "T21R13_PRIVATE_SPEC_AUTHORING_PROFILE"
    assert profile["namespace"]["case_id_prefix"] == "r13b-"
    assert profile["historical_access_policy"]["hash_only"] is True
    assert profile["suite_composition"]["total"] == 4800
