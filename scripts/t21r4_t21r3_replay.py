"""T21R4.6 — T21R3 development replay (NON-PROMOTIONAL).

The T21R3 holdout is EXPOSED (one-shot run completed). This script replays
the exposed holdout against the repaired T21R4 runtime for DEVELOPMENT
VERIFICATION ONLY:

  - the old six conflict misses must be repaired (remaining = 0)
  - conflict_detection must be 1.0 and conflict_false_resolution 0.0
  - no regressions in citations, spoof rejection, injection containment,
    retrieval, answers, temporal behavior, zero-tolerance counters

The output is written under evaluations/t21r4/ and can never promote
KNOWLEDGE_RAG. T21R3 artifacts are never modified.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r3_run_eval as r3eval  # noqa: E402
from sciencemath.knowledge.corpus import load_corpus  # noqa: E402

OUT_PATH = ROOT / "evaluations" / "t21r4" / "t21r3_replay_non_promotional.json"
T21R3_CORPUS = ROOT / "rag" / "gk_holdout_t21r3"


def replay() -> dict:
    corpus = load_corpus(T21R3_CORPUS)
    per_suite: dict[str, dict] = {}
    all_answer_results: list[dict] = []
    conflict_misses: list[dict] = []
    zero_totals: dict[str, int] = {}
    for suite in r3eval.SUITES:
        rows = r3eval.load_rows(suite)
        results = []
        for row in rows:
            if row["mode"] == "retrieval":
                results.append(r3eval.run_retrieval_row(row, corpus))
            else:
                result = r3eval.run_answer_row(row, corpus)
                results.append(result)
                all_answer_results.append(result)
                if suite == r3eval.SUITES[5] and \
                        row["gold"]["expect_status"] == \
                        "CONFLICTING_EVIDENCE" and \
                        result["status"] != "CONFLICTING_EVIDENCE":
                    conflict_misses.append({
                        "case_id": row["case_id"],
                        "query": row["request"]["query"],
                        "status": result["status"]})
        for r in results:
            for k in r.get("counters_nonzero", []):
                zero_totals[k] = zero_totals.get(k, 0) + 1
        suite_block: dict = {"n": len(rows)}
        if suite == r3eval.SUITES[0]:
            suite_block["metrics"] = r3eval.retrieval_metrics(results)
        elif suite == r3eval.SUITES[4]:
            suite_block["metrics"] = r3eval.citation_metrics(results, rows)
        elif suite == r3eval.SUITES[5]:
            suite_block["metrics"] = r3eval.abstention_metrics(results)
        elif suite == r3eval.SUITES[6]:
            suite_block["metrics"] = r3eval.temporal_metrics(rows, results)
        elif suite == r3eval.SUITES[7]:
            suite_block["metrics"] = r3eval.security_metrics(results, rows)
            suite_block["metrics"]["containment_rate"] = \
                r3eval.answer_correctness(results)
        else:
            m = {"grounded_accuracy": r3eval.answer_correctness(results)}
            cats: dict[str, list[dict]] = {}
            for row, r in zip(rows, results):
                cats.setdefault(row["category"], []).append(r)
            m["per_category"] = {
                c: round(sum(1 for r in rs if r["correct"]) / len(rs), 4)
                for c, rs in sorted(cats.items())}
            suite_block["metrics"] = m
        per_suite[suite] = suite_block
        print(f"{suite}: {json.dumps(suite_block['metrics'])[:200]}")
    return {
        "replay": per_suite,
        "conflict_misses": conflict_misses,
        "zero_tolerance_totals": zero_totals,
        "_all_answer_results": all_answer_results,
        "_per_suite_rows": None,
    }


def main() -> None:
    started = datetime.now(timezone.utc).isoformat()
    raw = replay()
    metrics: dict[str, float] = {}
    metrics.update(raw["replay"][r3eval.SUITES[0]]["metrics"])
    metrics.update(raw["replay"][r3eval.SUITES[5]]["metrics"])
    metrics.update(raw["replay"][r3eval.SUITES[6]]["metrics"])
    doc = {
        "milestone": "T21R4.6 - T21R3_REPLAY_NON_PROMOTIONAL",
        "recorded_at": started,
        "role": ("DEVELOPMENT ONLY. The T21R3 holdout is exposed; this "
                 "replay verifies the T21R4 conflict-scoping repair against "
                 "the exposed failure cases. It can never promote "
                 "KNOWLEDGE_RAG. Promotion evidence comes exclusively from "
                 "the fresh T21R4 blind holdout."),
        "runtime_under_test": "post-T21R4-conflict-scoping-repair",
        "replayed_holdout": "rag/gk_holdout_t21r3 + evaluations/t21r3/suites",
        "replayed_rows": sum(s["n"] for s in raw["replay"].values()),
        "metrics": {k: v for k, v in metrics.items()
                    if isinstance(v, (int, float))},
        "per_suite": {k: v["metrics"] for k, v in raw["replay"].items()},
        "old_six_conflict_misses_remaining": len(raw["conflict_misses"]),
        "conflict_miss_detail": raw["conflict_misses"],
        "zero_tolerance_totals": raw["zero_tolerance_totals"],
        "checks": {
            "old_six_misses_repaired":
                len(raw["conflict_misses"]) == 0,
            "conflict_detection_is_1.0":
                metrics.get("conflict_detection") == 1.0,
            "conflict_false_resolution_is_0.0":
                metrics.get("conflict_false_resolution") == 0.0,
            "zero_tolerance_all_zero": not raw["zero_tolerance_totals"],
        },
        "promotion_value": "NONE - T21R3_REPLAY_NON_PROMOTIONAL",
    }
    OUT_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"wrote {OUT_PATH.as_posix()}")
    print(json.dumps(doc["checks"], indent=1))
    print(json.dumps(doc["metrics"], indent=1)[:800])


if __name__ == "__main__":
    main()