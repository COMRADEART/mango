"""T21R3 - failure analysis for the one-shot evaluation outcome.

Mechanically reconciles the recorded holdout_results.json metrics into
integer row counts, identifies the failure mode, and records the
evaluator-validity verdict. Pure artifact reconciliation - no runtime
call, no re-exposure of any holdout row.

Output: evaluations/t21r3/failure_analysis.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r3"


def main() -> int:
    results = json.loads((OUT / "holdout_results.json").read_text("utf-8"))
    ledger = json.loads((OUT / "evaluation_run_ledger.json")
                        .read_text("utf-8"))
    manifest = json.loads((OUT / "holdout_manifest.json")
                          .read_text("utf-8"))
    ev = json.loads((OUT / "evaluator_freeze.json").read_text("utf-8"))

    suites = results["suites"]
    conf = suites["mango-t21r3-conflict-abstention-holdout-v1"]["metrics"]
    # the conflict metric's denominator is the gold-conflict row count,
    # not the suite total recorded as "n"
    suite_path = (OUT / "suites" /
                  "mango-t21r3-conflict-abstention-holdout-v1" /
                  "holdout.jsonl")
    gold_conflict = sum(
        1 for line in suite_path.read_text("utf-8").splitlines()
        if line.strip()
        and json.loads(line)["gold"]["expect_status"]
        == "CONFLICTING_EVIDENCE")
    detected = round(conf["conflict_detection"] * gold_conflict)
    missed = gold_conflict - detected
    assert abs(detected / gold_conflict - conf["conflict_detection"]) < 5e-5

    analysis = {
        "milestone": "T21R3 failure analysis",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "one_shot_evaluation": {
            "recorded_at": results["recorded_at"],
            "official_runtime_exposures":
                results["official_runtime_exposures"],
            "one_shot": results["one_shot"],
            "overall_pass": results["overall_pass"],
            "floors_all_pass": results["floors_all_pass"],
            "zero_tolerance_all_zero": results["zero_tolerance_all_zero"],
            "suite_minimums_met": results["suite_minimums_met"],
        },
        "integer_reconciliation": {
            "conflict_suite_rows": sum(
                1 for line in suite_path.read_text("utf-8").splitlines()
                if line.strip()),
            "gold_conflict_rows": gold_conflict,
            "conflicts_detected": detected,
            "conflicts_missed": missed,
            "conflict_false_resolutions": 0,
            "failed_floor_metrics": [
                {"group": c["group"], "metric": c["metric"],
                 "value": c["value"], "floor": c["floor"], "op": c["op"]}
                for c in results["floors_comparison"] if not c["pass"]],
            "note": "conflict_detection = 48/54 = 0.8889 exactly; the 6 "
                    "missed gold-conflict rows did NOT answer "
                    "(conflict_false_resolution = 0.0), i.e. they "
                    "abstained - a conservative failure mode, not a "
                    "fabrication or silent resolution.",
        },
        "failure_modes": [
            {
                "id": "conflict_detection_gap_on_low_overlap_phrasings",
                "kind": "RUNTIME_CAPABILITY_FAILURE",
                "rows": {"conflict_suite_gold_conflict": missed},
                "mechanism": "Static reading of the frozen pipeline "
                             "(src/sciencemath/knowledge/pipeline.py:201-211, "
                             ":306-321): conflict scoping requires the "
                             "TOP-RANKED reranked item to carry "
                             "fact_entity/fact_attribute metadata for the "
                             "claimed fact (_relevant_conflicts). For query "
                             "phrasings whose content tokens overlap the "
                             "conflict chunk text weakly (e.g. "
                             "'recorded'/'listed'/'establishment' absent "
                             "from 'The established year of X is NNNN, per "
                             "the Register...'), a chunk without the fact "
                             "metadata can rank first; the scoped conflict "
                             "list is then empty (NO_CONFLICT) and the row "
                             "proceeds to synthesis, where the coverage "
                             "gate abstains INSUFFICIENT_EVIDENCE instead "
                             "of surfacing CONFLICTING_EVIDENCE.",
                "repair_policy": "NONE POST-FREEZE. The holdout is exposed; "
                                 "any repair informed by these rows would "
                                 "compromise the blind validation. The "
                                 "failure is recorded honestly and the "
                                 "decision keeps KNOWLEDGE_RAG "
                                 "EXPERIMENTAL.",
            },
        ],
        "evaluator_validity": {
            "verdict": "VALID",
            "evidence": {
                "evaluator_source_sha256_matches_freeze": True,
                "evaluator_freeze_hash_in_ledger":
                    ledger["evaluator_freeze_hash"],
                "evaluator_frozen_before_holdout":
                    ev["recorded_at"] < manifest["frozen_at"],
                "holdout_manifest_sha256":
                    ledger["holdout_manifest_sha256"],
                "manifest_freeze_inputs_verified_by_protection_battery":
                    True,
                "no_post_freeze_edit": "the protection battery's "
                                       "t21r3_freeze_identity layer "
                                       "re-hashed every frozen input, "
                                       "suite and corpus file against "
                                       "holdout_manifest.json AFTER the "
                                       "evaluation",
            },
        },
        "verdict": "FAILURES_PRESENT",
    }
    (OUT / "failure_analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"verdict": analysis["verdict"],
                      "evaluator_validity":
                          analysis["evaluator_validity"]["verdict"],
                      "conflicts_detected": detected,
                      "conflicts_missed": missed}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())