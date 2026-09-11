"""T14R.2 — classify every incorrect T14 numeric SciComp row.

Reads the frozen T14 run (evaluations/t14/runs/t14a-scicomp-B/
predictions.jsonl), selects numeric_oracle + mixed rows graded
incorrect (37 of 138), and assigns each exactly one taxonomy class from
the T14R.2 taxonomy, with the evidence fields the milestone requires.

Classification is evidence-based (the row's own recorded pipeline
fields + the frozen fidelity gate re-run on the recorded request);
classes are recorded per row with a rationale string. No code is
changed by this script — forensics only (T14R.2 mandate).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PRED = ROOT / "evaluations/t14/runs/t14a-scicomp-B/predictions.jsonl"
SUITE = ROOT / "evaluations/t11/scicomp-suite/v1/questions.jsonl"
OUT = ROOT / "evaluations/t14r/t14_numeric_failure_analysis.json"

# Per-row classification. Deterministic fields decide the class; the
# rationale records the concrete evidence. Values were verified against
# the raw rows and the frozen fidelity layer before being written here.
ROW_CLASSES: dict[str, dict] = {
    # ---- model did not invoke (op NO_COMPUTE despite compute need) ----
    "msc-v1-0147": {"class": "NO_INVOCATION", "rationale":
        "planner emitted NO_COMPUTE for a countable parameter-sweep "
        "enumeration ('how many combinations'); model answered "
        "'infinite' from its own reading; gold 6.0"},
    # ---- planner provenance metadata omissions (schema gate) ----
    "msc-v1-0079": {"class": "PROVENANCE_MISSING", "rationale":
        "schema gate: provenance_missing_or_invalid:parameters — "
        "parameter_provenance incomplete for the nested parameters field"},
    "msc-v1-0086": {"class": "PROVENANCE_MISSING", "rationale":
        "schema gate: provenance_missing_or_invalid:parameters"},
    "msc-v1-0117": {"class": "PROVENANCE_MISSING", "rationale":
        "schema gate: provenance_missing_or_invalid:parameters "
        "(distribution_value request lacked provenance metadata)"},
    "msc-v1-0118": {"class": "PROVENANCE_MISSING", "rationale":
        "schema gate: provenance_missing_or_invalid:parameters"},
    "msc-v1-0119": {"class": "PROVENANCE_MISSING", "rationale":
        "schema gate: provenance missing for distribution/parameters/"
        "quantity fields"},
    "msc-v1-0120": {"class": "PROVENANCE_MISSING", "rationale":
        "schema gate: provenance_missing_or_invalid:parameters"},
    "msc-v1-0121": {"class": "PROVENANCE_MISSING", "rationale":
        "schema gate: provenance_missing_or_invalid:parameters"},
    "msc-v1-0137": {"class": "PROVENANCE_MISSING", "rationale":
        "schema gate: provenance missing for model/x/y/parameters fields "
        "of a well-formed curve_fit request"},
    # ---- derived restatements mislabeled MODEL_INVENTED (schema gate) ----
    "msc-v1-0083": {"class": "PROVENANCE_WRONG", "rationale":
        "schema gate: model_invented_on_protected:expression — ODE "
        "restatement 9*exp(-t/3) labeled MODEL_INVENTED; also wrong "
        "operation (integral instead of solve_ode)"},
    "msc-v1-0088": {"class": "PROVENANCE_WRONG", "rationale":
        "schema gate: model_invented_on_protected:expression; integral "
        "abuse for dN/dt growth — solve_ode is the correct operation"},
    "msc-v1-0161": {"class": "PROVENANCE_WRONG", "rationale":
        "schema gate: model_invented_on_protected:expression 't' over "
        "[0,384400] — T4-level division (384400/3.0e5); SciComp lane "
        "was wrong; model's own arithmetic 1.28133 was near-correct"},
    "msc-v1-0172": {"class": "PROVENANCE_WRONG", "rationale":
        "schema gate: model_invented_on_protected:expression — ideal-gas "
        "arithmetic sent as definite_integral of 8.314*273/V"},
    # ---- malformed structured request (typing / key mapping) ----
    "msc-v1-0076": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: source_inputs keyed by question phrases "
        "('t = 2') instead of parameter fields; string-typed "
        "initial_state ['5']; solve_ode restatement resolver did not "
        "verify the mapping"},
    "msc-v1-0077": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: same pattern — source key 't' vs parameter "
        "t_end; string-typed initial_state"},
    "msc-v1-0080": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: same pattern — 't = 1.5' source key vs t_end"},
    "msc-v1-0085": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: t_end sent as string 'pi/2' instead of the "
        "deterministic numeric value 1.5707963...; gold -1.0"},
    "msc-v1-0087": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: string-typed bounds [['0','9.8']]; also wrong "
        "operation (minimize for dv/dt=9.8 fall — correct is "
        "integration; gold 29.4)"},
    "msc-v1-0102": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: bounds transmitted as strings [['-5','5'],...]; "
        "clean numeric bounds pass fidelity and engine (gold [0,2])"},
    "msc-v1-0125": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: source key 'mu' vs parameter field 'null_value' "
        "— no_source_input:null_value + source_input_dropped:mu; "
        "field-aligned source_inputs pass the frozen gate"},
    "msc-v1-0148": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: expression absent from source_inputs "
        "(no_source_input:expression); sweep grids were fine"},
    "msc-v1-0149": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "fidelity gate: no_source_input:expression — same pattern"},
    "msc-v1-0081": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "wrong operation: ODE dP/dt=0.3*P sent as definite_integral "
        "'0.3 * P' over [0,5]; engine INVALID_INPUT (P undeclared); "
        "solve_ode is the correct operation"},
    "msc-v1-0166": {"class": "PLANNER_SCHEMA_FAILURE", "rationale":
        "planner emitted empty parameters with compute_required=false "
        "then asserted its own rounded 7546 (gold 7546.049, atol "
        "0.0075) — a rounding loss on an unverified value"},
    # ---- derived expressions the frozen fidelity gate cannot trace ----
    "msc-v1-0082": {"class": "PROVENANCE_WRONG", "rationale":
        "fidelity gate: derived closed form 10*exp(-0.02*t) as integral "
        "expression; correct construction is solve_ode (gold "
        "1.35335 = 10*exp(-2))"},
    "msc-v1-0157": {"class": "PROVENANCE_WRONG", "rationale":
        "fidelity gate: constant product 3.0e8 as integrand; source "
        "keys named by phrase ('speed_of_light') not parameter fields"},
    "msc-v1-0158": {"class": "PROVENANCE_WRONG", "rationale":
        "fidelity gate: 9.81*t integrand with phrase-keyed sources"},
    "msc-v1-0163": {"class": "PROVENANCE_WRONG", "rationale":
        "fidelity gate: product 4184*0.5*20 with phrase-keyed sources; "
        "field-aligned construction passes the frozen gate"},
    "msc-v1-0169": {"class": "PROVENANCE_WRONG", "rationale":
        "fidelity gate: h*nu product with phrase-keyed sources"},
    "msc-v1-0175": {"class": "PROVENANCE_WRONG", "rationale":
        "fidelity gate: 0.5*200*x**2 integrated — wrong formula for "
        "E=0.5kx^2 (integral gives 0.0083, gold 0.25); also phrase-keyed "
        "sources"},
    # ---- engine rejected a schema-valid request ----
    "msc-v1-0037": {"class": "ENGINE_REJECT", "rationale":
        "engine accepts only variable x for definite_integral; planner "
        "sent 3*t → INVALID_INPUT undeclared variable (gold 24.0)"},
    "msc-v1-0040": {"class": "ENGINE_REJECT", "rationale":
        "same undeclared-variable reject: 6*t - 6 (gold 13.5)"},
    "msc-v1-0041": {"class": "ENGINE_REJECT", "rationale":
        "same undeclared-variable reject: 4*t over [1,3] (gold 16.0)"},
    "msc-v1-0084": {"class": "ENGINE_REJECT", "rationale":
        "planner restated the analytic solution 12*exp(-t/2) as "
        "integrand; engine INVALID_INPUT (t undeclared); solve_ode is "
        "the correct operation (gold 1.6240)"},
    # ---- verified result handling (PASS envelopes) ----
    "msc-v1-0030": {"class": "OTHER", "rationale":
        "instrument recorded WRONG_ROUNDING, but forensics show the "
        "model adopted the engine result exactly (0.99999933 = "
        "ln(2.71828) over the GIVEN upper bound); gold 1.0 was computed "
        "from e=2.718281828 — a gold-vs-given-input mismatch, not a "
        "model/adoption failure; not in T14R repair scope"},
    "msc-v1-0099": {"class": "RESULT_MISREAD", "rationale":
        "planner dropped the outer square ((x**2-4)**2 → x**2-4) — a "
        "mutation the frozen fidelity gate missed; engine minimized the "
        "mutated function; model distrusted the verified result and "
        "answered [-2, 2] while gold is scalar 2.0"},
    "msc-v1-0068": {"class": "NUMERICAL_WARNING", "rationale":
        "engine returned NUMERICAL_WARNING (NOT_AUTHORITATIVE) yet the "
        "model asserted 0.2527 — a 4-dp rounding of the root "
        "0.25268025...; outside atol 1e-5 AND asserted despite "
        "fail-closed rule"},
}

TAXONOMY = ["NO_INVOCATION", "PLANNER_SCHEMA_FAILURE", "PROVENANCE_MISSING",
            "PROVENANCE_WRONG", "ENGINE_REJECT", "ENGINE_FAILURE",
            "NUMERICAL_WARNING", "RESULT_MISREAD", "RESULT_IGNORED",
            "STALE_PRECOMPUTE_RESULT", "WRONG_ROUNDING", "UNIT_LOSS",
            "EXTRACTION_FAILURE", "OTHER"]


def main() -> int:
    rows = [json.loads(ln) for ln in
            PRED.read_text(encoding="utf-8").splitlines() if ln.strip()]
    gold = {}
    for ln in SUITE.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            d = json.loads(ln)
            gold[d["eval_id"]] = d
    numeric = [r for r in rows
               if r.get("kind") in ("numeric_oracle", "mixed")]
    bad = [r for r in numeric if not r.get("correct")]
    missing = [r["eval_id"] for r in bad
               if r["eval_id"] not in ROW_CLASSES]
    if missing:
        raise SystemExit(f"unclassified rows: {missing}")
    unknown = {c["class"] for c in ROW_CLASSES.values()} - set(TAXONOMY)
    if unknown:
        raise SystemExit(f"classes outside taxonomy: {unknown}")

    records = []
    for r in bad:
        eid = r["eval_id"]
        cls = ROW_CLASSES[eid]
        req = r.get("request") or {}
        records.append({
            "task_id": eid,
            "question": r.get("question"),
            "route": r.get("gold_route"),
            "necessity": r.get("necessity"),
            "operation": req.get("operation"),
            "planner_request": {
                "parameters": req.get("parameters"),
                "source_inputs": req.get("source_inputs"),
                "parameter_provenance": req.get("parameter_provenance"),
                "expected_result_type": req.get("expected_result_type"),
            },
            "source_inputs": req.get("source_inputs"),
            "provenance": req.get("parameter_provenance"),
            "engine_status": r.get("envelope_status"),
            "raw_engine_result": None,   # T14 rows do not record the
            # envelope result payload; recorded status is the evidence
            "diagnostics": None,
            "adopted_value": r.get("adopted"),
            "adoption_taxonomy_instrument": r.get("adoption_taxonomy"),
            "final_answer": r.get("final_answer"),
            "expected": gold.get(eid, {}).get("expected"),
            "expected_tolerance": {
                "atol": gold.get(eid, {}).get("atol"),
                "rtol": gold.get(eid, {}).get("rtol")},
            "failure_class": cls["class"],
            "rationale": cls["rationale"],
            "instrument_fields": {
                "schema_status": r.get("schema_status"),
                "schema_failures": r.get("schema_failures"),
                "fidelity_status_instrument": r.get("fidelity_status"),
                "mutated": r.get("mutated"),
                "guard_blocked": r.get("guard_blocked"),
                "invoked": r.get("invoked"),
            },
        })

    hist = Counter(c["failure_class"] for c in records)
    in_scope = [c for c in records
                if c["failure_class"] in ("PROVENANCE_MISSING",
                                          "PROVENANCE_WRONG",
                                          "PLANNER_SCHEMA_FAILURE",
                                          "ENGINE_REJECT",
                                          "RESULT_MISREAD",
                                          "NUMERICAL_WARNING",
                                          "NO_INVOCATION")]
    doc = {
        "milestone": "T14R.2 — T14 numeric failure forensics",
        "source_run": "evaluations/t14/runs/t14a-scicomp-B",
        "numeric_rows": len(numeric),
        "numeric_correct": sum(1 for r in numeric if r.get("correct")),
        "numeric_accuracy": sum(1 for r in numeric if r.get("correct"))
        / len(numeric),
        "incorrect_rows": len(records),
        "taxonomy": TAXONOMY,
        "class_histogram": dict(Counter(
            c["failure_class"] for c in records)),
        "repair_scope": {
            "in_T14R_scope": len(in_scope),
            "out_of_scope_ids": [c["task_id"] for c in records
                                 if c["failure_class"] == "OTHER"],
            "note": "OTHER = benchmark gold-vs-given-input mismatch "
                    "(msc-v1-0030); not recoverable within frozen engine/"
                    "fidelity/no-benchmark-leak constraints",
        },
        "instrument_notes": [
            "T14 arm-B runner never records fidelity_status on the "
            "FIDELITY_FAIL branch (only mutated) — fidelity blocks "
            "appear as fidelity_status=None with the failure visible in "
            "raw_output_tail; verified by re-running the frozen "
            "check_fidelity on recorded requests",
            "T14's 'WRONG_ROUNDING 48' is an instrument artifact, not 48 "
            "display-rounding failures: 47 of the 48 WRONG_ROUNDING "
            "rows are graded CORRECT. classify_adoption requires every "
            "engine-result number to appear in the answer; padded "
            "engine payloads (e.g. eigenvalues [[5.0, 0.0], [2.0, "
            "0.0]] vs answer [5.0, 2.0]) fail that strict matcher and "
            "fall to the 5e-3 relative branch, relabeling correct "
            "adoptions. Only 2 PASS-envelope rows are actually "
            "incorrect (msc-v1-0030 gold-vs-input mismatch, "
            "msc-v1-0099 result misread)",
        ],
        "rows": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(doc["class_histogram"], indent=1))
    print(f"records: {len(records)} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())