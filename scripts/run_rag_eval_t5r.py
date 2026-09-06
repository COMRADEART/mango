"""T5R.12/T5R.13/T5R.14 — variant comparison + final frozen rerun.

Variants (pre-declared, T5R.12) — each differs from the next by exactly
one mechanism so any single-lucky-result selection is visible:

  NORAG  no retrieval (matched settings; frozen extract_answer)
  A      T5 rag arm as frozen (raw chunks, inline-citation instruction)
  B      + route-specific prompts + retrieval-eligibility gate (T5R.1/.6)
  C      B + evidence compression + firewall (T5R.2/.9)
  D      C + deterministic citations (T5R.7/.8)
  E      D + MIXED plan + multi-hop decomposition (T5R.4/.5)  == Final T5R

Suites:
  dev    mango-rag-dev-v1 (evaluations/rag-suite/dev-v1)  -> variant SELECTION
  frozen mango-rag-eval-v1 (integrity-checked, never modified)
         -> final rerun, results written to a NEW directory only.

Usage:
  python scripts/run_rag_eval_t5r.py --suite dev --variants NORAG,A,B,C,D,E
  python scripts/run_rag_eval_t5r.py --suite frozen --variants NORAG,E
  python scripts/run_rag_eval_t5r.py --suite dev --variant-budget 150,350,650
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.evaluation.extraction import (answers_match,
                                               extract_answer,
                                               signals_uncertainty,
                                               strip_think_block)
from sciencemath.evaluation.extraction_t5r import extract_answer_t5r
from sciencemath.rag.pipeline import GENERAL_EVAL_INSTRUCTION
from sciencemath.tools.benchmark import TOOL_PROTOCOL_INSTRUCTION
from sciencemath.utils.io_utils import write_json

SUITES = {
    "dev": (ROOT / "evaluations" / "rag-suite" / "dev-v1",
            ROOT / "evaluations" / "rag-results" / "t5r-dev"),
    "frozen": (ROOT / "evaluations" / "rag-suite" / "v1",
               ROOT / "evaluations" / "rag-results" / "v1" / "t5r"),
}
GENERATION = {"seed": 42, "do_sample": False, "max_new_tokens": 1024}


def candidate_provenance() -> dict:
    """Identify T8 base-model runs in summaries and resume fingerprints."""
    model_id = os.environ.get("MANGO_EVAL_MODEL")
    if not model_id:
        return {}
    return {"model_id": model_id, "adapter": None,
            "generation": dict(GENERATION)}

GEN_ELIGIBLE_CATEGORIES = {
    "factual_science_qa", "multi_hop_science_qa", "quantitative_science",
    "insufficient_evidence", "distractor_retrieval", "conflicting_evidence",
    "source_attribution", "mixed_math_science",
}
# T5R.6 invocation ground truth (declared in the dev manifest; the same
# mapping is applied to the frozen suite for the invocation metrics)
EXPECTED_RETRIEVAL = {
    "factual_science_qa": True, "multi_hop_science_qa": True,
    "quantitative_science": False, "insufficient_evidence": True,
    "distractor_retrieval": True, "conflicting_evidence": True,
    "source_attribution": True, "mixed_math_science": False,
}
VARIANT_FEATURES = {
    "B": {"retrieve_gate": True, "compression": False, "firewall": False,
          "decompose": False, "mixed_plan": False,
          "deterministic_citations": False},
    "C": {"retrieve_gate": True, "compression": True, "firewall": True,
          "decompose": False, "mixed_plan": False,
          "deterministic_citations": False},
    "D": {"retrieve_gate": True, "compression": True, "firewall": True,
          "decompose": False, "mixed_plan": False,
          "deterministic_citations": True},
    "E": {"retrieve_gate": True, "compression": True, "firewall": True,
          "decompose": True, "mixed_plan": True,
          "deterministic_citations": True},
    # G (selected from the A–E matrix): E's MIXED machinery (constants +
    # tool delegation, its only category gain) without decomposition,
    # which the matrix showed costs multi-hop
    "G": {"retrieve_gate": True, "compression": True, "firewall": True,
          "decompose": False, "mixed_plan": True,
          "deterministic_citations": True},
}


def verify_suite_integrity(suite_dir: Path) -> int:
    import hashlib
    checksums = json.loads((suite_dir / "checksum.json").read_text(
        encoding="utf-8"))
    n = 0
    for line in (suite_dir / "questions.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        assert checksums.get(row["eval_id"]) == digest, \
            f"suite tampered: {row['eval_id']}"
        n += 1
    print(f"suite integrity OK ({n} questions)", file=sys.stderr)
    return n


def load_rows(suite_dir: Path) -> list[dict]:
    return [json.loads(l) for l in (suite_dir / "questions.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]


def build_retriever(top_n: int | None = None,
                    reranker_mode: str = "adopted"):
    from sciencemath.rag.embeddings import (CANDIDATES,
                                            SentenceTransformerEmbedder)
    from sciencemath.rag.retriever import (RetrievalConfig, Retriever,
                                           load_corpus)
    from sciencemath.rag.vectorstore import BruteForceVectorStore
    corpus_dir = ROOT / "rag" / "corpus"
    chunk_by_id, manifest = load_corpus(corpus_dir)
    decision = json.loads((ROOT / "rag" / "embeddings" /
                           "embedding_decision.json").read_text(
        encoding="utf-8"))
    spec = CANDIDATES[decision["winner"]]
    embedder = SentenceTransformerEmbedder(spec, device="cpu")
    texts = [c["text"] for c in chunk_by_id.values()]
    vecs = embedder.embed_passages(texts)
    store = BruteForceVectorStore(vecs.shape[1])
    store.add(vecs, list(chunk_by_id))
    rd_path = ROOT / "rag" / "reranker" / "reranker_decision.json"
    reranker = None
    if reranker_mode == "adopted" and rd_path.exists():
        rd = json.loads(rd_path.read_text(encoding="utf-8"))
        if rd.get("adopted_reranker") == "cross-encoder":
            from sciencemath.rag.reranker import CrossEncoderReranker
            reranker = CrossEncoderReranker()
    cfg = RetrievalConfig()
    if top_n is not None:
        cfg.top_n = top_n
    return Retriever(store=store, chunk_by_id=chunk_by_id,
                     embedder=embedder, config=cfg, reranker=reranker)


def load_model():
    import yaml
    from sciencemath.evaluation.model_loader import load_model_safely
    # T8.16: env override evaluates a capacity-candidate BASE model instead
    # of configs/model.yaml; no T3 adapter is attached (candidates are
    # base models, and Mango-v0.1 results must not leak into them).
    override = os.environ.get("MANGO_EVAL_MODEL")
    GENERATION["max_new_tokens"] = 1024
    if override:
        tok, model, info = load_model_safely(override)
        if not info["ok"]:
            raise RuntimeError(f"model load failed: {info['error']}")
        # T8.7 exception: long-CoT comparators get a larger generation
        # budget (only honoured together with the model override)
        mx = os.environ.get("MANGO_EVAL_MAX_TOKENS")
        if mx:
            GENERATION["max_new_tokens"] = int(mx)
            print(f"T8 generation exception: max_new_tokens={mx}",
                  file=sys.stderr)
        print(f"T8 candidate model (no adapter): {override}",
              file=sys.stderr)
        return model, tok
    model_cfg = yaml.safe_load((ROOT / "configs" / "model.yaml").read_text(
        encoding="utf-8"))
    train_cfg = yaml.safe_load((ROOT / "configs" / "training.yaml")
                               .read_text(encoding="utf-8"))
    model_id = model_cfg.get("model_id") or "Qwen/Qwen3-1.7B"
    tok, model, info = load_model_safely(model_id)
    if not info["ok"]:
        raise RuntimeError(f"model load failed: {info['error']}")
    adapter_dir = ROOT / train_cfg["training"]["adapter_output_dir"]
    if adapter_dir.exists():
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(adapter_dir))
        model.eval()
        print(f"adapter attached: {adapter_dir}", file=sys.stderr)
    return model, tok


def score_question(row: dict, raw: str, *, t5r_extraction: bool) -> tuple[
        bool, str | None, str | None]:
    if row["answer_type"] == "uncertainty":
        visible = strip_think_block(raw or "")
        return signals_uncertainty(visible), visible.strip() or None, \
            None if visible.strip() else "EXTRACTION_FAILURE"
    extract = extract_answer_t5r if t5r_extraction else extract_answer
    extracted = extract(raw, row["answer_type"])
    if extracted is None:
        return False, None, "EXTRACTION_FAILURE"
    ok = answers_match(row.get("expected_answer", ""), extracted)
    return ok, extracted, None


def _read_preds(path: Path) -> list[dict]:
    """Read predictions tolerantly: an interrupted append must not
    permanently block resume (a torn trailing line is dropped)."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def run_variant(variant: str, rows: list[dict], retriever, model, tokenizer,
                registry, tool_logger, audit_logger, out_dir: Path,
                max_evidence_tokens: int = 350, *,
                features: dict | None = None,
                config_fp: dict | None = None) -> dict:
    from sciencemath.rag.pipeline import answer_question, answer_question_t5r
    arm_dir = out_dir / variant
    arm_dir.mkdir(parents=True, exist_ok=True)
    pred_path = arm_dir / "predictions.jsonl"
    done = {p["eval_id"] for p in _read_preds(pred_path)} \
        if pred_path.exists() else set()
    is_t5r = features is not None or variant in ("B", "C", "D", "E", "G")
    features = features or VARIANT_FEATURES.get(variant)
    t5r_extraction = is_t5r
    # resume fingerprint (T5R.17): a stale arm must never be silently
    # reused under a different configuration
    fp = {"features": features, "max_evidence_tokens": max_evidence_tokens,
          "t5r_extraction": t5r_extraction, **(config_fp or {})}
    cfg_path = arm_dir / "config.json"
    if cfg_path.exists():
        if json.loads(cfg_path.read_text(encoding="utf-8")) != fp:
            raise SystemExit(
                f"config mismatch for {variant}: remove {arm_dir} to re-run")
    else:
        write_json(cfg_path, fp)
    eligible = [r for r in rows if r["category"] in GEN_ELIGIBLE_CATEGORIES]
    n_new = 0
    for r in eligible:
        if r["eval_id"] in done:
            continue
        n_new += 1
        route = None
        t_start = time.time()
        if variant == "NORAG":
            from sciencemath.rag.route import classify_route
            route = classify_route(r["question"])
            parts = [r["question"].strip()]
            if route["route"] in ("MATH", "MIXED"):
                parts.append(TOOL_PROTOCOL_INSTRUCTION)
            parts.append(GENERAL_EVAL_INSTRUCTION)
            ans = answer_question(
                model=model, tokenizer=tokenizer, question=r["question"],
                question_id=r["eval_id"], retriever=None, registry=registry,
                tool_logger=tool_logger, audit_logger=audit_logger,
                generation=GENERATION,
                prompt_override="\n\n".join(parts))
            retrieval_used = False
            chunk_ids = []
        elif variant == "A":
            ans = answer_question(
                model=model, tokenizer=tokenizer, question=r["question"],
                question_id=r["eval_id"], retriever=retriever,
                registry=registry, tool_logger=tool_logger,
                audit_logger=audit_logger, generation=GENERATION)
            retrieval_used = bool(ans.retrieval
                                  and ans.retrieval.used_retrieval)
            chunk_ids = [c["chunk_id"] for c in
                         (ans.retrieval.chunks if ans.retrieval else [])]
            route = ans.route
        else:
            ans = answer_question_t5r(
                model=model, tokenizer=tokenizer, question=r["question"],
                question_id=r["eval_id"], retriever=retriever,
                registry=registry, tool_logger=tool_logger,
                audit_logger=audit_logger, generation=GENERATION,
                max_evidence_tokens=max_evidence_tokens,
                features=features)
            retrieval_used = ans.retrieval_used
            chunk_ids = [c["chunk_id"] for c in ans.chunks_supplied]
            route = ans.route
        raw = ans.raw_model_output
        correct, extracted, failure = score_question(
            r, raw, t5r_extraction=t5r_extraction)
        citation_report = None
        if is_t5r and features.get("deterministic_citations"):
            # T5R.7: citations are system-attached; fail-closed on
            # invalid refs; source_attribution REQUIRES a valid ref
            citation_report = {
                "n_citations": len(ans.citations),
                "n_fabricated": 0,
                "n_unsupported": 0,
                "n_valid": len(ans.citations),
                "all_valid": not ans.invalid_refs,
                "invalid_refs": ans.invalid_refs,
                "source": "deterministic attachment",
            }
            if r["category"] == "source_attribution":
                correct = correct and bool(ans.citations) \
                    and not ans.invalid_refs
        elif is_t5r:
            # citations were parsed from the model's inline markers —
            # verify them against the actually-supplied chunks
            from sciencemath.rag.citations import verify_answer_citations
            seen = {c["chunk_id"]: c for c in ans.chunks_supplied}
            rep = verify_answer_citations(raw, ans.citations, seen)
            citation_report = {
                "n_citations": len(ans.citations), "n_valid": len(rep.valid),
                "n_fabricated": len(rep.fabricated),
                "n_unsupported": len(rep.unsupported),
                "all_valid": rep.all_valid}
            if r["category"] == "source_attribution":
                correct = correct and bool(rep.valid)
        elif variant == "A":
            from sciencemath.rag.citations import verify_answer_citations
            seen = {c["chunk_id"]: c for c in
                    (ans.retrieval.chunks if ans.retrieval else [])}
            rep = verify_answer_citations(raw, ans.citations, seen)
            citation_report = {
                "n_citations": len(ans.citations), "n_valid": len(rep.valid),
                "n_fabricated": len(rep.fabricated),
                "n_unsupported": len(rep.unsupported),
                "all_valid": rep.all_valid}
            if r["category"] == "source_attribution":
                correct = correct and bool(rep.valid)
        rec = {
            "eval_id": r["eval_id"], "category": r["category"],
            "variant": variant,
            "question": r["question"], "route": route["route"],
            "subroute": (ans.subroute if is_t5r else None),
            "retrieval_used": retrieval_used,
            "expected_retrieval": EXPECTED_RETRIEVAL.get(r["category"]),
            "retrieved_chunk_ids": chunk_ids,
            "evidence_state": (ans.conflict_state
                               if is_t5r
                               else ans.contract.evidence_state),
            "raw_output": raw,
            "extracted_answer": extracted,
            "expected_answer": r.get("expected_answer"),
            "correct": correct, "failure": failure,
            "citation_report": citation_report,
            "latency_s": round(time.time() - t_start, 3),
            "input_tokens": ans.input_tokens,
            "output_tokens": ans.output_tokens,
            "error": getattr(ans, "error", None),
        }
        if is_t5r:
            comp = ans.compressed
            rec["compression"] = {
                "raw_tokens": comp.raw_tokens if comp else 0,
                "selected_tokens": comp.selected_tokens if comp else 0,
                "compression_ratio": (comp.compression_ratio
                                      if comp else None),
            }
            rec["evidence_refs"] = ans.evidence_refs
            rec["invalid_refs"] = ans.invalid_refs
        with open(pred_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{variant}] {r['eval_id']} correct={correct}",
              file=sys.stderr)
    preds = [p for p in _read_preds(pred_path)
             if p["category"] in GEN_ELIGIBLE_CATEGORIES]
    return summarize_variant(variant, preds)


