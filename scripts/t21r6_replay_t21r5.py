"""T21R6 Part C2 — T21R5 full replay, DEV-ONLY, NON-PROMOTIONAL.

Replays ALL 3531 rows of the EXPOSED (non-promotional) T21R5 blind
holdout through the REPAIRED T21R6 runtime + the REPAIRED evaluator
scoring code, proving:

  1. every row executes WITHOUT an evaluator exception (the T21R5
     official exposure crashed at scripts/t21r5_run_eval.py:186 on
     KnowledgeSourceRecord.get("domain"); the repaired required_domains
     path uses topic_tags over CITED sources),
  2. the 32 old multihop failures are eliminated (INTERROGATIVE_
     NORMALIZATION_GAP repair) with no new failures among the 288
     multihop rows,
  3. the T21R5 preregistered floors (read-only from
     evaluations/t21r5/validation_contract.json) are still met.

NEVER touches evaluations/t21r5/** or rag/gk_holdout_t21r5/** (read-only
inputs). The replay result is labeled T21R5_REPLAY_NON_PROMOTIONAL with
promotion_value ZERO: it is development evidence only and can never
promote anything.

Usage: python scripts/t21r6_replay_t21r5.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r6_run_eval as ev  # noqa: E402
from sciencemath.knowledge.corpus import load_corpus  # noqa: E402

R5_SUITES = [
    "mango-t21r5-retrieval-holdout-v1",
    "mango-t21r5-singlehop-holdout-v1",
    "mango-t21r5-multihop-holdout-v1",
    "mango-t21r5-crossdomain-holdout-v1",
    "mango-t21r5-citation-claim-holdout-v1",
    "mango-t21r5-conflict-abstention-holdout-v1",
    "mango-t21r5-temporal-holdout-v1",
    "mango-t21r5-adversarial-holdout-v1",
]
R5_SUITES_DIR = ROOT / "evaluations" / "t21r5" / "suites"
R5_CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r5"
R5_CONTRACT = ROOT / "evaluations" / "t21r5" / "validation_contract.json"
R5_RAW = ROOT / "evaluations" / "t21r5" / "raw_results.jsonl"
OUT_PATH = ROOT / "evaluations" / "t21r6" / "t21r5_replay_non_promotional.json"
RAW_OUT = ROOT / "evaluations" / "t21r6" / "t21r5_replay_raw.jsonl"


def load_rows(suite: str) -> list[dict]:
    path = R5_SUITES_DIR / suite / "holdout.jsonl"
    return [json.loads(line) for line
            in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    started = time.time()
    corpus = load_corpus(R5_CORPUS_DIR)
    ev._validate_corpus_domain_tags(corpus)
    contract = json.loads(R5_CONTRACT.read_text(encoding="utf-8"))

    # the 32 exposed failures (authoritative evidence, read-only)
    r5_raw = [json.loads(line)
              for line in R5_RAW.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    old_fails = {r["case_id"]: r for r in r5_raw
                 if r.get("suite") == R5_SUITES[2]
                 and r.get("expected_status") == "ANSWER"
                 and r.get("status") != "ANSWER"}
    assert len(old_fails) == 32, len(old_fails)

    zero_totals: dict[str, int] = {}
    per_suite: dict[str, dict] = {}
    all_answer_results: list[dict] = []
    all_answer_rows: list[dict] = []
    all_rows_all: list[tuple[str, list[dict], list[dict]]] = []
    exceptions: list[dict] = []
    n_executed = 0
    raw_fh = RAW_OUT.open("w", encoding="utf-8", newline="\n")
    try:
        for suite in R5_SUITES:
            rows = load_rows(suite)
            results: list[dict] = []
            for row in rows:
                try:
                    if row["mode"] == "retrieval":
                        raw = ev.run_retrieval_row(row, corpus)
                    else:
                        raw, _ = ev.run_answer_row(row, corpus)
                        all_answer_results.append(raw)
                        all_answer_rows.append(row)
                except Exception:
                    # an evaluator exception on ANY row is the exact defect
                    # class that killed the T21R5 exposure; record and fail
                    exceptions.append({
                        "suite": suite, "case_id": row.get("case_id"),
                        "traceback": traceback.format_exc()})
                    raise
                raw["suite"] = suite
                results.append(raw)
                n_executed += 1
                raw_fh.write(json.dumps(raw, ensure_ascii=False) + "\n")
                raw_fh.flush()
            all_rows_all.append((suite, rows, results))
            for r in results:
                for k in r.get("counters_nonzero", []):
                    zero_totals[k] = zero_totals.get(k, 0) + 1
            suite_block: dict = {"n": len(rows)}
            if suite == R5_SUITES[0]:
                suite_block["metrics"] = ev.retrieval_metrics(results)
            elif suite == R5_SUITES[4]:
                suite_block["metrics"] = ev.citation_metrics(results, rows)
            elif suite == R5_SUITES[5]:
                suite_block["metrics"] = ev.abstention_metrics(results)
            elif suite == R5_SUITES[6]:
                suite_block["metrics"] = ev.temporal_metrics(rows, results)
            elif suite == R5_SUITES[7]:
                suite_block["metrics"] = ev.security_metrics(results, rows)
            else:
                m: dict = {"grounded_accuracy":
                           ev.answer_correctness(results)}
                cats: dict[str, list[dict]] = {}
                for rrow, r in zip(rows, results):
                    cats.setdefault(rrow["category"], []).append(r)
                m["per_category"] = {
                    c: round(sum(1 for r in rs if r["correct"]) / len(rs), 4)
                    for c, rs in sorted(cats.items())}
                suite_block["metrics"] = m
            per_suite[suite] = suite_block
            print(f"{suite}: {json.dumps(suite_block['metrics'])[:200]}")
    finally:
        raw_fh.close()

    metrics = ev.aggregate_metrics(per_suite, all_rows_all,
                                   all_answer_results, all_answer_rows,
                                   R5_SUITES)
    comparisons = ev.compare_floors(metrics, contract)
    zero_ok = all(v == 0 for v in zero_totals.values())
    floors_all_pass = all(c["pass"] for c in comparisons)

    # ---- the old 32: replayed row-by-row -------------------------------
    mh_pair = {}
    for rrow, rraw in zip(all_rows_all[2][1], all_rows_all[2][2]):
        mh_pair[rrow["case_id"]] = rraw
    old32_now = []
    for cid, old in sorted(old_fails.items()):
        now = mh_pair[cid]
        old32_now.append({
            "case_id": cid,
            "query": old["query"],
            "old_status": old["status"],
            "old_trace": old["decision_trace"],
            "replay_status": now["status"],
            "replay_correct": now["correct"],
            "eliminated": now["correct"] is True,
        })
    eliminated = sum(1 for r in old32_now if r["eliminated"])
    mh_total = len(all_rows_all[2][1])
    mh_correct = sum(1 for r in all_rows_all[2][2] if r["correct"])

    doc = {
        "artifact": "T21R6 Part C2 — T21R5 full replay (dev-only)",
        "label": "T21R5_REPLAY_NON_PROMOTIONAL",
        "promotion_value": "ZERO",
        "note": ("Development evidence only: the T21R5 blind holdout was "
                 "already exposed once (non-promotional, crashed at "
                 "scripts/t21r5_run_eval.py:186) and can never promote. "
                 "This replay proves the T21R6 repairs on the exposed "
                 "rows; the T21R6 promotion decision comes ONLY from the "
                 "fresh T21R6 blind holdout's single official exposure."),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.time() - started, 1),
        "inputs": {
            "corpus_dir": "rag/gk_holdout_t21r5 (read-only)",
            "corpus_manifest_checksum": corpus.manifest.get(
                "manifest_checksum"),
            "suites_dir": "evaluations/t21r5/suites (read-only)",
            "contract": "evaluations/t21r5/validation_contract.json "
                        "(read-only)",
            "r5_raw_results_sha256": hashlib.sha256(
                R5_RAW.read_bytes()).hexdigest(),
            "pipeline_sha256": hashlib.sha256(
                (ROOT / "src/sciencemath/knowledge/pipeline.py")
                .read_bytes()).hexdigest(),
            "evaluator_sha256": hashlib.sha256(
                (ROOT / "scripts/t21r6_run_eval.py").read_bytes())
            .hexdigest(),
        },
        "rows_total": sum(len(rows) for _s, rows, _r in all_rows_all),
        "rows_executed": n_executed,
        "evaluator_exceptions": len(exceptions),
        "suites": per_suite,
        "metrics": metrics,
        "floors_comparison": comparisons,
        "floors_all_pass": floors_all_pass,
        "zero_tolerance_totals": zero_totals,
        "zero_tolerance_all_zero": zero_ok,
        "old_32_failures": {
            "total": len(old_fails),
            "eliminated": eliminated,
            "rows": old32_now,
        },
        "multihop_replay": {
            "total_rows": mh_total,
            "correct": mh_correct,
            "grounded_accuracy": ev.answer_correctness(all_rows_all[2][2]),
        },
        "replay_pass": bool(
            n_executed == sum(len(rows) for _s, rows, _r in all_rows_all)
            and not exceptions
            and eliminated == len(old_fails)
            and floors_all_pass
            and zero_ok),
    }
    OUT_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"\nwrote {OUT_PATH.as_posix()}")
    print(f"rows={n_executed} exceptions={len(exceptions)} "
          f"old32_eliminated={eliminated}/{len(old_fails)} "
          f"floors_all_pass={floors_all_pass} "
          f"zero_all_zero={zero_ok} replay_pass={doc['replay_pass']}")
    return 0 if doc["replay_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())