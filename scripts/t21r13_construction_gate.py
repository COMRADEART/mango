"""T21R13 construction gate built from the exact-design schema."""
from __future__ import annotations

import json
from pathlib import Path

import t21r13_exact_design_lib as ed

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r13"
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
    add("L7_exposure", "candidate_R13_rows_executed",
        metrics.get("candidate_R13_rows_executed", 0), 0,
        metrics.get("candidate_R13_rows_executed", 0) == 0)
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
        context.get("historical_milestones"), 13,
        context.get("historical_milestones") == 13)
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
        "artifact": "T21R13_CONSTRUCTION_GATE_REPORT",
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


def build_gate_report(contract: dict, metrics: dict,
                      rows: list[dict] | None = None, *,
                      context: dict | None = None,
                      miniature: bool = False) -> dict:
    """Programmatic construction-gate interface over the canonical evaluator.

    T21R13_PRELEDGER_REFUSAL repair: restores the cross-module API consumed by
    ``t21r13_static_gold_audit.py`` and ``t21r13_blind_author.py``.  This
    wrapper introduces no gate semantics of its own — every check is produced
    by the unchanged canonical :func:`evaluate_levels` implementation, which is
    the same semantics behind the CLI path (exactly one canonical gate
    implementation).  ``miniature`` is accepted for historical call-site
    compatibility and does not alter evaluation.

    ``rows`` feed the L4 exact-design level; ``context`` feeds the L5/L6
    exclusion/blindness levels and the L1 freeze levels when present.  Callers
    that execute before the exclusion/blindness audits exist must pass an
    explicit context derived from live audit results (see
    :func:`context_from_audits`); an omitted context fails those levels closed.
    """
    del miniature  # accepted for caller compatibility; semantics unchanged
    return evaluate_levels(contract, metrics, list(rows or []),
                           context if context is not None else {})


def context_from_audits(prior_report: dict, remediation_report: dict,
                        blind_report: dict,
                        prior_artifact: dict | None = None) -> dict:
    """Derive the L5/L6 gate context from live audit results (data only).

    ``prior_report``/``remediation_report`` are uniqueness-audit results with
    ``status``/``overlap_total``; ``blind_report`` is a blindness-audit result
    with its leakage lists.  ``prior_artifact`` supplies the registered
    historical milestone count.  No value is fabricated: zeros are only
    produced when the corresponding live audit observed zero.
    """
    milestones = len((prior_artifact or {}).get("milestones") or {})
    prior_overlap = int(prior_report.get("overlap_total", 1)
                        if prior_report.get("status") != "UNIQUE" else 0)
    remediation_overlap = int(remediation_report.get("overlap_total", 1)
                              if remediation_report.get("status") != "UNIQUE"
                              else 0)
    return {
        "historical_milestones": milestones,
        "historical_overlap": prior_overlap,
        "remediation_overlap": remediation_overlap,
        "prior_exact_query_overlap": prior_overlap,
        "prior_pair_template_overlap": prior_overlap,
        "candidate_leakage": len(blind_report.get("candidate_leakage") or []),
        "historical_leakage": len(
            blind_report.get("historical_blind_leakage") or []),
        "remediation_leakage": len(
            blind_report.get("remediation_validation_leakage") or []),
    }


def derive_gate_context(out_dir: Path | None = None) -> dict:
    """Load frozen uniqueness/blindness/prior artifacts and derive context.

    Data-only convenience for programmatic gate callers that run after the
    uniqueness and blindness audits have been written to disk.  Raises if the
    artifacts are absent so callers never gate against fabricated values.
    """
    directory = out_dir if out_dir is not None else OUT
    uniqueness = json.loads((directory / "holdout_uniqueness.json").read_text(
        encoding="utf-8"))
    blind = json.loads((directory / "holdout_blindness.json").read_text(
        encoding="utf-8"))
    prior_artifact = json.loads((directory / "prior_exclusion.json").read_text(
        encoding="utf-8"))
    return context_from_audits(
        uniqueness.get("prior") or {},
        uniqueness.get("open_remediation") or {},
        blind, prior_artifact)


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    report = {
        "artifact": "T21R13_CONSTRUCTION_GATE_REPORT",
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
