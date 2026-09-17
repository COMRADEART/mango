"""T19 post-merge audit metadata cleanup: SciComp label + stress coverage."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from t21r8_base_remediation import t21r8_hash_matches

ROOT = Path(__file__).resolve().parents[1]
T19 = ROOT / "evaluations" / "t19"
FLOORS_SHA = "0ccd53fab9aaf0040b63d10f80cb120a10b008f866190af591fc53ae5eef7526"
SCICOMP_HASH = "5be66a3afb5f17f6b07ec995938ee783cb9adee8f85c268c52562a258f8e22c8"
PLANNER_HASH = "d045885cefcd097ceffc6588b5e6b00a1072cfaa08526ba9e4070bbdc041528c"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "t19_post_merge_audit_cleanup",
        ROOT / "scripts" / "t19_post_merge_audit_cleanup.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _sha_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _sha_group(rel_dir: str) -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / rel_dir).glob("*.py")):
        rel = (rel_dir + "/" + p.name).replace("\\", "/")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()


def test_cleanup_json_matches_frozen_measurement():
    mod = _load_script()
    live = mod.measure_coverage()
    frozen = _json("evaluations/t19/post_merge_audit_cleanup.json")
    cov = frozen["long_horizon_coverage"]
    assert frozen["cleanup_type"] == "AUDIT_METADATA_ONLY"
    assert frozen["capability_behavior_changed"] is False
    assert frozen["benchmarks_changed"] is False
    assert frozen["thresholds_changed"] is False
    assert frozen["historical_scores_changed"] is False
    assert frozen["promotion_decision_changed"] is False
    assert frozen["planning_decision"] == "PROMOTE_PLANNING_SKILL"
    assert frozen["planning_availability"] == "ACTIVE"
    assert frozen["executive_router"] == "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL"
    assert frozen["t20_started"] is False
    assert cov["total_long_horizon_scenarios"] == live["total_long_horizon_scenarios"] == 28
    assert cov["task_count_ge_15"] == live["task_count_ge_15"] == 28
    assert cov["task_count_15_to_30"] == live["task_count_15_to_30"] == 28
    assert cov["ge_15_multiple_skills"] == live["ge_15_multiple_skills"] == 0
    assert cov["ge_15_multiple_dependencies"] == live["ge_15_multiple_dependencies"] == 28
    assert cov["ge_15_with_replan"] == live["ge_15_with_replan"] == 0
    assert cov["full_definition_count"] == live["full_definition_count"] == 0
    assert cov["required_count"] == 25
    assert cov["requirement_met"] is False
    assert cov["coverage_status"] == "SHORTFALL"
    assert cov["coverage_label"] == "T19_STRESS_COVERAGE_SHORTFALL"
    assert cov["scenario_ids"] == live["scenario_ids"]
    assert cov["full_definition_scenario_ids"] == []
    assert len(frozen["detailed_long_horizon_scenarios"]) == 28
    assert all(not row["meets_full_t19_55"] for row in frozen["detailed_long_horizon_scenarios"])


def test_scicomp_canonical_active_implementation_unchanged():
    freeze = _json("evaluations/t19/frozen_components.json")
    audit = _json("evaluations/t19/final_audit.json")
    cleanup = _json("evaluations/t19/post_merge_audit_cleanup.json")
    from sciencemath.executive.skills import SkillRegistry

    reg = SkillRegistry()
    sci = next(c for c in audit["checks"] if c["check"] == "scicomp_identity")
    measured = sci["measured"]
    assert measured["availability"] == "ACTIVE"
    assert measured["original_t19_audit_measured"] == "EXPERIMENTAL"
    assert measured["registry_availability_string"] == "EXPERIMENTAL"
    assert measured["implementation_hash"] == SCICOMP_HASH
    assert freeze["composites"]["scicomp"] == SCICOMP_HASH
    assert _sha_group("src/sciencemath/scicomp") == SCICOMP_HASH
    # Historical T19 cleanup recorded the stale registry string; live
    # registry is now aligned to canonical ACTIVE.
    assert cleanup["scicomp_status_cleanup"]["registry_availability_string"] == (
        "EXPERIMENTAL"
    )
    assert reg.availability("SCICOMP") == "ACTIVE"
    assert cleanup["scicomp_status_cleanup"]["canonical_value"] == "ACTIVE"
    assert cleanup["scicomp_status_cleanup"]["implementation_hash_unchanged"] is True
    decision = _json("evaluations/t14r2/scicomp_decision.json")
    assert decision["decision"] == "PROMOTE_SCICOMP_LAB"
    prot = _json("evaluations/t19/protection/regression_summary.json")
    assert prot["identity"]["scicomp"] is True
    assert prot["layers"]["scicomp"]["status"] == "PASS"


def test_historical_floors_checksums_and_planner_untouched():
    floors = T19 / "promotion_floors.json"
    assert _sha_lf(floors) == FLOORS_SHA
    freeze = _json("evaluations/t19/frozen_components.json")
    for name, key in (
        ("mango-planner-core-v1", "core"),
        ("mango-planning-eval-v1", "eval"),
        ("mango-plan-retention-v1", "retention"),
        ("mango-completion-gate-v1", "completion"),
        ("mango-planning-loop-v1", "loop"),
    ):
        man = _json(f"evaluations/t19/suites/{name}/manifest.json")
        finalp = T19 / "suites" / name / "final.jsonl"
        assert _sha_lf(finalp) == man["final_sha256"]
        pred = T19 / "runs" / "t19-final" / key / "predictions.jsonl"
        assert pred.exists()
    assert _sha_group("src/sciencemath/planning") == PLANNER_HASH
    trans = _json("evaluations/t19/planning_transition.json")
    assert trans["decision"] == "PROMOTE_PLANNING_SKILL"
    assert trans["after"] == "ACTIVE"
    audit = _json("evaluations/t19/final_audit.json")
    assert audit["gates_total"] == 76
    assert len(audit["checks"]) == 76
    assert audit["planning_decision"] == "PROMOTE_PLANNING_SKILL"
    assert audit["planner_implementation_sha256"] == PLANNER_HASH
    assert t21r8_hash_matches(
        ROOT, "code_runtime", _sha_group("src/sciencemath/code"),
        freeze["composites"]["code"])


def test_final_report_and_audit_record_shortfall():
    report = (T19 / "T19_FINAL_REPORT.md").read_text(encoding="utf-8")
    assert "## Post-Merge Audit Cleanup" in report
    assert "EXPERIMENTAL → ACTIVE" in report
    assert "Capability behavior changed:\nNO" in report
    assert "Benchmark scores changed:\nNO" in report
    assert "Promotion decision changed:\nNO" in report
    assert "Stress scenarios satisfying full 15–30 task T19 requirement:\n0" in report
    assert "Required:\n25" in report
    assert "Result:\nSHORTFALL" in report
    audit = _json("evaluations/t19/final_audit.json")
    assert audit["stress_coverage_verification"]["full_definition_count"] == 0
    assert audit["stress_coverage_verification"]["coverage_label"] == (
        "T19_STRESS_COVERAGE_SHORTFALL"
    )
    assert audit["post_merge_corrections"]["scicomp_identity"]["canonical_availability"] == (
        "ACTIVE"
    )
    assert audit["stress_coverage_verification"]["t19_family"] == "CLOSED"
    assert audit["post_merge_corrections"]["planning_decision_unchanged"] is True
