"""Read-only public/nonblind protection batteries for T19, T20, T22, T25."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from t21_protocol.util import sha256_json

T19_FILES = [
    "tests/test_t19_planning_core.py", "tests/test_t19_planning_replan.py",
    "tests/test_t19_planning_complete.py", "tests/test_t19_planning_security.py",
    "tests/test_t19_planning_skills.py",
]
T20_FILES = [
    "tests/test_t20_orchestration_contract.py",
    "tests/test_t20_orchestration_assignment.py",
    "tests/test_t20_orchestration_run.py",
    "tests/test_t20_orchestration_recovery.py",
    "tests/test_t20_orchestration_verify.py",
    "tests/test_t20_orchestration_adversarial.py",
]


def _read(root: Path, path: str) -> dict:
    return json.loads((root / path).read_text(encoding="utf-8"))


def _pytest(root: Path, files: list[str]) -> dict:
    with tempfile.TemporaryDirectory(prefix="t26-protection-pytest-") as tmp:
        junit = Path(tmp) / "results.xml"
        command = [sys.executable, "-m", "pytest", *files, "-q",
                   "-p", "no:cacheprovider", "--disable-warnings",
                   f"--junitxml={junit}"]
        result = subprocess.run(command, cwd=root, capture_output=True,
                                text=True, timeout=180)
        if not junit.is_file():
            return {"status": "FAIL", "exit_code": result.returncode,
                    "tests": 0, "failures": 0, "errors": 1, "skipped": 0}
        tree = ET.parse(junit)
        suite = tree.getroot().find("testsuite") if tree.getroot().tag == "testsuites" else tree.getroot()
        counts = {key: int(suite.attrib.get(key, 0)) for key in
                  ("tests", "failures", "errors", "skipped")}
        return {"status": "PASS" if result.returncode == 0 and
                counts["failures"] == counts["errors"] == counts["skipped"] == 0 else "FAIL",
                "exit_code": result.returncode, **counts,
                "deselected": 0, "xfails": 0}


def _planning_floors(root: Path) -> dict:
    floors = _read(root, "evaluations/t19/promotion_floors.json")
    summary = _read(root, "evaluations/t19/runs/t19-final/summary.json")
    combined = summary.get("combined") or {}
    checks = {}
    for name, floor in floors["quality"].items():
        if name == "unnecessary_replan_rate_max":
            observed = combined.get("unnecessary_replan_rate")
            checks[name] = observed is not None and observed <= floor
        else:
            observed = combined.get(name)
            checks[name] = observed is not None and observed >= floor
    for name, floor in floors["critical_zero_tolerance"].items():
        checks[name] = combined.get(name, 0) == floor
    return {"status": "PASS" if checks and all(checks.values()) else "FAIL",
            "floor_count": len(checks), "failed": sorted(k for k, v in checks.items() if not v)}


def _orchestration_floors(root: Path) -> dict:
    # This registry and its frozen public final-split results are read only.
    prior = _read(root, "evaluations/t20/results/floors_check.json")
    checks = prior.get("checks") or []
    status = "PASS" if prior.get("ok") is True and checks and all(
        c.get("ok") is True for c in checks) else "FAIL"
    return {"status": status, "floor_count": len(checks),
            "failed": [c.get("id", "unknown") for c in checks if not c.get("ok")]}


def _t25_runtime_identity(root: Path) -> dict:
    identity = _read(root, "evaluations/t25/candidate_identity.json")["t25_candidate"]
    mapping = identity["runtime_component_sha256"]
    drift = []
    for relative, expected in mapping.items():
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            drift.append(relative)
    root_ok = sha256_json(mapping) == identity["runtime_root"]
    return {"status": "PASS" if not drift and root_ok else "FAIL",
            "runtime_root": identity["runtime_root"],
            "component_count": len(mapping), "drift": drift,
            "root_recomputed": root_ok}


def run_protection(root: Path) -> dict:
    root = Path(root).resolve()
    t19_tests = _pytest(root, T19_FILES)
    t20_tests = _pytest(root, T20_FILES)
    t19_floors = _planning_floors(root)
    t20_floors = _orchestration_floors(root)
    from t25_protocol.evaluation import (protected_t22_floor_evidence,
                                         protected_t22_metric_evidence)

    t22 = protected_t22_floor_evidence(protected_t22_metric_evidence(root))
    from scripts.t25_candidate_protection import _router_protection_battery

    t25_router = _router_protection_battery()
    t25_identity = _t25_runtime_identity(root)
    promotion = _read(root, "evaluations/t25/T25_FINAL_PROMOTION_RECORD.json")
    dispatch = promotion["capability_dispatch_summary"]
    t25_dispatch = {
        "status": "PASS" if t25_identity["status"] == "PASS"
        and dispatch["unmatched"] == 0 and dispatch["general_unknown"] == 0
        and dispatch["matched"] == dispatch["rows"] else "FAIL",
        "public_promotion_receipt_rows": dispatch["rows"],
        "unmatched": dispatch["unmatched"],
        "unexpected_unknown_terminal": dispatch["general_unknown"],
        "runtime_byte_identity": t25_identity,
    }
    passed = (t19_tests["status"] == t20_tests["status"] ==
              t19_floors["status"] == t20_floors["status"] ==
              t22["status"] == t25_router["status"] ==
              t25_dispatch["status"] == "PASS" and
              t22["passed"] == 32 and t25_router["floor_count"] == 15)
    return {"schema_version": "t26-protection-v1",
            "artifact": "T26_HISTORICAL_PUBLIC_PROTECTION",
            "status": "PASS" if passed else "FAIL",
            "t19": {"tests": t19_tests, "floors": t19_floors,
                    "authority": "PROPOSE_ONLY"},
            "t20": {"tests": t20_tests, "floors": t20_floors,
                    "authority": "COORDINATE_INTERNAL_WORK_ONLY"},
            "t22": {"status": t22["status"], "passed": t22["passed"],
                    "total": t22["total"], "raw_blind_rows_accessed": 0},
            "t25_router": {"status": t25_router["status"],
                           "floor_count": t25_router["floor_count"],
                           "failed_floors": t25_router["failed_floors"]},
            "t25_dispatch": t25_dispatch,
            "historical_private_rows_accessed": 0,
            "candidate_executions_on_historical_rows": 0}
