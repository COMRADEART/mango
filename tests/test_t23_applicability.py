"""No bypass: independently exercise all 26 public-safe replacement checks."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from t23_protocol import applicability


ROOT = Path(__file__).resolve().parents[1]


def test_all_historical_replacements() -> None:
    ledger = applicability._json(ROOT, applicability.LEDGER)
    assert ledger == applicability.build_ledger(ROOT)
    assert len(ledger["entries"]) == 26
    reports = [applicability.verify_replacement(ROOT, entry)
               for entry in ledger["entries"]]
    assert len(reports) == 26
    assert all(report["status"] == "PASS" for report in reports)


def test_exact_historical_failure_set_is_applicable(monkeypatch) -> None:
    ledger = applicability.build_ledger(ROOT)
    observed = deepcopy(applicability._json(ROOT, applicability.RESULT))
    assert set(observed["failed_nodeids"]) == {
        entry["test_node_id"] for entry in ledger["entries"]
    }
    if applicability.REPLACEMENT_TEST not in observed["passed_nodeids"]:
        observed["passed_nodeids"].append(applicability.REPLACEMENT_TEST)
        observed["passed_nodeids"].sort()
        observed["counts"]["passed"] += 1
        observed["executed"] += 1
        observed["collected"] += 1
    original = applicability._json

    def source(root: Path, relative: str):
        if relative == applicability.RESULT:
            return observed
        if relative == applicability.LEDGER:
            return ledger
        return original(root, relative)

    monkeypatch.setattr(applicability, "_json", source)
    report = applicability.validate_applicability(ROOT)
    assert report["status"] == "PASS"
    assert report["recognized_historical_failures"] == 26
    assert report["stale_preconstruction"] == 9
    assert report["superseded_historical"] == 17


def test_applicability_rejects_changed_test_hash(monkeypatch) -> None:
    original = applicability._sha

    def changed(root: Path, relative: str) -> str:
        if relative == "tests/test_t22_preconstruction.py":
            return "0" * 64
        return original(root, relative)

    monkeypatch.setattr(applicability, "_sha", changed)
    with pytest.raises(ValueError, match="historical test changed"):
        applicability.build_ledger(ROOT)


def test_applicability_rejects_missing_promotion_evidence(monkeypatch) -> None:
    monkeypatch.setattr(applicability, "verify_lifecycle", lambda *_: {"status": "FAIL"})
    with pytest.raises(ValueError, match="T22 promotion"):
        applicability.build_ledger(ROOT)


def test_applicability_rejects_unrecognized_failure(monkeypatch) -> None:
    ledger = applicability.build_ledger(ROOT)
    observed = {
        "schema_version": "t23-unrestricted-pytest-result-v1",
        "execution_complete": True, "collected": 28, "executed": 28,
        "deselected": 0, "skipped_nodeids": [], "xfail_nodeids": [],
        "xpass_nodeids": [], "pytest_exit_code": 1,
        "counts": {"passed": 1, "failed": 27, "skipped": 0, "xfail": 0, "xpass": 0},
        "failed_nodeids": sorted([entry["test_node_id"] for entry in ledger["entries"]]
                                 + ["tests/test_new_live.py::test_unexpected"]),
        "passed_nodeids": [applicability.REPLACEMENT_TEST],
    }
    original = applicability._json

    def source(root: Path, relative: str):
        if relative == applicability.RESULT:
            return observed
        if relative == applicability.LEDGER:
            return ledger
        return original(root, relative)

    monkeypatch.setattr(applicability, "_json", source)
    report = applicability.validate_applicability(ROOT)
    assert report["status"] == "FAIL"
    assert report["unrecognized_failures"] == ["tests/test_new_live.py::test_unexpected"]


def test_applicability_rejects_unexpected_historical_pass(monkeypatch) -> None:
    ledger = applicability.build_ledger(ROOT)
    nodeids = [entry["test_node_id"] for entry in ledger["entries"]]
    observed = {
        "schema_version": "t23-unrestricted-pytest-result-v1",
        "execution_complete": True, "collected": 27, "executed": 27,
        "deselected": 0, "skipped_nodeids": [], "xfail_nodeids": [],
        "xpass_nodeids": [], "pytest_exit_code": 1,
        "counts": {"passed": 2, "failed": 25, "skipped": 0, "xfail": 0, "xpass": 0},
        "failed_nodeids": sorted(nodeids[1:]),
        "passed_nodeids": [nodeids[0], applicability.REPLACEMENT_TEST],
    }
    original = applicability._json

    def source(root: Path, relative: str):
        if relative == applicability.RESULT:
            return observed
        if relative == applicability.LEDGER:
            return ledger
        return original(root, relative)

    monkeypatch.setattr(applicability, "_json", source)
    report = applicability.validate_applicability(ROOT)
    assert report["status"] == "FAIL"
    assert report["unexpected_historical_passes"] == [nodeids[0]]


def test_applicability_rejects_all_historical_tests_turning_green(monkeypatch) -> None:
    ledger = applicability.build_ledger(ROOT)
    nodeids = [entry["test_node_id"] for entry in ledger["entries"]]
    observed = {
        "schema_version": "t23-unrestricted-pytest-result-v1",
        "execution_complete": True, "collected": 27, "executed": 27,
        "deselected": 0, "skipped_nodeids": [], "xfail_nodeids": [],
        "xpass_nodeids": [], "pytest_exit_code": 0,
        "counts": {"passed": 27, "failed": 0, "skipped": 0, "xfail": 0, "xpass": 0},
        "failed_nodeids": [],
        "passed_nodeids": sorted(nodeids + [applicability.REPLACEMENT_TEST]),
    }
    original = applicability._json

    def source(root: Path, relative: str):
        if relative == applicability.RESULT:
            return observed
        if relative == applicability.LEDGER:
            return ledger
        return original(root, relative)

    monkeypatch.setattr(applicability, "_json", source)
    report = applicability.validate_applicability(ROOT)
    assert report["status"] == "FAIL"
    assert report["unexpected_historical_passes"] == nodeids
