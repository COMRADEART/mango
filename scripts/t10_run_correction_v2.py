"""Run mango-correction-eval-v2 on a correction arm.

Arms:
  raw            Qwen3-4B without the firewall (v1-style reconsideration)
  t9             T9 stabilized path: correction_firewall, single repair
  t10            T10 improved repair path (structured context, deterministic
                 patch, bounded two-attempt escalation)

Writes evaluations/t10/runs/<label>/{predictions.jsonl,summary.json}.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SUITE = ROOT / "evaluations/t10/correction-suite/v2/questions.jsonl"


def generate(model, tok, messages: list[dict], max_new_tokens: int) -> tuple[str, float]:
    import torch
    prompt = tok.apply_chat_template(messages, tokenize=False,
                                     add_generation_prompt=True,
                                     enable_thinking=False)
    inputs = tok(prompt, return_tensors="pt").to(model.device)
    start = time.time()
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens,
                             do_sample=False,
                             pad_token_id=tok.pad_token_id or tok.eos_token_id)
    return tok.decode(out[0][inputs["input_ids"].shape[1]:],
                      skip_special_tokens=True), time.time() - start


def extract_repair(raw: str, expect_parts: bool) -> str:
    """Pull the repaired answer out of a repair generation.

    Multi-part answers keep the labeled '(a) ... (b) ...' segment; other
    answers use the standard short-answer extraction.
    """
    if expect_parts and re.search(r"\([a-c]\)", raw or ""):
        m = re.search(r"\([a-c]\).*$", raw, re.DOTALL)
        if m:
            text = re.sub(r"\s+", " ", m.group(0)).strip()
            return text[:400]
    from sciencemath.evaluation.extraction import extract_answer
    return extract_answer(raw, "short_answer") or (raw or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--arm", choices=["raw", "t9", "t10"], required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--split", choices=["dev", "final", "all"], default="all")
    ap.add_argument("--max-new-tokens", type=int, default=320)
    ap.add_argument("--limit", type=int, default=0,
                    help="smoke-test only: first N items of the split")
    args = ap.parse_args()

    from sciencemath.evaluation.correction_metrics import correction_metrics_v2, wilson_interval
    from sciencemath.evaluation.extraction import answers_match
    from sciencemath.evaluation.model_loader import load_model_safely
    from sciencemath.executive.correction import correction_firewall

    items = [json.loads(line) for line in
             SUITE.read_text(encoding="utf-8").splitlines() if line]
    if args.split != "all":
        items = [it for it in items if it["split"] == args.split]
    if args.limit:
        items = items[:args.limit]

    tok, model, load = load_model_safely(args.model)
    if not load["ok"]:
        raise SystemExit(load["error"])
    if args.adapter:
        from peft import PeftModel
        adapter_path = Path(args.adapter)
        if not adapter_path.is_absolute():
            adapter_path = ROOT / adapter_path
        model = PeftModel.from_pretrained(model, str(adapter_path)).eval()

    if args.arm == "t10":
        from sciencemath.executive.repair import t10_repair_trajectory

    rows = []
    for item in items:
        expected = item["expected_answer"]
        initial = item["initial_answer"]
        case_class = item["case_class"]
        expect_parts = case_class == "PARTIAL_FAIL"
        initial_correct = answers_match(expected, initial)
        latency = 0.0
        attempts = 0
        method = "NO_REPAIR"
        row_extra = {}

        def repair(prompt: str) -> str:
            nonlocal latency, attempts
            attempts += 1
            raw, dt = generate(model, tok,
                               [{"role": "user", "content": prompt}],
                               args.max_new_tokens)
            latency += dt
            return extract_repair(raw, expect_parts)

        def repair_value(prompt: str) -> str:
            """T10 part-scoped contract: extract just the repaired value."""
            nonlocal latency, attempts
            attempts += 1
            raw, dt = generate(model, tok,
                               [{"role": "user", "content": prompt}],
                               args.max_new_tokens)
            latency += dt
            from sciencemath.evaluation.extraction import extract_answer
            return extract_answer(raw, "short_answer") or (raw or "").strip()

        if args.arm == "raw":
            feedback = item["feedback"] + (
                " Reconsider the answer. End with only the corrected final "
                "answer inside \\boxed{} on the last line.")
            messages = [{"role": "user", "content": item["question"]},
                        {"role": "assistant", "content": initial},
                        {"role": "user", "content": feedback}]
            raw, dt = generate(model, tok, messages, args.max_new_tokens)
            latency = dt
            final = extract_repair(raw, expect_parts)
            trust, decision = "UNVERIFIED", "RAW_MODEL_RESPONSE"
        elif args.arm == "t9":
            state = correction_firewall(
                initial_answer=initial,
                feedback_type="CITATION_ERROR"
                if item["failed_component"] == "citation" else "CLAIM_ERROR",
                feedback_source=item["feedback_source"],
                repair_scope=item["failed_component"], question=item["question"],
                validation={"original_status":
                            "PASS" if initial_correct else "FAIL",
                            "feedback_status": item["feedback_status"],
                            "expected": expected,
                            "evidence": item["evidence"]},
                repair=repair,
                reverify=lambda ans: "PASS"
                if answers_match(expected, ans) else "FAIL")
            final = state.revised_answer or initial
            trust, decision = state.feedback_trust, state.correction_decision
            if decision == "DEFER":
                method = "DEFER"
            elif decision == "REJECT":
                method = "REJECT" if attempts else "NO_REPAIR"
            elif decision == "ACCEPT":
                method = ("CITATION_PATCH"
                          if item["failed_component"] == "citation"
                          else "LLM_REPAIR_1")
        else:
            failed_part = item.get("failed_part")
            traj = t10_repair_trajectory(
                question=item["question"], initial_answer=initial,
                expected_type=item["required_output_type"],
                feedback_source=item["feedback_source"],
                failed_component=item["failed_component"],
                evidence=item["evidence"],
                feedback_status=item["feedback_status"],
                original_correct=initial_correct, repair=repair_value,
                expected=expected,
                protected=item.get("protected") or None,
                failed_part=failed_part if isinstance(failed_part, str)
                else None)
            final = traj["final_answer"]
            trust = traj["feedback_trust"]
            decision = traj["correction_decision"]
            method = traj["repair_method"]
            attempts = traj["repair_attempts"]
            row_extra = {"protected_preserved":
                         traj.get("protected_preserved"),
                         "collateral_parts": traj.get("collateral_parts"),
                         "escalation_used": traj.get("escalation_used"),
                         "repair_evidence_strength":
                             traj.get("repair_evidence_strength")}

        final_correct = answers_match(expected, final)
        rows.append({
            **item, "initial_correct": initial_correct,
            "final_answer": final, "final_correct": final_correct,
            "changed": final.strip() != initial.strip(),
            "feedback_trust": trust, "correction_decision": decision,
            "repair_method": method, "repair_attempts": attempts,
            "repair_evidence_strength": item["evidence"][:120],
            "latency_s": round(latency, 3), **row_extra,
        })

    metrics = correction_metrics_v2(rows)
    n_true = metrics["counts"]["corrected_wrong"] + metrics["counts"]["still_wrong"]
    n_false = metrics["counts"]["preserved_correct"] + metrics["counts"]["destroyed_correct"]
    metrics["confidence_intervals_95"] = {
        "true_correction": wilson_interval(metrics["counts"]["corrected_wrong"], n_true),
        "preservation": wilson_interval(metrics["counts"]["preserved_correct"], n_false),
        "partial_repair": wilson_interval(metrics["counts_v2"]["partial_repaired"],
                                          len([r for r in rows
                                               if r["case_class"] == "PARTIAL_FAIL"])),
    }
    out = ROOT / "evaluations/t10/runs" / args.label
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    summary = {"label": args.label, "model": args.model, "adapter": args.adapter,
               "arm": args.arm, "split": args.split,
               "suite": "mango-correction-eval-v2", "questions": len(rows),
               "load": load, "metrics": metrics}
    (out / "summary.json").write_text(json.dumps(summary, indent=2,
                                                 ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    print(json.dumps(summary["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())