"""T21R12 construction gate built from the exact-design schema."""
from __future__ import annotations

import json
from pathlib import Path

import t21r12_exact_design_lib as ed

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r12"
CONTRACT_PATH = OUT / "holdout_construction_contract.json"


def evaluate_levels(contract: dict, metrics: dict, rows: list[dict],
                    context: dict | None = None) -> dict:
    context = context or {}
    checks = []

    def add(level: str, identifier: str, actual, expected, passed: bool) -> None:
        checks.append({
            "level": level,
            "id": identifier,
            "actual": actual,
            "expected": expected,
            "passed": bool(passed),
        })

    add("L7_exposure", "runtime_execution_count",
        metrics.get("runtime_execution_count"), 0,
        metrics.get("runtime_execution_count") == 0)
    add("L7_exposure", "candidate_R12_rows_executed",
        metrics.get("candidate_R12_rows_executed", 0), 0,
        metrics.get("candidate_R12_rows_executed", 0) == 0)
    add("L7_exposure", "official_evaluator_invocations",
        metrics.get("official_evaluator_invocations", 0), 0,
        metrics.get("official_evaluator_invocations", 0) == 0)
    add("L2_corpus", "annotation_violations",
        metrics.get("annotation_violations", 0), 0,
        metrics.get("annotation_violations", 0) == 0)

    if metrics.get("suite_rows") is not None:
        expected_suites = contract["suite_target_exact"]
        actual_suites = metrics.get("suite_rows") or {}
        add("L3_suites", "suite_ids", sorted(actual_suites), sorted(expected_suites),
            set(actual_suites) == set(expected_suites))
        for suite_id, expected in expected_suites.items():
            actual = actual_suites.get(suite_id)
            add("L3_suites", f"suite_count.{suite_id}", actual, expected, actual == expected)
        add("L3_suites", "total_rows", metrics.get("total_rows"),
            contract["total_rows_exact"],
            metrics.get("total_rows") == contract["total_rows_exact"])

    design = ed.evaluate_exact_design(contract, rows, context)
    for item in design["checks"]:
        add("L4_exact_design", item["contract_path"], item.get("observed"),
            item.get("required"), item.get("status") == "PASS")
    add("L4_exact_design", "unhandled_leaves", design["unhandled"], 0,
        design["unhandled"] == 0)
    add("L4_exact_design", "unknown_construction_tags",
        design.get("unknown_construction_tags"), [],
        not design.get("unknown_construction_tags"))

    add("L5_exclusion", "historical_milestones",
        context.get("historical_milestones"), 12,
        context.get("historical_milestones") == 12)
    add("L5_exclusion", "historical_overlap",
        context.get("historical_overlap", 0), 0,
        context.get("historical_overlap", 0) == 0)
    add("L5_exclusion", "remediation_overlap",
        context.get("remediation_overlap", 0), 0,
        context.get("remediation_overlap", 0) == 0)

    add("L6_blindness", "candidate_leakage",
        context.get("candidate_leakage", 0), 0,
        context.get("candidate_leakage", 0) == 0)
    add("L6_blindness", "historical_leakage",
        context.get("historical_leakage", 0), 0,
        context.get("historical_leakage", 0) == 0)
    add("L6_blindness", "remediation_leakage",
        context.get("remediation_leakage", 0), 0,
        context.get("remediation_leakage", 0) == 0)

    # Level 1 freeze bindings when provided
    if context.get("runtime_hash_mismatches") is not None:
        add("L1_freeze", "runtime_hash_mismatches",
            context.get("runtime_hash_mismatches"), 0,
            context.get("runtime_hash_mismatches") == 0)
    if context.get("evaluator_hash_mismatches") is not None:
        add("L1_freeze", "evaluator_hash_mismatches",
            context.get("evaluator_hash_mismatches"), 0,
            context.get("evaluator_hash_mismatches") == 0)

    passed = sum(1 for c in checks if c["passed"])
    return {
        "artifact": "T21R12_CONSTRUCTION_GATE_REPORT",
        "status": "PASS" if passed == len(checks) else "FAIL",
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "exact_design": {
            "leaf_requirements_total": design["leaf_requirements_total"],
            "passed": design["passed"],
            "failed": design["failed"],
            "unhandled": design["unhandled"],
        },
        "runtime_execution_count": 0,
    }


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    report = {
        "artifact": "T21R12_CONSTRUCTION_GATE_REPORT",
        "status": "PRECONSTRUCTION",
        "note": "Real suite/corpus metrics absent until construction authorization",
        "levels_required_before_seal": [
            "L1_freeze", "L2_corpus", "L3_suites", "L4_exact_design",
            "L5_exclusion", "L6_blindness", "L7_exposure",
        ],
        "runtime_execution_count": 0,
    }
    path = OUT / "construction_gate.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
