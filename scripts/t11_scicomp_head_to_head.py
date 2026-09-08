"""T11.20 head-to-head evaluation: arm A (no scicomp) vs arm B (scicomp).

Arm A (control): the base system answers the question directly.
Arm B (treatment): the executive may emit ONE structured compute request
    (JSON, operation from the frozen registry, NO code — T11.33); the
    request is prevalidated and executed by the deterministic engine;
    the observation is returned to the model for the final answer.

Suite: frozen mango-scicomp-eval-v1 (checksum verified before run).
Grading: per manifest.json — numeric oracles with per-item tolerances
(T11.21/T11.22), conceptual no-compute discipline, adversarial
non-PASS/abstain handling (T11.23), and the four-layer decomposition
(T11.24): router precision/recall, compute success, numerical validity,
model adoption.

Greedy decoding throughout; deterministic given the frozen weights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SUITE_DIR = ROOT / "evaluations/t11/scicomp-suite/v1"
QUESTIONS = SUITE_DIR / "questions.jsonl"
CHECKSUM = SUITE_DIR / "checksum.txt"
MANIFEST = SUITE_DIR / "manifest.json"

FINAL_RE = re.compile(r"FINAL ANSWER:\s*(.+)", re.I)
FRACTION_RE = re.compile(
    r"(?<![\d.])(-?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?![\d.])")
NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

# Required input fields per approved operation (prompt-facing contract,
# mirrored from the handlers in src/sciencemath/scicomp/*).
INPUT_SCHEMA: dict[str, str] = {
    "solve_linear_system": "matrix (n x n nested list), b (list)",
    "matrix_multiply": "a (nested list), b (nested list)",
    "determinant": "matrix (nested list)",
    "matrix_inverse": "matrix (nested list)",
    "eigen_decompose": "matrix (nested list)",
    "vector_or_matrix_norm": "vector (list) or matrix, norm (\"l1\"|\"l2\"|\"linf\"|\"frobenius\")",
    "matrix_rank": "matrix (nested list)",
    "least_squares": "matrix (nested list), b (list)",
    "definite_integral": "expression (string), lower (number), upper (number)",
    "cumulative_integral": "expression (string), x (list), y (list)",
    "numerical_derivative": "expression (string), at (number), order (1|2, optional)",
    "bracketed_root": "expression (string), bracket_low (number), bracket_high (number)",
    "scalar_root": "expression (string), initial_guess (number)",
    "system_root": "expressions (list of strings), initial_guess (list)",
    "solve_ode": "equations (list of strings in t, y0, y1, ... + parameters), initial_state (list), t_start (number), t_end (number), parameters (object, optional)",
    "minimize_scalar": "expression (string), bound_low (number), bound_high (number)",
    "minimize": "expression (string in x0, x1, ...), bounds (list of [low, high] pairs)",
    "describe": "values (list of numbers)",
    "confidence_interval_mean": "values (list), confidence (number, optional), method (\"t\"|\"normal\", optional)",
    "correlation": "x (list), y (list), method (\"pearson\"|\"spearman\", optional)",
    "linear_regression": "x (list), y (list)",
    "hypothesis_test": "test (\"ttest_1samp\"|\"ttest_ind\"), values (list), values2 (list for two-sample), null_value (number), equal_var (true|false, REQUIRED for ttest_ind)",
    "distribution_value": "distribution (\"normal\"|\"exponential\"|\"uniform\"|\"poisson\"|\"binomial\"), parameters (object), at (number), quantity (\"pdf\"|\"cdf\"|\"ppf\", optional)",
    "linear_interpolate": "x (list), y (list), at (number)",
    "polynomial_interpolate": "x (list), y (list), at (number)",
    "curve_fit": "model (string in x, p0, p1, ...), x (list), y (list), parameters (list of names)",
    "parameter_sweep": "expression (string), sweeps (object: name -> list of values), x (list, optional)",
}

ARM_A_SYSTEM = (
    "You are a careful scientific computing assistant. Solve the problem "
    "step by step. If the question asks for a number, vector, or matrix, "
    "end your reply with a line 'FINAL ANSWER: <value>' where <value> is "
    "just the numeric value (vectors in [a, b, ...] form). If it is a "
    "conceptual question, answer in words and do not add a FINAL ANSWER "
    "line."
)


def build_b1_system(manifest_lines: list[str]) -> str:
    return (
        "You are the compute-request planner of a scientific computing "
        "system. You may request ONE deterministic computation from an "
        "approved operation registry. The registry:\n"
        + "\n".join(manifest_lines)
        + "\n\nReply with ONLY one JSON object, no other text:\n"
        '{"operation": "<name from the registry>", "inputs": { ... }}\n'
        "or, if no listed operation would help answer the question:\n"
        '{"operation": "NO_COMPUTE"}\n\n'
        "Rules: never write code; inputs are plain numbers, arrays of "
        "numbers, expressions in standard math notation (e.g. 'x**2', "
        "'-k*y0'), or strings only where the schema says so. Expressions "
        "may use the variables implied by the question (x, t, y0, and "
        "named parameters)."
    )


B2_SYSTEM = (
    "You are a careful scientific computing assistant. A deterministic "
    "computation was executed and its observation is given. Use it: if "
    "the observation reports a computed result, base your answer on it; "
    "if it reports a failure, warning, or unknown status, do NOT invent "
    "or guess a number — state that the computation could not be "
    "completed. If the question asks for a number, vector, or matrix, "
    "end with a line 'FINAL ANSWER: <value>' (vectors in [a, b, ...] "
    "form). If the computation failed, do not add a FINAL ANSWER number; "
    "explain instead. Conceptual questions are answered in words."
)


def verify_suite() -> list[dict]:
    digest = hashlib.sha256(QUESTIONS.read_bytes()).hexdigest()
    expected = CHECKSUM.read_text(encoding="utf-8").strip()
    if digest != expected:
        raise SystemExit(
            f"suite checksum mismatch: {digest} != {expected} — refusing "
            "to evaluate against an unfrozen suite")
    return [json.loads(line) for line in
            QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]


def chat(tok, model, system: str, user: str, max_new_tokens: int) -> tuple[str, float]:
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    text = tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=False)
    import torch
    inputs = tok([text], return_tensors="pt").to(model.device)
    start = time.perf_counter()
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False,
            temperature=None, top_p=None, top_k=None,
            pad_token_id=tok.eos_token_id)
    latency = (time.perf_counter() - start) * 1000.0
    raw = tok.decode(out[0][inputs["input_ids"].shape[1]:],
                     skip_special_tokens=True)
    return raw, latency


def extract_final(raw: str) -> str | None:
    from sciencemath.evaluation.extraction import strip_think_block
    text = strip_think_block(raw)
    matches = FINAL_RE.findall(text)
    if matches:
        return matches[-1].strip().rstrip(".")
    return None


def numbers_in(text: str | None) -> list[float]:
    if not text:
        return []
    # resolve simple fractions (7/5 -> 1.4) before scanning for numbers
    text = FRACTION_RE.sub(
        lambda m: repr(float(m.group(1)) / float(m.group(2))), text)
    out = []
    for m in NUM_RE.finditer(text):
        try:
            out.append(float(m.group(0)))
        except ValueError:  # pragma: no cover
            continue
    return out


def flatten_expected(expected) -> list[float]:
    if expected is None:
        return []
    if isinstance(expected, (int, float)):
        return [float(expected)]
    flat = []

    def _walk(v):
        if isinstance(v, (int, float)):
            flat.append(float(v))
        elif isinstance(v, (list, tuple)):
            for e in v:
                _walk(e)
    _walk(expected)
    return flat


def numeric_correct(extracted: str | None, expected, atol: float,
                    rtol: float) -> bool | None:
    got = numbers_in(extracted)
    want = flatten_expected(expected)
    if not want:
        return None
    if extracted is None or len(got) < len(want):
        return False
    return all(abs(g - w) <= atol + rtol * abs(w) for g, w in zip(got, want))


def parse_request(raw: str) -> dict | None:
    """Extract the single JSON object from the planner reply."""
    from sciencemath.evaluation.extraction import strip_think_block
    text = strip_think_block(raw).strip()
    # direct parse, then first {...} block
    for candidate in [text] + re.findall(r"\{.*\}", text, re.S):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def grade_arm(items: list[dict], rows: list[dict]) -> dict:
    """Compute summary metrics for one arm's prediction rows."""
    from collections import Counter

    from sciencemath.scicomp.router import route, route_metrics
    numeric = [r for r in rows if r["kind"] == "numeric_oracle"]
    conceptual = [r for r in rows if r["kind"] == "conceptual"]
    adversarial = [r for r in rows if r["kind"] == "adversarial"]
    mixed = [r for r in rows if r["category"] == "MIXED_RAG_COMPUTE"]

    numeric_ok = [r for r in numeric + mixed if r.get("numeric_correct")]
    conceptual_ok = [r for r in conceptual if r.get("conceptual_correct")]
    adv_ok = [r for r in adversarial if r.get("adversarial_correct")]
    adv_false_answer = [r for r in adversarial
                        if r.get("asserted_number_on_failure")]

    decisions = [(route(r["question"])["route"], r["gold_route"])
                 for r in rows]
    router = route_metrics(decisions)

    invocations = [r for r in rows if r.get("invoked")]
    passes = [r for r in invocations if r.get("envelope_status") == "PASS"]
    valid_calls = [r for r in invocations if r.get("request_valid")]
    adopted = [r for r in passes if r.get("adopted")]

    by_cat: dict[str, dict] = {}
    for r in rows:
        c = by_cat.setdefault(r["category"],
                              {"total": 0, "correct": 0})
        c["total"] += 1
        graded = (r.get("numeric_correct") if r["kind"] == "numeric_oracle"
                  or r["category"] == "MIXED_RAG_COMPUTE"
                  else r.get("adversarial_correct")
                  if r["kind"] == "adversarial"
                  else r.get("conceptual_correct"))
        if graded:
            c["correct"] += 1

    lat = [r["total_llm_ms"] for r in rows if r.get("total_llm_ms")]
    comp_lat = [r["compute_latency_ms"] for r in invocations
                if r.get("compute_latency_ms") is not None]
    return {
        "questions": len(rows),
        "numeric_accuracy": len(numeric_ok) / max(1, len(numeric + mixed)),
        "conceptual_discipline": len(conceptual_ok) / max(1, len(conceptual)),
        "adversarial_handled_correctly": len(adv_ok) / max(1, len(adversarial)),
        "adversarial_false_answer_rate": len(adv_false_answer) / max(1, len(adversarial)),
        "router": router,
        "invocations": len(invocations),
        "compute_success_rate": len(passes) / max(1, len(invocations)),
        "valid_call_rate": len(valid_calls) / max(1, len(invocations)),
        "model_adoption_rate": len(adopted) / max(1, len(passes)),
        "per_category": by_cat,
        "envelope_status_histogram": dict(Counter(
            r.get("envelope_status") or "NO_INVOCATION" for r in rows)),
        "median_llm_ms": sorted(lat)[len(lat) // 2] if lat else None,
        "median_compute_ms": sorted(comp_lat)[len(comp_lat) // 2]
        if comp_lat else None,
    }


def run_arm(arm: str, items: list[dict], out_dir: Path, model: str,
            max_new: int, limit: int | None) -> dict:
    from sciencemath.evaluation.model_loader import load_model_safely
    tok, mdl, load = load_model_safely(model)
    if not load["ok"]:
        raise SystemExit(load["error"])

    if arm == "B":
        from sciencemath.scicomp.registry import build_registry, manifest
        manifest_lines = [
            f"- {m['name']} [{m['category']}]: {m['description']} "
            f"| required inputs: {INPUT_SCHEMA.get(m['name'], 'per schema')}"
            for m in manifest(build_registry())]
        b1_system = build_b1_system(manifest_lines)
        from sciencemath.scicomp.invocation import invoke, observation_text
        from sciencemath.scicomp.schemas import STATUS_PASS

    if limit:
        items = items[:limit]

    rows = []
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "predictions.jsonl"
    with open(pred_path, "w", encoding="utf-8", newline="\n") as pf:
        for it in items:
            row = {
                "eval_id": it["eval_id"],
                "category": it["category"],
                "kind": ("adversarial"
                         if it["answer_type"] == "abstain"
                         else "numeric_oracle"
                         if it["needs_compute"]
                         and it["category"] not in ("MIXED_RAG_COMPUTE",)
                         else "conceptual"
                         if not it["needs_compute"]
                         else "mixed"),
                "question": it["question"],
                "gold_route": (it["category"]
                               if it["needs_compute"]
                               and it["category"] != "MIXED_RAG_COMPUTE"
                               else "NO_COMPUTE"),
                "arm": arm,
            }
            llm_ms = 0.0
            invoked = False
            envelope_status = None
            request_valid = None
            adopted = None
            compute_latency = None
            request = None
            observation = None

            if arm == "A":
                raw, ms = chat(tok, mdl, ARM_A_SYSTEM, it["question"], max_new)
                llm_ms += ms
                final = extract_final(raw)
            else:
                raw1, ms1 = chat(tok, mdl, b1_system, it["question"], 300)
                llm_ms += ms1
                request = parse_request(raw1)
                op = (request or {}).get("operation")
                request_valid = isinstance(request, dict) and (
                    op == "NO_COMPUTE" or isinstance(op, str))
                if request_valid and op != "NO_COMPUTE":
                    invoked = True
                    result = invoke(request, question=it["question"])
                    envelope = result.envelope
                    envelope_status = envelope.get("status")
                    compute_latency = result.latency_ms
                    observation = observation_text(result)
                    adopted_raw, ms2 = chat(
                        tok, mdl, B2_SYSTEM,
                        it["question"] + "\n\nCOMPUTE OBSERVATION: "
                        + observation, max_new)
                    llm_ms += ms2
                    final = extract_final(adopted_raw)
                    raw = adopted_raw
                    if envelope_status == STATUS_PASS:
                        computed_nums = numbers_in(
                            json.dumps(envelope.get("result")))
                        ans_nums = numbers_in(final)
                        adopted = bool(computed_nums) and any(
                            abs(a - c) <= 1e-6 * max(1.0, abs(c))
                            for a in ans_nums for c in computed_nums)
                else:
                    # planner said no compute needed -> answer directly
                    raw2, ms2 = chat(tok, mdl, ARM_A_SYSTEM,
                                     it["question"], max_new)
                    llm_ms += ms2
                    final = extract_final(raw2)
                    raw = raw2

            # ---- grading (deterministic, oracle-based) ----
            kind = row["kind"]
            ok_numeric = None
            ok_conceptual = None
            ok_adversarial = None
            asserted_number = final is not None and bool(numbers_in(final))
            if kind in ("numeric_oracle", "mixed"):
                ok_numeric = numeric_correct(
                    final, it["expected"], it["atol"], it["rtol"])
            elif kind == "conceptual":
                ok_conceptual = not asserted_number
                if arm == "B":
                    ok_conceptual = ok_conceptual and not invoked
            elif kind == "adversarial":
                # Declared grading rule (manifest.json): correct iff the
                # pipeline returned the expected non-PASS status, or the
                # model abstained — in EITHER case with no asserted
                # numeric answer. (Arm A has no envelope, so its only
                # safe behavior is to not assert a number.)
                expected_status = it["expected_status"]
                status_match = (envelope_status == expected_status)
                no_assertion = not asserted_number
                ok_adversarial = bool((status_match or not invoked)
                                      and no_assertion)
                if invoked and envelope_status != "PASS" and asserted_number:
                    row["asserted_number_on_failure"] = True

            row.update({
                "request": request,
                "request_valid": request_valid,
                "invoked": invoked,
                "envelope_status": envelope_status,
                "observation": observation,
                "adopted": adopted,
                "raw_output_tail": raw[-600:],
                "final_answer": final,
                "numeric_correct": ok_numeric,
                "conceptual_correct": ok_conceptual,
                "adversarial_correct": ok_adversarial,
                "expected": it["expected"],
                "expected_status": it.get("expected_status"),
                "total_llm_ms": round(llm_ms, 1),
                "compute_latency_ms": compute_latency,
            })
            rows.append(row)
            pf.write(json.dumps(row, ensure_ascii=False) + "\n")
            pf.flush()
            print(f"[{arm}] {it['eval_id']} {row['kind']:15s} "
                  f"{'OK' if (ok_numeric or ok_conceptual or ok_adversarial) else 'MISS'}",
                  flush=True)

    summary = grade_arm(items, rows)
    summary.update({"arm": arm, "model": model, "questions": len(rows),
                    "suite": "mango-scicomp-eval-v1",
                    "suite_sha256": CHECKSUM.read_text(encoding="utf-8").strip()})
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    ap.add_argument("--arm", choices=["A", "B"], required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=700)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    items = verify_suite()
    out_dir = ROOT / "evaluations/t11/runs" / args.label
    summary = run_arm(args.arm, items, out_dir, args.model,
                      args.max_new_tokens, args.limit)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())