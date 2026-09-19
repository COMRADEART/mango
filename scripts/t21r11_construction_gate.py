"""Machine gate for the preregistered T21R11 construction contract."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r11"
CONTRACT_PATH = OUT_DIR / "holdout_construction_contract.json"


def evaluate_metrics(contract: dict, metrics: dict,
                     *, miniature: bool = False) -> list[dict]:
    checks: list[dict] = []

    def check(identifier: str, actual: object, expected: object,
              passed: bool) -> None:
        checks.append({"id": identifier, "actual": actual,
                       "expected": expected, "passed": bool(passed)})

    check("runtime_execution_count", metrics.get("runtime_execution_count"),
          0, metrics.get("runtime_execution_count") == 0)
    check("annotation_violations", metrics.get("annotation_violations"), 0,
          metrics.get("annotation_violations") == 0)
    check("builder_declared_windows", metrics.get("declared_initial_windows"),
          0, metrics.get("declared_initial_windows") == 0)

    if miniature:
        return checks

    expected_suites = contract["suite_target_exact"]
    actual_suites = metrics.get("suite_rows") or {}
    check("suite_ids", sorted(actual_suites), sorted(expected_suites),
          set(actual_suites) == set(expected_suites))
    for suite_id, expected in expected_suites.items():
        actual = actual_suites.get(suite_id)
        check(f"suite_count.{suite_id}", actual, expected, actual == expected)
    check("total_rows", metrics.get("total_rows"),
          contract["total_rows_exact"],
          metrics.get("total_rows") == contract["total_rows_exact"])
    return checks


def build_gate_report(contract: dict, metrics: dict,
                      *, miniature: bool = False) -> dict:
    checks = evaluate_metrics(contract, metrics, miniature=miniature)
    passed = sum(check["passed"] for check in checks)
    return {"status": "PASS" if passed == len(checks) else "FAIL",
            "checks": checks, "passed": passed, "total": len(checks),
            "runtime_execution_count": 0}


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    audit_path = OUT_DIR / "construction_audit.json"
    if not audit_path.exists():
        raise SystemExit("T21R11 construction audit is absent")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    report = build_gate_report(contract, audit["metrics"])
    path = OUT_DIR / "construction_gate.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
