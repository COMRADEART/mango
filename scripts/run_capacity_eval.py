"""T8.5-T8.12 — Capacity benchmark runner (mango-capacity-eval-v1).

MODEL-ONLY FIRST (T8.6): the primary arm runs
    MODEL + standard prompt + final-answer extraction
with the executive scaffolding DISABLED, so model capacity — not T7
orchestration — is what is measured.

Subtests implemented per the T8 pre-registration:
  T8.8  decomposition  — strict plan schema (executive/plan.py validator),
                         RAW_VALID vs REPAIRED_VALID reported apart; malformed
                         JSON is never silently counted as first-attempt success
  T8.9  uncertainty    — insufficient-info precision/recall/F1, false
                         uncertainty, hallucinated-answer rate
  T8.10 distractor     — clean vs distractor-loaded twins, robustness delta
  T8.11 self-correction— objective verifier feedback only (FAIL-only and
                         FAIL-with-computed-result tiers); overcorrection
                         probes get FAIL-only feedback on initially-correct
                         items (sycophancy check)
  T8.12 capability vector — JSON representation per candidate

Usage:
  python scripts/run_capacity_eval.py --model Qwen/Qwen3-1.7B \
      --label qwen3-1.7b-control [--thinking off] [--limit N] [--arm model]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

SUITE = REPO / "evaluations" / "t8" / "capacity-suite" / "v1"
RUNS = REPO / "evaluations" / "t8" / "runs"

# prompt for the capacity study: identical contract to the frozen suites
# (\boxed{} final answer), via the shared prompt builder.


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_suite() -> list[dict]:
    items = [json.loads(l) for l in
             (SUITE / "questions.jsonl").read_text(encoding="utf-8")
             .splitlines() if l.strip()]
    return items


# -- grading ------------------------------------------------------------------
def grade(item: dict, raw: str, extracted: str | None) -> dict:
    from sciencemath.evaluation.extraction import (
        answers_match, extract_answer, signals_uncertainty, strip_think_block)

    uncertain = signals_uncertainty(strip_think_block(raw or ""))
    rec = {"uncertainty_signaled": uncertain}
    if item["insufficient_info"]:
        answered = extracted is not None and not uncertain
        rec["correct"] = uncertain and not answered
        rec["hallucinated"] = answered
        rec["extracted_answer"] = extracted
        return rec
    if extracted is None:
        rec["correct"] = False
        rec["extraction_failure"] = True
        rec["extracted_answer"] = None
        return rec
    rec["extraction_failure"] = False
    rec["extracted_answer"] = extracted
    rec["correct"] = answers_match(item["expected_answer"], extracted)
    return rec


def dimension_of(item: dict) -> str:
    return item["capacity_dimension"]


# -- self-correction feedback (T8.11) -----------------------------------------
_BOXED_TAIL = ("Re-solve the problem carefully step by step, then put the "
               "corrected final answer inside \\boxed{} on the last line.")


def feedback_for(item: dict, tier: str) -> str:
    assert tier in ("FAIL_ONLY", "FAIL_WITH_RESULT")
    base = ("An automated verifier checked your previous answer against the "
            "required result and found it INCORRECT. " + _BOXED_TAIL)
    if tier == "FAIL_WITH_RESULT" and item.get("tool_check"):
        expr = item["tool_check"]["args"]["expression"]
        return ("An automated verifier re-evaluated the required computation "
                f"`{expr}` and obtained the exact result "
                f"`{item['expected_answer']}`. Your previous answer does not "
                "match. " + _BOXED_TAIL)
    return base


# -- decomposition (T8.8) -----------------------------------------------------
JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def repair_json(text: str) -> dict | None:
    """Extract and repair a JSON object. REPAIRED only — never counted as
    first-attempt success."""
    from sciencemath.evaluation.extraction import strip_think_block
    s = strip_think_block(text or "")
    m = JSON_RE.search(s)
    if not m:
        return None
    cand = m.group(0)
    try:
        return json.loads(cand)
    except Exception:  # noqa: BLE001
        pass
    # common repairs: trailing commas, single quotes
    for fix in (re.sub(r",\s*([}\]])", r"\1", cand),
                cand.replace("'", '"')):
        try:
            return json.loads(fix)
        except Exception:  # noqa: BLE001
            continue
    return None


def score_plan(plan: dict | None, item: dict) -> dict:
    from sciencemath.executive.plan import validate_plan

    out = {"json_ok": plan is not None, "schema_valid": False,
           "semantic_ok": False, "executable_ok": False}
    if plan is None:
        return out
    v = validate_plan(plan)
    out["schema_valid"] = v.ok
    if not v.ok:
        return out
    steps = plan["steps"]
    actions = [s["action"] for s in steps]
    need_tool = bool(item.get("requires_math_tool"))
    need_ret = bool(item.get("requires_retrieval"))
    out["semantic_ok"] = ((not need_tool or "MATH_TOOL" in actions)
                          and (not need_ret or "RETRIEVE" in actions)
                          and len(steps) >= 2)
    tool_steps = [s for s in steps if s["action"] == "MATH_TOOL"]
    out["executable_ok"] = all(
        isinstance(s.get("input"), str) and s["input"].strip()
        for s in tool_steps) if tool_steps else True
    return out


PLAN_PROMPT = """{question}

