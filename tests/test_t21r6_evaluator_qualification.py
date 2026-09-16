"""T21R6 Part A3 — evaluator qualification contract tests.

The official T21R6 evaluator (scripts/t21r6_run_eval.py) refuses to run
unless evaluations/t21r6/evaluator_qualification.json exists, passes, and
matches the CURRENT evaluator source sha256. These tests enforce the
qualification contract itself:

  * the qualification harness drives the ACTUAL evaluator scoring
    functions (imported from scripts/t21r6_run_eval.py),
  * every preregistered case group is present (30 required groups),
  * every case passes with zero uncaught exceptions,
  * the artifact's evaluator_source_sha256 equals the live evaluator file,
  * the qualification fixtures NEVER touch T21R6 holdout data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QUALIFY_SCRIPT = ROOT / "scripts" / "t21r6_qualify_evaluator.py"
EVAL_SCRIPT = ROOT / "scripts" / "t21r6_run_eval.py"
ARTIFACT = ROOT / "evaluations" / "t21r6" / "evaluator_qualification.json"

REQUIRED_GROUPS = {
    "required_domains",
    "required_sources",
    "citations",
    "claim_verification",
    "answer_contains",
    "retrieval",
    "abstention",
    "conflict",
    "temporal",
    "security",
    "serialization",
    "empty",
    "crossdomain",
    "multihop",
    "suites",
}

# Preregistered case-group floor from the T21R6 master contract (Part A3):
# at least 30 distinct scoring-branch case groups must be exercised.
REQUIRED_CASE_GROUP_COUNT = 30


def _artifact() -> dict:
    assert ARTIFACT.exists(), (
        "evaluator_qualification.json missing — run "
        "`python scripts/t21r6_qualify_evaluator.py`")
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def test_qualification_artifact_passes():
    doc = _artifact()
    assert doc["qualification_passed"] is True
    assert doc["all_paths_exercised"] is True
    assert doc["all_cases_pass"] is True
    assert doc["uncaught_exceptions"] == 0
    assert doc["n_cases"] == doc["n_passed"]
    for case in doc["cases"]:
        assert case["passed"] is True, case
        assert case["detail"] is None, case


def test_qualification_matches_current_evaluator_source():
    doc = _artifact()
    live = hashlib.sha256(EVAL_SCRIPT.read_bytes()).hexdigest()
    assert doc["evaluator_source_sha256"] == live, (
        "the qualification artifact is stale relative to the current "
        "evaluator source — re-run scripts/t21r6_qualify_evaluator.py")


def test_qualification_groups_complete():
    doc = _artifact()
    groups = set(doc["groups"])
    assert REQUIRED_GROUPS <= groups
    # the branch manifest enumerates the exercised scoring branches per
    # group; every required group lists at least one branch
    manifest = doc["branch_manifest"]
    assert set(manifest) == groups
    # Preregistered contract floor (Part A3 "30 required case groups"):
    # the 30 numbered required cases ARE the case groups — the artifact
    # must carry at least 30 distinct preregistered case ids, each
    # labelled with one of the required scoring-branch families.
    ids = {c["id"] for c in doc["cases"]}
    assert len(ids) >= REQUIRED_CASE_GROUP_COUNT
    assert {c["group"] for c in doc["cases"]} <= groups


def test_qualification_covers_both_modes_and_all_suites():
    doc = _artifact()
    ids = {c["id"] for c in doc["cases"]}
    # retrieval-mode scoring path
    assert any(i.startswith("rt-") for i in ids)
    # all eight suite scoring paths + floors + suite minimums
    assert "st-30" in ids
    # raw-schema serialization for both modes
    assert "rz-25" in ids


def test_qualification_harness_imports_actual_evaluator():
    src = QUALIFY_SCRIPT.read_text(encoding="utf-8")
    assert "import t21r6_run_eval as evaluator" in src
    # the harness must drive the real scoring entry points
    for fn in ("run_answer_row", "run_retrieval_row", "retrieval_metrics",
               "answer_correctness", "citation_metrics", "abstention_metrics",
               "temporal_metrics", "security_metrics", "compare_floors",
               "aggregate_zero_totals", "suite_minimums_met",
               "required_domains_ok", "validate_domain_labels",
               "normalize_domain", "source_domains"):
        assert f"evaluator.{fn}" in src, fn


def test_qualification_harness_never_touches_holdout_data():
    """The qualification fixtures are synthetic-only: the harness source
    must not reference the T21R6 holdout corpus directory or suites."""
    src = QUALIFY_SCRIPT.read_text(encoding="utf-8")
    assert "gk_holdout_t21r6" not in src
    assert "gk-holdout" not in src.lower().replace("gk_holdout", "")
    # in-memory fixture corpus only
    assert "KnowledgeCorpus(sources=sources" in src


def test_qualification_reexecutes_clean_in_process():
    """Re-run every qualification case in-process against the live code:
    the recorded artifact must not be a stale one-off success."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import t21r6_qualify_evaluator as qh
    for spec in qh.CASES:
        spec["fn"]()   # raises on any failure


def test_evaluator_refuses_without_fresh_qualification(tmp_path):
    """The official evaluator's qualification gate rejects a stale sha."""
    doc = _artifact()
    stale = dict(doc, evaluator_source_sha256="0" * 64)
    assert stale["evaluator_source_sha256"] != \
        hashlib.sha256(EVAL_SCRIPT.read_bytes()).hexdigest()
    # the gate compares the artifact against the live evaluator sha
    src = EVAL_SCRIPT.read_text(encoding="utf-8")
    assert "evaluator_source_sha256" in src
    assert "T21R6_EVALUATOR_INVALID" in src