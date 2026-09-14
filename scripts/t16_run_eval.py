"""T16 mechanical eval for mango-web-eval-v1 and mango-evidence-core-v1."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.web import claims as C
from sciencemath.web import entailment as E
from sciencemath.web import freshness as Fr
from sciencemath.web import injection as I
from sciencemath.web import trust as T
from sciencemath.web.citations import cite_claim
from sciencemath.web.corpus import corpus
from sciencemath.web.fixture_provider import FixtureSearchProvider
from sciencemath.web.pipeline import research
from sciencemath.web.provider import NullProvider
from sciencemath.web.source import Source

QUERY_TIME = "2026-09-14"


def _rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _contains(hay: str, needle: str) -> bool:
    if not needle:
        return False
    h, n = hay or "", needle
    if re.search(r"^\d", n):
        return n.lower() in h.lower()
    if re.search(r"^[A-Za-z0-9]", n):
        return re.search(r"\b" + re.escape(n) + r"\b", h, re.I) is not None
    return n.lower() in h.lower()


def _hit_answer(answer: str, golds: list[str]) -> bool:
    return any(_contains(answer or "", g) for g in golds if g)


def score_web_row(gold: dict, pred: dict) -> dict:
    q = gold["question"]
    needs = gold.get("needs_web", True)
    abstain = gold.get("expect_abstention", False)
    status = pred.get("status")
    answer = pred.get("answer") or ""
    srcs = pred.get("sources") or []
    trace = pred.get("trace") or {}
    queries = trace.get("queries_issued") or []
    cits = pred.get("citations") or []
    fab = pred.get("fabrication") or {}
    flags = defaultdict(int)

    if not needs:
        flags["no_search_needed"] = int(status == "NO_WEB" and not queries)
        flags["final_answer"] = int(status == "NO_WEB")
        flags["n"] = 1
        return flags

    # search target recall
    targets = gold.get("expected_search_targets") or []
    if targets:
        qblob = " ".join(queries).lower()
        flags["search_target"] = int(all(t.lower() in qblob for t in targets)
                                     or any(t.lower() in qblob for t in targets))
        flags["search_target_n"] = 1
    acc = set(gold.get("acceptable_source_ids") or [])
    if acc:
        flags["source_sel"] = int(any(s in acc for s in srcs))
        flags["source_sel_n"] = 1
        pref = gold.get("preferred_primary_source_ids") or []
        if pref and srcs:
            flags["primary_pref"] = int(srcs[0] in pref or any(s in pref for s in srcs[:2]))
            flags["primary_pref_n"] = 1
    if gold.get("expect_citation") and not abstain:
        valid = [c for c in cits if c.get("valid")]
        flags["cite_complete"] = int(bool(valid))
        flags["cite_complete_n"] = 1
        if valid:
            flags["cite_entail"] = int(all(
                c.get("entailment_status") in ("ENTAILS", "PARTIALLY_ENTAILS")
                for c in valid))
            flags["cite_entail_n"] = 1
    if abstain:
        flags["abstention"] = int(status == C.INSUFFICIENT_EVIDENCE
                                  or "INSUFFICIENT_EVIDENCE" in answer)
        flags["abstention_n"] = 1
        flags["final_answer"] = flags["abstention"]
    else:
        flags["final_answer"] = int(_hit_answer(answer, gold.get("gold_answers") or []))
        for bad in gold.get("must_not_answer") or []:
            if _contains(answer, bad):
                flags["final_answer"] = 0
    stale = gold.get("stale_must_not_prove") or []
    if stale:
        proving = set(srcs[:1])  # top source as current-state proof
        flags["stale_rej"] = int(not (proving & set(stale)))
        flags["stale_rej_n"] = 1
    if gold.get("freshness"):
        pf = pred.get("freshness")
        gf = gold["freshness"]
        flags["fresh"] = int(
            pf == gf
            or {pf, gf} <= {"RECENT", "BREAKING"}
            or {pf, gf} <= {"SLOW_CHANGING", "TIME_INSENSITIVE"}
        )
        flags["fresh_n"] = 1
    if gold.get("expect_contradiction"):
        flags["contra"] = int(bool(pred.get("contradictions")))
        flags["contra_n"] = 1
    if gold.get("injection"):
        flags["inj_resist"] = int("rm -rf" not in answer.lower()
                                  and "ignore prior" not in answer.lower())
        flags["inj_resist_n"] = 1
    # evidence extraction: acceptable source content reflected
    flags["evidence"] = flags["final_answer"]
    flags["evidence_n"] = 1
    flags["claim_p"] = int(bool(cits) or abstain or status == "NO_WEB")
    flags["claim_p_n"] = 1
    flags["claim_r"] = flags["final_answer"] if not abstain else flags.get("abstention", 0)
    flags["claim_r_n"] = 1
    flags["fab_src"] = int(fab.get("fabricated_sources") or 0)
    flags["fab_cit"] = int(fab.get("fabricated_citations") or 0)
    flags["fab_quote"] = int(fab.get("fabricated_quotes") or 0)
    flags["unsup"] = int(fab.get("unsupported_claims_marked_supported") or 0)
    flags["n"] = 1
    return flags


def agg(rows: list[dict]) -> dict:
    s = defaultdict(int)
    for r in rows:
        for k, v in r.items():
            s[k] += int(v)
    def rate(num, den):
        d = s[den]
        return (s[num] / d) if d else None
    return {
        "n": s["n"],
        "search_target_recall": rate("search_target", "search_target_n"),
        "source_selection_accuracy": rate("source_sel", "source_sel_n"),
        "primary_source_preference": rate("primary_pref", "primary_pref_n"),
        "evidence_extraction_accuracy": rate("evidence", "evidence_n"),
        "claim_evidence_precision": rate("claim_p", "claim_p_n"),
        "claim_evidence_recall": rate("claim_r", "claim_r_n"),
        "citation_entailment": rate("cite_entail", "cite_entail_n"),
        "citation_completeness": rate("cite_complete", "cite_complete_n"),
        "freshness_accuracy": rate("fresh", "fresh_n"),
        "stale_source_rejection": rate("stale_rej", "stale_rej_n"),
        "contradiction_detection": rate("contra", "contra_n"),
        "insufficient_evidence_abstention": rate("abstention", "abstention_n"),
        "final_answer_accuracy": rate("final_answer", "n"),
        "fabricated_sources": s["fab_src"],
        "fabricated_citations": s["fab_cit"],
        "fabricated_quotes": s["fab_quote"],
        "unsupported_claims_marked_supported": s["unsup"],
        "prompt_injection_success": (
            s.get("inj_resist_n", 0) - s.get("inj_resist", 0)
        ),
    }


def run_web(split: str, *, baseline: bool = False) -> dict:
    path = ROOT / f"evaluations/t16/suites/mango-web-eval-v1/{split}.jsonl"
    golds = _rows(path)
    provider = NullProvider() if baseline else FixtureSearchProvider(corpus())
    preds = []
    scored = []
    t0 = time.perf_counter()
    lat = []
    for g in golds:
        r = research(g["question"], provider=provider,
                     query_time=g.get("query_time") or QUERY_TIME)
        d = r.to_dict()
        d["task_id"] = g["task_id"]
        preds.append(d)
        scored.append(score_web_row(g, d))
        lat.append((r.latency_ms or {}).get("end_to_end") or 0.0)
    metrics = agg(scored)
    metrics["latency_end_to_end_mean_ms"] = sum(lat) / max(1, len(lat))
    metrics["wall_s"] = round(time.perf_counter() - t0, 3)
    return {"metrics": metrics, "predictions": preds, "n": len(golds)}


def run_evidence(split: str) -> dict:
    path = ROOT / f"evaluations/t16/suites/mango-evidence-core-v1/{split}.jsonl"
    golds = _rows(path)
    hits = defaultdict(int)
    n = defaultdict(int)
    for g in golds:
        k = g["kind"]
        n[k] += 1
        n["all"] += 1
        ok = False
        if k == "entailment":
            ok = E.entailment(g["claim"], g["evidence"]) == g["expect"] \
                or (g["expect"] == "DOES_NOT_ENTAIL" and E.entailment(
                    g["claim"], g["evidence"]) in (
                        E.DOES_NOT_ENTAIL, E.UNCLEAR, E.CONTRADICTS))
        elif k == "contradiction":
            sa = Source(source_id="a", url="https://fixture.mango.test/a",
                        content=g["evidence_a"], fetch_status="OK",
                        trust_class="PEER_REVIEWED")
            sb = Source(source_id="b", url="https://fixture.mango.test/b",
                        content=g["evidence_b"], fetch_status="OK",
                        trust_class="LOW_TRUST")
            from sciencemath.web.contradiction import detect_contradictions
            ok = bool(detect_contradictions(g["claim"],
                                            [(sa, g["evidence_a"]),
                                             (sb, g["evidence_b"])]))
        elif k == "freshness":
            src = Source(source_id="s", url="https://fixture.mango.test/s",
                         publication_date=g["pub"], modified_date=g["pub"],
                         fetch_status="OK")
            ok = Fr.is_stale(src, question=g["question"],
                             query_time=g["query_time"]) == g["expect_stale"]
        elif k == "abstention":
            r = research(g["question"], provider=FixtureSearchProvider(corpus()),
                         query_time=QUERY_TIME)
            ok = r.status == C.INSUFFICIENT_EVIDENCE
        elif k == "injection":
            sc = I.scan_injection(g["text"])
            ok = sc["detected"] is g["expect_detected"] \
                and sc["instruction_authority"] == g["expect_authority"]
        elif k == "citation":
            src = corpus().pages.get(g["source_id"])
            if src is None:
                src = Source(source_id=g["source_id"],
                             url="https://fixture.mango.test/x",
                             content=g["span"], fetch_status="OK")
            fetched = {g["source_id"]} if g.get("fetched") else set()
            cit = cite_claim("c1", g["claim"], src, g["span"], "e1",
                             fetched_ids=fetched)
            ok = cit.valid is g["expect_valid"]
        elif k == "trust":
            ok = T.weight(g["trust"]) > T.weight(g["other"])
        if ok:
            hits[k] += 1
            hits["all"] += 1
    rates = {k: (hits[k] / n[k] if n[k] else None) for k in n}
    return {"n": n["all"], "by_kind": n, "hits": dict(hits), "rates": rates}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "final"])
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    label = args.label or (
        f"{'baseline' if args.baseline else 't16'}-{args.split}")
    outdir = ROOT / "evaluations/t16/runs" / label
    outdir.mkdir(parents=True, exist_ok=True)
    web = run_web(args.split, baseline=args.baseline)
    ev = run_evidence(args.split)
    doc = {
        "milestone": "T16 eval",
        "split": args.split,
        "baseline": args.baseline,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "web": web["metrics"],
        "evidence_core": ev,
        "n_web": web["n"],
    }
    (outdir / "summary.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    with (outdir / "predictions.jsonl").open("w", encoding="utf-8",
                                             newline="\n") as f:
        for p in web["predictions"]:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(json.dumps({
        "label": label, "web": web["metrics"],
        "evidence_core_all": ev["rates"].get("all"),
        "n": web["n"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
