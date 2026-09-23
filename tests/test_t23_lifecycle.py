"""Lifecycle-aware replacement protection for T22's frozen preconstruction doctor."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from t23_protocol import lifecycle


ROOT = Path(__file__).resolve().parents[1]


def test_promoted_t22_paths_require_verified_promotion_evidence() -> None:
    report = lifecycle.verify_lifecycle(ROOT, "t22")
    assert report == {
        "status": "PASS", "experiment": "t22", "state": "PROMOTED",
        "registered_paths": 28, "present_paths": 28, "evidence_valid": True,
    }


def test_preconstruction_t23_paths_are_absent() -> None:
    report = lifecycle.verify_lifecycle(ROOT, "t23")
    assert report["status"] == "PASS"
    assert report["state"] == "PRECONSTRUCTION"
    assert report["registered_paths"] == 22
    assert report["present_paths"] == 0


def test_unknown_experiment_fails_closed() -> None:
    assert lifecycle.verify_lifecycle(ROOT, "t24")["status"] == "FAIL"


def test_forged_lifecycle_state_fails_closed(monkeypatch) -> None:
    original = lifecycle._read

    def forged(root: Path, relative: str):
        value = original(root, relative)
        if relative == lifecycle.REGISTRY:
            value = deepcopy(value)
            value["experiments"]["t22"]["state"] = "UNRECOGNIZED"
        return value

    monkeypatch.setattr(lifecycle, "_read", forged)
    assert lifecycle.verify_lifecycle(ROOT, "t22")["status"] == "FAIL"


def test_promotion_checksum_mismatch_fails_closed(monkeypatch) -> None:
    original = lifecycle._sha256

    def forged(root: Path, relative: str) -> str:
        if relative.endswith("T22_FINAL_PROMOTION_RECORD.json"):
            return "0" * 64
        return original(root, relative)

    monkeypatch.setattr(lifecycle, "_sha256", forged)
    assert lifecycle.verify_lifecycle(ROOT, "t22")["status"] == "FAIL"
