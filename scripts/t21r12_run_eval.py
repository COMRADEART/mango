"""Preregistered T21R12 evaluator; never used during preconstruction.

Metric implementations retain the qualified T21R8/T21R6 lineage while the
T21R12 scoring conjunction is loaded from its single preregistered contract.
The official runner is the only permitted caller of ``evaluate``.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r8_run_eval as _qualified  # noqa: E402


OUT_DIR = ROOT / "evaluations" / "t21r12"
CONTRACT_PATH = OUT_DIR / "validation_contract.json"
SEMANTICS_PATH = OUT_DIR / "scoring_semantics.json"
SUITES = [
    "mango-t21r12-retrieval-holdout-v1",
    "mango-t21r12-singlehop-holdout-v1",
    "mango-t21r12-multihop-holdout-v1",
    "mango-t21r12-crossdomain-holdout-v1",
    "mango-t21r12-citation-claim-holdout-v1",
    "mango-t21r12-conflict-abstention-holdout-v1",
    "mango-t21r12-temporal-holdout-v1",
    "mango-t21r12-adversarial-holdout-v1",
]

_SEMANTICS_DOCUMENT = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
SCORING_SEMANTICS = _SEMANTICS_DOCUMENT["definition"]


def scoring_semantics_sha256() -> str:
    canonical = json.dumps(SCORING_SEMANTICS, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _check_conjunction(conjunction: list[str], raw: dict) -> bool:
    result = True
    for name in conjunction:
        if name == "zero_tolerance_all_zero":
            result = result and not (raw.get("counters_nonzero") or [])
        elif name in raw:
            result = result and bool(raw[name])
        else:
            raise ValueError(f"evaluator raw schema lacks conjunction {name}")
    return bool(result)


def answer_row_correct(raw: dict) -> bool:
    section = "answer_row_correctness" if raw.get(
        "expected_status", "ANSWER") == "ANSWER" \
        else "non_answer_row_correctness"
    return _check_conjunction(SCORING_SEMANTICS[section]["conjunction"], raw)


def _run_answer_row(row: dict, corpus) -> tuple[dict, object]:
    raw, result = _qualified.run_answer_row(row, corpus)
    raw["correct"] = answer_row_correct(raw)
    raw["scoring_semantics_sha256"] = scoring_semantics_sha256()
    return raw, result


def _write_raw(handle, raw: dict) -> None:
    handle.write(json.dumps(raw, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def evaluate(corpus, rows_by_suite: dict[str, list[dict]], raw_path: Path,
             validation_contract: dict) -> dict:
    """Execute every frozen row exactly once after official preflight."""
    if list(rows_by_suite) != SUITES:
        raise ValueError("suite order/schema mismatch")
    _qualified._r6.SUITES = list(SUITES)
    per_suite: dict[str, dict] = {}
    all_answer_results: list[dict] = []
    all_answer_rows: list[dict] = []
    all_rows_all: list[tuple[str, list[dict], list[dict]]] = []
    zero_totals: dict[str, int] = {}
    with raw_path.open("x", encoding="utf-8", newline="\n") as handle:
        for suite in SUITES:
            rows = rows_by_suite[suite]
            results: list[dict] = []
            for row in rows:
                if row.get("mode") == "retrieval":
                    raw = _qualified.run_retrieval_row(row, corpus)
                else:
                    raw, _result = _run_answer_row(row, corpus)
                    all_answer_results.append(raw)
                    all_answer_rows.append(row)
                raw["suite"] = suite
                results.append(raw)
                _write_raw(handle, raw)
                for counter in raw.get("counters_nonzero") or []:
                    zero_totals[counter] = zero_totals.get(counter, 0) + 1
            all_rows_all.append((suite, rows, results))
            if suite == SUITES[0]:
                metrics = _qualified.retrieval_metrics(results)
            elif suite == SUITES[4]:
                metrics = _qualified.citation_metrics(results, rows)
            elif suite == SUITES[5]:
                metrics = _qualified.abstention_metrics(results)
            elif suite == SUITES[6]:
                metrics = _qualified.temporal_metrics(rows, results)
            elif suite == SUITES[7]:
                metrics = _qualified.security_metrics(results, rows)
            else:
                metrics = {"grounded_accuracy":
                           _qualified.answer_correctness(results)}
            per_suite[suite] = {"n": len(rows), "metrics": metrics}
    metrics = _qualified.aggregate_metrics(
        per_suite, all_rows_all, all_answer_results, all_answer_rows, SUITES)
    comparisons = _qualified.compare_floors(metrics, validation_contract)
    expected = validation_contract["official_evaluation"]
    del expected
    return {
        "artifact": "T21R12_OFFICIAL_HOLDOUT_RESULTS",
        "per_suite": per_suite,
        "metrics": metrics,
        "floor_comparisons": comparisons,
        "zero_tolerance_totals": zero_totals,
        "pass": all(item["pass"] for item in comparisons)
        and not any(zero_totals.values()),
        "runtime_rows_executed": sum(len(rows) for rows in rows_by_suite.values()),
        "official_runtime_exposures": 1,
    }


def main() -> int:
    raise SystemExit(
        "T21R12 evaluator cannot be run directly; use "
        "python scripts/t21r12_official_eval.py after a valid seal")


if __name__ == "__main__":
    raise SystemExit(main())


