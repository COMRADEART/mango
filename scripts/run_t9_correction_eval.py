"""Run identical mango-correction-eval-v1 inputs on a raw or firewall arm."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SUITE = ROOT / "evaluations/t9/correction-suite/v1/questions.jsonl"


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--firewall", action="store_true")
    ap.add_argument("--arm", choices=["raw", "firewall", "t10"], default=None,
                    help="overrides --firewall when set (T10 regression arm)")
    ap.add_argument("--max-new-tokens", type=int, default=160)
    args = ap.parse_args()
    from sciencemath.evaluation.correction_metrics import correction_metrics, wilson_interval
    from sciencemath.evaluation.extraction import answers_match, extract_answer
    from sciencemath.evaluation.model_loader import load_model_safely
    from sciencemath.executive.correction import correction_firewall

    items = [json.loads(line) for line in SUITE.read_text().splitlines() if line]
    tok, model, load = load_model_safely(args.model)
    if not load["ok"]:
        raise SystemExit(load["error"])
    if args.adapter:
        from peft import PeftModel
        adapter_path = Path(args.adapter)
        if not adapter_path.is_absolute():
            adapter_path = ROOT / adapter_path
        model = PeftModel.from_pretrained(model, str(adapter_path)).eval()
    rows = []
    if args.arm == "t10":
        from sciencemath.executive.repair import t10_repair_trajectory
    for item in items:
        initial_correct = answers_match(item["expected_answer"], item["initial_answer"])
        expected = item["expected_answer"]
        latency = 0.0
        method = "NO_REPAIR"
        if args.arm == "t10":
            feedback_status = ("PASS" if item["case_class"] == "FALSE_FAIL" else
                               "UNKNOWN" if item["case_class"] == "AMBIGUOUS" else "FAIL")

            def repair(prompt: str) -> str:
                nonlocal latency
                raw, dt = generate(model, tok,
                                   [{"role": "user", "content": prompt}],
                                   args.max_new_tokens)
                latency += dt
                return extract_answer(raw, "short_answer") or raw.strip()

            traj = t10_repair_trajectory(
                question=item["question"], initial_answer=item["initial_answer"],
                expected_type="short_answer",
                feedback_source=item["feedback_source"],
                failed_component=item["failed_component"],
                evidence="independent frozen-suite verification",
                feedback_status=feedback_status,
                original_correct=initial_correct, repair=repair,
                expected=expected)
            final = traj["final_answer"]
            trust, decision = traj["feedback_trust"], traj["correction_decision"]
            method = traj["repair_method"]
        elif args.firewall:
            feedback_status = ("PASS" if item["case_class"] == "FALSE_FAIL" else
                               "UNKNOWN" if item["case_class"] == "AMBIGUOUS" else "FAIL")
            def repair(prompt: str) -> str:
                nonlocal latency
                raw, dt = generate(model, tok, [{"role": "user", "content": prompt}],
                                   args.max_new_tokens)
                latency += dt
                return extract_answer(raw, "short_answer") or raw.strip()
            state = correction_firewall(
                initial_answer=item["initial_answer"], feedback_type="CLAIM_ERROR",
                feedback_source=item["feedback_source"],
                repair_scope=item["failed_component"], question=item["question"],
                validation={"original_status": "PASS" if initial_correct else "FAIL",
                            "feedback_status": feedback_status, "expected": expected,
                            "evidence": "independent frozen-suite verification"},
                repair=repair, reverify=lambda ans: "PASS" if answers_match(expected, ans) else "FAIL")
            final = state.revised_answer or item["initial_answer"]
            trust, decision = state.feedback_trust, state.correction_decision
        else:
            messages = [{"role": "user", "content": item["question"]},
                        {"role": "assistant", "content": item["initial_answer"]},
                        {"role": "user", "content": item["feedback"] +
                         " Reconsider the answer. End with only the corrected final "
                         "answer inside \\boxed{} on the last line."}]
            raw, latency = generate(model, tok, messages, args.max_new_tokens)
            final = extract_answer(raw, "short_answer") or raw.strip()
            trust, decision = "UNVERIFIED", "RAW_MODEL_RESPONSE"
        final_correct = answers_match(expected, final)
        rows.append({**item, "initial_correct": initial_correct,
                     "final_answer": final, "final_correct": final_correct,
                     "changed": final.strip() != item["initial_answer"].strip(),
                     "feedback_trust": trust, "correction_decision": decision,
                     "repair_method": method,
                     "latency_s": round(latency, 3)})
    metrics = correction_metrics(rows)
    n_true = metrics["counts"]["corrected_wrong"] + metrics["counts"]["still_wrong"]
    n_false = metrics["counts"]["preserved_correct"] + metrics["counts"]["destroyed_correct"]
    metrics["confidence_intervals_95"] = {
        "true_correction": wilson_interval(metrics["counts"]["corrected_wrong"], n_true),
        "preservation": wilson_interval(metrics["counts"]["preserved_correct"], n_false)}
    out = ROOT / "evaluations/t9/runs" / args.label
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    summary = {"label": args.label, "model": args.model, "adapter": args.adapter,
               "firewall": args.firewall, "suite": "mango-correction-eval-v1",
               "questions": len(rows), "load": load, "metrics": metrics}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
