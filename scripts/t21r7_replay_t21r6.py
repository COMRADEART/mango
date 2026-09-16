"""Run the exposed T21R6 holdout as non-promotional T21R7 development data."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r6_run_eval as evaluator  # noqa: E402
from sciencemath.knowledge.corpus import load_corpus  # noqa: E402


OUT_DIR = ROOT / "evaluations" / "t21r7"
SUMMARY_PATH = OUT_DIR / "t21r6_replay_non_promotional.json"
RAW_PATH = OUT_DIR / "t21r6_replay_raw.jsonl"
FREEZE_PATH = OUT_DIR / "t21r6_failure_freeze.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _suite_block(suite: str, rows: list[dict], results: list[dict]) -> dict:
    if suite == evaluator.SUITES[0]:
        metrics = evaluator.retrieval_metrics(results)
    elif suite == evaluator.SUITES[4]:
        metrics = evaluator.citation_metrics(results, rows)
    elif suite == evaluator.SUITES[5]:
        metrics = evaluator.abstention_metrics(results)
    elif suite == evaluator.SUITES[6]:
        metrics = evaluator.temporal_metrics(rows, results)
    elif suite == evaluator.SUITES[7]:
        metrics = evaluator.security_metrics(results, rows)
        metrics["containment_rate"] = evaluator.answer_correctness(results)
    else:
        metrics = {"grounded_accuracy": evaluator.answer_correctness(results)}
        categories: dict[str, list[dict]] = {}
        for row, result in zip(rows, results):
            categories.setdefault(row["category"], []).append(result)
        metrics["per_category"] = {
            category: round(
                sum(1 for result in values if result["correct"]) / len(values),
                4,
            )
            for category, values in sorted(categories.items())
        }
    return {"n": len(rows), "metrics": metrics}


def main() -> int:
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    corpus = load_corpus(evaluator.CORPUS_DIR)
    evaluator._validate_corpus_domain_tags(corpus)
    contract = json.loads(evaluator.CONTRACT_PATH.read_text(encoding="utf-8"))

    per_suite: dict[str, dict] = {}
    all_answer_results: list[dict] = []
    all_answer_rows: list[dict] = []
    all_rows_all: list[tuple[str, list[dict], list[dict]]] = []
    by_case: dict[str, dict] = {}
    raw_lines: list[str] = []

    for suite in evaluator.SUITES:
        rows = evaluator.load_rows(suite)
        results: list[dict] = []
        for row in rows:
            if row["mode"] == "retrieval":
                raw = evaluator.run_retrieval_row(row, corpus)
            else:
                raw, _runtime_result = evaluator.run_answer_row(row, corpus)
                all_answer_results.append(raw)
                all_answer_rows.append(row)
            raw["suite"] = suite
            results.append(raw)
            by_case[raw["case_id"]] = raw
            raw_lines.append(json.dumps(raw, ensure_ascii=False, sort_keys=True))
        all_rows_all.append((suite, rows, results))
        per_suite[suite] = _suite_block(suite, rows, results)
        print(f"{suite}: {per_suite[suite]['metrics']}")

    metrics = evaluator.aggregate_metrics(
        per_suite, all_rows_all, all_answer_results, all_answer_rows,
        evaluator.SUITES,
    )
    comparisons = evaluator.compare_floors(metrics, contract)
    zero_totals = evaluator.aggregate_zero_totals(all_rows_all)
    zero_ok = all(value == 0 for value in zero_totals.values())
    suites_ok = evaluator.suite_minimums_met(per_suite, contract)

    repaired_classes: dict[str, dict] = {}
    for class_id, block in freeze["classes"].items():
        ids = [row["case_id"] for row in block["rows"]]
        remaining = [case_id for case_id in ids
                     if not by_case.get(case_id, {}).get("correct")]
        repaired_classes[class_id] = {
            "original_count": len(ids),
            "remaining_count": len(remaining),
            "remaining_case_ids": remaining,
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text("\n".join(raw_lines) + "\n", encoding="utf-8",
                        newline="\n")
    floors_all_pass = all(item["pass"] for item in comparisons)
    old_failures_remaining = sum(
        block["remaining_count"] for block in repaired_classes.values())
    document = {
        "milestone": "T21R7",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "label": "T21R6_REPLAY_NON_PROMOTIONAL",
        "promotion_value": "ZERO",
        "source_holdout": "T21R6 exposed/consumed development data",
        "rows_executed": len(by_case),
        "expected_rows": 3753,
        "all_rows_executed": len(by_case) == 3753,
        "raw_results_path": str(RAW_PATH.relative_to(ROOT)).replace("\\", "/"),
        "raw_results_sha256": _sha256(RAW_PATH),
        "failure_freeze_sha256": _sha256(FREEZE_PATH),
        "repaired_failure_classes": repaired_classes,
        "old_failures_remaining": old_failures_remaining,
        "suites": per_suite,
        "metrics": metrics,
        "floors_comparison": comparisons,
        "floors_all_pass": floors_all_pass,
        "zero_tolerance_totals": zero_totals,
        "zero_tolerance_all_zero": zero_ok,
        "suite_minimums_met": suites_ok,
        "development_gate_pass": (
            len(by_case) == 3753
            and old_failures_remaining == 0
            and floors_all_pass
            and zero_ok
            and suites_ok
        ),
    }
    SUMMARY_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({
        "rows_executed": document["rows_executed"],
        "old_failures_remaining": old_failures_remaining,
        "floors_all_pass": floors_all_pass,
        "zero_tolerance_all_zero": zero_ok,
        "development_gate_pass": document["development_gate_pass"],
    }, indent=2))
    return 0 if document["development_gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
