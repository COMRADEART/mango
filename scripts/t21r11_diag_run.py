"""T21R11 open diagnostic runner — executes the independent diagnostic
suites against the runtime and records stage-probe + gold evidence.

NOT a blind qualification and NOT an official evaluation: the diagnostic
world is open, inspectable material built entirely for this remediation
phase.  Every row executes the full frozen runtime (answer_knowledge) and,
for retrieval rows, the BM25/rerank/dedup stage directly.

Per-row probes (mechanism attribution, aggregate only):
  answer rows   status/answer/citations + decision trace, evidence window,
                surfaced conflicts, extractive lineage, citation grammar,
                zero-tolerance counters, payload-leakage scan
  retrieval rows bm25 rank / rerank rank / deduped rank of the gold chunk
                ( Recall@5/10, MRR, nDCG@5, source diversity )

Metrics JSON mirrors the §19 engineering-readiness targets per track.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from sciencemath.knowledge.corpus import load_corpus  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402
from sciencemath.knowledge.retrieval import retrieve  # noqa: E402

import t21r11_diag_world as world  # noqa: E402
from t21r6_run_eval import (  # noqa: E402
    required_domains_ok,
    source_domains,
    validate_domain_labels,
)

OUT_DIR = world.OUT_DIR
RESULTS_DIR = OUT_DIR / "results"
SUITES = {"dev": OUT_DIR / "dev_suites.jsonl",
          "validation": OUT_DIR / "validation_suites.jsonl"}
FREEZE_PATH = OUT_DIR / "validation_freeze.json"

ABSTAIN_STATUSES = ("INSUFFICIENT_EVIDENCE", "ROUTE_WEB_RESEARCH",
                    "CONFLICTING_EVIDENCE")
_CITATION_ID_RE = re.compile(r"\[[A-Z]\d+-[0-9a-f]{12}\]")


def _sha256_file(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_validation_freeze(split: str) -> None:
    if split != "validation":
        return
    if not FREEZE_PATH.exists():
        raise SystemExit(
            "T21R11 VALIDATION_FREEZE_MISSING: the validation split must be "
            "frozen (validation_freeze.json) before any validation run")
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    want = _sha256_file(SUITES["validation"])
    if freeze.get("validation_sha256") != want:
        raise SystemExit(
            "T21R11 VALIDATION_FREEZE_MISMATCH: validation_suites.jsonl "
            "does not match the recorded freeze; refusing to run")


def _resolve_sources(required: list[str], key_to_id: dict) -> list[str]:
    return sorted({key_to_id[key] for key in required if key in key_to_id})


def _sentence_unit(sentence: str) -> str:
    return " ".join(sentence.casefold().split())


def _lineage_check(answer: str, citations: list[dict], corpus,
                   flagged_payloads: dict[str, str]) -> bool | None:
    """Extractive lineage: every answer sentence (citation markers removed)
    must appear in the text of a cited chunk."""
    if not citations:
        return None
    cited_text = ""
    for citation in citations:
        chunk = corpus.chunk(citation.get("chunk_id", ""))
        if chunk is None:
            continue
        text = chunk.text
        payload = flagged_payloads.get(citation.get("chunk_id", ""))
        if payload:
            # quarantined directive text is not part of the retained payload
            text = text.replace(payload, " ")
        cited_text += " " + _sentence_unit(text)
    body = _CITATION_ID_RE.sub(" ", answer)
    body = _sentence_unit(body)
    sentences = [s.strip() for s in body.split(".") if s.strip()]
    return all(s and s in cited_text for s in sentences)


def _payload_leak(answer: str, payloads: list[str]) -> list[str]:
    lowered = answer.casefold()
    return [key for key in payloads
            if key.casefold() in lowered]


def run_answer_probe(row: dict, corpus, world_index: dict,
                     flagged_payloads: dict[str, str],
                     payload_list: list[str]) -> dict:
    gold = row["gold"]
    result = answer_knowledge(row["query"], corpus)
    counters = result.zero_tolerance
    counters_nonzero = [k for k, v in counters.items() if v]

    status_match = result.status == gold["expect_status"]
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
    required_domains = gold.get("required_domains") or []
    domains_ok = True
    cited_domains: set[str] = set()
    if gold["expect_status"] == "ANSWER" and required_domains:
        validate_domain_labels(required_domains)
        cited_sources = [corpus.source(c["source_id"])
                         for c in result.citations]
        cited_sources = [s for s in cited_sources if s is not None]
        for s in cited_sources:
            cited_domains |= source_domains(s)
        domains_ok = required_domains_ok(required_domains, cited_sources)
    claims_ok = gold["expect_status"] != "ANSWER" or bool(
        result.claim_review.get("all_claims_supported"))

    correct = (status_match and contains_ok and citations_ok
               and sources_ok and domains_ok and claims_ok
               and not counters_nonzero)

    pack = result.evidence_pack or {}
    window_ids = [it["chunk_id"] for it in pack.get("evidence_items") or []]
    probes = row.get("probes") or {}
    probe_records: dict = {"alt_chunk_ranks": {}}
    dedup_ids = window_ids  # window == selected evidence, rank = position
    for probe_key in ("alt_chunk_ids",):
        for cid in probes.get(probe_key) or []:
            rank = next((i for i, wid in enumerate(window_ids, 1)
                         if wid == cid), 0)
            probe_records["alt_chunk_ranks"][cid] = rank
    gold_rank_in_window = 0
    if gold.get("gold_chunk_id"):
        gold_rank_in_window = next(
            (i for i, wid in enumerate(window_ids, 1)
             if wid == gold["gold_chunk_id"]), 0)

    conflicts_surfaced = pack.get("conflicts") or []
    conflicts_compact = [
        {"claim_key": c.get("claim_key"),
         "winner": c.get("winner"),
         "resolution": c.get("resolution")}
        for c in conflicts_surfaced]

    citations_compact = [
        {"citation_id": c.get("citation_id"), "source_id": c.get("source_id"),
         "chunk_id": c.get("chunk_id")}
        for c in result.citations]
    lineage_ok = _lineage_check(result.answer, result.citations, corpus,
                                flagged_payloads)
    leaks = _payload_leak(result.answer, payload_list)
    trace_conflicts = [entry for entry in result.decision_trace
                       if "conflict" in entry.lower()]

    return {
        "case_id": row["case_id"],
        "split": row["split"], "track": row["track"],
        "family": row["family"], "mode": row["mode"],
        "stress": row.get("stress", False),
        "query": row["query"],
        "status": result.status,
        "expected_status": gold["expect_status"],
        "status_match": status_match,
        "answer": result.answer,
        "expected_answer_contains": gold.get("expect_answer_contains") or [],
        "contains_ok": contains_ok,
        "citations": citations_compact,
        "n_citations": len(result.citations),
        "citation_report_ok": bool(result.citation_report.get("ok")),
        "citation_verdicts": [v.get("status")
                              for v in result.citation_report.get(
                                  "verdicts", [])],
        "claims_supported": bool(result.claim_review.get(
            "all_claims_supported")),
        "claim_counts": result.claim_review.get("counts") or {},
        "required_sources": required_sources,
        "required_sources_ok": sources_ok,
        "required_domains": required_domains,
        "required_domains_ok": domains_ok,
        "cited_source_domains": sorted(cited_domains),
        "citations_ok": citations_ok,
        "counters": dict(counters),
        "counters_nonzero": counters_nonzero,
        "correct": correct,
        "decision_trace": list(result.decision_trace),
        "trace_conflicts": trace_conflicts,
        "coverage": (pack.get("coverage_status") or {}).get("coverage"),
        "window_chunk_ids": window_ids,
        "n_window_items": len(window_ids),
        "gold_chunk_id": gold.get("gold_chunk_id"),
        "gold_rank_in_window": gold_rank_in_window,
        "alt_chunk_ranks": probe_records["alt_chunk_ranks"],
        "conflicts_surfaced": conflicts_compact,
        "evidence_path_trace": pack.get("evidence_path_trace") or {},
        "retrieval_status": (pack.get("retrieval_status") or ""),
        "lineage_ok": lineage_ok,
        "payload_leak": leaks,
        "query_injection": dict(result.query_injection or {}),
        "source_injection": dict(result.source_injection or {}),
        "temporal_action": (result.freshness or {}).get("action"),
        "snapshot_date": pack.get("snapshot_date"),
    }


def run_retrieval_probe(row: dict, corpus) -> dict:
    stage = retrieve(corpus.index, corpus.chunks_by_id, row["query"],
                     top_k=8)
    gold_id = row["gold"]["gold_chunk_id"]

    def rank_in(seq: list) -> int:
        return next((i for i, (cid, _s) in enumerate(seq, 1)
                     if cid == gold_id), 0)

    return {
        "case_id": row["case_id"],
        "split": row["split"], "track": row["track"],
        "family": row["family"], "mode": row["mode"],
        "stress": row.get("stress", False),
        "query": row["query"],
        "gold_chunk_id": gold_id,
        "bm25_rank": rank_in(stage.ranked),
        "rerank_rank": rank_in(stage.reranked),
        "rank": rank_in(stage.deduped),
        "n_returned": len(stage.deduped),
        "deduped_chunk_ids": [cid for cid, _s in stage.deduped],
        "sources_kept": list(stage.sources_kept),
        "source_diversity": stage.source_diversity,
        "correct": 0 < rank_in(stage.deduped) <= 10,
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def retrieval_metrics(results: list[dict]) -> dict:
    n = len(results)
    if not n:
        return {}
    ranks = [r["rank"] for r in results]

    def recall(k: int) -> float:
        return sum(1 for r in ranks if 0 < r <= k) / n

    mrr = sum(1.0 / r for r in ranks if r) / n
    ndcg = sum(1.0 / math.log2(r + 1) for r in ranks if 0 < r <= 5) / n
    diversity = sum(r["source_diversity"] for r in results) / n
    return {"recall_at_5": round(recall(5), 4),
            "recall_at_10": round(recall(10), 4),
            "mrr": round(mrr, 4),
            "ndcg_at_5": round(ndcg, 4),
            "source_diversity": round(diversity, 4),
            "n": n}


def grounded(results: list[dict]) -> dict:
    n = len(results)
    if not n:
        return {}
    return {"accuracy": round(sum(1 for r in results
                                  if r["correct"]) / n, 4), "n": n}


def conflict_metrics(track_results: list[dict]) -> dict:
    gold_conflict = [r for r in track_results
                     if r["expected_status"] == "CONFLICTING_EVIDENCE"]
    gold_answer = [r for r in track_results
                   if r["expected_status"] == "ANSWER"]
    detected = sum(1 for r in gold_conflict
                   if r["status"] == "CONFLICTING_EVIDENCE")
    false_resolution = sum(1 for r in gold_conflict
                           if r["status"] == "ANSWER")
    detection = detected / len(gold_conflict) if gold_conflict else None
    return {
        "conflict_detection": round(detection, 4) if detection is not None
        else None,
        "false_resolution": round(false_resolution / len(gold_conflict), 4)
        if gold_conflict else None,
        "resolution_accuracy": grounded(gold_answer).get("accuracy"),
        "n_gold_conflicting": len(gold_conflict),
        "n_gold_answer": len(gold_answer),
    }


def abstention_metrics(all_results: list[dict]) -> dict:
    def is_abstain(status: str) -> bool:
        return status in ABSTAIN_STATUSES

    tp = sum(1 for r in all_results
             if r["expected_status"] in ABSTAIN_STATUSES
             and is_abstain(r["status"]))
    fp = sum(1 for r in all_results
             if r["expected_status"] in ABSTAIN_STATUSES
             and not is_abstain(r["status"]))
    fn = sum(1 for r in all_results
             if r["expected_status"] not in ABSTAIN_STATUSES
             and is_abstain(r["status"]))
    tn = sum(1 for r in all_results
             if r["expected_status"] not in ABSTAIN_STATUSES
             and not is_abstain(r["status"]))
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "abstention_precision": round(precision, 4) if precision is not None
        else None,
        "abstention_recall": round(recall, 4) if recall is not None else None,
        "false_abstention": fn,
        "false_answer": fp,
        "true_abstain": tp, "true_answer": tn,
    }


def citation_metrics(answer_results: list[dict]) -> dict:
    gold_answer = [r for r in answer_results
                   if r["expected_status"] == "ANSWER"]
    if not gold_answer:
        return {}
    resolvable = sum(1 for r in gold_answer if r["citation_report_ok"])
    precise = sum(1 for r in gold_answer
                  if r["citation_report_ok"]
                  and all(v == "OK" for v in r["citation_verdicts"]))
    fabricated = sum(1 for r in gold_answer
                     for v in r["citation_verdicts"] if v != "OK")
    lineage = sum(1 for r in gold_answer if r["lineage_ok"] is True)
    with_citations = sum(1 for r in gold_answer if r["n_citations"] > 0)
    sources_ok = sum(1 for r in gold_answer if r["required_sources_ok"])
    domains_ok = sum(1 for r in gold_answer if r["required_domains_ok"])
    return {
        "citation_resolvability": round(resolvable / len(gold_answer), 4),
        "citation_precision": round(precise / len(gold_answer), 4),
        "fabricated_citations": fabricated,
        "extractive_lineage_ok": round(lineage / len(gold_answer), 4),
        "citation_coverage": round(with_citations / len(gold_answer), 4),
        "required_sources_ok": round(sources_ok / len(gold_answer), 4),
        "required_domains_ok": round(domains_ok / len(gold_answer), 4),
        "n_gold_answer": len(gold_answer),
    }


def compute_metrics(results: list[dict]) -> dict:
    tracks: dict[str, dict] = {}
    for track in sorted({r["track"] for r in results}):
        rows = [r for r in results if r["track"] == track]
        entry: dict = {"n": len(rows)}
        if track == "A":
            entry.update(retrieval_metrics(rows))
        else:
            entry.update(grounded(rows))
            if track == "D":
                entry.update(conflict_metrics(rows))
        for family in sorted({r["family"] for r in rows}):
            fam_rows = [r for r in rows if r["family"] == family]
            fam_entry: dict = {"n": len(fam_rows)}
            if track == "A":
                fam_entry.update(retrieval_metrics(fam_rows))
            else:
                fam_entry.update(grounded(fam_rows))
            entry.setdefault("families", {})[family] = fam_entry
        tracks[track] = entry

    answer_rows = [r for r in results if r["mode"] == "answer"]
    metrics = {
        "tracks": tracks,
        "abstention": abstention_metrics(answer_rows),
        "citations": citation_metrics(answer_rows),
        "overall_grounded": grounded(
            [r for r in answer_rows
             if r["expected_status"] == "ANSWER"]),
        "zero_tolerance_rows_nonzero": sum(
            1 for r in results if r.get("counters_nonzero")),
        "injection_payload_leaks": sum(1 for r in answer_rows
                                       if r.get("payload_leak")),
        "lineage_failures": sum(1 for r in answer_rows
                                if r["expected_status"] == "ANSWER"
                                and r.get("lineage_ok") is False),
    }
    return metrics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", required=True,
                        choices=("dev", "validation"))
    parser.add_argument("--label", required=True,
                        choices=("before", "after"))
    parser.add_argument("--out", default=None)
    parser.add_argument("--metrics", default=None)
    arguments = parser.parse_args()

    _check_validation_freeze(arguments.split)

    world_index = json.loads(
        (OUT_DIR / "world_index.json").read_text(encoding="utf-8"))
    key_to_id = world_index["source_key_to_id"]
    corpus = load_corpus(world.WORLD_DIR)

    suites_path = SUITES[arguments.split]
    rows = [json.loads(line) for line in
            suites_path.read_text(encoding="utf-8").splitlines() if line]

    # flagged injection chunks -> payload strings for leakage/lineage probes
    payload_by_key = {key: text for key, text
                      in world.INJECTION_SENTENCES.items()}
    flagged_payloads: dict[str, str] = {}
    for cid_row in world_index["injection_chunks"]:
        key = cid_row["payload_key"]
        if key in payload_by_key:
            flagged_payloads[cid_row["chunk_id"]] = payload_by_key[key]
    payload_list = sorted(set(payload_by_key.values()))

    results = []
    for row in rows:
        for src in row["gold"].get("required_sources") or []:
            if src not in key_to_id:
                raise SystemExit(
                    f"required_sources key not in world registry: {src}")
        row["gold"]["required_sources"] = _resolve_sources(
            row["gold"].get("required_sources") or [], key_to_id)
        if row["mode"] == "retrieval":
            results.append(run_retrieval_probe(row, corpus))
        else:
            results.append(run_answer_probe(row, corpus, world_index,
                                            flagged_payloads, payload_list))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(arguments.out) if arguments.out else \
        RESULTS_DIR / f"{arguments.label}_{arguments.split}.jsonl"
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        for record in results:
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True) + "\n")
    metrics = compute_metrics(results)
    metrics["artifact"] = "T21R11_DIAGNOSTIC_METRICS"
    metrics["label"] = arguments.label
    metrics["split"] = arguments.split
    metrics["n_rows"] = len(results)
    metrics["suites_sha256"] = _sha256_file(suites_path)
    metrics_path = Path(arguments.metrics) if arguments.metrics else \
        RESULTS_DIR / f"{arguments.label}_{arguments.split}_metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"rows": len(results),
                      "out": str(out_path),
                      "metrics": str(metrics_path)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())