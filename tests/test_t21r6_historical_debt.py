"""T21R6 inherited historical debt protection (KNOWN_CANONICAL_HISTORICAL_DEBT).

The T21R6 entry gate inherited one freeze-hash mismatch from the canonical
base f71cdb6e7855ba20d58e38b05d7286457bc300ae: scripts/t21r4_run_eval.py
was edited by the T21R4 blind-validation commit itself, so the T21R4
evaluator freeze no longer matches the file. That debt is pinned
byte-exactly in evaluations/t21r6/inherited_historical_debt.json — NOT
rewritten, NOT relaxed.

These tests enforce the R6 historical protection rule:

  PASS  only when the inherited mismatch is EXACTLY the pinned canonical
        mismatch and the ledger structure is complete;
  FAIL  on any further drift of the pinned file, any inconsistency
        between the ledger and the artifacts it pins, or any expansion of
        the inherited debt list.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEBT_PATH = REPO_ROOT / "evaluations" / "t21r6" / \
    "inherited_historical_debt.json"
CANONICAL_BASE = "f71cdb6e7855ba20d58e38b05d7286457bc300ae"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def debt() -> dict:
    return json.loads(DEBT_PATH.read_text(encoding="utf-8"))


def test_debt_ledger_is_canonical_debt(debt):
    assert debt["classification"] == "KNOWN_CANONICAL_HISTORICAL_DEBT"
    assert debt["canonical_base_sha"] == CANONICAL_BASE


def test_debt_ledger_matches_reality(debt):
    """Every pinned mismatch must still exist byte-exactly as pinned:
    the file's current hash equals the pinned canonical actual hash AND
    disagrees with the pinned historical expected hash."""
    assert debt["inherited_mismatches"], "debt ledger is empty"
    for m in debt["inherited_mismatches"]:
        p = REPO_ROOT / m["path"]
        assert p.exists(), f"pinned debt file missing: {m['path']}"
        current = _sha256(p)
        assert current == m["canonical_actual_sha256"], \
            f"pinned historical file drifted: {m['path']} " \
            f"(pinned {m['canonical_actual_sha256']}, got {current})"
        assert current != m["historical_expected_sha256"], \
            f"pinned mismatch no longer mismatches: {m['path']}"


def test_debt_ledger_pinned_values_match_artifacts(debt):
    """The pinned historical expected hash must still equal the value
    recorded in the historical artifact that pins it."""
    for m in debt["inherited_mismatches"]:
        artifact = json.loads((REPO_ROOT / m["artifact"])
                              .read_text(encoding="utf-8"))
        node = artifact
        for key in m["ledger_field"].split("."):
            node = node[key]
        assert node == m["historical_expected_sha256"], \
            f"pinned expected hash disagrees with {m['artifact']}"


def test_debt_ledger_does_not_expand(debt):
    """The inherited debt is bounded: exactly one pinned mismatch, the
    canonical T21R4 evaluator freeze debt. Any addition would expand the
    debt and must fail."""
    paths = [m["path"] for m in debt["inherited_mismatches"]]
    assert paths == ["scripts/t21r4_run_eval.py"], \
        f"inherited debt expanded beyond the pinned entry: {paths}"


def test_debt_ledger_records_both_hash_polarities(debt):
    for m in debt["inherited_mismatches"]:
        assert m["historical_expected_sha256"] != \
            m["canonical_actual_sha256"]
        assert m["canonical_base_sha_at_mismatch"] == CANONICAL_BASE