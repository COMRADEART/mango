"""T21.40-T21.42 / T21.43-T21.50 — evaluation runner for the frozen
general-knowledge RAG benchmarks.

Runs the deterministic pipeline over every row of the seven frozen suites
(dev and final positional halves), computes the preregistered metrics,
compares them against evaluations/t21/floors.json, and writes
evaluations/t21/eval_results.json. The FINAL split is scored exactly once
per suite version; no threshold or gold may change afterwards (T21.50).

Usage:
    python scripts/t21_run_eval.py            # dev + final
    python scripts/t21_run_eval.py --split dev
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402
from sciencemath.knowledge.retrieval import retrieve  # noqa: E402
from sciencemath.knowledge.routing import (  # noqa: E402
    CONFLICTING_EVIDENCE,
    INSUFFICIENT_EVIDENCE,
    ROUTE_WEB_RESEARCH,
)

SUITES_DIR = ROOT / "evaluations" / "t21" / "suites"
OUT_PATH = ROOT / "evaluations" / "t21" / "eval_results.json"
FLOORS_PATH = ROOT / "evaluations" / "t21" / "floors.json"

ABSTAIN_STATUSES = {INSUFFICIENT_EVIDENCE, CONFLICTING_EVIDENCE}


def load_rows(suite: str, split: str) -> list[dict]:
    path = SUITES_DIR / suite / f"{split}.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def answer_correct(row: dict, result) -> bool:
    gold = row["gold"]
    if result.status != gold["expect_status"]:
        return False
    if gold["expect_status"] != "ANSWER":
        return True
    lowered = result.answer.lower()
    if not all(s in lowered for s in gold.get("expect_answer_contains", [])):
        return False
    if gold.get("require_citations"):
        if not result.citations or not result.citation_report.get("ok"):
            return False
    return True


def run_answer_row(row: dict, corpus) -> dict:
    result = answer_knowledge(row["request"]["query"], corpus)
    counters = result.zero_tolerance
    return {
        "correct": answer_correct(row, result),
        "status": result.status,
        "expected_status": row["gold"]["expect_status"],
        "citation_report_ok": bool(result.citation_report.get("ok")),
        "n_citations": len(result.citations),
        "all_citations_resolve": bool(
            result.citations and result.citation_report.get("ok")),
        "counters_nonzero": [k for k, v in counters.items() if v],
        "counters": dict(counters),
    }


def run_retrieval_row(row: dict, corpus) -> dict:
    gold_id = row["gold"]["gold_chunk_id"]
    stage = retrieve(corpus.index, corpus.chunks_by_id,
                     row["request"]["query"], top_k=8)
    rank = 0
    for i, (chunk_id, _score) in enumerate(stage.deduped, start=1):
        if chunk_id == gold_id:
            rank = i
            break
    return {"rank": rank, "n_returned": len(stage.deduped)}


def retrieval_metrics(results: list[dict]) -> dict:
    n = len(results)
    ranks = [r["rank"] for r in results]

    def recall(k: int) -> float:
        return sum(1 for r in ranks if 0 < r <= k) / n if n else 0.0

    mrr = sum(1.0 / r for r in ranks if r) / n if n else 0.0
    ndcg = sum(1.0 / math.log2(r + 1) for r in ranks if 0 < r <= 5) / n \
        if n else 0.0
    return {"recall_at_5": round(recall(5), 4), "recall_at_10": round(
        recall(10), 4), "mrr": round(mrr, 4), "ndcg_at_5": round(ndcg, 4)}


def answer_metrics(results: list[dict]) -> dict:
    n = len(results)
    correct = sum(1 for r in results if r["correct"])
    # macro computed by the caller (needs categories); here overall only.
    return {"answer_accuracy_overall": round(correct / n, 4) if n else 0.0,
            "n": n}


def citation_metrics(results: list[dict]) -> dict:
    n = len(results)
    answered = [r for r in results if r["status"] == "ANSWER"]
    if not n:
        return {}
    resolvable = sum(1 for r in answered if r["all_citations_resolve"])
    valid = sum(1 for r in answered if r["citation_report_ok"]
                and r["n_citations"] > 0)
    precise = sum(1 for r in answered if r["citation_report_ok"]
                  and r["n_citations"] > 0 and r["all_citations_resolve"])
    return {
        "citation_resolvability": round(resolvable / n, 4),
        "citation_validity": round(valid / n, 4),
        "citation_precision": round(precise / n, 4),
        "n": n, "n_answered": len(answered),
    }


def abstention_metrics(results: list[dict]) -> dict:
    n = len(results)
    abstained = [r for r in results if r["status"] in ABSTAIN_STATUSES]
    recall = len(abstained) / n if n else 0.0
    precision = (sum(1 for r in abstained if r["expected_status"]
                     in ABSTAIN_STATUSES) / len(abstained)) if abstained \
        else 0.0
    return {"abstention_recall": round(recall, 4),
            "abstention_precision": round(precision, 4), "n": n}


def temporal_metrics(results: list[dict], rows: list[dict]) -> dict:
    current_rows = [r for r, row in zip(results, rows)
                    if row["category"] in ("explicit_current",
                                           "latest phrasing")]
    static_rows = [r for r, row in zip(results, rows)
                   if row["category"] in ("snapshot_answer",
                                          "historical_as_of")]
    routed = sum(1 for r in current_rows
                 if r["status"] == ROUTE_WEB_RESEARCH)
    stale_false = sum(1 for r in current_rows if r["status"] == "ANSWER")
    unnecessary = sum(1 for r in static_rows
                      if r["status"] == ROUTE_WEB_RESEARCH)
    return {
        "explicit_current_routing_accuracy":
            round(routed / len(current_rows), 4) if current_rows else 0.0,
        "stale_current_false_answers": stale_false,
        "unnecessary_web_rate": round(unnecessary / len(static_rows), 4)
        if static_rows else 0.0,
        "n": len(results),
    }


def adversarial_metrics(results: list[dict]) -> dict:
    n = len(results)
    contained = sum(1 for r in results
                    if r["correct"] and not r["counters_nonzero"])
    backfill = sum(1 for r in results
                   if "model_memory_backfill_as_evidence"
                   in r["counters_nonzero"])
    return {"containment_rate": round(contained / n, 4) if n else 0.0,
            "model_memory_backfill_events": backfill,
            "n": n}


def suite_metrics(suite: str, rows: list[dict], results: list[dict]) -> dict:
    mode = rows[0]["mode"]
    if mode == "retrieval":
        metrics = retrieval_metrics(results)
    elif suite == "mango-general-citation-v1":
        metrics = citation_metrics(results)
    elif suite == "mango-general-abstention-v1":
        metrics = abstention_metrics(results)
    elif suite == "mango-general-temporal-boundary-v1":
        metrics = temporal_metrics(results, rows)
    elif suite == "mango-general-adversarial-v1":
        metrics = adversarial_metrics(results)
    else:
        metrics = answer_metrics(results)
        # macro accuracy over categories
        cats: dict[str, list[dict]] = {}
        for row, r in zip(rows, results):
            cats.setdefault(row["category"], []).append(r)
        per_cat = {c: round(sum(1 for r in rs if r["correct"]) / len(rs), 4)
                   for c, rs in sorted(cats.items())}
        metrics["answer_accuracy_macro"] = round(
            sum(per_cat.values()) / len(per_cat), 4) if per_cat else 0.0
        metrics["per_category"] = per_cat
    zero_hits = sum(len(r["counters_nonzero"]) for r in results
                    if "counters_nonzero" in r)
    metrics["rows_with_zero_tolerance_hits"] = zero_hits
    return metrics


def compare_floors(all_metrics: dict, floors: dict) -> list[dict]:
    comparisons = []
    for suite, floor_map in floors["suites"].items():
        for split in ("dev", "final"):
            if split not in all_metrics[suite]:
                continue
            metrics = all_metrics[suite][split]
            for metric, floor_spec in floor_map.items():
                floor = floor_spec["value"]
                op = floor_spec["op"]
                value = metrics.get(metric)
                if value is None:
                    comparisons.append({
                        "suite": suite, "split": split, "metric": metric,
                        "floor": floor, "value": None, "pass": False,
                        "reason": "metric missing"})
                else:
                    ok = value <= floor if op == "<=" else value >= floor
                    comparisons.append({"suite": suite, "split": split,
                                        "metric": metric, "op": op,
                                        "floor": floor, "value": value,
                                        "pass": ok})
    return comparisons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "final", "both"),
                        default="both")
    args = parser.parse_args()
    splits = ["dev", "final"] if args.split == "both" else [args.split]

    corpus = load_corpus()
    floors = json.loads(FLOORS_PATH.read_text(encoding="utf-8"))
    suite_names = sorted(p.name for p in SUITES_DIR.iterdir()
                         if p.is_dir())

    all_metrics: dict[str, dict] = {}
    zero_totals: dict[str, int] = {}
    for suite in suite_names:
        all_metrics[suite] = {}
        for split in splits:
            rows = load_rows(suite, split)
            results = []
            for row in rows:
                if row["mode"] == "retrieval":
                    results.append(run_retrieval_row(row, corpus))
                else:
                    results.append(run_answer_row(row, corpus))
            all_metrics[suite][split] = suite_metrics(suite, rows, results)
            for r in results:
                for k in r.get("counters_nonzero", []):
                    zero_totals[k] = zero_totals.get(k, 0) + 1
        print(f"{suite}: " + " | ".join(
            f"{split}={json.dumps(all_metrics[suite][split])[:200]}"
            for split in splits))

    comparisons = compare_floors(all_metrics, floors)
    zero_ok = all(v == 0 for v in zero_totals.values())
    result_doc = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "corpus_manifest_checksum": corpus.manifest.get("manifest_checksum"),
        "splits": splits,
        "suites": all_metrics,
        "zero_tolerance_totals": zero_totals,
        "zero_tolerance_all_zero": zero_ok,
        "floors_comparison": comparisons,
        "floors_all_pass": all(c["pass"] for c in comparisons),
        "overall_pass": all(c["pass"] for c in comparisons) and zero_ok,
    }
    OUT_PATH.write_text(
        json.dumps(result_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    print(f"\nwrote {OUT_PATH.as_posix()}")
    print(f"floors_all_pass={result_doc['floors_all_pass']} "
          f"zero_tolerance_all_zero={zero_ok} "
          f"overall_pass={result_doc['overall_pass']}")
    if not result_doc["floors_all_pass"]:
        for c in comparisons:
            if not c["pass"]:
                print(f"  FAIL {c['suite']}/{c['split']} "
                      f"{c['metric']}={c['value']} floor={c['floor']}")


if __name__ == "__main__":
    main()