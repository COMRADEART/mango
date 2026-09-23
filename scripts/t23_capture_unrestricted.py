"""Run every tracked pytest item unchanged and write public-safe outcome IDs.

This wrapper supplies no selection, skipping, xfail, or outcome mutation hooks.
"""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evaluations" / "t23" / "unrestricted_pytest_result.json"


class Capture:
    def __init__(self) -> None:
        self.collected: list[str] = []
        self.deselected: list[str] = []
        self.outcomes: dict[str, str] = {}

    def pytest_collection_modifyitems(self, items):
        self.collected = [item.nodeid for item in items]

    def pytest_deselected(self, items):
        self.deselected.extend(item.nodeid for item in items)

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            if hasattr(report, "wasxfail"):
                self.outcomes[report.nodeid] = "xfail" if report.skipped else "xpass"
            else:
                self.outcomes[report.nodeid] = report.outcome
        elif report.when == "setup" and report.outcome in {"failed", "skipped"}:
            self.outcomes[report.nodeid] = report.outcome


def main() -> int:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    capture = Capture()
    # The repository's pytest configuration supplies testpaths and basetemp.
    # There is intentionally no -k, --ignore, deselection, or xfail modifier.
    exit_code = int(pytest.main(["-q", "--tb=line"], plugins=[capture]))
    counts = {name: sum(value == name for value in capture.outcomes.values())
              for name in ("passed", "failed", "skipped", "xfail", "xpass")}
    ledger = json.loads((ROOT / "evaluations/t23/historical_applicability.json").read_text(encoding="utf-8"))
    relevant_passes = {entry["test_node_id"] for entry in ledger["entries"]}
    relevant_passes.add("tests/test_t23_applicability.py::test_all_historical_replacements")
    executed_ids = sorted(capture.outcomes)
    executed_hash = hashlib.sha256(json.dumps(executed_ids, separators=(",", ":"),
                                           ensure_ascii=False).encode("utf-8")).hexdigest()
    report = {
        "schema_version": "t23-unrestricted-pytest-result-v1",
        "artifact": "T23_UNRESTRICTED_PYTEST_RESULT",
        "execution_complete": set(capture.collected) == set(capture.outcomes) | set(capture.deselected),
        "collected": len(capture.collected) + len(capture.deselected),
        "executed": len(capture.outcomes),
        "deselected": len(capture.deselected),
        "counts": counts,
        "executed_nodeids_sha256": executed_hash,
        "failed_nodeids": sorted(node for node, outcome in capture.outcomes.items() if outcome == "failed"),
        "passed_nodeids": sorted(node for node, outcome in capture.outcomes.items()
                               if outcome == "passed" and node in relevant_passes),
        "skipped_nodeids": sorted(node for node, outcome in capture.outcomes.items() if outcome == "skipped"),
        "xfail_nodeids": sorted(node for node, outcome in capture.outcomes.items() if outcome == "xfail"),
        "xpass_nodeids": sorted(node for node, outcome in capture.outcomes.items() if outcome == "xpass"),
        "deselected_nodeids": sorted(capture.deselected),
        "pytest_exit_code": exit_code,
    }
    REPORT.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
