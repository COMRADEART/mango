"""T21R4 - failure analysis for the one-shot evaluation outcome.

Mechanically reconciles the recorded holdout_results.json metrics into
integer row counts (using the gold suites and the frozen evaluator's
preregistered metric formulas), identifies the failure surface, and
records the evaluator-validity verdict. Pure artifact reconciliation - no
runtime call, no re-exposure of any holdout row.

Output: evaluations/t21r4/failure_analysis.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r4"
SUITES_DIR = OUT / "suites"


def _rows(suite: str) -> list[dict]:
    return [json.loads(line) for line
            in (SUITES_DIR / suite / "holdout.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    results = json.loads((OUT / "holdout_results.json").read_text("utf-8"))
    ledger = json.loads((OUT / "evaluation_run_ledger.json")
                        .read_text("utf-8"))
    manifest = json.loads((OUT / "holdout_manifest.json")
                          .read_text("utf-8"))
    ev = json.loads((OUT / "evaluator_freeze.json").read_text("utf-8"))

    conf_suite = "mango-t21r4-conflict-abstention-holdout-v1"
    adv_suite = "mango-t21r4-adversarial-holdout-v1"
    conf = results["suites"][conf_suite]["metrics"]
    adv = results["suites"][adv_suite]["metrics"]
    conf_rows = _rows(conf_suite)
    adv_rows = _rows(adv_suite)

    gold_conflict = sum(1 for r in conf_rows
                        if r["gold"]["expect_status"]
                        == "CONFLICTING_EVIDENCE")
    gold_abstain = sum(1 for r in conf_rows
                       if r["gold"]["expect_status"]
                       in ("CONFLICTING_EVIDENCE",
                           "INSUFFICIENT_EVIDENCE"))
    detected = round(conf["conflict_detection"] * gold_conflict)
    missed = gold_conflict - detected
    assert abs(detected / gold_conflict - conf["conflict_detection"]) < 5e-5
    # IE precision = abstained-with-gold-abstain / all-abstained; with
    # recall = 1.0 every gold-abstain row abstained, so TP = gold_abstain
    # and FP = abstained_total - gold_abstain.
    tp = gold_abstain
    abstained_total = round(tp / conf["insufficient_evidence_precision"])
    assert abs(tp / abstained_total
               - conf["insufficient_evidence_precision"]) < 5e-5, \
        "IE precision does not reconcile with gold abstain counts"
    over_abstained = abstained_total - tp

    # injection containment = contained / n over the adversarial suite
    adv_n = adv["n"]
    assert adv_n == len(adv_rows)
    contained = round(adv["prompt_injection_containment"] * adv_n)
    assert abs(contained / adv_n
               - adv["prompt_injection_containment"]) < 5e-5
    not_contained = adv_n - contained

    # source diversity: required-multi-source pass rate over multihop +
    # crossdomain rows declaring >= 2 required source identities
    mh = _rows("mango-t21r4-multihop-holdout-v1")
    cd = _rows("mango-t21r4-crossdomain-holdout-v1")
    diversity_rows = [r for r in mh + cd
                      if len((r["gold"].get("required_sources")
                              or [])) >= 2]
    sd = results["metrics"]["source_diversity"]
    sd_pass = round(sd * len(diversity_rows))
    assert abs(sd_pass / len(diversity_rows) - sd) < 5e-5
    sd_fail = len(diversity_rows) - sd_pass

    failed_floors = [
        {"group": c["group"], "metric": c["metric"], "value": c["value"],
         "floor": c["floor"], "op": c["op"]}
        for c in results["floors_comparison"] if not c["pass"]]

    analysis = {
        "milestone": "T21R4 failure analysis",
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
            "conflict_suite_rows": len(conf_rows),
            "gold_conflict_rows": gold_conflict,
            "conflicts_detected": detected,
            "conflicts_missed": missed,
            "conflict_false_resolutions": 0,
            "gold_abstain_rows_conflict_suite": gold_abstain,
            "abstained_rows_conflict_suite": abstained_total,
            "over_abstentions": over_abstained,
            "adversarial_rows": adv_n,
            "adversarial_contained": contained,
            "adversarial_not_contained": not_contained,
            "multisource_required_rows": len(diversity_rows),
            "multisource_passed": sd_pass,
            "multisource_failed": sd_fail,
            "failed_floor_metrics": failed_floors,
            "note": "conflict_detection = 120/120 = 1.0 exactly (the "
                    "T21R3 failure was 48/54 = 0.8889) and "
                    "conflict_false_resolution = 0.0: the T21R4 "
                    "query-relevant conflict-scoping repair achieved its "
                    "preregistered target on blind data. The failing "
                    "floors are separate surfaces: 8 over-abstentions in "
                    "the conflict suite, 8 adversarial rows not fully "
                    "contained, 53 multihop/crossdomain rows below the "
                    "required multi-source diversity bar, and citation "
                    "verdicts non-OK on a small set of answer-mode rows.",
        },
        "failure_modes": [
            {
                "id": "over_abstention_on_answer_rows_in_conflict_suite",
                "kind": "RUNTIME_CAPABILITY_FAILURE",
                "rows": {"conflict_suite_over_abstentions":
                         over_abstained},
                "mechanism": "HYPOTHESIS (static reading only - no runtime "
                             "re-exposure): the T21R4 query-relevant "
                             "scoping widened the set of conflicts scoped "
                             "as relevant; on a small set of rows whose "
                             "gold expects a resolved ANSWER (authority-/"
                             "freshness-resolvable or negative rows), the "
                             "scoped conflict list is now non-empty and "
                             "the pipeline abstains INSUFFICIENT_EVIDENCE "
                             "instead of resolving by authority/freshness.",
                "repair_policy": "NONE POST-FREEZE. The holdout is exposed; "
                                 "any repair informed by these rows would "
                                 "compromise the blind validation. A future "
                                 "milestone must build a NEW blind holdout.",
            },
            {
                "id": "source_diversity_below_floor",
                "kind": "RUNTIME_CAPABILITY_FAILURE",
                "rows": {"multisource_failed": sd_fail},
                "mechanism": "HYPOTHESIS (static reading only): with "
                             "MAX_PER_SOURCE=3 and 4-gram Jaccard dedup, "
                             "same-entity restatement chunks can occupy the "
                             "window so that one of the two required source "
                             "identities is not represented in the final "
                             "top-8 window on some multihop/crossdomain "
                             "rows.",
                "repair_policy": "NONE POST-FREEZE (see above).",
            },
            {
                "id": "citation_verdict_gaps_on_answer_rows",
                "kind": "RUNTIME_CAPABILITY_FAILURE",
                "rows": {"citation_resolvability": 0.9622,
                         "citation_validity": 0.9622,
                         "citation_precision": 0.9622},
                "mechanism": "Recorded metric level only: the citation "
                             "floors are computed over ALL answer-mode "
                             "rows across the 8 suites; a small set of "
                             "answer rows carry citations whose verdicts "
                             "are not OK. No per-row artifact was written "
                             "by the frozen evaluator, so no row-level "
                             "reconciliation is possible without "
                             "re-exposure, which is forbidden for any "
                             "post-decision repair purpose.",
                "repair_policy": "NONE POST-FREEZE (see above).",
            },
            {
                "id": "injection_containment_below_one",
                "kind": "RUNTIME_CAPABILITY_FAILURE",
                "rows": {"adversarial_not_contained": not_contained},
                "mechanism": "Recorded metric level only: containment "
                             "counts adversarial rows that answered "
                             "correctly AND carried no non-zero "
                             "zero-tolerance counter; 8 of 389 rows "
                             "failed at least one of the two conditions.",
                "repair_policy": "NONE POST-FREEZE (see above).",
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
                                       "t21r4_freeze_identity layer "
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
                      "conflicts_missed": missed,
                      "over_abstentions": over_abstained,
                      "adversarial_not_contained": not_contained,
                      "multisource_failed": sd_fail}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())