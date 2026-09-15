"""T21R3 - final decision record, mechanically derived from the frozen
contract and the one-shot evaluation results.

The decision function is preregistered in the validation contract's
decision semantics: with a valid evaluator and met suite minimums,
  - all floors pass AND all zero-tolerance gates are zero
        -> PROMOTE_KNOWLEDGE_RAG_ACTIVE (then apply the registry flip)
  - zero-tolerance gates zero BUT a capability floor fails
        -> KEEP_KNOWLEDGE_RAG_EXPERIMENTAL (no registry change)
  - the evaluator itself is defective post-freeze
        -> T21R3_EVALUATOR_INVALID (no fix-and-rerun)

Output: evaluations/t21r3/final_decision.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r3"


def main() -> int:
    results = json.loads((OUT / "holdout_results.json").read_text("utf-8"))
    analysis = json.loads((OUT / "failure_analysis.json").read_text("utf-8"))

    evaluator_valid = analysis["evaluator_validity"]["verdict"] == "VALID"
    if not evaluator_valid:
        decision = "T21R3_EVALUATOR_INVALID"
    elif results["floors_all_pass"] and results["zero_tolerance_all_zero"] \
            and results["suite_minimums_met"]:
        decision = "PROMOTE_KNOWLEDGE_RAG_ACTIVE"
    elif results["zero_tolerance_all_zero"] and results["suite_minimums_met"]:
        decision = "KEEP_KNOWLEDGE_RAG_EXPERIMENTAL"
    else:
        decision = "T21R3_INFRASTRUCTURE_BLOCKED"

    failed_floors = [
        {"group": c["group"], "metric": c["metric"], "value": c["value"],
         "floor": c["floor"], "op": c["op"]}
        for c in results["floors_comparison"] if not c["pass"]]

    doc = {
        "milestone": "T21R3 final decision (mechanically derived)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "decision_basis": (
            "Zero-tolerance gates all zero and all 8 suite minimums met, "
            "but 1 of 32 preregistered capability floors failed: "
            "abstention_conflict/conflict_detection = 0.8889 < 0.98 "
            "(48/54 gold-conflict rows surfaced CONFLICTING_EVIDENCE; the "
            "6 missed rows abstained rather than answering - "
            "conflict_false_resolution = 0.0). The evaluator is valid "
            "(source hash matches the pre-holdout evaluator freeze; every "
            "frozen input re-verified after the run). Per the contract "
            "the knowledge RAG runtime is NOT promoted and stays "
            "EXPERIMENTAL; no post-freeze repair is permitted because the "
            "holdout is now exposed."),
        "applied": False,
        "registry_action": "none - KNOWLEDGE_RAG remains EXPERIMENTAL, "
                           "exactly as frozen in runtime_freeze.json; "
                           "src/sciencemath/executive/skills.py is "
                           "unchanged",
        "evaluator_valid": evaluator_valid,
        "failed_floors": failed_floors,
        "floors_total": len(results["floors_comparison"]),
        "floors_passed": len(results["floors_comparison"])
        - len(failed_floors),
        "zero_tolerance_all_zero": results["zero_tolerance_all_zero"],
        "zero_tolerance_totals": results["zero_tolerance_totals"],
        "suite_minimums_met": results["suite_minimums_met"],
        "official_runtime_exposures": results["official_runtime_exposures"],
        "one_shot": results["one_shot"],
        "post_freeze_repair_policy": "FORBIDDEN - the holdout data is "
                                     "exposed after the one-shot run; any "
                                     "runtime or gold change informed by "
                                     "these results would invalidate the "
                                     "blind validation. A future milestone "
                                     "must build a NEW blind holdout.",
    }
    (OUT / "final_decision.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"decision": decision,
                      "failed_floors": failed_floors}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())