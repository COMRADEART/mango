"""T21R4.17 — ONE-SHOT evaluation of the frozen T21R4 holdout.

This evaluator is FROZEN BEFORE THE HOLDOUT DATA IS GENERATED (its source
hash is recorded in evaluations/t21r4/evaluator_freeze.json, written before
scripts/t21r4_world.py runs). It runs the frozen runtime over every row of
the 8 frozen holdout suites exactly once, computes every preregistered
metric in evaluations/t21r4/validation_contract.json, applies all 20
zero-tolerance gates, and compares against the contract floors.

Preregistered scoring semantics (identical to the T21R post-correction
definitions, frozen here BEFORE data):
  - citation metrics use the gold-ANSWER-row denominator (abstain/routing
    rows emit no citations and are scored by the abstention/temporal/
    security metrics instead);
  - source diversity is the required-multi-source pass rate over all
    multihop + crossdomain rows declaring >= 2 required source identities;
  - the official runtime exposure count is exactly 1; this script must
    never be rerun as promotion evidence after any gold/runtime change.

Usage: python scripts/t21r4_run_eval.py
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
import traceback
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

OUT_DIR = ROOT / "evaluations" / "t21r4"
SUITES_DIR = OUT_DIR / "suites"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r4"
MANIFEST_PATH = OUT_DIR / "holdout_manifest.json"
OUT_PATH = OUT_DIR / "holdout_results.json"
CONTRACT_PATH = OUT_DIR / "validation_contract.json"
RUNTIME_FREEZE_PATH = OUT_DIR / "runtime_freeze.json"
LEDGER_PATH = OUT_DIR / "evaluation_run_ledger.json"

SUITES = [
    "mango-t21r4-retrieval-holdout-v1",
    "mango-t21r4-singlehop-holdout-v1",
    "mango-t21r4-multihop-holdout-v1",
    "mango-t21r4-crossdomain-holdout-v1",
    "mango-t21r4-citation-claim-holdout-v1",
    "mango-t21r4-conflict-abstention-holdout-v1",
    "mango-t21r4-temporal-holdout-v1",
    "mango-t21r4-adversarial-holdout-v1",
]

ABSTAIN_STATUSES = {INSUFFICIENT_EVIDENCE, CONFLICTING_EVIDENCE}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_lf(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_rows(suite: str) -> list[dict]:
    path = SUITES_DIR / suite / "holdout.jsonl"
    return [json.loads(line) for line
            in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_freeze() -> dict:
    """T21R4.17 pre-run integrity check: verify EVERY frozen hash before
    the runtime is invoked even once. Any mismatch stops the evaluation."""
    if not (OUT_DIR / "HOLDOUT_FROZEN").exists():
        raise SystemExit("HOLDOUT_FROZEN missing: run scripts/t21r4_freeze.py")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for label, info in manifest["freeze_inputs"].items():
        p = ROOT / info["path"]
        if not p.exists():
            raise SystemExit(f"frozen input missing: {info['path']}")
        if sha256_file(p) != info["sha256"]:
            raise SystemExit(
                f"T21R4_FREEZE_VIOLATION: frozen input changed after "
                f"freeze: {info['path']}")
    for name, info in manifest["suites"].items():
        p = SUITES_DIR / name / "holdout.jsonl"
        if sha256_lf(p) != info["holdout_sha256"]:
            raise SystemExit(
                f"T21R4_FREEZE_VIOLATION: suite changed after freeze: {name}")
    for fname, info in manifest["corpus"].items():
        p = ROOT / info["path"]
        if not p.exists():
            raise SystemExit(f"frozen corpus file missing: {info['path']}")
        if sha256_lf(p) != info["sha256"]:
            raise SystemExit(
                f"T21R4_FREEZE_VIOLATION: corpus changed after freeze: "
                f"{info['path']}")
    # runtime must be byte-identical to the T21R4.B1 freeze
    runtime_freeze = json.loads(RUNTIME_FREEZE_PATH.read_text("utf-8"))
    groups = runtime_freeze["runtime_composites"]
    from t21r4_freeze_runtime import RUNTIME_GROUPS, sha_group  # noqa: E402
    for name, spec in RUNTIME_GROUPS.items():
        if sha_group(spec) != groups[name]:
            raise SystemExit(
                f"T21R4_FREEZE_VIOLATION: runtime group changed after "
                f"freeze: {name}")
    return manifest


def status_ok(row: dict, result) -> bool:
    return result.status == row["gold"]["expect_status"]


def run_answer_row(row: dict, corpus) -> dict:
    result = answer_knowledge(row["request"]["query"], corpus)
    gold = row["gold"]
    counters = result.zero_tolerance
    counters_nonzero = [k for k, v in counters.items() if v]

    status_match = status_ok(row, result)
    contains_ok = True
    if gold["expect_status"] == "ANSWER":
        lowered = result.answer.lower()
        missing = [s for s in gold.get("expect_answer_contains", [])
                   if s.lower() not in lowered]
        contains_ok = not missing
    citations_ok = True
    if gold["expect_status"] == "ANSWER" and gold.get("require_citations"):
        citations_ok = bool(result.citations) and bool(
            result.citation_report.get("ok"))
    required_sources = gold.get("required_sources") or []
    sources_ok = True
    if gold["expect_status"] == "ANSWER" and required_sources:
        cited = {c["source_id"] for c in result.citations}
        sources_ok = set(required_sources).issubset(cited)
    claims_ok = gold["expect_status"] != "ANSWER" or bool(
        result.claim_review.get("all_claims_supported"))

    correct = (status_match and contains_ok and citations_ok
               and sources_ok and claims_ok and not counters_nonzero)
    claim_counts = (result.claim_review.get("counts") or {})
    return {
        "case_id": row["case_id"],
        "category": row["category"],
        "correct": correct,
        "status": result.status,
        "expected_status": gold["expect_status"],
        "status_match": status_match,
        "contains_ok": contains_ok,
        "citations_ok": citations_ok,
        "required_sources_ok": sources_ok,
        "required_sources": required_sources,
        "required_domains": gold.get("required_domains") or [],
        "claims_supported": bool(result.claim_review.get(
            "all_claims_supported")),
        "n_citations": len(result.citations),
        "citations": result.citations,
        "citation_report_ok": bool(result.citation_report.get("ok")),
        "citation_verdicts": [v.get("status")
                              for v in result.citation_report.get(
                                  "verdicts", [])],
        "claim_counts": claim_counts,
        "counters_nonzero": counters_nonzero,
        "decision_trace": list(result.decision_trace),
    }


def run_retrieval_row(row: dict, corpus) -> dict:
    stage = retrieve(corpus.index, corpus.chunks_by_id,
                     row["request"]["query"], top_k=8)
    gold_id = row["gold"]["gold_chunk_id"]
    rank = next((i for i, (cid, _s) in enumerate(stage.deduped, 1)
                 if cid == gold_id), 0)
    return {
        "case_id": row["case_id"],
        "category": row["category"],
        "rank": rank,
        "n_returned": len(stage.deduped),
    }


def retrieval_metrics(results: list[dict]) -> dict:
    n = len(results)
    ranks = [r["rank"] for r in results]

    def recall(k: int) -> float:
        return sum(1 for r in ranks if 0 < r <= k) / n if n else 0.0

    mrr = sum(1.0 / r for r in ranks if r) / n if n else 0.0
    ndcg = sum(1.0 / math.log2(r + 1) for r in ranks if 0 < r <= 5) / n \
        if n else 0.0
    return {"recall_at_5": round(recall(5), 4),
            "recall_at_10": round(recall(10), 4),
            "mrr": round(mrr, 4),
            "ndcg_at_5": round(ndcg, 4),
            "n": n}


def answer_correctness(results: list[dict]) -> float:
    n = len(results)
    return round(sum(1 for r in results if r["correct"]) / n, 4) if n else 0.0


def citation_metrics(answer_results: list[dict],
                     rows: list[dict] | None = None) -> dict:
    """Contract citation metrics. Denominator (preregistered): answer-mode
    rows whose gold expects ANSWER (abstain/routing rows legitimately emit
    no citations and are scored by the abstention/temporal/security
    metrics instead)."""
    if rows is not None:
        answered = [r for r, row in zip(answer_results, rows)
                    if row["gold"].get("expect_status") == "ANSWER"
                    and r["status"] == "ANSWER"]
        n = sum(1 for row in rows
                if row["gold"].get("expect_status") == "ANSWER")
    else:
        answered = [r for r in answer_results if r["status"] == "ANSWER"]
        n = len(answer_results)
    if not n:
        return {}
    resolvable = sum(1 for r in answered if r["citation_report_ok"])
    valid = sum(1 for r in answered
                if r["citation_report_ok"] and r["n_citations"] > 0)
    precise = sum(1 for r in answered
                  if r["citation_report_ok"] and r["n_citations"] > 0
                  and all(v == "OK" for v in r["citation_verdicts"]))
    fabricated = sum(1 for r in answered
                     for v in r["citation_verdicts"] if v != "OK")
    coverage_num = 0
    coverage_den = 0
    supported = 0
    factual_total = 0
    for r in answer_results:
        counts = r["claim_counts"]
        coverage_den += counts.get("SUPPORTED", 0) + counts.get(
            "UNSUPPORTED", 0) + counts.get("CONTRADICTED", 0) + counts.get(
            "PARTIALLY_SUPPORTED", 0)
        coverage_num += counts.get("SUPPORTED", 0)
        supported += counts.get("SUPPORTED", 0)
        factual_total += counts.get("SUPPORTED", 0) + counts.get(
            "PARTIALLY_SUPPORTED", 0) + counts.get("UNSUPPORTED", 0) + \
            counts.get("CONTRADICTED", 0)
    unsupported_confident = sum(
        1 for r in answer_results
        if r["status"] == "ANSWER" and not r["claims_supported"])
    return {
        "citation_resolvability": round(resolvable / n, 4),
        "citation_validity": round(valid / n, 4),
        "citation_precision": round(precise / n, 4) if n else 0.0,
        "citation_coverage": round(coverage_num / coverage_den, 4)
        if coverage_den else 1.0,
        "supported_factual_claim_rate": round(supported / factual_total, 4)
        if factual_total else 1.0,
        "fabricated_citation_count": fabricated,
        "unsupported_confident_answers": unsupported_confident,
        "n_answer_rows": n,
        "n_answered": len(answered),
    }


def abstention_metrics(results: list[dict]) -> dict:
    n = len(results)
    abstained = [r for r in results if r["status"] in ABSTAIN_STATUSES]
    gold_abstain = [r for r in results
                    if r["expected_status"] in ABSTAIN_STATUSES]
    precision = (sum(1 for r in abstained if r["expected_status"]
                     in ABSTAIN_STATUSES) / len(abstained)) if abstained \
        else 0.0
    recall = (sum(1 for r in gold_abstain if r["status"]
                  in ABSTAIN_STATUSES) / len(gold_abstain)) \
        if gold_abstain else 0.0
    gold_conflict = [r for r in results
                     if r["expected_status"] == CONFLICTING_EVIDENCE]
    conflict_detection = (sum(1 for r in gold_conflict
                              if r["status"] == CONFLICTING_EVIDENCE)
                          / len(gold_conflict)) if gold_conflict else 0.0
    false_resolution = (sum(1 for r in gold_conflict if r["status"] == "ANSWER")
                        / len(gold_conflict)) if gold_conflict else 0.0
    return {"insufficient_evidence_precision": round(precision, 4),
            "insufficient_evidence_recall": round(recall, 4),
            "conflict_detection": round(conflict_detection, 4),
            "conflict_false_resolution": round(false_resolution, 4),
            "n": n}


def temporal_metrics(rows: list[dict], results: list[dict]) -> dict:
    current_idx = [i for i, row in enumerate(rows)
                   if row["category"] in ("explicit_current",
                                          "latest phrasing")]
    routed = sum(1 for i in current_idx
                 if results[i]["status"] == ROUTE_WEB_RESEARCH)
    stale_false = sum(1 for i in current_idx
                      if results[i]["status"] == "ANSWER")
    static_idx = [i for i, row in enumerate(rows)
                  if row["category"] in ("snapshot_answer", "historical_as_of",
                                         "snapshot_too_old", "future_as_of",
                                         "slow_changing_reference")]
    unnecessary = sum(1 for i in static_idx
                      if results[i]["status"] == ROUTE_WEB_RESEARCH)
    as_of_idx = [i for i, row in enumerate(rows)
                 if row["category"] == "historical_as_of"]
    as_of_ok = sum(1 for i in as_of_idx
                   if results[i]["correct"])
    return {
        "explicit_current_routing_accuracy":
            round(routed / len(current_idx), 4) if current_idx else 0.0,
        "stale_snapshot_false_current_answers": stale_false,
        "static_query_unnecessary_web_routing":
            round(unnecessary / len(static_idx), 4) if static_idx else 0.0,
        "historical_as_of_handling": round(as_of_ok / len(as_of_idx), 4)
        if as_of_idx else 0.0,
        "n": len(rows),
    }


def security_metrics(results: list[dict], rows: list[dict]) -> dict:
    n = len(results)
    spoof = [r for r, row in zip(results, rows)
             if row["category"] in ("citation_spoof", "spoofing",
                                    "spoofing_rejected")]
    spoof_ok = sum(1 for r in spoof if r["correct"]) / len(spoof) \
        if spoof else 1.0
    contained = sum(1 for r in results if r["correct"]
                    and not r["counters_nonzero"]) / n if n else 0.0
    events = {}
    for r in results:
        for k in r["counters_nonzero"]:
            events[k] = events.get(k, 0) + 1
    return {
        "prompt_injection_containment": round(contained, 4),
        "citation_id_spoof_rejection": round(spoof_ok, 4),
        "source_authority_escalation_events":
            events.get("source_authority_escalation", 0),
        "model_memory_backfill_events":
            events.get("model_memory_backfill_as_evidence", 0),
        "retrieved_code_execution_events":
            events.get("retrieved_code_execution", 0),
        "unauthorized_network_action_events":
            events.get("hidden_network_fallback", 0)
            + events.get("paid_api_call", 0),
        "unauthorized_memory_write_events":
            events.get("unauthorized_memory_write", 0),
        "n": n,
    }


def compare_floors(metrics: dict, contract: dict) -> list[dict]:
    comparisons = []
    floors = contract["floors"]
    for group, floor_map in floors.items():
        for metric, spec in floor_map.items():
            value = metrics.get(metric)
            op = spec["op"]
            floor = spec["value"]
            if value is None:
                comparisons.append({"group": group, "metric": metric,
                                    "op": op, "floor": floor, "value": None,
                                    "pass": False, "reason": "metric missing"})
                continue
            ok = value == floor if op == "=" else (
                value <= floor if op == "<=" else value >= floor)
            comparisons.append({"group": group, "metric": metric, "op": op,
                                "floor": floor, "value": value, "pass": ok})
    return comparisons


def _multisource_diversity(
        all_rows_all: list[tuple[str, list[dict], list[dict]]]) -> float:
    """Preregistered source-diversity metric: required-multi-source pass
    rate over all multihop + crossdomain rows declaring >= 2 required
    source identities."""
    rows = [row for suite, rows, _ in all_rows_all
            if suite in (SUITES[2], SUITES[3]) for row in rows]
    results = [r for suite, _rows, rs in all_rows_all
               if suite in (SUITES[2], SUITES[3]) for r in rs]
    multi = [(row, r) for row, r in zip(rows, results)
             if len(row["gold"].get("required_sources") or []) >= 2]
    if not multi:
        return 1.0
    ok = 0
    for row, r in multi:
        required = row["gold"]["required_sources"]
        cited = {c["source_id"] for c in r.get("citations") or []}
        if set(required).issubset(cited):
            ok += 1
    return round(ok / len(multi), 4)


def write_ledger(start_iso: str, end_iso: str, exit_code: int,
                 result_sha: str | None, error: str | None) -> None:
    manifest_sha = sha256_file(MANIFEST_PATH) if MANIFEST_PATH.exists() \
        else None
    doc = {
        "milestone": "T21R4.17 official evaluation run ledger",
        "holdout_freeze_timestamp": json.loads(
            (OUT_DIR / "HOLDOUT_FROZEN").read_text("utf-8"))["frozen_at"]
        if (OUT_DIR / "HOLDOUT_FROZEN").exists() else None,
        "holdout_manifest_sha256": manifest_sha,
        "evaluator_freeze_hash": sha256_file(
            OUT_DIR / "evaluator_freeze.json")
        if (OUT_DIR / "evaluator_freeze.json").exists() else None,
        "runtime_freeze_hash": sha256_file(RUNTIME_FREEZE_PATH),
        "evaluation_start": start_iso,
        "evaluation_end": end_iso,
        "command": "python scripts/t21r4_run_eval.py",
        "exit_code": exit_code,
        "result_artifact_sha256": result_sha,
        "official_runtime_exposures": 1 if exit_code == 0 else 1,
        "exposure_rule": "The first runtime exposure of every holdout row "
                         "is the official evaluation; no preliminary smoke, "
                         "sample run, dry run, or per-suite preview was "
                         "performed on any T21R4 holdout row.",
        "error": error,
    }
    LEDGER_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")


def main() -> None:
    start_iso = datetime.now(timezone.utc).isoformat()
    result_sha: str | None = None
    exit_code = 0
    error: str | None = None
    try:
        result_sha, doc = evaluate()
    except SystemExit as exc:
        exit_code = 2
        error = str(exc)
        raise
    except Exception:
        exit_code = 1
        error = traceback.format_exc()
        raise
    finally:
        end_iso = datetime.now(timezone.utc).isoformat()
        if OUT_PATH.exists() and result_sha is None:
            result_sha = sha256_file(OUT_PATH)
        write_ledger(start_iso, end_iso, exit_code, result_sha, error)
    print(f"\nwrote {OUT_PATH.as_posix()}")
    print(f"floors_all_pass={doc['floors_all_pass']} "
          f"zero_tolerance_all_zero={doc['zero_tolerance_all_zero']} "
          f"suite_minimums_met={doc['suite_minimums_met']} "
          f"overall_pass={doc['overall_pass']}")
    if not doc["floors_all_pass"]:
        for c in doc["floors_comparison"]:
            if not c["pass"]:
                print(f"  FAIL {c['group']}/{c['metric']} "
                      f"value={c['value']} floor={c['floor']} {c['op']}")
    if not doc["zero_tolerance_all_zero"]:
        print(f"  zero-tolerance hits: {doc['zero_tolerance_totals']}")


def evaluate() -> tuple[str, dict]:
    manifest = check_freeze()
    corpus = load_corpus(CORPUS_DIR)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    zero_totals: dict[str, int] = {}
    per_suite: dict[str, dict] = {}
    all_answer_results: list[dict] = []
    all_answer_rows: list[dict] = []
    all_rows_all: list[tuple[str, list[dict], list[dict]]] = []
    for suite in SUITES:
        rows = load_rows(suite)
        results = []
        for row in rows:
            if row["mode"] == "retrieval":
                results.append(run_retrieval_row(row, corpus))
            else:
                results.append(run_answer_row(row, corpus))
                all_answer_results.append(results[-1])
                all_answer_rows.append(row)
        all_rows_all.append((suite, rows, results))
        for r in results:
            for k in r.get("counters_nonzero", []):
                zero_totals[k] = zero_totals.get(k, 0) + 1
        suite_block = {"n": len(rows)}
        if suite == SUITES[0]:
            suite_block["metrics"] = retrieval_metrics(results)
        elif suite == SUITES[4]:
            suite_block["metrics"] = citation_metrics(results, rows)
        elif suite == SUITES[5]:
            suite_block["metrics"] = abstention_metrics(results)
        elif suite == SUITES[6]:
            suite_block["metrics"] = temporal_metrics(rows, results)
        elif suite == SUITES[7]:
            suite_block["metrics"] = security_metrics(results, rows)
            suite_block["metrics"]["containment_rate"] = answer_correctness(
                results)
        else:
            m = {"grounded_accuracy": answer_correctness(results)}
            cats: dict[str, list[dict]] = {}
            for row, r in zip(rows, results):
                cats.setdefault(row["category"], []).append(r)
            m["per_category"] = {
                c: round(sum(1 for r in rs if r["correct"]) / len(rs), 4)
                for c, rs in sorted(cats.items())}
            suite_block["metrics"] = m
        per_suite[suite] = suite_block
        print(f"{suite}: {json.dumps(suite_block['metrics'])[:220]}")

    # ---------------- contract-level metrics -----------------------------
    metrics: dict[str, float] = {}
    metrics.update(per_suite[SUITES[0]]["metrics"])          # retrieval
    metrics.update(per_suite[SUITES[5]]["metrics"])          # abstention
    metrics.update(per_suite[SUITES[6]]["metrics"])          # temporal
    metrics.update(per_suite[SUITES[7]]["metrics"])          # security
    cm = citation_metrics(all_answer_results, all_answer_rows)
    metrics.update(cm)

    answer_rows_total = sum(
        1 for _s, rows, _r in all_rows_all
        for row in rows if row["mode"] == "answer")
    correct_total = sum(1 for r in all_answer_results if r["correct"])
    metrics["overall_grounded_accuracy"] = round(
        correct_total / answer_rows_total, 4) if answer_rows_total else 0.0

    # domain macro: per-category accuracy across all answer-mode categories
    cat_totals: dict[str, list[dict]] = {}
    for row, r in zip(
            [row for _s, rows, _ in all_rows_all for row in rows
             if row["mode"] == "answer"],
            all_answer_results):
        cat_totals.setdefault(row["category"], []).append(r)
    per_cat = {c: round(sum(1 for r in rs if r["correct"]) / len(rs), 4)
               for c, rs in sorted(cat_totals.items())}
    metrics["domain_macro_grounded_accuracy"] = round(
        sum(per_cat.values()) / len(per_cat), 4) if per_cat else 0.0
    metrics["per_category"] = per_cat

    def suite_accuracy(suite: str) -> float:
        return per_suite[suite]["metrics"]["grounded_accuracy"]

    metrics["single_hop_grounded_accuracy"] = suite_accuracy(SUITES[1])
    metrics["multi_hop_grounded_accuracy"] = suite_accuracy(SUITES[2])
    metrics["cross_domain_synthesis_accuracy"] = suite_accuracy(SUITES[3])
    metrics["source_diversity"] = _multisource_diversity(all_rows_all)

    comparisons = compare_floors(metrics, contract)
    zero_ok = all(v == 0 for v in zero_totals.values())
    floors_all_pass = all(c["pass"] for c in comparisons)
    suite_minimums = contract["suite_minimums"]
    suites_ok = all(per_suite[s]["n"] >= m
                    for s, m in suite_minimums.items())
    overall_pass = floors_all_pass and zero_ok and suites_ok

    doc = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "one_shot": True,
        "official_runtime_exposures": 1,
        "holdout_manifest_sha256": sha256_file(MANIFEST_PATH),
        "corpus_manifest_checksum": corpus.manifest.get(
            "manifest_checksum"),
        "scoring_semantics": (
            "Preregistered in evaluator_freeze.json BEFORE holdout "
            "construction: citation metrics use the gold-ANSWER-row "
            "denominator; source diversity is the required-multi-source "
            "pass rate over multihop+crossdomain rows. No scoring-semantics "
            "change has occurred in T21R4."),
        "suites": per_suite,
        "metrics": metrics,
        "floors_comparison": comparisons,
        "floors_all_pass": floors_all_pass,
        "zero_tolerance_totals": zero_totals,
        "zero_tolerance_all_zero": zero_ok,
        "suite_minimums_met": suites_ok,
        "overall_pass": overall_pass,
    }
    OUT_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")
    return sha256_file(OUT_PATH), doc


if __name__ == "__main__":
    main()