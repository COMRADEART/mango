"""T14R2.1/T14R2.2 — freeze the six ODE planner operation-selection
failures from the T14R frozen recheck (run t14r-scicomp-B2) and classify
them.

Source of truth: evaluations/t14r/runs/t14r-scicomp-B2/predictions.jsonl
(numeric accuracy 0.8188405797101449 = 113/138; 25 incorrect numeric
rows). The T14R final report identifies the dominant recoverable block:
6 ODE final-state questions routed to the wrong operation (5 x
definite_integral, 1 x minimize) instead of solve_ode.

The freeze is written BEFORE any code change and is never edited after
repair (no relabeling of expected outcomes).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

B2 = ROOT / "evaluations/t14r/runs/t14r-scicomp-B2/predictions.jsonl"
RUN_B = ROOT / "evaluations/t14r/runs/t14r-scicomp-B/predictions.jsonl"
RUN_T14 = ROOT / "evaluations/t14/runs/t14a-scicomp-B/predictions.jsonl"
SUITE = ROOT / "evaluations/t11/scicomp-suite/v1/questions.jsonl"
OUT_FREEZE = ROOT / "evaluations/t14r2/ode_failure_freeze.json"
OUT_ANALYSIS = ROOT / "evaluations/t14r2/ode_failure_analysis.json"

# the six operation-selection failures (T14R final report: 6 of the 25
# incorrect numeric rows in B2 are ODE planner-operation-selection
# failures). msc-v1-0085 selected the CORRECT operation (solve_ode) and
# failed request construction (second-order equation, string 'pi/2');
# it is captured separately as the T14R2.10 higher-order audit row.
SIX = ["msc-v1-0081", "msc-v1-0082", "msc-v1-0083", "msc-v1-0084",
       "msc-v1-0087", "msc-v1-0088"]
AUDIT_SECOND_ORDER = "msc-v1-0085"

TAXONOMY = {
    "msc-v1-0081": {
        "failure_taxonomy": "WRONG_ODE_OPERATION",
        "expected_operation": "solve_ode",
        "rationale": "dP/dt = 0.3*P, P(0)=2, evaluate P(5): the planner "
                     "routed the IVP to definite_integral of the rate "
                     "0.3*P over [0,5] (accumulated change 3.75), not "
                     "the solution P(t)=2*e^{0.3t} (gold 8.9634). The "
                     "engine PASSed and the adopter adopted the "
                     "verified-but-wrong-quantity value.",
    },
    "msc-v1-0082": {
        "failure_taxonomy": "WRONG_ODE_OPERATION",
        "expected_operation": "solve_ode",
        "rationale": "Verbal exponential-decay IVP (rate constant 0.02, "
                     "initial mass 10 g, evaluate at 100 y): the planner "
                     "restated the ANALYTIC SOLUTION 10*exp(-0.02*t) as "
                     "an integrand over [0,100] (432.33) instead of "
                     "requesting solve_ode (gold 1.3534 = 10*e^-2).",
    },
    "msc-v1-0083": {
        "failure_taxonomy": "WRONG_ODE_OPERATION",
        "expected_operation": "solve_ode",
        "rationale": "dQ/dt = -Q/3, Q(0)=9, evaluate Q(6): planner "
                     "derived the closed-form solution 9*exp(-t/3) and "
                     "sent it as a definite_integral integrand (23.346 "
                     "= accumulated change) instead of solve_ode (gold "
                     "1.2180 = 9*e^-2).",
    },
    "msc-v1-0084": {
        "failure_taxonomy": "WRONG_ODE_OPERATION",
        "expected_operation": "solve_ode",
        "rationale": "Capacitor discharge dV/dt = -V/RC, RC=2 s, "
                     "V(0)=12 V, evaluate V(4): planner restated the "
                     "closed form 12*exp(-t/2) as an integrand (20.75) "
                     "instead of solve_ode (gold 1.6240 = 12*e^-2).",
    },
    "msc-v1-0087": {
        "failure_taxonomy": "WRONG_ODE_OPERATION",
        "expected_operation": "solve_ode",
        "rationale": "dv/dt = 9.8, v(0)=0, evaluate v(3): planner chose "
                     "minimize on 9.8*t (wrong operation family "
                     "entirely) and string-typed bounds; the request "
                     "failed the schema gate. Correct: solve_ode with "
                     "equations ['9.8'], initial_state [0], t_end 3 "
                     "(gold 29.4).",
    },
    "msc-v1-0088": {
        "failure_taxonomy": "WRONG_ODE_OPERATION",
        "expected_operation": "solve_ode",
        "rationale": "dN/dt = r*N, r=0.07, N(0)=1000, evaluate N(10): "
                     "planner sent definite_integral of 0.07*N over "
                     "[0,10] (3.5, then rounded to 4) instead of "
                     "solve_ode (gold 2013.75 = 1000*e^0.7).",
    },
}


def load_jsonl(path: Path) -> dict[str, dict]:
    return {
        row["eval_id"]: row
        for row in (json.loads(ln) for ln in
                    path.read_text(encoding="utf-8").splitlines()
                    if ln.strip())
    }


def main() -> int:
    b2 = load_jsonl(B2)
    run_b = load_jsonl(RUN_B)
    run_t14 = load_jsonl(RUN_T14)
    suite = load_jsonl(SUITE)

    wrong = [r for r in b2.values()
             if r.get("kind") in ("numeric_oracle", "mixed")
             and not r.get("correct")]
    assert len(wrong) == 25, \
        f"expected 25 wrong numeric rows, got {len(wrong)}"

    frozen: list[dict] = []
    for tid in SIX:
        r = b2[tid]
        s = suite[tid]
        req = r.get("request") or {}
        contract = r.get("contract") or {}
        rb = run_b.get(tid) or {}
        rt = run_t14.get(tid) or {}
        frozen.append({
            "task_id": tid,
            "question": r["question"],
            "source_inputs": req.get("source_inputs"),
            "expected_task_type": {
                "kind": r.get("kind"),
                "gold_route": r.get("gold_route"),
                "answer_type": s.get("answer_type"),
                "needs_compute": s.get("needs_compute"),
                "gold_expected": s.get("expected"),
                "atol": s.get("atol"), "rtol": s.get("rtol"),
            },
            "current_route": r.get("gold_route"),
            "current_necessity_class": r.get("necessity"),
            "planner_selected_operation": req.get("operation"),
            "expected_operation": TAXONOMY[tid]["expected_operation"],
            "planner_request": req,
            "provenance": req.get("parameter_provenance"),
            "scicomp_engine_status": r.get("envelope_status"),
            "raw_engine_result": (
                {"note": "raw engine payload not retained by the frozen "
                         "runner; the verified envelope's authoritative "
                         "value is recorded instead",
                 "verified_authoritative_value":
                     contract.get("authoritative_value"),
                 "invoked": r.get("invoked"),
                 "adoption_taxonomy": r.get("adoption_taxonomy")}),
            "adopted_result": r.get("adopted"),
            "final_answer": r.get("final_answer"),
            "failure_taxonomy": TAXONOMY[tid]["failure_taxonomy"],
            "rationale": TAXONOMY[tid]["rationale"],
            "outcome_history": {
                "t14_armB_correct": rt.get("correct"),
                "t14_armB_operation": (rt.get("request") or {}).get(
                    "operation"),
                "t14r_armB_correct": rb.get("correct"),
                "t14r_armB_operation": (rb.get("request") or {}).get(
                    "operation"),
                "t14r2_b2_correct": r.get("correct"),
                "t14r2_b2_operation": req.get("operation"),
            },
        })

    freeze_doc = {
        "milestone": "T14R2.1 — frozen ODE planner operation-selection "
                     "failures",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_run": "evaluations/t14r/runs/t14r-scicomp-B2",
        "source_run_numeric_accuracy": 113 / 138,
        "source_run_wrong_numeric_rows": len(wrong),
        "frozen_failure_count": len(SIX),
        "frozen_before_any_code_change": True,
        "relabeling_prohibited": "expected outcomes and gold values come "
                                 "from the frozen suite "
                                 "(mango-scicomp-eval-v1, sha256 "
                                 "e6e3f04839c5cd0caa3f319e5c32ca511371c00"
                                 "a040eed25756e328a3aabf0f1) and are "
                                 "recorded verbatim; no expected outcome "
                                 "may be relabeled after repair",
        "suite_row_expected_values": {tid: suite[tid].get("expected")
                                      for tid in SIX},
        "cases": frozen,
    }
    OUT_FREEZE.write_text(json.dumps(freeze_doc, indent=2,
                                     ensure_ascii=False) + "\n",
                          encoding="utf-8")

    # ---- T14R2.2 taxonomy analysis ----
    audit = b2[AUDIT_SECOND_ORDER]
    analysis_doc = {
        "milestone": "T14R2.2 — ODE failure taxonomy",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "method": "per-case forensic classification over the B2 recorded "
                  "planner request, schema/fidelity instrument fields, "
                  "envelope status, and grading outcome; no code changes "
                  "made before this analysis",
        "allowed_categories": [
            "WRONG_ODE_OPERATION", "IVP_MISCLASSIFIED",
            "BOUNDARY_VALUE_CONFUSION", "MISSING_INITIAL_STATE",
            "MISSING_TIME_SPAN", "STATE_ORDER_MISMATCH",
            "DERIVATIVE_EXPRESSION_MISBOUND", "SCHEMA_CONSTRUCTION_FAILURE",
            "PROVENANCE_FAILURE", "MODEL_DECLINED_COMPUTE", "OTHER"],
        "taxonomy_histogram": {"WRONG_ODE_OPERATION": 6},
        "single_cause_assumption": False,
        "finding": (
            "All six share one measurable mechanism — the planner "
            "selected a non-solve_ode operation for a fully-specified "
            "initial-value problem — but they arrive there by two "
            "distinct routes that the repair must handle separately: "
            "(a) explicit derivative-notation IVPs (0081, 0083, 0084, "
            "0087, 0088) routed to definite_integral/minimize of the "
            "rate function, and (b) a VERBAL decay IVP (0082) where the "
            "planner derived the analytic closed form and sent it as an "
            "integrand. In all six the extracted numbers are "
            "question-verbatim and every downstream frozen layer "
            "(repair, schema, fidelity, engine, envelope, adopter) "
            "behaves correctly — the failure is purely the operation "
            "choice at structured-request construction."),
        "sub_patterns": {
            "explicit_derivative_notation_routed_to_integral": [
                "msc-v1-0081", "msc-v1-0083", "msc-v1-0084", "msc-v1-0088"],
            "explicit_derivative_notation_routed_to_optimization": [
                "msc-v1-0087"],
            "verbal_decay_law_restated_as_closed_form_integrand": [
                "msc-v1-0082"],
        },
        "higher_order_audit_T14R2_10": {
            "task_id": AUDIT_SECOND_ORDER,
            "question": audit["question"],
            "planner_selected_operation": "solve_ode",
            "operation_selection_correct": True,
            "not_an_operation_selection_failure": True,
            "observed_failure": (
                "second-order ODE d2x/dt2 = -4*x sent to solve_ode as a "
                "non-RHS equation string 'd2x/dt2 + 4*x = 0' with "
                "string-typed t_end 'pi/2' and an unused decorative "
                "parameters dict; schema gate failed; no invocation"),
            "engine_capability_audit": (
                "The frozen engine (ode.solve_ode) natively integrates "
                "systems of FIRST-order RHS expressions in y0..y{n-1}. "
                "It has no second-order entry point; a second-order IVP "
                "is expressible ONLY via deterministic first-order-system "
                "conversion at request construction (y0=x, y1=dx/dt => "
                "equations ['y1', '-4*y0'], initial_state [1, 0]) — a "
                "planner-side deterministic derivation, not a new engine "
                "capability. Disposition recorded in "
                "higher_order_disposition below."),
            "outcome_history": {
                "t14_armB_correct": (run_t14.get(AUDIT_SECOND_ORDER)
                                     or {}).get("correct"),
                "t14r_armB_correct": (run_b.get(AUDIT_SECOND_ORDER)
                                      or {}).get("correct"),
                "t14r2_b2_correct": audit.get("correct"),
            },
        },
        "remaining_wrong_rows_context": (
            "The other 19 of 25 wrong numeric rows in B2 are: 1 gold-vs-"
            "given-input mismatch (msc-v1-0030, out of scope since T14R), "
            "1 dropped-exponent mutation misread (msc-v1-0099), 5 no-"
            "invocation fail-closed rows, 9 engine-not-PASS rows, 2 "
            "RESULT_IGNORED/MISREAD statistics rows, 1 no-compute "
            "parameter-sweep row, 3 speed-of-light NO_COMPUTE rows, 2 "
            "describe-mode statistics rows — none is an ODE "
            "operation-selection failure and all are outside T14R2 "
            "scope."),
        "no_implementation_changes_before_this_analysis": True,
    }
    OUT_ANALYSIS.write_text(json.dumps(analysis_doc, indent=2,
                                       ensure_ascii=False) + "\n",
                            encoding="utf-8")

    print(f"froze {len(frozen)} cases -> {OUT_FREEZE}")
    print(f"taxonomy analysis -> {OUT_ANALYSIS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())