def summarize_variant(variant: str, preds: list[dict]) -> dict:
    total = len(preds)
    correct = sum(1 for p in preds if p["correct"])
    by_cat: dict[str, list[int]] = {}
    for p in preds:
        by_cat.setdefault(p["category"], []).append(int(p["correct"]))
    per_cat = {c: round(sum(v) / len(v), 4) for c, v in sorted(by_cat.items())}
    unc = [p for p in preds if p["category"] in ("insufficient_evidence",
                                                 "conflicting_evidence")]
    # T5R.6 retrieval invocation precision/recall vs declared ground truth
    tp = sum(1 for p in preds if p["retrieval_used"]
             and p["expected_retrieval"])
    fp = sum(1 for p in preds if p["retrieval_used"]
             and p["expected_retrieval"] is False)
    fn = sum(1 for p in preds if not p["retrieval_used"]
             and p["expected_retrieval"])
    math_route = [p for p in preds if p["route"] == "MATH"]
    citations = [p.get("citation_report") or {} for p in preds]
    comp = [p.get("compression") for p in preds
            if p.get("compression") and p["compression"]["raw_tokens"]]
    metrics = {
        "variant": variant, "n": total, "correct": correct,
        "accuracy": round(correct / total, 4) if total else None,
        "per_category_accuracy": per_cat,
        "uncertainty_accuracy": round(
            sum(1 for p in unc if p["correct"]) / len(unc), 4) if unc
        else None,
        "retrieval_invocation": {
            "expected_true": tp + fn, "retrieved_when_expected": tp,
            "invoked_but_not_expected": fp,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
        },
        "retrieval_used_on_math_route": sum(
            1 for p in math_route if p["retrieval_used"]),
        "citation_summary": {
            "n_questions_with_citations": sum(
                1 for c in citations if c.get("n_citations")),
            "n_fabricated": sum(c.get("n_fabricated", 0) for c in citations),
            "n_unsupported": sum(c.get("n_unsupported", 0) for c in citations),
            "n_invalid_refs": sum(len(c.get("invalid_refs") or [])
                                  for c in citations),
        },
        "compression_mean_ratio": (round(
            sum(c["compression_ratio"] for c in comp) / len(comp), 3)
            if comp else None),
        "mean_prompt_tokens_in": (round(sum(p["input_tokens"] for p in preds)
                                        / total) if total else None),
        "avg_latency_s": round(sum(p["latency_s"] for p in preds) / total, 3)
        if total else None,
    }
    return metrics


