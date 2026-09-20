"""T21R14 authoring disjointness tests (hash-only historical access).

Every historical comparison uses the SHA-256 fingerprints of the
authoritative 14-milestone prior-exclusion registry.  No raw historical
corpus, holdout, private spec, or quarantined partial result is opened.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import t21r14_blind_author as author  # noqa: E402
import t21r14_uniqueness as uniqueness  # noqa: E402


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
    assert document["historical_milestone_count"] == 14
    assert document["historical_dimensions"] == 8
    assert document["raw_values_included"] is False
    assert len(document["milestone_order"]) == 14
    assert "T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE" in document["milestones"]


def test_eight_dimension_historical_disjointness(material, exclusion_index):
    world_spec, suites_spec = material
    fingerprints = uniqueness.fingerprint_material(
        world_spec["sources"], world_spec["chunks"],
        suites_spec["rows"], world_spec["world"])
    for dimension in uniqueness.DIMENSIONS:
        overlap = fingerprints[dimension] & exclusion_index[dimension]
        assert overlap == set(), f"{dimension} historical overlap: {len(overlap)}"


def test_case_id_prefix_and_intra_r14_uniqueness(material):
    _, suites_spec = material
    rows = suites_spec["rows"]
    case_ids = [row["case_id"] for row in rows]
    assert len(case_ids) == len(set(case_ids))
    assert all(case_id.startswith("r14b-") for case_id in case_ids)


def test_source_chunk_id_uniqueness(material):
    world_spec, _ = material
    source_ids = [s["source_id"] for s in world_spec["sources"]]
    chunk_ids = [c["chunk_id"] for c in world_spec["chunks"]]
    assert len(source_ids) == len(set(source_ids))
    assert len(chunk_ids) == len(set(chunk_ids))
    assert all(not sid.startswith("gk-r13") for sid in source_ids)


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
                      "T21R12_FAILED_PARTIAL_BLIND",
                      "T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE"):
        block = document["milestones"][milestone]
        for dimension in uniqueness.DIMENSIONS:
            overlap = (fingerprints[dimension]
                       & set(block["dimensions"][dimension]["fingerprints"]))
            assert overlap == set(), f"{milestone}/{dimension}: {len(overlap)}"


def test_t21r13_overlap_zero_all_dimensions(material):
    """Explicit T21R13 isolation across all eight dimensions (section 34)."""
    world_spec, suites_spec = material
    fingerprints = uniqueness.fingerprint_material(
        world_spec["sources"], world_spec["chunks"],
        suites_spec["rows"], world_spec["world"])
    document = json.loads(
        author.PRIOR_FINGERPRINT_PATH.read_text(encoding="utf-8"))
    block = document["milestones"]["T21R13_SEALED_PARTIAL_OFFICIAL_EXPOSURE"]
    overlaps = {}
    for dimension in uniqueness.DIMENSIONS:
        overlap = (fingerprints[dimension]
                   & set(block["dimensions"][dimension]["fingerprints"]))
        overlaps[dimension] = len(overlap)
        assert overlap == set()
    assert sum(overlaps.values()) == 0


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
    with tempfile.TemporaryDirectory(prefix="t21r14-shadow-1-") as first, \
            tempfile.TemporaryDirectory(prefix="t21r14-shadow-2-") as second:
        run_1 = author.shadow_author(Path(first))
        run_2 = author.shadow_author(Path(second))
    assert run_1["status"] == "UNIQUE"
    assert run_1["fingerprint_root"] == run_2["fingerprint_root"]
    assert run_1["historical_overlap_total"] == 0
    assert run_1["counts"]["rows"] == 4800
    for name in ("private_world_spec.json", "private_suites_spec.json"):
        assert not (Path(first) / name).exists()


def test_no_quarantined_r13_partial_results_read():
    """R14 tooling must never READ the quarantined R13 partial results.

    Path-absence assertions (prohibited-path lists in the preconstruction
    contract) are permitted; opening raw_results.jsonl for reading is not.
    """
    import ast
    forbidden = ("t21r13/raw_results.jsonl",
                 "OFFICIAL_PARTIAL_RESULTS_QUARANTINE",
                 "T21R13_EVALUATION_PROVENANCE")
    files = ("t21r14_blind_author.py", "t21r14_world.py",
             "t21r14_build_suites.py", "t21r14_uniqueness.py",
             "t21r14_spec_author.py", "t21r14_fixtures.py")
    violations = []
    for name in files:
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                opened = (isinstance(func, ast.Attribute)
                          and func.attr in {"read_text", "read_bytes", "open"})
                if not opened:
                    continue
                rendered = ast.dump(node)
                for marker in forbidden:
                    if marker in rendered:
                        violations.append(f"{name}:{marker}")
    assert violations == [], violations
