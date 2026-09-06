"""T7.19/T7.38 — Matched EXECUTIVE OFF vs ON experiment + ablations A-G.

Same checkpoint (Mango-v0.1), same frozen suite (mango-executive-eval-v1),
same generation config; the ONLY difference between arms is the
executive feature set. Arms:
  A_off  baseline (canonical eval prompt, no executive machinery)
  B..G   executive with the feature flags from configs/executive.yaml

Per-class harness fault injection (declared per question in the suite):
  harness.fail_tools     -> calculator returns a runtime error
  harness.fail_retrieval -> retriever returns no chunks

Durable: each arm writes predictions.jsonl; completed question_ids are
skipped on re-run (no duplicate tool calls). Trajectory JSONL per arm
(think-blocks already stripped in llm.py).

Metrics + pre-registered gate evaluation -> metrics.json / gate_decision.json.

Usage:
  python -X utf8 scripts/run_executive_eval.py --arms A_off,E_full_executive \
      [--subset] [--limit N] [--suite evaluations/executive-suite/v1]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from sciencemath.evaluation.extraction import (  # noqa: E402
    extract_answer, signals_uncertainty)
from sciencemath.evaluation.prompts import build_evaluation_content
from sciencemath.executive.budgets import Budgets
from sciencemath.executive.checkpoint import RunCheckpointer
from sciencemath.executive.trajectory import TrajectoryLogger
from sciencemath.executive.runner import ExecContext, run_executive
from sciencemath.tools.router import build_default_registry

MODEL_ID = "Qwen/Qwen3-1.7B"
PARENT_ADAPTER = REPO / "training" / "adapters" / "sciencemath-v0.1-t3"
RESULTS = REPO / "evaluations" / "t7" / "exec_results"
GENERATION = {"seed": 42, "max_new_tokens": 1024, "do_sample": False}

# ablations evaluated on the full diagnostic classes; the head-to-head
# (A vs E) runs on the whole suite
ABLATION_CLASSES = {"distractor", "missing_info", "contradictory",
                    "tool_failure", "retrieval_failure", "self_correction",
                    "multi_step_math", "mixed"}


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def append_jsonl(p: Path, rec: dict) -> None:
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


class FailRegistry:
    """Wraps the real registry; returns a runtime error for the
    calculator on flagged questions (tool_failure class)."""

    def __init__(self, inner, fail: bool):
        self.inner = inner
        self.fail = fail

    def invoke(self, name, arguments):
        from types import SimpleNamespace
        if self.fail and name == "calculator":
            return SimpleNamespace(
                status="error",
                error={"code": "SIMULATED_FAILURE",
                       "message": "calculator unavailable (eval harness)"},
                result=None)
        return self.inner.invoke(name, arguments)

    def manifest(self):
        return self.inner.manifest()


class FailRetriever:
    def __init__(self, inner, fail: bool):
        self.inner = inner
        self.fail = fail

    def search(self, query, k=3):
        if self.fail:
            return []
        return self.inner.search(query, k=k)


class RetrieverAdapter:
    """Adapts the T5R Retriever (retrieve(question, *, top_n=) ->
    RetrievalResult) to the executive contract
    search(query, k=) -> list of {chunk_id, source_id, text} dicts."""

    def __init__(self, inner):
        self.inner = inner

    def search(self, query, k=3):
        res = self.inner.retrieve(query, top_n=k)
        return [{"chunk_id": c.get("chunk_id", ""),
                 "source_id": c.get("source_id", ""),
                 "text": c.get("text", "")}
                for c in (getattr(res, "chunks", None) or [])]


# ---- OFF arm ----------------------------------------------------------------
def run_off_arm(model, tok, items, out_path, registry, retriever) -> None:
    import torch
    done = {r["question_id"] for r in read_jsonl(out_path)}
    for item in items:
        if item["question_id"] in done:
            continue
        t0 = time.perf_counter()
        content = build_evaluation_content(item["question"],
                                           item["answer_type"],
                                           item.get("choices"))
        # MUST match call_model (T5R/T6 baseline tokenization): the
        # prompt goes through render_for_model (chat template,
        # thinking disabled). Bare-content tokenization produces a
        # DIFFERENT model regime and an unmatched comparison.
        from sciencemath.evaluation.prompts import render_for_model
        templ = render_for_model(tok, content, enable_thinking=False)
        torch.manual_seed(int(GENERATION["seed"]))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(GENERATION["seed"]))
        inputs = tok(templ, return_tensors="pt", truncation=True,
                     max_length=4096)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        n_in = int(inputs["input_ids"].shape[1])
        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=GENERATION["max_new_tokens"],
                pad_token_id=tok.pad_token_id or tok.eos_token_id,
                do_sample=False)
        n_out = int(out.shape[1]) - n_in
        raw = tok.decode(out[0][n_in:], skip_special_tokens=True)
        from sciencemath.evaluation.extraction import strip_think_block
        raw = strip_think_block(raw)
        rec = {
            "question_id": item["question_id"], "arm": "A_off",
            "raw": raw,
            "extracted_answer": extract_answer(
                raw, item["answer_type"], item.get("choices")),
            "expected_answer": item["expected_answer"],
            "answer_type": item["answer_type"],
            "class": item["class"],
            "declined": bool(signals_uncertainty(raw)),
            "latency_s": round(time.perf_counter() - t0, 3),
            "input_tokens": n_in, "output_tokens": n_out,
            "plan_attempts": 0, "steps_executed": 0, "replans": 0,
            "tool_calls": 0, "retrievals": 0, "model_calls": 1,
            "fast_path": None, "termination_reason": "OFF_BASELINE",
            "evidence_status": None, "first_attempt_plan_valid": None,
            "retry_plan_valid": None, "plan_fallback_used": None,
        }
        append_jsonl(out_path, rec)


# ---- ON arms (B..G) -----------------------------------------------------------
def run_exec_arm(model, tok, items, arm, features, out_path, registry,
                 retriever, trajectories: Path, ckpt_dir: Path) -> None:
    done = {r["question_id"] for r in read_jsonl(out_path)}
    budgets = Budgets()
    harness = item_harness_map(items)
    for item in items:
        if item["question_id"] in done:
            continue
        flags = harness.get(item["question_id"], {})
        ctx = ExecContext(
            model=model, tokenizer=tok,
            registry=FailRegistry(registry, flags.get("fail_tools", False)),
            retriever=FailRetriever(retriever,
                                    flags.get("fail_retrieval", False)),
            generation=dict(GENERATION), budgets=Budgets(),
            features=features,
            trajectory=TrajectoryLogger(trajectories /
                                        f"{arm}_trajectory.jsonl"),
            checkpointer=RunCheckpointer(ckpt_dir / arm),
        )
        res = run_executive(item["question"], item["question_id"], ctx=ctx,
                            answer_type=item["answer_type"],
                            choices=item.get("choices"),
                            expected=item["expected_answer"])
        rec = {
            "question_id": item["question_id"], "arm": arm,
            "raw": res.get("raw") or "",
            "extracted_answer": res.get("final_answer"),
            "expected_answer": item["expected_answer"],
            "answer_type": item["answer_type"],
            "class": item["class"],
            "declined": declined_flag(res),
            "termination_reason": res["termination_reason"],
            "evidence_status": res["evidence_status"],
            "failure_category": res.get("failure_category"),
            "fast_path": res["fast_path"],
            "plan_source": res.get("plan_source"),
            "citations": res.get("citations"),
            "plan_attempts": res["plan_attempts"],
            "first_attempt_plan_valid": res["first_attempt_plan_valid"],
            "retry_plan_valid": res["retry_plan_valid"],
            "plan_fallback_used": res["plan_fallback_used"],
            "steps_executed": res["steps_executed"],
            "replans": res["replans"],
            "latency_s": res["latency_s"],
            "input_tokens": res["input_tokens"],
            "output_tokens": res["output_tokens"],
            "tool_calls": ctx.usage["tool_calls"],
            "retrievals": ctx.usage["retrievals"],
            "model_calls": ctx.usage["model_calls"],
            "error": res.get("error"),
        }
        append_jsonl(out_path, rec)
        # per-question usage is per-question (fresh ExecContext each time)


def item_harness_map(items) -> dict:
    m = {}
    for it in items:
        h = (it.get("harness") or {})
        if h:
            m[it["question_id"]] = h
    return m


# ---- scoring -------------------------------------------------------------------
def declined_flag(res: dict) -> bool:
    """Honest-decline semantics. A run is 'declined' when its committed
    final answer is itself an uncertainty statement, or when it
    terminated with an honest no-answer reason. Harness/system failures
    (SYSTEM_ERROR, BUDGET_EXHAUSTED) and extraction failures on an
    otherwise-solved run are NOT declines — counting them inflates
    uncertainty precision/recall."""
    fa = res.get("final_answer")
    if fa is not None:
        return bool(signals_uncertainty(str(fa)))
    return res.get("termination_reason") in (
        "INSUFFICIENT_INFORMATION", "CONFLICTING_EVIDENCE", "STALLED")


def normalize(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    return s


def is_correct(rec) -> bool:
    exp = rec["expected_answer"]
    got = rec["extracted_answer"]
    if got is None:
        return False
    if normalize(exp) == "insufficient":
        return False  # handled by uncertainty metrics
    from sciencemath.evaluation.extraction import answers_match
    return bool(answers_match(str(exp), str(got)))


def compute_metrics(records: list[dict], arm: str) -> dict:
    n = len(records)
    if not n:
        return {"arm": arm, "n": 0}
    by_class: dict[str, list] = {}
    for r in records:
        by_class.setdefault(r["class"], []).append(r)

    def acc(rs):
        return sum(1 for r in rs if is_correct(r)) / len(rs) if rs else None

    # uncertainty: precision/recall of "declined" on INSUFFICIENT classes
    insuf = [r for r in records
             if normalize(r["expected_answer"]) == "insufficient"]
    non_insuf = [r for r in records
                 if normalize(r["expected_answer"]) != "insufficient"]
    tp = sum(1 for r in insuf if r["declined"])
    fp = sum(1 for r in non_insuf if r["declined"])
    fn = len(insuf) - tp
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None

    # plan validity (T7.23) — over items where a model plan was attempted
    attempted = [r for r in records
                 if r.get("first_attempt_plan_valid") is not None]
    first_ok = [r for r in attempted if r["first_attempt_plan_valid"]]
    retry_scope = [r for r in attempted if not r["first_attempt_plan_valid"]]
    retry_ok = [r for r in retry_scope if r.get("retry_plan_valid")]
    fallback = [r for r in records if r.get("plan_fallback_used")]

    # correction net gain (T7.36) — MEASURED from correction events:
    # corrections that fixed a wrong answer minus corrections that broke
    # a right one. Declared definition, no proxy.
    fixes = breaks = used = 0
    from sciencemath.evaluation.extraction import answers_match
    for r in records:
        if r.get("corrections_used"):
            used += 1
        ev = r.get("correction_event")
        if not ev:
            continue
        exp = str(r["expected_answer"])
        pre_ok = answers_match(exp, str(ev["pre_answer"]))
        post_ok = answers_match(exp, str(ev["post_answer"]))
        if not pre_ok and post_ok:
            fixes += 1
        elif pre_ok and not post_ok:
            breaks += 1

    # correction / overcorrection: measured in the self_correction class
    sc = by_class.get("self_correction", [])
    sc_correct = sum(1 for r in sc if is_correct(r))

    # G8: every cited chunk id that was never supplied (fabricated
    # reference), summed over the arm — counted ONLY for runs where
    # evidence was actually supplied. A harness-injected retrieval
    # failure leaves nothing to cite, and a run with no supplied
    # chunks cannot fabricate evidence-backed citations. Runs that
    # had supplied chunks but no citation audit are reported
    # separately (should be 0 — every such run is audited).
    citations_fabricated = 0
    citations_unaudited = 0
    for r in records:
        if not (r.get("supplied_chunks") or 0):
            continue
        cit = r.get("citations")
        if cit is None:
            citations_unaudited += 1
        else:
            citations_fabricated += len((cit.get("invalid_refs")) or [])

    m = {
        "arm": arm, "n": n,
        "accuracy": acc(records),
        "accuracy_by_class": {k: acc(v) for k, v in sorted(by_class.items())},
        "uncertainty": {
            "precision": precision, "recall": recall,
            "tp": tp, "fp": fp, "fn": fn,
        },
        "plan": {
            "first_attempt_validity": (len(first_ok) / len(attempted))
            if attempted else None,
            "retry_validity": (len(retry_ok) / len(retry_scope))
            if retry_scope else None,
            "fallback_rate": len(fallback) / n,
        },
        "self_correction_accuracy": sc_correct / len(sc) if sc else None,
        "correction": {"used": used, "net_gain": fixes - breaks,
                       "fixes": fixes, "breaks": breaks},
        "verified_solution_rate": sum(
            1 for r in records
            if r.get("termination_reason") == "SOLVED_VERIFIED") / n,
        "avg_plan_attempts": _avg(records, "plan_attempts"),
        "avg_steps": _avg(records, "steps_executed"),
        "avg_replans": _avg(records, "replans"),
        "avg_latency_s": _avg(records, "latency_s"),
        "avg_input_tokens": _avg(records, "input_tokens"),
        "avg_output_tokens": _avg(records, "output_tokens"),
        "total_tool_calls": sum(r.get("tool_calls") or 0 for r in records),
        "total_retrievals": sum(r.get("retrievals") or 0 for r in records),
        "citations_fabricated": citations_fabricated,
        "citations_unaudited": citations_unaudited,
        "stalled_rate": sum(1 for r in records
                            if r.get("termination_reason") == "STALLED") / n,
        "error_rate": sum(1 for r in records
                          if r.get("termination_reason") == "SYSTEM_ERROR")
        / n,
        "fast_path_rate": sum(1 for r in records if r.get("fast_path")) / n,
        "termination_reasons": _counts(records, "termination_reason"),
        "failure_categories": _counts(records, "failure_category"),
        "evidence_statuses": _counts(records, "evidence_status"),
    }
    return m


def _avg(rs, key):
    vals = [r.get(key) or 0 for r in rs]
    return round(sum(vals) / len(rs), 3)


def _counts(rs, key):
    from collections import Counter
    return dict(Counter(str(r.get(key)) for r in rs))


def evaluate_gates(off_m: dict, on_m: dict, gates_cfg: dict) -> dict:
    """Pre-registered gates — thresholds read from configs/executive.yaml
    exactly as declared, OFF vs E_full_executive."""
    results = {}

    def thr(key, field):
        return float(gates_cfg[key][field])

    def delta(metric):
        """accuracy.overall -> m['accuracy']; accuracy.<class> ->
        m['accuracy_by_class'][<class>]; else dotted path."""
        def get(m):
            if metric == "accuracy.overall":
                return m.get("accuracy")
            if metric.startswith("accuracy."):
                return (m.get("accuracy_by_class") or {}).get(
                    metric.split(".", 1)[1])
            cur = m
            for part in metric.split("."):
                cur = (cur or {}).get(part) if isinstance(cur, dict) \
                    else None
            return cur
        o, e = get(off_m), get(on_m)
        if o is None or e is None:
            return None
        return (e - o) * 100.0

    t1 = thr("G1_overall_gain_pp", "on_off_delta_min")
    g1 = delta("accuracy.overall")
    results["G1_overall_gain_pp"] = {
        "measured": g1, "threshold": t1, "pass": g1 is not None and g1 >= t1}
    t2 = thr("G2_distractor_robustness_pp", "on_off_delta_min")
    g2 = delta("accuracy.distractor")
    results["G2_distractor_robustness_pp"] = {
        "measured": g2, "threshold": t2, "pass": g2 is not None and g2 >= t2}
    t3 = thr("G3_uncertainty_precision_min", "min")
    up = on_m.get("uncertainty", {}).get("precision")
    results["G3_uncertainty_precision_min"] = {
        "measured": up, "threshold": t3,
        "pass": up is not None and up >= t3}
    t4 = thr("G4_uncertainty_recall_min", "min")
    ur = on_m.get("uncertainty", {}).get("recall")
    results["G4_uncertainty_recall_min"] = {
        "measured": ur, "threshold": t4,
        "pass": ur is not None and ur >= t4}
    t5 = thr("G5_plan_validity_improvement", "min")
    fv = on_m.get("plan", {}).get("first_attempt_validity")
    results["G5_plan_validity_improvement"] = {
        "measured": fv, "threshold": t5, "baseline": 0.10,
        "pass": fv is not None and fv >= t5}
    # G6 correction net gain — the DECLARED T7.36 definition, measured
    # directly from correction events: corrections that fixed a wrong
    # answer minus corrections that broke a right one. (The old proxy
    # — declines on non-insufficient items — is kept as a diagnostic
    # only; it conflates honest declines with overcorrection.)
    cor = on_m.get("correction") or {}
    net = cor.get("net_gain")
    fp_rate = on_m.get("uncertainty", {}).get("fp") or 0
    results["G6_correction_net_gain"] = {
        "measured": net, "fixes": cor.get("fixes"),
        "breaks": cor.get("breaks"), "corrections_used": cor.get("used"),
        "overcorrection_proxy_fp": fp_rate,
        "threshold": 0.0, "pass": net is not None and net > 0.0}
    t7 = thr("G7_regression_bound_pp", "max_regression")
    simple_off = (off_m.get("accuracy_by_class") or {}).get("simple")
    simple_on = (on_m.get("accuracy_by_class") or {}).get("simple")
    reg = (simple_off - simple_on) * 100 if (simple_off is not None
                                             and simple_on is not None) \
        else None
    results["G7_regression_bound_pp"] = {
        "measured": reg, "threshold": t7,
        "pass": reg is not None and reg <= t7}
    results["G8_t4_t5r_preservation"] = {
        "measured": on_m.get("citations_fabricated", 0),
        "threshold": thr("G8_t4_t5r_preservation", "max"),
        "pass": (on_m.get("citations_fabricated", 0)
                 <= thr("G8_t4_t5r_preservation", "max"))}
    decision = ("PROMOTED" if all(v["pass"] for v in results.values())
                else "NOT PROMOTED")
    return {"gates": results, "decision": decision,
            "note": "thresholds pre-registered in configs/executive.yaml "
                    "before any ON-arm measurement (2026-09-04)"}


# ---- main -----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="evaluations/executive-suite/v1")
    ap.add_argument("--arms", default="A_off,E_full_executive")
    ap.add_argument("--label", default="mango-v0.1")
    ap.add_argument("--ablation-subset", action="store_true",
                    help="run B..G arms on the diagnostic classes only")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load((REPO / "configs" / "executive.yaml").read_text(
        encoding="utf-8"))
    ablations = cfg["ablations"]
    gates_cfg = cfg["gates"]

    suite_dir = REPO / args.suite
    items = read_jsonl(suite_dir / "questions.jsonl")
    if args.ablation_subset:
        items = [it for it in items
                 if it["class"] in ABLATION_CLASSES]
    if args.limit:
        items = items[:args.limit]
    print(f"suite items: {len(items)}")

    model = tok = None
    needs_gpu = any(a != "metrics_only" for a in args.arms.split(","))
    registry = build_default_registry()
    from run_rag_eval_t5r import build_retriever
    retriever = RetrieverAdapter(build_retriever())
    if needs_gpu:
        from sciencemath.training.attach import load_base_with_adapter
        tok, model, info = load_base_with_adapter(MODEL_ID,
                                                  str(PARENT_ADAPTER))
        if not info.get("ok"):
            print("model load failed:", info)
            return 1

    results_dir = RESULTS / args.label
    results_dir.mkdir(parents=True, exist_ok=True)
    trajectories = results_dir / "trajectories"
    ckpt_dir = results_dir / "checkpoints"

    arm_metrics = {}
    for arm in args.arms.split(","):
        out_path = results_dir / f"{arm}_predictions.jsonl"
        if arm == "A_off":
            print(f"[{arm}] running OFF baseline ...", flush=True)
            t0 = time.time()
            run_off_arm(model, tok, items, out_path, registry, retriever)
            print(f"[{arm}] done in {time.time() - t0:.0f}s", flush=True)
        elif arm in ablations:
            feats = dict(ablations[arm])
            print(f"[{arm}] features: {feats}", flush=True)
            t0 = time.time()
            run_exec_arm(model, tok, items, arm, feats, out_path, registry,
                         retriever, trajectories, ckpt_dir)
            print(f"[{arm}] done in {time.time() - t0:.0f}s", flush=True)
        else:
            print(f"[{arm}] unknown arm; known: A_off, "
                  f"{', '.join(ablations)}")
            return 2
        arm_metrics[arm] = compute_metrics(read_jsonl(out_path), arm)
        print(f"[{arm}] accuracy: {arm_metrics[arm].get('accuracy')}",
              flush=True)

    # ---- matched comparison + gates (only when both arms present) ----
    comparison = {"suite": str(suite_dir), "checkpoint": "Mango-v0.1",
                  "date": time.strftime("%Y-%m-%d"),
                  "arms": list(arm_metrics)}
    if "A_off" in arm_metrics and "E_full_executive" in arm_metrics:
        comparison["off"] = arm_metrics["A_off"]
        comparison["on"] = arm_metrics["E_full_executive"]
        # gates only over a COMPLETE matched run: identical question-id
        # sets on both arms, covering the full (untruncated) suite —
        # a partial or mismatched comparison must not produce a
        # pre-registered gate decision
        off_recs = read_jsonl(results_dir / "A_off_predictions.jsonl")
        on_recs = read_jsonl(results_dir / "E_full_executive_predictions.jsonl")
        off_ids = {r["question_id"] for r in off_recs}
        on_ids = {r["question_id"] for r in on_recs}
        complete = (not args.limit and not args.ablation_subset
                    and off_ids == on_ids
                    and len(off_recs) == len(items) == len(on_recs))
        if complete:
            comparison["gate_evaluation"] = evaluate_gates(
                arm_metrics["A_off"], arm_metrics["E_full_executive"],
                gates_cfg)
        else:
            comparison["gate_evaluation"] = {
                "skipped": True,
                "reason": f"incomplete matched run (limit={args.limit}, "
                          f"ablation_subset={args.ablation_subset}, "
                          f"off_ids={len(off_ids)}, on_ids={len(on_ids)}, "
                          f"suite={len(items)})"}
    (results_dir / "metrics.json").write_text(
        json.dumps({"per_arm": arm_metrics, "comparison": comparison},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print("metrics written:", results_dir / "metrics.json")
    if comparison.get("gate_evaluation"):
        print("gate decision:",
              comparison["gate_evaluation"]["decision"])
        (results_dir / "gate_decision.json").write_text(
            json.dumps(comparison["gate_evaluation"], indent=2,
                       ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())