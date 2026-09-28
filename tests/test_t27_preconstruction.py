"""Persisted public T27 preconstruction artifact gate."""
from __future__ import annotations

import json
from pathlib import Path

from t27_protocol.doctor import run_doctor
from t27_protocol.exclusion import DIMENSIONS
from t27_protocol.freeze import (PRESERVED_V1_FREEZE_SHA256,
                                 PRESERVED_V2_FREEZE_SHA256,
                                 PRESERVED_V3_FREEZE_SHA256, verify_freeze_v4)

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "evaluations" / "t27"


def _read(name: str) -> dict:
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def test_candidate_and_public_root_cause_are_frozen():
    candidate = _read("candidate_identity.json")
    reproduction = _read("T27_PUBLIC_ROOT_CAUSE_REPRODUCTION.json")
    assert candidate["parent_candidate"] == "6cb029c0f4edb4116c7f9a1f187cdc4671077a1f"
    assert candidate["candidate_changed"] is True
    assert candidate["runtime_root"] != candidate["parent_runtime_root"]
    assert reproduction["status"] == "REPRODUCED_AND_REMEDIATED"
    assert reproduction["t26_row_specific_cause_claimed"] is False


def test_future_design_storage_tokens_and_exclusion_are_exact():
    design = _read("prospective_design.json")
    storage = _read("private_storage_policy.json")
    exclusion = _read("historical_exclusion_policy.json")
    assert (design["family_count"], design["cases_per_family"],
            design["total_real_blind_cases"]) == (16, 32, 512)
    assert design["construction_token"] == "T27_REAL_BLIND_HOLDOUT_CONSTRUCTION_AUTHORIZATION"
    assert design["evaluation_token"] == "T27_ONE_SHOT_OFFICIAL_EVALUATION"
    assert storage["store_id"] == "T27-STORE-01"
    assert storage["namespace"] == "t27"
    assert storage["locator_scheme"] == "t27-private://"
    assert exclusion["dimensions"] == list(DIMENSIONS)
    assert exclusion["t26_private_rows_opened"] == 0


def test_protections_qualification_test_gate_and_diagnostics_pass():
    protection = _read("protection_report.json")
    qualification = _read("qualification_report.json")
    diagnostics = _read("diagnostics_report.json")
    test_gate = _read("test_gate_report.json")
    assert protection["status"] == "PASS"
    assert protection["t19"]["authority"] == "PROPOSE_ONLY"
    assert protection["t20"]["authority"] == "COORDINATE_INTERNAL_WORK_ONLY"
    assert protection["t22"]["passed"] == protection["t22"]["total"] == 32
    assert protection["t25_router"]["floor_count"] == 15
    assert protection["t25_dispatch"]["status"] == "PASS"
    assert qualification["status"] == "PASS"
    assert all(value["status"] == "PASS" for value in diagnostics.values())
    assert test_gate["status"] == "PASS"
    assert all(test_gate[name] == 0 for name in (
        "live_failures", "unknown_failures", "unexplained_skips",
        "xfails", "deselections"))


def test_doctor_and_freeze_reproduce():
    historical = _read("preconstruction_freeze.json")
    assert historical["freeze_sha256"] == PRESERVED_V1_FREEZE_SHA256
    frozen_v2 = _read("preconstruction_freeze_v2.json")
    assert frozen_v2["freeze_sha256"] == PRESERVED_V2_FREEZE_SHA256
    frozen_v3 = _read("preconstruction_freeze_v3.json")
    assert frozen_v3["freeze_sha256"] == PRESERVED_V3_FREEZE_SHA256
    assert frozen_v3["supersedes"]["artifact"] == (
        "T27_PRECONSTRUCTION_FREEZE_V2_SUPERSEDED_PRE_EXPOSURE")
    frozen_v4 = _read("preconstruction_freeze_v4.json")
    assert frozen_v4["supersedes"]["reason"] == (
        "T26_OFFICIAL_EVALUATION_MARKER_PATH_COMPATIBILITY_DEFECT")
    assert frozen_v4["real_construction_authorized"] is False
    assert frozen_v4["real_evaluation_authorized"] is False
    assert verify_freeze_v4(ROOT, frozen_v4)["status"] == "PASS"
    report = run_doctor(ROOT)
    assert report["status"] == "PASS"
    assert report["failed_checks"] == []
    assert all(report["checks"].values())


def test_real_exposure_and_ledgers_remain_zero_and_absent():
    exposure = _read("real_exposure.json")
    assert all(value == 0 for value in exposure.values()
               if isinstance(value, int))
    assert not (EVAL / "construction_ledger.json").exists()
    assert not (EVAL / "evaluation_ledger.json").exists()
