"""Machine gate for the preregistered T21R10 construction contract."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r10"
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
    required_ie = set(contract["partial_path_configurations"])
    present_ie = set(metrics.get("partial_path_configurations") or [])
    if miniature:
        check("partial_path_enum_valid", sorted(present_ie),
              "subset of preregistered enum", present_ie <= required_ie)
    else:
        check("partial_path_enum_complete", sorted(present_ie),
              sorted(required_ie), required_ie <= present_ie)
        expected_suites = contract["suite_target_exact"]
        actual_suites = metrics.get("suite_rows") or {}
        check("suite_ids", sorted(actual_suites), sorted(expected_suites),
              set(actual_suites) == set(expected_suites))
        for suite_id, expected in expected_suites.items():
            actual = actual_suites.get(suite_id)
            check(f"suite_count.{suite_id}", actual, expected,
                  actual == expected)
        check("total_rows", metrics.get("total_rows"),
              contract["total_rows_exact"],
              metrics.get("total_rows") == contract["total_rows_exact"])
        stress = metrics.get("stress") or {}
        requirements = contract["stress_requirements"]
        mappings = {
            "multihop_rows_minimum": ("multihop_rows", ">="),
            "multihop_chain_families_minimum":
                ("multihop_chain_families", ">="),
            "multihop_largest_family_share_maximum":
                ("multihop_largest_family_share", "<="),
            "multihop_relation_surface_mismatch_fraction_minimum":
                ("multihop_relation_surface_mismatch_fraction", ">="),
            "crossdomain_rows_minimum": ("crossdomain_rows", ">="),
            "crossdomain_two_source_two_domain_minimum":
                ("crossdomain_two_source_two_domain", ">="),
            "domain_pair_families_minimum": ("domain_pair_families", ">="),
            "largest_domain_pair_share_maximum":
                ("largest_domain_pair_share", "<="),
            "multisource_path_rows_minimum":
                ("multisource_path_rows", ">="),
            "partial_path_rows_minimum": ("partial_path_rows", ">="),
            "relation_surface_rows_minimum": ("relation_surface_rows", ">="),
            "canonical_relations_minimum": ("canonical_relations", "count"),
            "relation_surface_mismatch_fraction_minimum":
                ("relation_surface_mismatch_fraction", ">="),
            "source_injection_rows_minimum": ("source_injection_rows", ">="),
            "query_injection_or_spoof_rows_minimum":
                ("query_injection_or_spoof_rows", ">="),
            "safe_fact_with_directive_rows_minimum":
                ("safe_fact_with_directive_rows", ">="),
        }
        for requirement, (metric, operator) in mappings.items():
            expected = requirements[requirement]
            raw = stress.get(metric)
            actual = len(raw or []) if operator == "count" else raw
            passed = actual is not None and (
                actual <= expected if operator == "<=" else actual >= expected)
            check(f"stress.{metric}", actual, f"{operator} {expected}", passed)
        minimum = requirements["partial_path_configuration_minimum"]
        configuration_counts = stress.get(
            "partial_path_configuration_counts") or {}
        for component in contract["partial_path_configurations"]:
            actual = configuration_counts.get(component, 0)
            check(f"stress.partial_path.{component}", actual,
                  f">= {minimum}", actual >= minimum)
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
        raise SystemExit("T21R10 construction audit is absent")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    report = build_gate_report(contract, audit["metrics"])
    path = OUT_DIR / "construction_gate.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
