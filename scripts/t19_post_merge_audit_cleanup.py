"""T19 post-merge audit cleanup: SciComp label + long-horizon coverage.

Reads frozen T19 artifacts only. Does not regenerate suites, edit gold,
edit predictions, or change planner behavior.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T19 = ROOT / "evaluations" / "t19"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

SUITES = (
    ("mango-planner-core-v1", "core"),
    ("mango-planning-eval-v1", "eval"),
    ("mango-plan-retention-v1", "retention"),
    ("mango-completion-gate-v1", "completion"),
    ("mango-planning-loop-v1", "loop"),
)

SCICOMP_HASH = "5be66a3afb5f17f6b07ec995938ee783cb9adee8f85c268c52562a258f8e22c8"
REQUIRED_FULL_DEFINITION = 25
BASE_MAIN = "b2079cc903b3ede273fb009904fa8551735e5278"

OBS_TRIGGERS = {
    "dependency_fail",
    "assumption_invalidated",
    "assumption_invalidation",
    "tool_failure",
    "artifact_changed",
    "evidence_changed",
    "observation",
    "task_failed",
    "missing_input",
}


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def unique_skills(skills) -> list[str]:
    return sorted({s for s in (skills or []) if s})


def has_observation_source(row: dict) -> bool:
    if row.get("fail_task") or row.get("task_observations") or row.get(
            "malicious_observation") or row.get("invalidate_after"):
        return True
    for event in row.get("events") or []:
        if isinstance(event, dict) and event.get("observation"):
            return True
    return False


def pred_plan(row: dict) -> dict:
    pred = row.get("_pred") or {}
    return pred.get("plan") or {}


def pred_task_count(row: dict) -> int:
    return len(pred_plan(row).get("tasks") or [])


def pred_skills(row: dict) -> list[str]:
    return unique_skills(
        t.get("required_skill") for t in (pred_plan(row).get("tasks") or [])
    )


def pred_dep_count(row: dict) -> int:
    return len(pred_plan(row).get("dependencies") or [])


def gold_task_count(row: dict) -> int:
    return len((row.get("gold") or {}).get("skills") or [])


def gold_skills(row: dict) -> list[str]:
    if row.get("required_skills"):
        return unique_skills(row.get("required_skills"))
    return unique_skills((row.get("gold") or {}).get("skills") or [])


def gold_dep_count(row: dict) -> int:
    return len((row.get("gold") or {}).get("deps") or [])


def pred_version(row: dict) -> int:
    return int(pred_plan(row).get("plan_version") or 1)


def pred_replan_triggers(row: dict) -> list[str]:
    plan = pred_plan(row)
    out: list[str] = []
    for blob in (plan.get("history") or []) + (plan.get("decision_metadata") or []):
        if isinstance(blob, dict) and blob.get("replan_trigger"):
            out.append(blob["replan_trigger"])
    return out


def is_long_horizon_definition(row: dict) -> bool:
    gold = row.get("gold") or {}
    return (
        str(row.get("horizon") or "").lower() == "long"
        or bool(gold.get("long"))
        or int(row.get("target_tasks") or 0) >= 15
    )


def effective_task_count(row: dict) -> int:
    """Prefer executed/predicted plan size; fall back to target_tasks then gold."""
    n = pred_task_count(row)
    if n:
        return n
    target = int(row.get("target_tasks") or 0)
    if target:
        return target
    return gold_task_count(row)


def effective_skills(row: dict) -> list[str]:
    return pred_skills(row) or gold_skills(row)


def effective_dep_count(row: dict) -> int:
    return pred_dep_count(row) or gold_dep_count(row)


def has_observation_driven_replan(row: dict) -> bool:
    gold = row.get("gold") or {}
    gold_replan = bool(gold.get("replan"))
    obs = has_observation_source(row)
    triggers = pred_replan_triggers(row)
    pred_od = pred_version(row) > 1 and (
        obs or any(t in OBS_TRIGGERS for t in triggers)
    )
    return (gold_replan and obs) or pred_od


def load_joined_rows() -> list[dict]:
    preds: dict[tuple, dict] = {}
    for suite, key in SUITES:
        for split, run in (("dev", "t19-dev"), ("final", "t19-final")):
            path = T19 / "runs" / run / key / "predictions.jsonl"
            for pred in _rows(path):
                preds[(pred.get("task_id"), split, suite)] = pred
    out: list[dict] = []
    for suite, _key in SUITES:
        for split in ("dev", "final"):
            for row in _rows(T19 / "suites" / suite / f"{split}.jsonl"):
                item = dict(row)
                item["_suite"] = suite
                item["_split"] = split
                item["_pred"] = preds.get((row.get("task_id"), split, suite))
                out.append(item)
    return out


def scenario_record(row: dict) -> dict:
    skills = effective_skills(row)
    n = effective_task_count(row)
    deps = effective_dep_count(row)
    od = has_observation_driven_replan(row)
    return {
        "scenario_id": row.get("task_id"),
        "task_count": n,
        "skill_count": len(skills),
        "skills": skills,
        "dependency_count": deps,
        "has_observation_driven_replan": od,
        "split": row.get("_split"),
        "suite": row.get("_suite"),
        "category": row.get("category"),
        "target_tasks": row.get("target_tasks"),
        "gold_replan": bool((row.get("gold") or {}).get("replan")),
        "observation_source": has_observation_source(row),
        "pred_plan_version": pred_version(row) if row.get("_pred") else None,
        "pred_task_count": pred_task_count(row),
        "meets_full_t19_55": (
            15 <= n <= 30
            and len(skills) >= 2
            and deps >= 2
            and od
        ),
    }


def report_heuristic_final() -> dict:
    preds: list[dict] = []
    for rel in (
        "runs/t19-final/core/predictions.jsonl",
        "runs/t19-final/eval/predictions.jsonl",
        "runs/t19-final/retention/predictions.jsonl",
    ):
        preds.extend(_rows(T19 / rel))
    long = []
    for pred in preds:
        plan = pred.get("plan") or {}
        n = len(plan.get("tasks") or [])
        cat = pred.get("category") or ""
        if (
            n >= 12
            or cat in ("checkpointing", "resume_after_checkpoint")
            or (plan.get("budget") or {}).get("max_tasks", 0) >= 16
        ):
            long.append(pred)
    n_tasks = [len((p.get("plan") or {}).get("tasks") or []) for p in long]
    return {
        "source": "scripts/t19_write_report.py::long_horizon_stats",
        "scenarios": len(long),
        "mean_tasks": (sum(n_tasks) / len(n_tasks)) if n_tasks else 0,
        "max_tasks": max(n_tasks) if n_tasks else 0,
        "task_count_ge_15": sum(1 for n in n_tasks if n >= 15),
        "task_count_15_to_30": sum(1 for n in n_tasks if 15 <= n <= 30),
        "note": (
            "Original T19 report used this loose heuristic (n>=12 or "
            "checkpoint/resume category or max_tasks>=16) over FINAL "
            "core/eval/retention predictions only. Mean ~5 because most "
            "matched rows are short checkpoint/resume plans."
        ),
    }


def measure_coverage() -> dict:
    rows = load_joined_rows()
    long_rows = [r for r in rows if is_long_horizon_definition(r)]
    records = [scenario_record(r) for r in long_rows]
    ge15 = [s for s in records if s["task_count"] >= 15]
    band = [s for s in records if 15 <= s["task_count"] <= 30]
    ge15_ms = [s for s in ge15 if s["skill_count"] >= 2]
    ge15_md = [s for s in ge15 if s["dependency_count"] >= 2]
    ge15_re = [s for s in ge15 if s["has_observation_driven_replan"]]
    full = [s for s in records if s["meets_full_t19_55"]]
    requirement_met = len(full) >= REQUIRED_FULL_DEFINITION
    if requirement_met:
        classification = None
        coverage_status = "PASS"
        label = None
    else:
        classification = "B_benchmark_coverage_shortfall"
        coverage_status = "SHORTFALL"
        label = "T19_STRESS_COVERAGE_SHORTFALL"
    return {
        "definition": {
            "eligible": (
                "Frozen gold rows with horizon==long OR gold.long OR "
                "target_tasks>=15. Task/skill/dependency counts prefer "
                "joined frozen predictions, then target_tasks / gold."
            ),
            "full_t19_55": (
                "15 <= task_count <= 30 AND skill_count >= 2 AND "
                "dependency_count >= 2 AND at least one "
                "observation-driven replan"
            ),
        },
        "total_long_horizon_scenarios": len(records),
        "task_count_ge_15": len(ge15),
        "task_count_15_to_30": len(band),
        "ge_15_multiple_skills": len(ge15_ms),
        "ge_15_multiple_dependencies": len(ge15_md),
        "ge_15_with_replan": len(ge15_re),
        "full_definition_count": len(full),
        "required_count": REQUIRED_FULL_DEFINITION,
        "requirement_met": requirement_met,
        "coverage_status": coverage_status,
        "coverage_label": label,
        "classification": classification,
        "classification_detail": {
            "A_documentation_only_gap": False,
            "B_benchmark_coverage_shortfall": not requirement_met,
            "C_harness_counting_ambiguity": True,
        },
        "scenario_ids": [s["scenario_id"] for s in records],
        "full_definition_scenario_ids": [s["scenario_id"] for s in full],
        "ge15_scenario_ids": [s["scenario_id"] for s in ge15],
        "by_suite_split": dict(Counter(
            f"{s['suite']}:{s['split']}" for s in records
        )),
        "skill_sets": dict(Counter(tuple(s["skills"]) for s in records)),
        "scenarios": records,
        "original_report_heuristic": report_heuristic_final(),
    }


def scicomp_evidence() -> dict:
    freeze = _load(T19 / "frozen_components.json")
    prot = _load(T19 / "protection" / "regression_summary.json")
    entry = _load(T19 / "t19_entry_gate.json")
    decision = _load(ROOT / "evaluations/t14r2/scicomp_decision.json")
    audit = _load(T19 / "final_audit.json")
    original = next(
        (c for c in audit.get("checks") or [] if c.get("check") == "scicomp_identity"),
        {},
    )
    measured = original.get("measured")
    if isinstance(measured, dict):
        previous = measured.get("original_t19_audit_measured") or "EXPERIMENTAL"
    else:
        previous = measured or "EXPERIMENTAL"
    from sciencemath.executive.skills import SkillRegistry

    reg = SkillRegistry()
    hash_now = freeze.get("composites", {}).get("scicomp")
    scicomp_check = None
    for c in entry.get("checks") or []:
        if c.get("check") == "scicomp_active":
            scicomp_check = c
            break
    return {
        "previous_recorded_value": previous,
        "canonical_value": "ACTIVE",
        "registry_availability_string": reg.availability("SCICOMP"),
        "implementation_hash": hash_now,
        "implementation_hash_frozen": SCICOMP_HASH,
        "implementation_hash_unchanged": hash_now == SCICOMP_HASH,
        "status": "CORRECTED",
        "t14r2_decision": decision.get("decision"),
        "protection_scicomp": (prot.get("layers") or {}).get("scicomp"),
        "protection_identity_scicomp": (prot.get("identity") or {}).get("scicomp"),
        "t19_entry_gate_scicomp_active": scicomp_check,
        "evidence_paths": [
            "src/sciencemath/executive/skills.py",
            "evaluations/t14r2/scicomp_decision.json",
            "evaluations/t14r2/T14R2_FINAL_REPORT.md",
            "evaluations/t18/T18_FINAL_REPORT.md",
            "evaluations/t19/t19_entry_gate.json",
            "evaluations/t19/frozen_components.json",
            "evaluations/t19/protection/regression_summary.json",
            "evaluations/t19/final_audit.json",
            "evaluations/t19/T19_FINAL_REPORT.md",
        ],
        "note": (
            "T19.71 recorded SkillRegistry.availability(SCICOMP), which "
            "remained EXPERIMENTAL after T14R2 PROMOTE_SCICOMP_LAB. "
            "Canonical promoted availability is ACTIVE. The registry string "
            "is not flipped here; this cleanup corrects audit metadata only."
        ),
    }


def build_cleanup_document() -> dict:
    cov = measure_coverage()
    sci = scicomp_evidence()
    compact_cov = {
        "total_long_horizon_scenarios": cov["total_long_horizon_scenarios"],
        "task_count_ge_15": cov["task_count_ge_15"],
        "task_count_15_to_30": cov["task_count_15_to_30"],
        "ge_15_multiple_skills": cov["ge_15_multiple_skills"],
        "ge_15_multiple_dependencies": cov["ge_15_multiple_dependencies"],
        "ge_15_with_replan": cov["ge_15_with_replan"],
        "full_definition_count": cov["full_definition_count"],
        "required_count": cov["required_count"],
        "requirement_met": cov["requirement_met"],
        "coverage_status": cov["coverage_status"],
        "coverage_label": cov["coverage_label"],
        "classification": cov["classification"],
        "classification_detail": cov["classification_detail"],
        "scenario_ids": cov["scenario_ids"],
        "full_definition_scenario_ids": cov["full_definition_scenario_ids"],
        "ge15_scenario_ids": cov["ge15_scenario_ids"],
        "by_suite_split": cov["by_suite_split"],
        "definition": cov["definition"],
        "original_report_heuristic": cov["original_report_heuristic"],
        "t19_family": "CLOSED",
        "t19r_recommended": False,
        "promotion_claim_undermined": False,
        "note": (
            "Frozen long-horizon rows are CODE_BUGFIX pads (unique skill=1). "
            "None combine 15-30 tasks with multiple skills, multiple "
            "dependencies, and an observation-driven replan. Quality/safety "
            "floors remain valid; this is documented benchmark-coverage debt, "
            "not a T19 reopen."
        ),
    }
    return {
        "milestone": "T19 post-merge audit cleanup",
        "base_main": BASE_MAIN,
        "cleanup_type": "AUDIT_METADATA_ONLY",
        "capability_behavior_changed": False,
        "benchmarks_changed": False,
        "thresholds_changed": False,
        "historical_scores_changed": False,
        "promotion_decision_changed": False,
        "scicomp_status_cleanup": {
            "previous_recorded_value": sci["previous_recorded_value"],
            "canonical_value": sci["canonical_value"],
            "registry_availability_string": sci["registry_availability_string"],
            "implementation_hash": sci["implementation_hash"],
            "implementation_hash_unchanged": sci["implementation_hash_unchanged"],
            "status": sci["status"],
            "t14r2_decision": sci["t14r2_decision"],
            "evidence_paths": sci["evidence_paths"],
            "note": sci["note"],
        },
        "long_horizon_coverage": compact_cov,
        "planning_decision": "PROMOTE_PLANNING_SKILL",
        "planning_availability": "ACTIVE",
        "executive_router": "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
        "t19_family": "CLOSED",
        "t20_started": False,
        "detailed_long_horizon_scenarios": cov["scenarios"],
    }


def main() -> int:
    doc = build_cleanup_document()
    dest = T19 / "post_merge_audit_cleanup.json"
    dest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    cov = doc["long_horizon_coverage"]
    print(json.dumps({
        "wrote": str(dest.relative_to(ROOT)).replace("\\", "/"),
        "scicomp_previous": doc["scicomp_status_cleanup"]["previous_recorded_value"],
        "scicomp_canonical": doc["scicomp_status_cleanup"]["canonical_value"],
        "hash_unchanged": doc["scicomp_status_cleanup"]["implementation_hash_unchanged"],
        "total_long_horizon_scenarios": cov["total_long_horizon_scenarios"],
        "task_count_ge_15": cov["task_count_ge_15"],
        "task_count_15_to_30": cov["task_count_15_to_30"],
        "ge_15_multiple_skills": cov["ge_15_multiple_skills"],
        "ge_15_multiple_dependencies": cov["ge_15_multiple_dependencies"],
        "ge_15_with_replan": cov["ge_15_with_replan"],
        "full_definition_count": cov["full_definition_count"],
        "requirement_met": cov["requirement_met"],
        "coverage_status": cov["coverage_status"],
        "heuristic": cov["original_report_heuristic"]["scenarios"],
        "scenario_ids": cov["scenario_ids"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
