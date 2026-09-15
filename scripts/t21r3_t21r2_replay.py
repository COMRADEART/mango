"""T21R3.A5 — NON-PROMOTIONAL replay of the T21R2 holdout after repair.

This is explicitly NOT promotion evidence. The T21R2 holdout is
runtime-exposed. Promotion evidence requires a brand-new T21R3 holdout.

Does NOT enforce the T21R2 runtime freeze (the repair intentionally
changes knowledge runtime). Does NOT rewrite any T21R2 artifact.

Usage: python scripts/t21r3_t21r2_replay.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r2_run_eval as E  # noqa: E402
from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.routing import (  # noqa: E402
    CONFLICTING_EVIDENCE,
    INSUFFICIENT_EVIDENCE,
)

OUT = ROOT / "evaluations" / "t21r3" / "t21r2_replay_non_promotional.json"


def main() -> int:
    corpus = load_corpus(E.CORPUS_DIR)
    contract = json.loads(E.CONTRACT_PATH.read_text(encoding="utf-8"))

    zero_totals: dict[str, int] = {}
    per_suite: dict[str, dict] = {}
    all_answer_results: list[dict] = []
    all_answer_rows: list[dict] = []
    all_rows_all: list[tuple[str, list[dict], list[dict]]] = []

    gold_answer_over_abstain = 0
    false_conflict_remaining = 0
    spoof_total = 0
    spoof_miss_remaining = 0
    regressions: list[dict] = []

    for suite in E.SUITES:
        rows = E.load_rows(suite)
        results: list[dict] = []
        for row in rows:
            if row["mode"] == "retrieval":
                results.append(E.run_retrieval_row(row, corpus))
            else:
                r = E.run_answer_row(row, corpus)
                results.append(r)
                all_answer_results.append(r)
                all_answer_rows.append(row)
                expect = row["gold"].get("expect_status")
                if expect == "ANSWER" and r["status"] in (
                        INSUFFICIENT_EVIDENCE, CONFLICTING_EVIDENCE):
                    gold_answer_over_abstain += 1
                    if r["status"] == CONFLICTING_EVIDENCE:
                        false_conflict_remaining += 1
                    regressions.append({
                        "case_id": row["case_id"], "suite": suite,
                        "kind": "gold_answer_over_abstention",
                        "status": r["status"],
                    })
                elif expect == "ANSWER" and not r["correct"]:
                    regressions.append({
                        "case_id": row["case_id"], "suite": suite,
                        "kind": "gold_answer_incorrect",
                        "status": r["status"],
                    })
                if row.get("category") == "citation_spoof":
                    spoof_total += 1
                    if not (r["correct"]
                            and r["status"] == INSUFFICIENT_EVIDENCE):
                        spoof_miss_remaining += 1
                        regressions.append({
                            "case_id": row["case_id"], "suite": suite,
                            "kind": "spoof_miss",
                            "status": r["status"],
                            "correct": r["correct"],
                        })
        all_rows_all.append((suite, rows, results))
        for r in results:
            for k in r.get("counters_nonzero", []):
                zero_totals[k] = zero_totals.get(k, 0) + 1
        suite_block: dict = {"n": len(rows)}
        if suite == E.SUITES[0]:
            suite_block["metrics"] = E.retrieval_metrics(results)
        elif suite == E.SUITES[4]:
            suite_block["metrics"] = E.citation_metrics(results, rows)
        elif suite == E.SUITES[5]:
            suite_block["metrics"] = E.abstention_metrics(results)
        elif suite == E.SUITES[6]:
            suite_block["metrics"] = E.temporal_metrics(rows, results)
        elif suite == E.SUITES[7]:
            suite_block["metrics"] = E.security_metrics(results, rows)
            suite_block["metrics"]["containment_rate"] = \
                E.answer_correctness(results)
        else:
            m = {"grounded_accuracy": E.answer_correctness(results)}
            cats: dict[str, list[dict]] = {}
            for row, r in zip(rows, results):
                cats.setdefault(row["category"], []).append(r)
            m["per_category"] = {
                c: round(sum(1 for x in rs if x["correct"]) / len(rs), 4)
                for c, rs in sorted(cats.items())}
            suite_block["metrics"] = m
        per_suite[suite] = suite_block
        print(f"{suite}: {json.dumps(suite_block['metrics'])[:220]}")

    metrics: dict = {}
    metrics.update(per_suite[E.SUITES[0]]["metrics"])
    metrics.update(per_suite[E.SUITES[5]]["metrics"])
    metrics.update(per_suite[E.SUITES[6]]["metrics"])
    metrics.update(per_suite[E.SUITES[7]]["metrics"])
    metrics.update(E.citation_metrics(all_answer_results, all_answer_rows))
    answer_rows_total = len(all_answer_results)
    correct_total = sum(1 for r in all_answer_results if r["correct"])
    metrics["overall_grounded_accuracy"] = round(
        correct_total / answer_rows_total, 4) if answer_rows_total else 0.0
    cat_totals: dict[str, list[dict]] = {}
    for row, r in zip(all_answer_rows, all_answer_results):
        cat_totals.setdefault(row["category"], []).append(r)
    per_cat = {c: round(sum(1 for x in rs if x["correct"]) / len(rs), 4)
               for c, rs in sorted(cat_totals.items())}
    metrics["domain_macro_grounded_accuracy"] = round(
        sum(per_cat.values()) / len(per_cat), 4) if per_cat else 0.0
    metrics["per_category"] = per_cat
    metrics["single_hop_grounded_accuracy"] = \
        per_suite[E.SUITES[1]]["metrics"]["grounded_accuracy"]
    metrics["multi_hop_grounded_accuracy"] = \
        per_suite[E.SUITES[2]]["metrics"]["grounded_accuracy"]
    metrics["cross_domain_synthesis_accuracy"] = \
        per_suite[E.SUITES[3]]["metrics"]["grounded_accuracy"]
    metrics["source_diversity"] = E._multisource_diversity(all_rows_all)

    comparisons = E.compare_floors(metrics, contract)
    floors_all_pass = all(c["pass"] for c in comparisons)
    zero_ok = all(v == 0 for v in zero_totals.values())

    # New regressions = incorrect non-abstention failures beyond the
    # reconciled old defect families (should be empty after repair).
    new_regressions = [r for r in regressions
                       if r["kind"] == "gold_answer_incorrect"]

    record = {
        "milestone": "T21R3.A5 T21R2_REPLAY_NON_PROMOTIONAL",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "promotional": False,
        "label": "T21R2_REPLAY_NON_PROMOTIONAL",
        "note": ("Replay of the exposed T21R2 holdout after conflict and "
                 "provenance-spoof repair. NOT promotion evidence."),
        "reconciliation": {
            "old_64_false_over_abstentions_remaining":
                gold_answer_over_abstain,
            "old_false_conflict_status_remaining":
                false_conflict_remaining,
            "old_2_spoof_misses_remaining": spoof_miss_remaining,
            "spoof_rows": spoof_total,
            "spoof_ok": spoof_total - spoof_miss_remaining,
            "new_regressions": len(new_regressions),
        },
        "floors_all_pass": floors_all_pass,
        "zero_tolerance_all_zero": zero_ok,
        "zero_tolerance_totals": zero_totals,
        "floor_comparisons": comparisons,
        "metrics": metrics,
        "per_suite": per_suite,
        "regressions_sample": regressions[:40],
        "pass_gate": {
            "old_false_over_abstentions_remaining_is_0":
                gold_answer_over_abstain == 0,
            "old_spoof_misses_remaining_is_0": spoof_miss_remaining == 0,
            "new_regressions_is_0": len(new_regressions) == 0,
            "zero_tolerance_all_zero": zero_ok,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps(record["reconciliation"], indent=2))
    print("floors_all_pass", floors_all_pass, "zero_ok", zero_ok)
    print("wrote", OUT.as_posix())
    return 0 if all(record["pass_gate"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
