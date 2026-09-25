"""Unrestricted pytest gate with historical failure attribution."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from t23_protocol.applicability import build_ledger, verify_replacement


T25_PROMOTION = "8940d96aacb08d8acf110e5f3e45e9ce84f03577"


def _historical_ids(root: Path) -> tuple[set[str], dict]:
    """Authenticate both public historical ledgers without suppressing tests."""
    t23_path = root / "evaluations/t23/historical_applicability.json"
    t23 = json.loads(t23_path.read_text(encoding="utf-8"))
    if t23 != build_ledger(root) or any(
        verify_replacement(root, entry)["status"] != "PASS"
        for entry in t23["entries"]
    ):
        raise ValueError("T23 historical applicability is not authenticated")
    t23_ids = {
        entry["test_node_id"].replace("/", ".", 1).replace(".py::", "::")
        for entry in t23["entries"]
    }
    t25_path = "evaluations/t25/T25_FINAL_PROMOTION_RECORD.json"
    public_bytes = (root / t25_path).read_bytes()
    committed = subprocess.run(
        ["git", "show", f"{T25_PROMOTION}:{t25_path}"], cwd=root,
        check=True, capture_output=True,
    ).stdout
    if public_bytes != committed:
        raise ValueError("T25 promotion record differs from promotion commit")
    record = json.loads(public_bytes)
    items = record["protection_gate"]["pytest_suite"]["classification"]["historical"]
    t25_ids = {item["test"] for item in items}
    if len(t25_ids) != 15 or len(t23_ids) != 26:
        raise ValueError("historical ledger cardinality changed")
    changed_tests = subprocess.run(
        ["git", "diff", "--name-only", T25_PROMOTION, "--", "tests"],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    changed_tests = [name for name in changed_tests
                     if name != "tests/test_t26_integrated_execution.py"
                     and not name.startswith("tests/test_t26_")]
    if changed_tests:
        raise ValueError("historical tests changed after T25 promotion")
    return t23_ids | t25_ids, {
        "t23_authenticated_count": len(t23_ids),
        "t23_ledger_sha256": hashlib.sha256(t23_path.read_bytes()).hexdigest(),
        "t25_promotion_count": len(t25_ids),
        "t25_promotion_sha256": hashlib.sha256(public_bytes).hexdigest(),
        "overlap": len(t23_ids & t25_ids),
    }


def run_test_gate(root: Path) -> dict:
    root = Path(root).resolve()
    with tempfile.TemporaryDirectory(prefix="t26-full-pytest-") as tmp:
        junit = Path(tmp) / "results.xml"
        basetemp = Path(tmp) / "basetemp"
        basetemp.mkdir()
        result = subprocess.run([sys.executable, "-m", "pytest", "-q",
                                 "-p", "no:cacheprovider", "--disable-warnings",
                                 "--tb=no", f"--basetemp={basetemp}",
                                 f"--junitxml={junit}"],
                                cwd=root, capture_output=True, text=True,
                                timeout=1800)
        if not junit.is_file():
            return {"status": "FAIL", "error": "junit missing",
                    "exit_code": result.returncode}
        document = ET.parse(junit)
        cases = document.getroot().findall(".//testcase")
        failed = []
        skipped = []
        xfails = []
        for case in cases:
            name = f"{case.get('classname')}::{case.get('name')}"
            if case.find("failure") is not None or case.find("error") is not None:
                failed.append(name)
            skip = case.find("skipped")
            if skip is not None:
                if "xfail" in (skip.get("message") or "").casefold():
                    xfails.append(name)
                else:
                    skipped.append(name)
        historical, historical_sources = _historical_ids(root)
        observed_historical = sorted(set(failed) & historical)
        new = sorted(set(failed) - historical)
        new_live = [name for name in new if name.startswith("tests.test_t26_")]
        new_unknown = sorted(set(new) - set(new_live))
        missing_historical = sorted(historical - set(failed))
        output = result.stdout + result.stderr
        deselected = "deselected" in output.casefold()
        status = "PASS" if (
            not new and not missing_historical and not skipped and not xfails
            and not deselected and result.returncode == 1 and len(cases) >= 3000
        ) else "FAIL"
        return {"schema_version": "t26-unrestricted-test-gate-v1",
                "artifact": "T26_UNRESTRICTED_TEST_GATE",
                "status": status,
                "total": len(cases),
                "historical_failures": len(observed_historical),
                "historical_failure_ids": observed_historical,
                "historical_absent": missing_historical,
                "new_live_failures": len(new_live),
                "new_unknown_failures": len(new_unknown),
                "new_failure_ids": new,
                "skips": len(skipped), "xfails": len(xfails),
                "deselections": int(deselected),
                "exit_code": result.returncode,
                "baseline_historical_count": len(historical),
                "historical_sources": historical_sources}