Before answering, produce a plan for this task as JSON that exactly matches this schema:
{schema}

Return ONLY the JSON plan."""

SPONTANEOUS_PLAN_RE = re.compile(r"\{\s*\"steps\"\s*:", re.DOTALL)


# -- generation ---------------------------------------------------------------
# T8.7: matched settings where families allow, but upstream guidance is not
# overridden — the Qwen3 card explicitly warns greedy decoding causes
# endless-repetition degradation, so Qwen3 arms use the card's non-thinking
# sampling settings (fixed seed). Profiles are RECORDED, never tuned after
# seeing final evaluation scores.
SAMPLING_PROFILES = {
    "qwen3": {"profile": "qwen3-card-non-thinking", "do_sample": True,
              "temperature": 0.7, "top_p": 0.8, "top_k": 20},
    "phi4": {"profile": "phi4-card", "do_sample": True,
             "temperature": 0.6, "top_p": 0.9, "top_k": 20},
    "smollm3": {"profile": "smollm3-card", "do_sample": True,
                "temperature": 0.6, "top_p": 0.95, "top_k": 20},
    "default": {"profile": "greedy", "do_sample": False},
}


def sampling_profile_for(model_id: str) -> dict:
    low = model_id.lower()
    for key in ("qwen3", "phi4", "smollm3"):
        if key in low:
            return dict(SAMPLING_PROFILES[key])
    return dict(SAMPLING_PROFILES["default"])


def generate(model, tok, text: str, max_new_tokens: int,
             samp: dict | None = None) -> tuple[str, dict]:
    import torch

    samp = samp or SAMPLING_PROFILES["default"]
    inputs = tok(text, return_tensors="pt").to(model.device)
    t0 = time.time()
    kwargs = {"max_new_tokens": max_new_tokens,
              "pad_token_id": tok.pad_token_id or tok.eos_token_id}
    if samp["do_sample"]:
        kwargs.update(do_sample=True, temperature=samp["temperature"],
                      top_p=samp["top_p"], top_k=samp["top_k"])
    else:
        kwargs["do_sample"] = False
    with torch.no_grad():
        out = model.generate(**inputs, **kwargs)
    dt = time.time() - t0
    n_new = int(out.shape[1] - inputs["input_ids"].shape[1])
    return tok.decode(out[0][inputs["input_ids"].shape[1]:],
                      skip_special_tokens=True), {
        "latency_s": round(dt, 3), "new_tokens": n_new,
        "tokens_per_s": round(n_new / dt, 2) if dt > 0 else None,
    }


def vram_mib() -> dict:
    import torch

    if not torch.cuda.is_available():
        return {}
    return {
        "allocated_mib": round(torch.cuda.memory_allocated() / 2**20, 1),
        "reserved_mib": round(torch.cuda.memory_reserved() / 2**20, 1),
        "peak_allocated_mib": round(
            torch.cuda.max_memory_allocated() / 2**20, 1),
        "peak_reserved_mib": round(
            torch.cuda.max_memory_reserved() / 2**20, 1),
    }


# -- main ---------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--revision", default=None)
    ap.add_argument("--label", required=True)
    ap.add_argument("--arm", default="model", choices=["model"])
    ap.add_argument("--thinking", default="off", choices=["off", "on"])
    ap.add_argument("--max-new-tokens", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--decomp-subset", type=int, default=24)
    ap.add_argument("--correct-subset", type=int, default=12,
                    help="overcorrection probes on initially-correct items")
    ap.add_argument("--compute-dtype", default="bfloat16")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    items = load_suite()
    if args.limit:
        items = items[:args.limit]
    out_dir = Path(args.out) if args.out else RUNS / args.label / args.arm
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------- model load (4-bit NF4, hardware-safe path) ----------
    import torch
    from sciencemath.evaluation.model_loader import load_model_safely

    torch.manual_seed(args.seed)
    tok, model, load_info = load_model_safely(
        args.model, compute_dtype=args.compute_dtype)
    if not load_info.get("ok"):
        print("MODEL LOAD FAILED:", load_info["error"])
        (out_dir / "summary.json").write_text(json.dumps({
            "label": args.label, "model": args.model,
            "revision": args.revision, "arm": args.arm,
            "load": load_info, "ok": False, "recorded_at": now(),
        }, indent=2), encoding="utf-8")
        return 1
    torch.cuda.reset_peak_memory_stats()

    # matched generation settings (T8.7) — recorded, not tuned post hoc
    samp = sampling_profile_for(args.model)
    gen_cfg = {
        **samp,
        "max_new_tokens": args.max_new_tokens, "seed": args.seed,
        "thinking_mode": args.thinking,
        "chat_template": "tokenizer.apply_chat_template(add_generation_prompt)",
        "stop": None,
        "note": "profile selected by model family BEFORE evaluation "
                "(upstream card guidance); fixed seed; never tuned after "
                "seeing final evaluation scores",
    }

    from sciencemath.evaluation.extraction import extract_answer
    from sciencemath.evaluation.prompts import build_evaluation_content, \
        render_for_model

    preds: list[dict] = []
    total_tokens = 0
    total_latency = 0.0

    # ================= main pass =================
    for it in items:
        content = build_evaluation_content(it["question"], it["answer_type"],
                                           it.get("choices"))
        prompt = render_for_model(tok, content,
                                  enable_thinking=(args.thinking == "on"))
        raw, m = generate(model, tok, prompt, args.max_new_tokens, samp)
        extracted = extract_answer(raw, it["answer_type"],
                                   it.get("choices"))
        g = grade(it, raw, extracted)
        total_tokens += m["new_tokens"]
        total_latency += m["latency_s"]
        preds.append({
            "eval_id": it["eval_id"], "dimension": dimension_of(it),
            "category": it["category"],
            "expected": it["expected_answer"], "raw": raw,
            **m, **g,
            "spontaneous_plan": bool(SPONTANEOUS_PLAN_RE.search(raw or "")),
        })
    with open(out_dir / "predictions.jsonl", "w", encoding="utf-8") as f:
        for p in preds:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # ================= metrics =================
    def acc(preds_sub: list[dict]) -> float | None:
        if not preds_sub:
            return None
        return sum(1 for p in preds_sub if p["correct"]) / len(preds_sub)

    dims = Counter(p["dimension"] for p in preds)
    answerable = [p for p in preds if p["dimension"] != "uncertainty"]
    uncertain = [p for p in preds if p["dimension"] == "uncertainty"]

    # T8.9 uncertainty metrics
    tp = sum(1 for p in uncertain if p["uncertainty_signaled"]
             and not p["hallucinated"])
    fn = sum(1 for p in uncertain if not p["uncertainty_signaled"])
    fp = sum(1 for p in answerable if p["uncertainty_signaled"])
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
    halluc = sum(1 for p in uncertain if p["hallucinated"])
    uncertainty_metrics = {
        "insufficient_info_precision": prec, "insufficient_info_recall": rec,
        "insufficient_info_f1": f1, "false_uncertainty_count": fp,
        "false_uncertainty_rate": fp / len(answerable) if answerable else None,
        "hallucinated_answer_rate": halluc / len(uncertain)
        if uncertain else None,
    }

    # T8.10 distractor metrics
    clean = [p for p in preds if p["dimension"] == "distractor_clean"]
    loaded = [p for p in preds if p["dimension"] == "distractor_loaded"]
    a_clean, a_loaded = acc(clean), acc(loaded)
    distractor_metrics = {
        "clean_accuracy": a_clean, "distractor_accuracy": a_loaded,
        "robustness_delta": (a_loaded - a_clean)
        if (a_clean is not None and a_loaded is not None) else None,
        "robustness_ratio": (a_loaded / a_clean)
        if (a_clean and a_loaded is not None) else None,
    }

    math_p = [p for p in preds if p["dimension"] == "math"]
    sci_p = [p for p in preds if p["dimension"] == "science"]
    math_macro = acc(math_p)
    science_macro = acc(sci_p)
    overall = acc(answerable)

    # ================= self-correction pass (T8.11) =================
    wrong = [p for p in answerable if not p["correct"]]
    correct = [p for p in answerable if p["correct"]]
    sc_records: list[dict] = []
    item_by_id = {it["eval_id"]: it for it in items}
    tier_of = {}
    for p in wrong:
        it = item_by_id[p["eval_id"]]
        tier_of[p["eval_id"]] = ("FAIL_WITH_RESULT"
                                 if it.get("tool_check") else "FAIL_ONLY")
    probe_ids = {p["eval_id"] for p in correct[:args.correct_subset]}
    for p in correct[:args.correct_subset]:
        tier_of[p["eval_id"]] = "FAIL_ONLY"   # overcorrection probe

    sc_subset = wrong + correct[:args.correct_subset]
    for p in sc_subset:
        it = item_by_id[p["eval_id"]]
        tier = tier_of[p["eval_id"]]
        content = build_evaluation_content(it["question"], it["answer_type"],
                                           it.get("choices"))
        prev_ans = p.get("extracted_answer") or "(no answer extracted)"
        convo = [
            {"role": "user", "content": content},
            {"role": "assistant", "content": p["raw"]},
            {"role": "user", "content": feedback_for(it, tier)
             + f"\n\nYour previous answer was: {prev_ans}"},
        ]
        try:
            prompt = tok.apply_chat_template(
                convo, tokenize=False, add_generation_prompt=True,
                enable_thinking=(args.thinking == "on"))
        except Exception:
            prompt = tok.apply_chat_template(convo, tokenize=False,
                                             add_generation_prompt=True)
        raw2, m = generate(model, tok, prompt, args.max_new_tokens, samp)
        ex2 = extract_answer(raw2, it["answer_type"], it.get("choices"))
        g2 = grade(it, raw2, ex2)
        sc_records.append({
            "eval_id": p["eval_id"], "tier": tier,
            "initially_correct": p["correct"], "initial": p["extracted_answer"],
            "revised": ex2, "revised_correct": g2["correct"],
            "changed": (ex2 or "") != (p["extracted_answer"] or ""),
        })
    corrected = sum(1 for r in sc_records if not r["initially_correct"]
                    and r["revised_correct"])
    preserved = sum(1 for r in sc_records if r["initially_correct"]
                    and r["revised_correct"])
    over = sum(1 for r in sc_records if r["initially_correct"]
               and not r["revised_correct"])
    still_wrong = sum(1 for r in sc_records if not r["initially_correct"]
                      and not r["revised_correct"])
    n_wrong = max(1, len(wrong[:len(wrong)]))
    self_correction = {
        "corrected_wrong": corrected, "still_wrong": still_wrong,
        "preserved_correct": preserved, "overcorrections": over,
        "n_wrong_probed": len([r for r in sc_records
                               if not r["initially_correct"]]),
        "n_correct_probed": len([r for r in sc_records
                                 if r["initially_correct"]]),
        "net_benefit": (corrected - over) / n_wrong,
    }
    with open(out_dir / "self_correction.jsonl", "w", encoding="utf-8") as f:
        for r in sc_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ================= decomposition pass (T8.8) =================
    from sciencemath.executive.plan import PLAN_SCHEMA_DOC
    decomp_items = items[:args.decomp_subset]
    plan_records = []
    for it in decomp_items:
        prompt = render_for_model(
            tok, PLAN_PROMPT.format(question=it["question"],
                                    schema=PLAN_SCHEMA_DOC),
            enable_thinking=(args.thinking == "on"))
        raw, m = generate(model, tok, prompt, args.max_new_tokens, samp)
        plan_raw = repair_json(raw)          # extraction is itself a repair
        # first-attempt validity: the RAW text must be a bare JSON object
        try:
            direct = json.loads((raw or "").strip())
            raw_valid = score_plan(direct if isinstance(direct, dict) else None,
                                   it)
            raw_valid_raw = raw_valid["schema_valid"]
        except Exception:  # noqa: BLE001
            raw_valid_raw = False
        rep = score_plan(plan_raw, it)
        plan_records.append({
            "eval_id": it["eval_id"], "dimension": dimension_of(it),
            "raw_valid": raw_valid_raw, "repaired_valid": rep["schema_valid"],
            "semantic_ok": rep["semantic_ok"],
            "executable_ok": rep["executable_ok"],
            "raw_extract": (raw or "")[:400],
        })
    n = max(1, len(plan_records))
    decomposition = {
        "subset": len(plan_records),
        "raw_valid_rate": sum(1 for r in plan_records
                              if r["raw_valid"]) / n,
        "repaired_valid_rate": sum(1 for r in plan_records
                                   if r["repaired_valid"]) / n,
        "semantic_valid_rate": sum(1 for r in plan_records
                                   if r["semantic_ok"]) / n,
        "executable_rate": sum(1 for r in plan_records
                               if r["executable_ok"]) / n,
        "unnecessary_plan_rate": (sum(1 for p in preds
                                      if p["spontaneous_plan"])
                                  / max(1, len(preds))),
    }
    with open(out_dir / "plans.jsonl", "w", encoding="utf-8") as f:
        for r in plan_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ================= capability vector (T8.12) =================
    cf = [p for p in preds if p["dimension"] == "counterfactual"]
    comp = [p for p in preds if p["dimension"] == "compositional"]
    xd = [p for p in preds if p["dimension"] == "cross_domain"]
    extraction_ok = sum(1 for p in answerable if not p.get("extraction_failure"))
    tool_routing = decomposition["semantic_valid_rate"]
    capability_vector = {
        "overall": overall,
        "math_macro": math_macro,
        "science_macro": science_macro,
        "cross_domain": acc(xd),
        "compositional": acc(comp),
        "counterfactual": acc(cf),
        "distractor": distractor_metrics["distractor_accuracy"],
        "uncertainty": uncertainty_metrics["insufficient_info_f1"],
        "decomposition": decomposition["repaired_valid_rate"],
        "self_correction": self_correction["net_benefit"],
        "tool_routing": tool_routing,
        "retrieval_routing": None,   # filled by RAG arm / plans w/ RETRIEVE
        "extraction": extraction_ok / max(1, len(answerable)),
    }

    # ================= hardware record (T8.27) =================
    try:
        import psutil
        ram = {"ram_total_gb": round(psutil.virtual_memory().total / 2**30, 2),
               "ram_used_gb": round(psutil.virtual_memory().used / 2**30, 2)}
    except Exception:  # noqa: BLE001
        ram = {}
    disk_gb = None
    try:
        from huggingface_hub import snapshot_download
        import os
        d = snapshot_download(args.model, revision=args.revision,
                              allow_patterns=["*.safetensors", "*.json",
                                              "*.txt"])
        disk_gb = round(sum(
            os.path.getsize(os.path.join(r, f)) for r, _, fs in
            os.walk(d) for f in fs) / 2**30, 2)
    except Exception:  # noqa: BLE001
        pass
    hardware = {
        "load": {k: v for k, v in load_info.items() if k != "error"},
        "vram_after_run": vram_mib(),
        "ram": ram,
        "disk_size_gb": disk_gb,
        "total_gen_tokens": total_tokens,
        "total_gen_latency_s": round(total_latency, 1),
        "mean_tokens_per_s": round(total_tokens / total_latency, 2)
        if total_latency else None,
        "quantization": "4bit-nf4-double-quant",
        "cpu_offload": "none (device_map=auto, all layers on GPU unless OOM)",
    }

    summary = {
        "label": args.label, "model": args.model,
        "revision": args.revision, "arm": args.arm,
        "suite": str(SUITE), "suite_version": "mango-capacity-eval-v1",
        "recorded_at": now(), "ok": True,
        "generation": gen_cfg,
        "n_questions": len(items),
        "capability_vector": capability_vector,
        "metrics": {
            "overall": overall, "math_macro": math_macro,
            "science_macro": science_macro,
            "counterfactual": acc(cf), "compositional": acc(comp),
            "cross_domain": acc(xd),
            "uncertainty": uncertainty_metrics,
            "distractor": distractor_metrics,
            "decomposition": decomposition,
            "self_correction": self_correction,
            "spontaneous_plan_rate": decomposition["unnecessary_plan_rate"],
        },
        "hardware": hardware,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "capability_vector.json").write_text(
        json.dumps({"label": args.label, "model": args.model,
                    "arm": args.arm, **capability_vector}, indent=2),
        encoding="utf-8")
    print(json.dumps({"capability_vector": capability_vector,
                      "hardware": hardware}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())