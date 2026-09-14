"""T16.44 — research failure taxonomy on the FINAL split."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from t16_run_eval import _rows, score_web_row

PRED = ROOT / "evaluations/t16/runs/t16-final/predictions.jsonl"
GOLD = ROOT / "evaluations/t16/suites/mango-web-eval-v1/final.jsonl"
OUT = ROOT / "evaluations/t16/failure_analysis.json"

TAXONOMY = (
    "SEARCH_MISS", "SOURCE_SELECTION_ERROR", "FETCH_FAILURE",
    "STALE_SOURCE_USED", "PRIMARY_SOURCE_MISSED", "EVIDENCE_EXTRACTION_ERROR",
    "ENTAILMENT_ERROR", "CITATION_MISSING", "CITATION_WRONG",
    "CLAIM_UNSUPPORTED", "CONTRADICTION_MISSED", "TEMPORAL_ERROR",
    "INJECTION_FAILURE", "ABSTENTION_FAILURE", "PROVIDER_FAILURE", "OTHER",
)


def classify(gold: dict, pred: dict, flags: dict) -> str:
    fab = pred.get("fabrication") or {}
    if (fab.get("fabricated_sources") or fab.get("fabricated_citations")
            or fab.get("fabricated_quotes")):
        return "CITATION_WRONG"
    if gold.get("expect_abstention") and not flags.get("abstention"):
        return "ABSTENTION_FAILURE"
    if gold.get("injection") and not flags.get("inj_resist", 1):
        return "INJECTION_FAILURE"
    if gold.get("expect_contradiction") and not flags.get("contra"):
        return "CONTRADICTION_MISSED"
    if gold.get("freshness") and flags.get("fresh_n") and not flags.get("fresh"):
        return "TEMPORAL_ERROR"
    stale = gold.get("stale_must_not_prove") or []
    if stale and not flags.get("stale_rej", 1):
        return "STALE_SOURCE_USED"
    if gold.get("preferred_primary_source_ids") and flags.get("primary_pref_n") \
            and not flags.get("primary_pref"):
        return "PRIMARY_SOURCE_MISSED"
    if gold.get("acceptable_source_ids") and flags.get("source_sel_n") \
            and not flags.get("source_sel"):
        return "SOURCE_SELECTION_ERROR"
    if gold.get("expected_search_targets") and flags.get("search_target_n") \
            and not flags.get("search_target"):
        return "SEARCH_MISS"
    if gold.get("expect_citation") and not gold.get("expect_abstention") \
            and not flags.get("cite_complete"):
        return "CITATION_MISSING"
    if pred.get("status") == "INSUFFICIENT_EVIDENCE" and not gold.get(
            "expect_abstention"):
        return "EVIDENCE_EXTRACTION_ERROR"
    if not flags.get("final_answer"):
        return "CLAIM_UNSUPPORTED"
    return "OTHER"


def main() -> int:
    golds = {g["task_id"]: g for g in _rows(GOLD)}
    preds = _rows(PRED) if PRED.exists() else []
    counts = Counter({k: 0 for k in TAXONOMY})
    misses = []
    for p in preds:
        g = golds.get(p.get("task_id"))
        if not g:
            continue
        flags = score_web_row(g, p)
        if flags.get("final_answer") and (
                not g.get("expect_contradiction") or flags.get("contra", 1)):
            continue
        kind = classify(g, p, flags)
        counts[kind] += 1
        misses.append({
            "task_id": g["task_id"], "category": g["category"],
            "taxonomy": kind, "status": p.get("status"),
            "answer_prefix": (p.get("answer") or "")[:160],
        })
    n_fail = sum(counts.values())
    doc = {
        "milestone": "T16.44 failure taxonomy",
        "n_final": len(preds),
        "n_flagged": n_fail,
        "counts": dict(counts),
        "examples": misses[:40],
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n_flagged": n_fail, "counts": dict(counts)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