def compare_variants(metrics: dict[str, dict], out_dir: Path,
                     label: str) -> dict:
    base = metrics.get("NORAG")
    out = {"comparison": label, "variants": metrics}
    have_base = bool(base and base.get("accuracy") is not None)
    if have_base:
        for name, m in metrics.items():
            if name == "NORAG" or m.get("accuracy") is None:
                continue
            m["delta_vs_norag_pp"] = round(
                100 * (m["accuracy"] - base["accuracy"]), 2)
    if have_base:
        cats = sorted({c for m in metrics.values()
                       for c in (m.get("per_category_accuracy") or {})})
        out["per_category_pp_delta_vs_norag"] = {
            v: {c: round(100 * (metrics[v]["per_category_accuracy"].get(c, 0)
                                - (metrics["NORAG"]["per_category_accuracy"]
                                   .get(c, 0))),
                        2)
                for c in cats if v != "NORAG" and v in metrics}
            for v in metrics if v != "NORAG"}
    else:
        # no NORAG arm in this run: deltas vs no-RAG are undefined
        out["per_category_pp_delta_vs_norag"] = None
    write_json(out_dir / "comparison.json", out)
    return out


def budget_matrix(model, tokenizer, retriever, registry, tool_logger,
                  audit_logger, rows, out_dir: Path,
                  budgets: list[int]) -> dict:
    """T5R.3: 1/2/3-chunk context-budget matrix (chunk count via top_n,
    evidence tokens via max_evidence_tokens) on the dev suite."""
    results = {}
    for budget in budgets:
        for top_n in (1, 2, 3):
            key = f"e{budget}_k{top_n}"
            print(f"--- budget {key}", file=sys.stderr)
            r = build_retriever(top_n=top_n)
            metrics = run_variant(
                f"E_k{top_n}_t{budget}", rows, r, model, tokenizer, registry,
                tool_logger, audit_logger,
                out_dir / "budgets" / key,
                max_evidence_tokens=budget,
                features=dict(VARIANT_FEATURES["E"]),
                config_fp={"top_n": top_n, "reranker": "adopted",
                           "budget": budget})
            results[key] = metrics
    write_json(out_dir / "budgets_matrix.json", results)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=("dev", "frozen"), default="dev")
    ap.add_argument("--variants", default="NORAG,A,B,C,D,E")
    ap.add_argument("--top-n", type=int, default=None,
                    help="retrieval top_n override (chunk budget)")
    ap.add_argument("--reranker", choices=("adopted", "none"),
                    default="adopted",
                    help="T5R.13 ablation: disable the adopted reranker")
    ap.add_argument("--max-evidence-tokens", type=int, default=350)
    ap.add_argument("--budgets", default=None,
                    help="comma list of evidence token budgets for the "
                         "T5R.3 matrix (implies variant E)")
    ap.add_argument("--out-dir", default=None,
                    help="output dir override (e.g. the --reranker none "
                         "ablation arm writes under its own dir; the per-"
                         "arm config fingerprint would refuse a variant "
                         "dir from a differently-configured run)")
    args = ap.parse_args()

    suite_dir, default_out = SUITES[args.suite]
    out_dir = Path(args.out_dir) if args.out_dir else default_out
    verify_suite_integrity(suite_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(suite_dir)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    need_retriever = any(v in ("A", "B", "C", "D", "E", "G") for v in variants) \
        or bool(args.budgets)

    from sciencemath.rag.audit import RetrievalAuditLogger
    from sciencemath.tools.router import ToolCallLogger, build_default_registry
    model = tokenizer = None
    retriever = None
    registry = build_default_registry()
    tool_logger = ToolCallLogger(out_dir / "tool_calls.jsonl")
    audit = RetrievalAuditLogger(out_dir / "audit.jsonl")
    if need_retriever:
        retriever = build_retriever(top_n=args.top_n,
                                    reranker_mode=args.reranker)
    if need_retriever or args.budgets or variants:
        model, tokenizer = load_model()

    metrics: dict[str, dict] = {}
    run_fp = {"top_n": args.top_n, "reranker": args.reranker,
              **candidate_provenance()}
    if args.budgets:
        budgets = [int(b) for b in args.budgets.split(",")]
        budget_matrix(model, tokenizer, retriever, registry, tool_logger,
                      audit, rows, out_dir, budgets)
        return 0
    for v in variants:
        print(f"=== variant {v}", file=sys.stderr)
        if v == "NORAG":
            metrics[v] = run_variant("NORAG", rows, None, model, tokenizer,
                                     registry, tool_logger, audit, out_dir,
                                     args.max_evidence_tokens,
                                     config_fp=run_fp)
        elif v == "A":
            metrics[v] = run_variant("A", rows, retriever, model, tokenizer,
                                     registry, tool_logger, audit, out_dir,
                                     args.max_evidence_tokens,
                                     config_fp=run_fp)
        else:
            metrics[v] = run_variant(
                v, rows, retriever, model, tokenizer, registry, tool_logger,
                audit, out_dir, args.max_evidence_tokens,
                config_fp=run_fp)
        write_json(out_dir / v / "metrics.json", metrics[v])
    if len(metrics) > 1:
        comp = compare_variants(metrics, out_dir, args.suite)
        print(json.dumps(comp.get("variants", comp), indent=2)[:2000])
    write_json(out_dir / "run_summary.json", {
        "suite": args.suite, "variants": variants, "finished_at":
        time.strftime("%Y-%m-%d %H:%M:%S"),
        "generating": (os.environ.get("MANGO_EVAL_MODEL") or
                       "Mango-v0.1 (Qwen3-1.7B + T3 LoRA, unmerged)"),
        **candidate_provenance(),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
