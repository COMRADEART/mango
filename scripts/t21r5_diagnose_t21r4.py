"""T21R5 Phase A — diagnostic replay of the EXPOSED T21R4 holdout.

T21R4_REPLAY_NON_PROMOTIONAL. This replay has ZERO promotion value: it is
DEVELOPMENT-ONLY instrumentation over the already-exposed T21R4 blind
holdout (one official run completed, decision recorded). Nothing in
evaluations/t21r4/** or rag/gk_holdout_t21r4/** is modified.

For EVERY row of all 8 T21R4 suites this script records the full runtime
decision material that the frozen T21R4 evaluator did not persist:

  retrieval candidate ranking (BM25) -> rerank -> dedup,
  per-item source IDs and scores, final evidence window,
  selected evidence, emitted citations, citation verdicts,
  claim verdicts, conflicts (detected + query-relevant), resolution,
  coverage, decision trace, zero-tolerance counters, and the gold
  comparison verdicts the evaluator used.

Outputs (all under evaluations/t21r5/):
  t21r4_diagnostic_replay.jsonl   one record per row
  t21r4_failure_taxonomy.json     aggregate failure taxonomy

Usage: python scripts/t21r5_diagnose_t21r4.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.conflicts import resolve_conflicts  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402
from sciencemath.knowledge.retrieval import retrieve  # noqa: E402
from sciencemath.knowledge.routing import (  # noqa: E402
    CONFLICTING_EVIDENCE,
    INSUFFICIENT_EVIDENCE,
)

OUT_DIR = ROOT / "evaluations" / "t21r5"
SUITES_DIR = ROOT / "evaluations" / "t21r4" / "suites"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r4"

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


def load_rows(suite: str) -> list[dict]:
    path = SUITES_DIR / suite / "holdout.jsonl"
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _stage_detail(stage) -> dict:
    """Ranking at every stage with chunk->source projection."""
    def proj(pairs):
        return [{"chunk_id": cid, "score": round(score, 6)}
                for cid, score in pairs]
    return {"ranked": proj(stage.ranked),
            "reranked": proj(stage.reranked),
            "deduped": proj(stage.deduped)}


def diagnose_row(row: dict, corpus) -> dict:
    query = row["request"]["query"]
    gold = row["gold"]
    result = answer_knowledge(query, corpus)

    # retrieval detail: rerun the read-only stage retrieval for the record
    stage = retrieve(corpus.index, corpus.chunks_by_id, query, top_k=8)
    gold_chunk_id = gold.get("gold_chunk_id")
    gold_rank = next((i for i, (cid, _s) in enumerate(stage.deduped, 1)
                      if cid == gold_chunk_id), 0)
    dedup_sources = [corpus.chunks_by_id[cid].source_id
                     for cid, _ in stage.deduped
                     if cid in corpus.chunks_by_id]

    # conflicts: the pack carries the query-relevant conflicts the pipeline
    # scoped (T21R4 semantics); resolution/winner are recomputed with the
    # same preregistered resolver for the diagnostic record.
    pack_conflicts = (result.evidence_pack or {}).get("conflicts") or []
    resolution, winner = resolve_conflicts(pack_conflicts) \
        if pack_conflicts else ("NO_CONFLICT", None)
    rec = {
        "case_id": row["case_id"],
        "suite": suite_of(row),
        "category": row["category"],
        "mode": row["mode"],
        "query": query,
        "gold": {
            "expect_status": gold.get("expect_status"),
            "expect_answer_contains": gold.get("expect_answer_contains"),
            "required_sources": gold.get("required_sources") or [],
            "gold_chunk_id": gold_chunk_id,
            "gold_chunk_rank_in_dedup": gold_rank,
        },
        "retrieval": {
            "stages": _stage_detail(stage),
            "deduped_sources": dedup_sources,
            "n_deduped": len(stage.deduped),
        },
        "status": result.status,
        "answer": result.answer,
        "citations": result.citations,
        "citation_report": result.citation_report,
        "claim_review": {
            "counts": result.claim_review.get("counts"),
            "all_claims_supported":
                result.claim_review.get("all_claims_supported"),
            "unsupported": result.claim_review.get(
                "unsupported_confident_claims"),
        },
        "evidence_pack": {
            "retrieval_status": (result.evidence_pack or {}).get(
                "retrieval_status"),
            "coverage": (result.evidence_pack or {}).get(
                "coverage_status"),
            "n_items": len((result.evidence_pack or {}).get(
                "evidence_items") or []),
            "items": [{
                "chunk_id": it.get("chunk_id"),
                "source_id": it.get("source_id"),
                "rank": it.get("rank"),
                "score": it.get("score"),
                "authority_class": it.get("authority_class"),
                "freshness_class": it.get("freshness_class"),
                "fact_entity": (it.get("metadata") or {}).get("fact_entity"),
                "fact_attribute": (it.get("metadata") or {}).get(
                    "fact_attribute"),
                "fact_value": (it.get("metadata") or {}).get("fact_value"),
                "text_span": it.get("text_span"),
            } for it in (result.evidence_pack or {}).get(
                "evidence_items") or []],
        },
        "conflicts": {
            "pack_conflicts": (result.evidence_pack or {}).get("conflicts"),
            "resolution": resolution,
            "winner_chunk_id": (winner or {}).get("chunk_id")
            if winner else None,
        },
        "freshness": result.freshness,
        "query_injection": result.query_injection,
        "source_injection": result.source_injection,
        "subqueries": result.subqueries,
        "decision_trace": result.decision_trace,
        "zero_tolerance_nonzero": [k for k, v in
                                   result.zero_tolerance.items() if v],
    }

    # ---- gold comparison (same semantics as the frozen evaluator) --------
    # Retrieval-mode rows are scored by gold-chunk rank only; answer-mode
    # rows get the full evaluator verdict battery.
    ok = True
    reasons: list[str] = []
    if row["mode"] == "retrieval":
        ok = gold_rank > 0
        if not ok:
            reasons.append("gold_chunk_not_retrieved")
    else:
        if result.status != gold.get("expect_status"):
            ok = False
            reasons.append("status_mismatch")
        if gold.get("expect_status") == "ANSWER":
            lowered = result.answer.lower()
            missing = [s for s in gold.get("expect_answer_contains", [])
                       if s.lower() not in lowered]
            if missing:
                ok = False
                reasons.append(f"missing_substrings:{missing}")
            cited = {c["source_id"] for c in result.citations}
            required = gold.get("required_sources") or []
            if required and not set(required).issubset(cited):
                ok = False
                reasons.append("required_sources_missing:"
                               f"{sorted(set(required) - cited)}")
            if gold.get("require_citations") and (not result.citations
                                                  or not result.citation_report
                                                  .get("ok")):
                ok = False
                reasons.append("citations_defective")
            if not result.claim_review.get("all_claims_supported"):
                ok = False
                reasons.append("claims_unsupported")
        if result.zero_tolerance and any(result.zero_tolerance.values()):
            ok = False
            reasons.append("zero_tolerance:"
                           f"{[k for k, v in result.zero_tolerance.items() if v]}")
    rec["correct"] = ok
    rec["failure_reasons"] = reasons
    return rec


_SUITE_BY_NAME: dict[str, str] = {}


def suite_of(row: dict) -> str:
    return _SUITE_BY_NAME.get(row["case_id"], "")


def short(suite: str) -> str:
    return suite.replace("mango-t21r4-", "").replace("-holdout-v1", "")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    corpus = load_corpus(CORPUS_DIR)
    rows_out = []
    for suite in SUITES:
        rows = load_rows(suite)
        for row in rows:
            _SUITE_BY_NAME[row["case_id"]] = short(suite)
            rows_out.append(diagnose_row(row, corpus))
        print(f"{short(suite)}: {len(rows)} rows diagnosed")

    replay_path = OUT_DIR / "t21r4_diagnostic_replay.jsonl"
    with open(replay_path, "w", encoding="utf-8", newline="\n") as fh:
        for rec in rows_out:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    taxonomy = build_taxonomy(rows_out)
    tax_path = OUT_DIR / "t21r4_failure_taxonomy.json"
    doc = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "label": "T21R4_REPLAY_NON_PROMOTIONAL",
        "promotion_value": "ZERO",
        "n_rows": len(rows_out),
        "n_correct": sum(1 for r in rows_out if r["correct"]),
        "taxonomy": taxonomy,
    }
    tax_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"wrote {replay_path.as_posix()} and {tax_path.as_posix()}")


def build_taxonomy(rows: list[dict]) -> dict:
    failed = [r for r in rows if not r["correct"]]
    by_reason: Counter = Counter()
    by_suite: dict[str, Counter] = {}
    for r in failed:
        for reason in r["failure_reasons"]:
            key = reason.split(":")[0]
            by_reason[key] += 1
            s = r["suite"]
            by_suite.setdefault(s, Counter())[key] += 1
    return {
        "n_failed": len(failed),
        "by_reason": dict(by_reason),
        "by_suite": {s: dict(c) for s, c in sorted(by_suite.items())},
        "failed_case_ids": [r["case_id"] for r in failed],
    }


if __name__ == "__main__":
    main()