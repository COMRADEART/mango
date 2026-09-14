"""T21R pre-freeze gold-consistency QA (T21R.6 gate).

Runs the FROZEN runtime over every gold row of every holdout suite and
reports every mismatch between gold and the frozen pipeline. This is a
corpus-construction QA pass BEFORE HOLDOUT_FROZEN — its only allowed
outcome is fixing corpus/gold construction errors (wrong value lookups,
phrasings outside the coverage budget, misclassified temporal framing).
The runtime itself must never change to satisfy it.

The recorded evaluation (T21R.9) is run once, after the freeze.

Usage: python scripts/t21r_gold_qa.py [--suite NAME]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402
from sciencemath.knowledge.retrieval import retrieve  # noqa: E402

SUITES_DIR = ROOT / "evaluations" / "t21r" / "suites"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r"

ABSTAIN = {"INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"}


def check_row(row: dict, corpus) -> dict:
    """Return {ok, reason} for one gold row."""
    query = row["request"]["query"]
    gold = row["gold"]
    counters_nonzero = None

    if row["mode"] == "retrieval":
        stage = retrieve(corpus.index, corpus.chunks_by_id, query, top_k=8)
        gold_id = gold["gold_chunk_id"]
        rank = next((i for i, (cid, _s) in enumerate(stage.deduped, 1)
                     if cid == gold_id), 0)
        if not rank:
            return {"ok": False, "reason": f"gold chunk not in retrieval "
                                           f"(rank 0)"}
        return {"ok": True, "rank": rank}

    result = answer_knowledge(query, corpus)
    counters_nonzero = [k for k, v in result.zero_tolerance.items() if v]
    expected = gold["expect_status"]
    if result.status != expected:
        return {"ok": False,
                "reason": f"status {result.status} != {expected}"
                          f" (trace: {' > '.join(result.decision_trace[-3:])})"}
    if expected == "ANSWER":
        lowered = result.answer.lower()
        missing = [s for s in gold.get("expect_answer_contains", [])
                   if s.lower() not in lowered]
        if missing:
            return {"ok": False, "reason": f"answer missing {missing}; "
                                            f"answer={result.answer!r}"}
        if gold.get("require_citations"):
            if not result.citations or not result.citation_report.get("ok"):
                return {"ok": False,
                        "reason": "citations required but report not ok"}
        rs = gold.get("required_sources")
        if rs:
            cited_sources = {c["source_id"] for c in result.citations}
            if not set(rs).issubset(cited_sources):
                return {"ok": False,
                        "reason": f"required sources {rs} not all cited "
                                  f"(cited: {sorted(cited_sources)})"}
    if counters_nonzero:
        return {"ok": False, "reason": f"counters nonzero: {counters_nonzero}"}
    return {"ok": True}


def main() -> int:
    only = None
    if "--suite" in sys.argv:
        only = sys.argv[sys.argv.index("--suite") + 1]
    corpus = load_corpus(CORPUS_DIR)
    failures: list[dict] = []
    n_ok = 0
    n_total = 0
    for suite_dir in sorted(SUITES_DIR.iterdir()):
        if only and suite_dir.name != only:
            continue
        path = suite_dir / "holdout.jsonl"
        if not path.exists():
            continue
        suite_fail = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            n_total += 1
            verdict = check_row(row, corpus)
            if verdict["ok"]:
                n_ok += 1
            else:
                suite_fail += 1
                failures.append({"suite": suite_dir.name,
                                 "case_id": row["case_id"],
                                 "category": row["category"],
                                 "query": row["request"]["query"],
                                 "reason": verdict["reason"]})
        print(f"{suite_dir.name}: "
              f"{sum(1 for f in failures if f['suite'] == suite_dir.name)}"
              f" failures")
    summary = {"total": n_total, "ok": n_ok, "failures": len(failures)}
    out = ROOT / "evaluations" / "t21r" / "gold_qa_report.json"
    out.write_text(
        json.dumps({"summary": summary, "failures": failures},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(summary))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())