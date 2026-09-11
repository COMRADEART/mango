"""T14R.14 runner — SciComp replay through the repaired pipeline.

Fork of t12_scicomp_eval.py arm B (frozen evaluation protocol, same
suites, same grading). Arm-B pipeline order with the T14R layers
inserted at exactly two points; nothing frozen is touched:

  parse_request (LLM)
  1. compute-necessity guard   — FROZEN, unchanged
  2. repair_planner_request    — T14R.3/T14R.4 deterministic planner-
                                 provenance repair (value-preserving,
                                 mutation-safe; replaces nothing the
                                 question did not say)
  3. strict planner schema     — FROZEN, unchanged
  4. parameter-fidelity gate   — FROZEN, unchanged
  5. invoke (engine)           — FROZEN, unchanged
  6. verified_envelope         — FROZEN, unchanged
  7. result_contract           — T14R.5–T14R.11 canonical verified-
                                 result contract (authoritative field,
                                 deterministic display, unit guard,
                                 stale supersession) fed to the
                                 adopter via observe_contract
  8. adopter LLM               — T14R adopter prompt (contract rules)

Grading and taxonomy are unchanged from T12/T14 (classify_adoption now
receives the contract's authoritative_field so the expected numbers are
taken from the authoritative payload field, fixing the padded-payload
instrument artifact identified in T14R.2).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t11_scicomp_head_to_head as t11  # noqa: E402
import t12_scicomp_eval as t12  # noqa: E402

SUITES = t12.SUITES
load_suite = t12.load_suite
asserts_numeric = t12.asserts_numeric

# --------------------------------------------------------------------------
# T14R adopter prompt: the contract rules are restated verbatim
# --------------------------------------------------------------------------
ADOPTER_SYSTEM_T14R = (
    "You are a careful scientific computing assistant. A deterministic "
    "computation was executed on parameters transmitted EXACTLY as the "
    "question stated them, and a VERIFIED-RESULT CONTRACT is given in "
    "the observation.\n"
    "Rules:\n"
    "1. If the observation carries VERIFIED_COMPUTE_RESULT, adopt the "
    "verified value EXACTLY as given — DO NOT recompute, re-derive, or "
    "double-check it with your own arithmetic. The verified value is "
    "authoritative; any number you estimated earlier is superseded.\n"
    "2. Use the display value the contract provides when the question "
    "asked for a specific rounding; otherwise report the verified "
    "value as computed. Do not invent a precision of your own.\n"
    "3. If the observation says NOT_AUTHORITATIVE or "
    "COMPUTE_RESULT_NOT_USABLE, do NOT invent, guess, or mentally "
    "compute a replacement number — state that the computation could "
    "not be completed and why.\n"
    "4. If any value given in the question is physically impossible "
    "for what it describes (negative mass, stiffness, concentration, "
    "frequency, variance, rate, or amount; a probability outside 0..1; "
    "reversed bounds), do NOT present a computed number: flag the "
    "impossible or inconsistent input and say a corrected value is "
    "needed.\n"
    "5. If the verified result declares units, attach exactly those "
    "units to the number in your answer; never convert or drop them.\n"
    "6. If the question asks for a number, vector, or matrix, end with "
    "'FINAL ANSWER: <value>' (vectors in [a, b, ...] form) using the "
    "verified value. Otherwise answer in words with no FINAL ANSWER "
    "line."
)


def run_arm_b_t14r(tok, mdl, it: dict, registry_lines: str,
                   max_new: int) -> dict:
    from sciencemath.scicomp.adoption import (
        NOT_AUTHORITATIVE, classify_adoption, verified_envelope)
    from sciencemath.scicomp.fidelity import (
        FIDELITY_FAIL, SCHEMA_FAIL, check_fidelity, validate_planner_request)
    from sciencemath.scicomp.invocation import invoke
    from sciencemath.scicomp.planner_repair import repair_planner_request
    from sciencemath.scicomp.result_contract import (
        observe_contract, result_contract)
    from sciencemath.scicomp.router import (
        blocks_scicomp_invocation, compute_necessity)

    out: dict = {"necessity": None, "guard_blocked": False,
                 "schema_status": None, "schema_failures": [],
                 "fidelity_status": None, "fidelity_failures": [],
                 "mutated": False, "source_parameter_hash": None,
                 "binding": None, "adoption_taxonomy": None,
                 "envelope_status": None, "invoked": False,
                 "adopted": None, "compute_latency_ms": None,
                 "repair": {"changed": False, "bindings": [],
                            "unknown_provenance": []},
                 "contract": None}
    q = it["question"]
    nec = compute_necessity(q)
    out["necessity"] = nec["necessity"]
    out["legacy_necessity"] = nec.get("legacy_necessity")
    out["necessity_reason"] = nec.get("reason")

    system = t12.PLANNER_SYSTEM_T12.format(
        registry=registry_lines,
        necessity=t12.NECESSITY_HINT.get(nec["necessity"], ""))
    raw1, ms1 = t11.chat(tok, mdl, system, q, 450)
    llm_ms = ms1
    request = t11.parse_request(raw1)
    observation = None
    envelope_doc = None
    contract = None
    authoritative_field = None

    op = (request or {}).get("operation")
    if request is None or not isinstance(request, dict):
        observation = ("PLANNER_OUTPUT_UNPARSEABLE — no computation was "
                       "performed; answer from the question alone.")
    elif op == "NO_COMPUTE":
        observation = None  # direct answer path
    elif blocks_scicomp_invocation(nec["necessity"]):
        out["guard_blocked"] = True
        observation = (
            f"ROUTING_GUARD: necessity={nec['necessity']} "
            f"({nec.get('reason')}); the compute "
            "request was blocked. Answer from the question alone in "
            "words. Do not invent missing numerical inputs.")
    else:
        # ---- T14R.3/T14R.4: deterministic provenance repair ----
        rep = repair_planner_request(request, q)
        out["repair"] = {"changed": rep["changed"],
                         "bindings": rep["bindings"],
                         "unknown_provenance": rep["unknown_provenance"]}
        fixed = rep["request"]

        schema = validate_planner_request(fixed)
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
                fid = check_fidelity(fixed, q)
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
                result = invoke({"operation": fixed["operation"],
                                 "inputs": fixed.get("parameters") or {}},
                                question=q)
                out["invoked"] = True
                out["envelope_status"] = result.envelope.get("status")
                out["compute_latency_ms"] = result.latency_ms
                envelope_doc = verified_envelope(
                    result.envelope, fid.source_parameter_hash)
                out["binding"] = envelope_doc["binding"]
                # ---- T14R.5–R.11: canonical result contract ----
                contract = result_contract(
                    envelope_doc, fixed, q,
                    (fixed or {}).get("expected_result_type"))
                out["contract"] = contract
                observation = observe_contract(contract)
                if contract.get("binding") == NOT_AUTHORITATIVE and \
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
        raw2, ms2 = t11.chat(tok, mdl, ADOPTER_SYSTEM_T14R,
                             q + "\n\nCOMPUTE OBSERVATION: " + observation,
                             max_new)
        llm_ms += ms2
        final = t11.extract_final(raw2)
        raw = raw2
        if contract is not None and \
                contract.get("binding") == "VERIFIED_COMPUTE_RESULT":
            computed = t11.numbers_in(json.dumps(
                contract.get("authoritative_value")))
            ans = t11.numbers_in(final)
            out["adopted"] = bool(computed) and any(
                abs(a - c) <= 1e-6 * max(1.0, abs(c))
                for a in ans for c in computed)
            out["adoption_taxonomy"] = classify_adoption(
                envelope_doc, final,
                float(it.get("atol") or 0.0),
                float(it.get("rtol") or 0.0),
                authoritative_field=contract.get("authoritative_field"))
        elif envelope_doc is not None and \
                envelope_doc["binding"] == "VERIFIED_COMPUTE_RESULT" and \
                contract is None:
            # contract could not be built (should not happen) — fall
            # back to the T12 instrument so the row is never ungraded
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
    ap.add_argument("--label", required=True)
    ap.add_argument("--arm", default="B")  # grade() reads args.arm
    ap.add_argument("--max-new-tokens", type=int, default=700)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out-root", default="evaluations/t14r/runs")
    args = ap.parse_args()

    items, sha = load_suite(args.suite)
    if args.limit:
        items = items[:args.limit]

    from sciencemath.evaluation.model_loader import load_model_safely
    tok, mdl, load = load_model_safely(args.model)
    if not load["ok"]:
        raise SystemExit(load["error"])

    from sciencemath.scicomp.registry import build_registry, manifest
    registry_lines = "\n".join(
        f"- {m['name']} [{m['category']}]: {m['description']} "
        f"| required inputs: {t11.INPUT_SCHEMA.get(m['name'], 'per schema')}"
        for m in manifest(build_registry()))

    out_root = Path(args.out_root)
    out_dir = out_root / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    pred_path = out_dir / "predictions.jsonl"
    with open(pred_path, "w", encoding="utf-8", newline="\n") as pf:
        for it in items:
            q = it["question"]
            row = {"eval_id": it["eval_id"], "category": it["category"],
                   "question": q, "arm": "B-T14R",
                   "suite": args.suite}
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

            hard = run_arm_b_t14r(tok, mdl, it, registry_lines,
                                  args.max_new_tokens)
            extra = {k: v for k, v in hard.items()
                     if k not in ("request", "invoked", "envelope_status",
                                  "adopted", "compute_latency_ms",
                                  "total_llm_ms", "final_answer",
                                  "raw_output_tail")}
            invoked = hard["invoked"]
            envelope_status = hard["envelope_status"]
            adopted = hard["adopted"]
            llm_ms = hard["total_llm_ms"]
            final = hard["final_answer"]
            raw = hard["raw_output_tail"]
            compute_latency = hard["compute_latency_ms"]
            request = hard["request"]

            asserted = asserts_numeric(final)
            if args.suite == "scicomp":
                kind = row["kind"]
                if kind in ("numeric_oracle", "mixed"):
                    ok = t11.numeric_correct(final, it["expected"],
                                             it["atol"], it["rtol"])
                elif kind == "conceptual":
                    ok = (not asserted) and not invoked
                else:
                    status_match = envelope_status == it["expected_status"]
                    ok = bool((status_match or not invoked) and not asserted)
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

            if extra.get("pipeline_exception"):
                ok = False

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
            print(f"[B-T14R/{args.suite}] {it['eval_id']} "
                  f"{row['kind']:12s} "
                  f"{'OK' if ok else 'MISS'}", flush=True)

    summary = t12.grade(rows, args)
    summary.update({
        "arm": "B-T14R", "suite": args.suite,
        "model": args.model,
        "questions": len(rows), "suite_sha256": sha,
        "label": args.label})
    summary.update({"pipeline_exception_count": sum(
        1 for r in rows if r.get("pipeline_exception"))})
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())