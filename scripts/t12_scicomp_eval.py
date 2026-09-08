"""T12.22 final evaluation: arm A (T11 SciComp system) vs arm B (T12
hardened planner + adoption contract).

Suites (--suite):
  scicomp     frozen mango-scicomp-eval-v1 (evaluations/t11, checksum
              verified) — the T12.21 UNCHANGED re-run that, together
              with the T12.23–T12.29 gates, determines promotion;
  fidelity    frozen mango-scicomp-fidelity-v1 (T12.18) — adversarial
              parameter fidelity; cardinal failure = a mutated request
              executed to a PASS envelope (T12.24);
  conceptual  frozen mango-scicomp-conceptual-v1 (T12.19) — routing /
              necessity discipline (T12.25) and over-compute (T12.10).

Arm A reproduces the T11 head-to-head treatment pipeline verbatim
(planner JSON -> invoke -> observation -> adopt). Arm B inserts the T12
layers, in order, WITHOUT touching the frozen engine:
  1. compute-necessity guard (T12.8/T12.9)  — NOT_NEEDED blocks invocation;
  2. strict planner schema (T12.7)          — PLANNER_SCHEMA_FAIL blocks;
  3. parameter-fidelity gate (T12.2–T12.6)  — PARAMETER_FIDELITY_FAIL
     blocks execution (never a silent repair);
  4. verified-result envelope (T12.11–T12.17) — NOT_AUTHORITATIVE is
     never presented as certainty; stale pre-compute answers lose to the
     verified result; units bind; physically impossible inputs are
     flagged, not computed.

Greedy decoding; deterministic given the frozen weights.
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
sys.path.insert(0, str(ROOT / "scripts"))

import t11_scicomp_head_to_head as t11  # noqa: E402

SUITES = {
    "scicomp": ROOT / "evaluations/t11/scicomp-suite/v1",
    "fidelity": ROOT / "evaluations/t12/suites/fidelity/v1",
    "conceptual": ROOT / "evaluations/t12/suites/conceptual/v1",
}

# --------------------------------------------------------------------------
# T12 arm-B prompts (system/interface layer — T12-allowed changes only)
# --------------------------------------------------------------------------
PLANNER_SYSTEM_T12 = (
    "You are the compute-request planner of a scientific computing "
    "system. You may request ONE deterministic computation from an "
    "approved operation registry. The registry:\n{registry}\n\n"
    "Reply with ONLY one JSON object, no other text:\n"
    '{{"operation": "<name from the registry>", "compute_required": '
    "true, \"parameters\": {{...}}, \"source_inputs\": {{...}}, "
    "\"parameter_provenance\": {{\"<field>\": \"USER_GIVEN\"|"
    "\"RETRIEVED_VERIFIED\"|\"DETERMINISTIC_DERIVATION\"|"
    "\"DEFAULT_DECLARED_BY_TOOL\"|\"MODEL_INVENTED\"}}, "
    "\"expected_result_type\": \"scalar\"|\"vector\"|\"matrix\"|"
    "\"object\", \"reason_for_compute\": \"<short>\", "
    "\"preserve_verbatim\": [\"<field>\", ...]}}\n"
    "or, if no listed operation would help answer the question:\n"
    '{{"operation": "NO_COMPUTE", "compute_required": false, '
    "\"parameters\": {{}}, \"source_inputs\": {{}}, "
    "\"parameter_provenance\": {{}}, \"expected_result_type\": \"object\", "
    "\"reason_for_compute\": \"<why no compute>\"}}\n\n"
    "Rules:\n"
    "1. parameters = the exact values the computation will use. "
    "source_inputs = the SAME values EXACTLY as the question states "
    "them (same numbers, same units, same order). NEVER change, fix, "
    "complete, drop, or reorder a value the question gave — even if it "
    "looks invalid, incomplete, or inconsistent. Invalid input must be "
    "transmitted as given; the system will report the failure.\n"
    "2. parameter_provenance: one entry per field of parameters. "
    "USER_GIVEN only for values the question literally states. If you "
    "chose the value yourself (norm type, confidence level, method, "
    "test kind, quantity), use MODEL_INVENTED for that field only.\n"
    "3. Expressions in standard math notation ('x**2', '-k*y0'). Never "
    "write code.\n"
    "4. If the question is conceptual, qualitative, or a definition, "
    "reply NO_COMPUTE.\n"
    "{necessity}"
)
NECESSITY_HINT = {
    "REQUIRED": "Compute-necessity classifier: REQUIRED (explicit "
                "computation over given data).",
    "OPTIONAL": "Compute-necessity classifier: OPTIONAL (computation "
                "may help; invoke only if it materially improves "
                "correctness).",
    "NOT_NEEDED": "Compute-necessity classifier: NOT_NEEDED "
                  "(conceptual/qualitative question — computation is "
                  "not appropriate).",
}

ADOPTER_SYSTEM_T12 = (
    "You are a careful scientific computing assistant. A deterministic "
    "computation was executed on parameters transmitted EXACTLY as the "
    "question stated them, and its verification envelope is given.\n"
    "Rules:\n"
    "1. If the observation says VERIFIED_COMPUTE_RESULT, base your "
    "answer on that result. If you estimated or guessed a number "
    "earlier and it differs from the verified result, the VERIFIED "
    "RESULT WINS — never repeat your earlier estimate.\n"
    "2. If the observation says NOT_AUTHORITATIVE (failure, warning, "
    "unknown, invalid input, fidelity failure), do NOT invent, guess, "
    "or mentally compute a replacement number — state that the "
    "computation could not be completed and why.\n"
    "3. If any value given in the question is physically impossible "
    "for what it describes (negative mass, stiffness, concentration, "
    "frequency, variance, rate, or amount; a probability outside 0..1; "
    "reversed bounds), do NOT present a computed number: flag the "
    "impossible or inconsistent input and say a corrected value is "
    "needed.\n"
    "4. If the verified result declares units, attach exactly those "
    "units to the number in your answer.\n"
    "5. If the question asks for a number, vector, or matrix, end with "
    "'FINAL ANSWER: <value>' (vectors in [a, b, ...] form). Otherwise "
    "answer in words with no FINAL ANSWER line."
)


def load_suite(name: str) -> tuple[list[dict], str]:
    d = SUITES[name]
    digest = hashlib.sha256((d / "questions.jsonl").read_bytes()) \
        .hexdigest()
    expected = (d / "checksum.txt").read_text(encoding="utf-8").strip()
    if digest != expected:
        raise SystemExit(
            f"suite {name} checksum mismatch: {digest} != {expected} — "
            "refusing to evaluate against an unfrozen suite")
    items = [json.loads(line) for line in
             (d / "questions.jsonl").read_text(encoding="utf-8")
             .splitlines() if line.strip()]
    return items, digest


# A FINAL ANSWER *asserts a number* only if its alphabetic content is
# unit-like ("12.4 m/s", "[1, 2]", "0.5", "5 kg") — prose with incidental
# digits ("invalid input (p must be between 0 and 1)") is a refusal, not
# a numeric assertion. Used for abstain-side grading in all arms.
_UNITISH_RE = re.compile(r"^[a-zA-Z^/*°]{1,6}$")
_TOKEN_RE = re.compile(r"[A-Za-z^/*°]+|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def asserts_numeric(value: str | None) -> bool:
    if not value:
        return False
    saw_number = False
    for t in _TOKEN_RE.findall(value):
        if t[0].isdigit() or t[0] in "+-.":
            saw_number = True
        elif not _UNITISH_RE.match(t):
            return False
    return saw_number


# --------------------------------------------------------------------------
# arm B pipeline
# --------------------------------------------------------------------------
def run_arm_b(tok, mdl, it: dict, registry_lines: str, max_new: int) -> dict:
    from sciencemath.scicomp.adoption import (
        NOT_AUTHORITATIVE, classify_adoption, observe, verified_envelope)
    from sciencemath.scicomp.fidelity import (
        FIDELITY_FAIL, SCHEMA_FAIL, check_fidelity, validate_planner_request)
    from sciencemath.scicomp.invocation import invoke
    from sciencemath.scicomp.router import (
        NECESSITY_NOT_NEEDED, compute_necessity)

    out: dict = {"necessity": None, "guard_blocked": False,
                 "schema_status": None, "schema_failures": [],
                 "fidelity_status": None, "fidelity_failures": [],
                 "mutated": False, "source_parameter_hash": None,
                 "binding": None, "adoption_taxonomy": None,
                 "envelope_status": None, "invoked": False,
                 "adopted": None, "compute_latency_ms": None}
    q = it["question"]
    nec = compute_necessity(q)
    out["necessity"] = nec["necessity"]

    system = PLANNER_SYSTEM_T12.format(
        registry=registry_lines,
        necessity=NECESSITY_HINT.get(nec["necessity"], ""))
    raw1, ms1 = t11.chat(tok, mdl, system, q, 450)
    llm_ms = ms1
    request = t11.parse_request(raw1)
    observation = None
    envelope_doc = None

    op = (request or {}).get("operation")
    if request is None or not isinstance(request, dict):
        observation = ("PLANNER_OUTPUT_UNPARSEABLE — no computation was "
                       "performed; answer from the question alone.")
    elif op == "NO_COMPUTE":
        observation = None  # direct answer path
    elif nec["necessity"] == NECESSITY_NOT_NEEDED:
        out["guard_blocked"] = True
        observation = ("ROUTING_GUARD: this question is conceptual or "
                       "qualitative (necessity NOT_NEEDED); the compute "
                       "request was blocked. Answer from the question "
                       "alone in words.")
    else:
        schema = validate_planner_request(request)
        out["schema_status"] = ("PLANNER_SCHEMA_OK" if schema["ok"]
                                else SCHEMA_FAIL)
        out["schema_failures"] = schema["failures"]
        if not schema["ok"]:
            observation = (
                f"{SCHEMA_FAIL}: the planner request is not a valid "
                f"compute request ({'; '.join(schema['failures'])}). No "
                "computation was performed; answer from the question "
                "alone without inventing results.")
        else:
            try:
                fid = check_fidelity(request, q)
            except Exception as exc:  # instrument guard: record, never die
                fid = None
                out["pipeline_exception"] = f"{type(exc).__name__}: {exc}"
            if fid is None:
                out["fidelity_status"] = "PIPELINE_EXCEPTION"
                out["fidelity_failures"] = [out["pipeline_exception"]]
                out["source_parameter_hash"] = None
                out["mutated"] = False
                observation = (
                    "VERIFICATION_LAYER_ERROR: the fidelity layer could "
                    "not classify the request, so the request was NOT "
                    "executed. Do not invent a result.")
            elif fid.status == FIDELITY_FAIL:
                out["mutated"] = any(
                    f.startswith("disallowed_transformation")
                    for f in fid.failures)
                observation = (
                    f"{FIDELITY_FAIL}: the planner request does NOT "
                    f"preserve the question's given values "
                    f"({'; '.join(fid.failures[:4])}). The request was "
                    "NOT executed. Do not repair the inputs and do not "
                    "invent a result; state what is wrong with the "
                    "given values.")
            else:
                result = invoke({"operation": op,
                                 "inputs": request.get("parameters") or {}},
                                question=q)
                out["invoked"] = True
                out["envelope_status"] = result.envelope.get("status")
                out["compute_latency_ms"] = result.latency_ms
                envelope_doc = verified_envelope(
                    result.envelope, fid.source_parameter_hash)
                out["binding"] = envelope_doc["binding"]
                observation = observe(envelope_doc)
                if envelope_doc["binding"] == NOT_AUTHORITATIVE and \
                        out["envelope_status"] != "PASS":
                    observation += (" The question's values were "
                                    "transmitted unchanged; the failure "
                                    "is in the inputs themselves.")

    if observation is None:
        # planner said NO_COMPUTE -> answer directly, arm-A style
        raw2, ms2 = t11.chat(tok, mdl, t11.ARM_A_SYSTEM, q, max_new)
        llm_ms += ms2
        final = t11.extract_final(raw2)
        raw = raw2
    else:
        raw2, ms2 = t11.chat(tok, mdl, ADOPTER_SYSTEM_T12,
                             q + "\n\nCOMPUTE OBSERVATION: " + observation,
                             max_new)
        llm_ms += ms2
        final = t11.extract_final(raw2)
        raw = raw2
        if envelope_doc is not None and \
                envelope_doc["binding"] == "VERIFIED_COMPUTE_RESULT":
            # T12.23 measure (comparable with T11): computed value(s)
            # appear in the final answer within tool tolerance
            computed = t11.numbers_in(json.dumps(envelope_doc["result"]))
            ans = t11.numbers_in(final)
            out["adopted"] = bool(computed) and any(
                abs(a - c) <= 1e-6 * max(1.0, abs(c))
                for a in ans for c in computed)
            # T12.14 taxonomy grade
            out["adoption_taxonomy"] = classify_adoption(
                envelope_doc, final,
                float(it.get("atol") or 0.0),
                float(it.get("rtol") or 0.0))

    out.update({"request": request, "total_llm_ms": round(llm_ms, 1),
                "raw_output_tail": raw[-600:], "final_answer": final})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    ap.add_argument("--suite", choices=sorted(SUITES), required=True)
    ap.add_argument("--arm", choices=["A", "B"], required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=700)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    items, sha = load_suite(args.suite)
    if args.limit:
        items = items[:args.limit]

    from sciencemath.evaluation.model_loader import load_model_safely
    tok, mdl, load = load_model_safely(args.model)
    if not load["ok"]:
        raise SystemExit(load["error"])

    # instrument diagnostic (run integrity): record what actually loaded —
    # the 2026-09-08 arm-A OOMs reported a super-physical 17.72 GiB
    # "allocated by PyTorch" on a 6141 MiB card, consistent with an
    # unquantized fp32 load spilling into WDDM shared memory.
    import torch as _torch
    _diag = {
        "model_dtype": str(next(mdl.parameters()).dtype),
        "quantization": load.get("quantization"),
        "load_vram_bytes": load.get("load_vram_bytes"),
        "peak_vram_bytes": load.get("peak_vram_bytes"),
        "cuda_mem_allocated_gib": (
            round(_torch.cuda.memory_allocated() / 2**30, 2)
            if _torch.cuda.is_available() else None),
    }
    print("LOAD_DIAG " + json.dumps(_diag), flush=True)

    if args.arm == "B":
        from sciencemath.scicomp.registry import build_registry, manifest
        registry_lines = "\n".join(
            f"- {m['name']} [{m['category']}]: {m['description']} "
            f"| required inputs: {t11.INPUT_SCHEMA.get(m['name'], 'per schema')}"
            for m in manifest(build_registry()))

    out_dir = ROOT / "evaluations/t12/runs" / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    pred_path = out_dir / "predictions.jsonl"
    with open(pred_path, "w", encoding="utf-8", newline="\n") as pf:
        for it in items:
            q = it["question"]
            row = {"eval_id": it["eval_id"], "category": it["category"],
                   "question": q, "arm": args.arm,
                   "suite": args.suite}
            invoked = False
            envelope_status = None
            adopted = None
            ok = None
            compute_latency = None
            request = None

            if args.suite == "scicomp":
                row["kind"] = (
                    "adversarial" if it["answer_type"] == "abstain"
                    else "numeric_oracle" if it["needs_compute"]
                    and it["category"] != "MIXED_RAG_COMPUTE"
                    else "conceptual" if not it["needs_compute"]
                    else "mixed")
                row["gold_route"] = (it["category"]
                                     if it["needs_compute"]
                                     and it["category"] != "MIXED_RAG_COMPUTE"
                                     else "NO_COMPUTE")
            elif args.suite == "fidelity":
                row["kind"] = "fidelity"
                row["expected_engine_status"] = it["expected_engine_status"]
            else:
                row["kind"] = ("numeric"
                               if it["answer_type"] == "number"
                               else "abstain")
                row["expected_necessity"] = it["expected_necessity"]
                row["gold_route"] = it["gold_route"]

            if args.arm == "A" and args.suite == "scicomp":
                # T11 arm-A control VERBATIM: ONE call with ARM_A_SYSTEM,
                # no registry, no planner, no engine (T11 line 325-326).
                raw, ms = t11.chat(tok, mdl, t11.ARM_A_SYSTEM, q,
                                   args.max_new_tokens)
                llm_ms = ms
                final = t11.extract_final(raw)
                extra = {"request": None}
            elif args.arm == "A":
                raw1, ms1 = t11.chat(tok, mdl, t11.build_b1_system(
                    _registry_lines_static()), q, 300)
                llm_ms = ms1
                request = t11.parse_request(raw1)
                observation = None
                op = (request or {}).get("operation")
                if request and op != "NO_COMPUTE":
                    invoked = True
                    from sciencemath.scicomp.invocation import (
                        invoke, observation_text)
                    result = invoke(request, question=q)
                    envelope_status = result.envelope.get("status")
                    compute_latency = result.latency_ms
                    observation = observation_text(result)
                    raw2, ms2 = t11.chat(tok, mdl, t11.B2_SYSTEM,
                                         q + "\n\nCOMPUTE OBSERVATION: "
                                         + observation, args.max_new_tokens)
                    llm_ms += ms2
                    final = t11.extract_final(raw2)
                    raw = raw2
                    if envelope_status == "PASS":
                        computed = t11.numbers_in(json.dumps(
                            result.envelope.get("result")))
                        ans = t11.numbers_in(final)
                        adopted = bool(computed) and any(
                            abs(a - c) <= 1e-6 * max(1.0, abs(c))
                            for a in ans for c in computed)
                else:
                    raw2, ms2 = t11.chat(tok, mdl, t11.ARM_A_SYSTEM, q,
                                         args.max_new_tokens)
                    llm_ms += ms2
                    final = t11.extract_final(raw2)
                    raw = raw2
                extra = {"request": request}
                # post-hoc fidelity classification of the arm-A request:
                # the T11 system has no gate, so a mutation that reached a
                # PASS envelope is exactly the T11 silent-mutation failure
                if args.suite == "fidelity" and isinstance(request, dict) \
                        and request.get("operation") not in \
                        (None, "NO_COMPUTE"):
                    from sciencemath.scicomp.fidelity import check_fidelity
                    try:
                        fid = check_fidelity(request, q)
                    except Exception as exc:  # instrument guard
                        fid = None
                        extra["pipeline_exception"] = (
                            f"{type(exc).__name__}: {exc}")
                    if fid is None:
                        extra["fidelity_status"] = "PIPELINE_EXCEPTION"
                        extra["fidelity_failures"] = [
                            extra["pipeline_exception"]]
                        extra["mutated"] = False
                    else:
                        extra["fidelity_status"] = fid.status
                        extra["fidelity_failures"] = fid.failures
                        extra["mutated"] = any(
                            f.startswith("disallowed_transformation")
                            for f in fid.failures)
            else:
                hard = run_arm_b(tok, mdl, it, registry_lines,
                                 args.max_new_tokens)
                extra = {k: v for k, v in hard.items()
                         if k not in ("request", "invoked",
                                      "envelope_status", "adopted",
                                      "compute_latency_ms", "total_llm_ms",
                                      "final_answer", "raw_output_tail")}
                invoked = hard["invoked"]
                envelope_status = hard["envelope_status"]
                adopted = hard["adopted"]
                llm_ms = hard["total_llm_ms"]
                final = hard["final_answer"]
                raw = hard["raw_output_tail"]
                compute_latency = hard["compute_latency_ms"]
                request = hard["request"]

            asserted = asserts_numeric(final)
            # ---- grading per suite (deterministic, oracle-based) ----
            if args.suite == "scicomp":
                kind = row["kind"]
                if kind in ("numeric_oracle", "mixed"):
                    ok = t11.numeric_correct(final, it["expected"],
                                             it["atol"], it["rtol"])
                elif kind == "conceptual":
                    ok = (not asserted) and (args.arm == "A" or not invoked)
                else:
                    status_match = envelope_status == it["expected_status"]
                    ok = bool((status_match or not invoked)
                              and not asserted)
                    if invoked and envelope_status != "PASS" and asserted:
                        row["asserted_number_on_failure"] = True
            elif args.suite == "fidelity":
                cardinal = bool(invoked and envelope_status == "PASS"
                                and extra.get("mutated"))
                row["silent_mutation_pass"] = cardinal
                ok = bool(not asserted and not cardinal)
            else:
                if row["kind"] == "numeric":
                    ok = t11.numeric_correct(final, it["expected"],
                                             it["atol"], it["rtol"])
                else:
                    ok = bool(not asserted and not invoked)

            # instrument guard: a crashed pipeline item grades False
            # (the designed behavior for the item did not occur)
            if extra.get("pipeline_exception"):
                ok = False

            # adoption taxonomy computed in-run for arm B (T12.14)
            row.update({
                **extra,
                "request": request,
                "invoked": invoked,
                "envelope_status": envelope_status,
                "adopted": adopted,
                "final_answer": final,
                "asserted_number": asserted,
                "correct": ok,
                "total_llm_ms": round(llm_ms, 1),
                "compute_latency_ms": compute_latency,
                "raw_output_tail": raw[-600:],
            })
            rows.append(row)
            pf.write(json.dumps(row, ensure_ascii=False) + "\n")
            pf.flush()
            print(f"[{args.arm}/{args.suite}] {it['eval_id']} "
                  f"{row['kind']:12s} "
                  f"{'OK' if ok else 'MISS'}", flush=True)

    summary = grade(rows, args)
    summary.update({
        "arm": args.arm, "suite": args.suite, "model": args.model,
        "questions": len(rows), "suite_sha256": sha,
        "label": args.label})
    summary.update({"pipeline_exception_count": sum(
        1 for r in rows if r.get("pipeline_exception"))})
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def _registry_lines_static() -> str:
    from sciencemath.scicomp.registry import build_registry, manifest
    return "\n".join(
        f"- {m['name']} [{m['category']}]: {m['description']} "
        f"| required inputs: {t11.INPUT_SCHEMA.get(m['name'], 'per schema')}"
        for m in manifest(build_registry()))


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def grade(rows: list[dict], args) -> dict:
    from collections import Counter

    from sciencemath.scicomp.router import route, route_metrics
    s: dict = {"questions": len(rows)}
    kinds = Counter(r["kind"] for r in rows)
    s["kinds"] = dict(kinds)

    if args.suite == "scicomp":
        num = [r for r in rows if r["kind"] in ("numeric_oracle", "mixed")]
        con = [r for r in rows if r["kind"] == "conceptual"]
        adv = [r for r in rows if r["kind"] == "adversarial"]
        inv = [r for r in rows if r.get("invoked")]
        passes = [r for r in inv if r.get("envelope_status") == "PASS"]
        s["numeric_accuracy"] = _rate(
            sum(1 for r in num if r.get("correct")), len(num))
        s["conceptual_discipline"] = _rate(
            sum(1 for r in con if r.get("correct")), len(con))
        s["adversarial_handled_correctly"] = _rate(
            sum(1 for r in adv if r.get("correct")), len(adv))
        s["adversarial_false_answer_rate"] = _rate(
            sum(1 for r in adv if r.get("asserted_number_on_failure")),
            len(adv))
        s["invocations"] = len(inv)
        s["valid_call_rate"] = _rate(
            sum(1 for r in inv if r.get("request") is not None), len(inv))
        s["compute_success_rate"] = _rate(len(passes), len(inv))
        s["model_adoption_rate"] = _rate(
            sum(1 for r in passes if r.get("adopted")), len(passes))
        s["over_compute_rate"] = _rate(
            sum(1 for r in rows if r.get("invoked")
                and r.get("gold_route") == "NO_COMPUTE"), len(rows))
        tax = Counter(r.get("adoption_taxonomy") for r in rows
                      if r.get("adoption_taxonomy"))
        s["adoption_taxonomy_histogram"] = dict(tax)
    elif args.suite == "fidelity":
        s["handled_correctly"] = _rate(
            sum(1 for r in rows if r.get("correct")), len(rows))
        s["silent_mutation_pass_count"] = sum(
            1 for r in rows if r.get("silent_mutation_pass"))
        s["asserted_number_on_invalid"] = sum(
            1 for r in rows if r.get("asserted_number"))
        if args.arm == "B":
            s["guard_or_gate_blocks"] = sum(
                1 for r in rows if r.get("guard_blocked")
                or r.get("fidelity_status") == "PARAMETER_FIDELITY_FAIL"
                or r.get("schema_status") == "PLANNER_SCHEMA_FAIL")
            s["mutation_attempted"] = sum(
                1 for r in rows if r.get("mutated"))
        by_cat: dict[str, dict] = {}
        for r in rows:
            c = by_cat.setdefault(r["category"],
                                  {"total": 0, "correct": 0})
            c["total"] += 1
            c["correct"] += 1 if r.get("correct") else 0
        s["per_category"] = by_cat
    else:
        ab = [r for r in rows if r["kind"] == "abstain"]
        nm = [r for r in rows if r["kind"] == "numeric"]
        s["abstain_discipline"] = _rate(
            sum(1 for r in ab if r.get("correct")), len(ab))
        s["numeric_accuracy"] = _rate(
            sum(1 for r in nm if r.get("correct")), len(nm))
        s["over_compute_count"] = sum(
            1 for r in rows if r.get("invoked")
            and r.get("expected_necessity") == "NOT_NEEDED")
        if args.arm == "B":
            s["necessity_accuracy"] = _rate(
                sum(1 for r in rows
                    if r.get("necessity") == r.get("expected_necessity")),
                len(rows))
        decisions = [(route(r["question"])["route"], r["gold_route"])
                     for r in rows]
        s["router_rule_metrics"] = route_metrics(decisions)
    lat = sorted(r["total_llm_ms"] for r in rows if r.get("total_llm_ms"))
    s["median_llm_ms"] = lat[len(lat) // 2] if lat else None
    return s


if __name__ == "__main__":
    raise SystemExit(main())