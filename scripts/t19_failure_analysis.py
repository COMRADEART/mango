"""T19.68 failure taxonomy from FINAL predictions."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t19/failure_analysis.json"

TAXONOMY = (
    "GOAL_CAPTURE_ERROR", "CONSTRAINT_LOSS", "DECOMPOSITION_ERROR",
    "DEPENDENCY_ERROR", "CYCLE_ERROR", "SKILL_SELECTION_ERROR",
    "SUCCESS_CRITERIA_ERROR", "BUDGET_ERROR", "CHECKPOINT_ERROR",
    "REPLAN_MISSED", "UNNECESSARY_REPLAN", "INVALIDATION_ERROR",
    "PROGRESS_LOSS", "FAILURE_CLASSIFICATION_ERROR", "RECOVERY_ERROR",
    "LOOP_ERROR", "NON_PROGRESS_ERROR", "FALSE_COMPLETE",
    "FALSE_INCOMPLETE", "APPROVAL_ERROR", "POLICY_BYPASS",
    "FABRICATED_TOOL_RESULT", "OTHER",
)

CAT_MAP = {
    "simple_decomposition": "DECOMPOSITION_ERROR",
    "multi_skill_decomposition": "SKILL_SELECTION_ERROR",
    "dependency_ordering": "DEPENDENCY_ERROR",
    "constraint_conflict": "CONSTRAINT_LOSS",
    "ambiguous_goal": "GOAL_CAPTURE_ERROR",
    "budget_compliance": "BUDGET_ERROR",
    "checkpointing": "CHECKPOINT_ERROR",
    "loop_trap": "LOOP_ERROR",
    "non_progress_trap": "NON_PROGRESS_ERROR",
    "premature_completion": "FALSE_COMPLETE",
    "false_incomplete": "FALSE_INCOMPLETE",
    "paid_service_proposal": "POLICY_BYPASS",
    "malicious_observation": "POLICY_BYPASS",
    "selective_downstream_invalidation": "INVALIDATION_ERROR",
    "permanent_failure": "RECOVERY_ERROR",
    "transient_failure": "RECOVERY_ERROR",
}


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def main() -> int:
    fin = json.loads(
        (ROOT / "evaluations/t19/runs/t19-final/summary.json").read_text(
            encoding="utf-8"))
    d = fin.get("combined") or {}
    counts = Counter()
    if d.get("false_complete"):
        counts["FALSE_COMPLETE"] += int(d["false_complete"])
    if d.get("silent_constraint_drop"):
        counts["CONSTRAINT_LOSS"] += int(d["silent_constraint_drop"])
    if d.get("cycle_accepted"):
        counts["CYCLE_ERROR"] += int(d["cycle_accepted"])
    if d.get("unbounded_loops"):
        counts["LOOP_ERROR"] += int(d["unbounded_loops"])
    if (d.get("overall_scenario_success") or 1) < 1:
        counts["OTHER"] += 0
    dominant = "none"
    if counts:
        dominant = counts.most_common(1)[0][0]
    elif (d.get("overall_scenario_success") or 0) < 1:
        dominant = "OTHER"
    else:
        dominant = (
            "Propose-only planner is deterministic and template-driven; "
            "future work is an autonomous workflow/action layer, not T19."
        )
    out = {
        "milestone": "T19.68 failure taxonomy",
        "taxonomy": list(TAXONOMY),
        "counts": dict(counts),
        "dominant": dominant,
        "notes": "Counts derived from FINAL combined metrics; zero-count "
                 "classes omitted.",
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
