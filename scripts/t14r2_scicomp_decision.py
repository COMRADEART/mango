"""T14R2.14-2.17 — ODE subset replay evidence, promotion critical gates,
and the T14R2.17 SciComp decision (exactly one of PROMOTE / KEEP /
REJECT — never pre-selected from the estimated 0.862).

Reads the official frozen recheck run (t14r2-scicomp-B3) produced by
scripts/t14r2_scicomp_eval.py over the unchanged frozen suite
(mango-scicomp-eval-v1) and the T14R baseline run (t14r-scicomp-B2).

Critical gates (T14R2.16, mirroring the T14R gate set):
  numeric_floor                 0.848 (unalterable)
  adoption_floor                0.90
  conceptual_discipline         1.0
  adversarial_handled           0.96
  silent_mutations              0
  fidelity_false_acceptance     0
  pipeline_exceptions           0
  ode_regression                0 previously-correct ODE rows lost

Decision rule (same as T14R):
  all criticals pass  -> PROMOTE_SCICOMP_LAB
  numeric >= 0.5 and exactly the numeric floor fails (or >1 critical
  fails with all non-numeric passing) -> KEEP_SCICOMP_EXPERIMENTAL
  numeric < 0.5 or fidelity false-acceptance / silent mutation -> REJECT
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

B2 = ROOT / "evaluations/t14r/runs/t14r-scicomp-B2/predictions.jsonl"
B3 = ROOT / "evaluations/t14r2/runs/t14r2-scicomp-B3/predictions.jsonl"
B3_SUMMARY = ROOT / "evaluations/t14r2/runs/t14r2-scicomp-B3/summary.json"
OUT_DECISION = ROOT / "evaluations/t14r2/scicomp_decision.json"
OUT_SUBSET = ROOT / "evaluations/t14r2/ode_subset_replay.json"

# the 16 ODE-route rows of the frozen suite (first-order solve_ode rows
# 0075-0080 + 0086, the six frozen failures, the second-order audit row
# 0085, and the two adversarial ODE rows)
ODE_IDS = [f"msc-v1-{i:04d}" for i in range(75, 89)] + \
    ["msc-v1-0182", "msc-v1-0195"]
SIX = ["msc-v1-0081", "msc-v1-0082", "msc-v1-0083", "msc-v1-0084",
       "msc-v1-0087", "msc-v1-0088"]
AUDIT = "msc-v1-0085"


def load_jsonl(path: Path) -> dict[str, dict]:
    return {r["eval_id"]: r for r in
            (json.loads(ln) for ln in
             path.read_text(encoding="utf-8").splitlines() if ln.strip())}


def main() -> int:
    b2 = load_jsonl(B2)
    b3 = load_jsonl(B3)
    summary = json.loads(B3_SUMMARY.read_text(encoding="utf-8"))

    # ---- T14R2.14: ODE subset replay (no material regression) ----
    subset_rows = []
    regressions = []
    for tid in ODE_IDS:
        old, new = b2.get(tid) or {}, b3.get(tid) or {}
        was, now = bool(old.get("correct")), bool(new.get("correct"))
        if was and not now:
            regressions.append(tid)
        subset_rows.append({
            "eval_id": tid, "b2_correct": was, "b3_correct": now,
            "changed": was != now,
            "ode_intent_fired": bool((new.get("ode_intent") or {}).get(
                "fired")),
            "b3_final_answer": new.get("final_answer"),
            "b2_final_answer": old.get("final_answer"),
        })
    recovered_six = [tid for tid in SIX if (b3.get(tid) or {}).get("correct")]
    audit_now = bool((b3.get(AUDIT) or {}).get("correct"))
    subset_doc = {
        "milestone": "T14R2.14 — full ODE subset replay",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "subset_ids": ODE_IDS,
        "rows": subset_rows,
        "six_recovered": recovered_six,
        "six_recovered_count": len(recovered_six),
        "second_order_audit_correct": audit_now,
        "regressions": regressions,
        "no_material_regression": not regressions,
    }
    OUT_SUBSET.write_text(json.dumps(subset_doc, indent=2,
                                     ensure_ascii=False) + "\n",
                          encoding="utf-8")

    # ---- T14R2.16: promotion critical gates ----
    # T14R instrument convention: a "silent mutation" is a flagged
    # mutation that nonetheless executed to a PASS envelope (the runner
    # sets `mutated` only on fidelity-gate rejection, so this should be
    # structurally impossible; the mutation-safety probe is the second
    # instrument). fidelity false-acceptance shares the measurement.
    silent = sum(1 for r in b3.values()
                 if r.get("mutated") and r.get("envelope_status") == "PASS")
    numeric = summary.get("numeric_accuracy")
    gates = {
        "numeric_floor": {
            "measured": numeric, "target": 0.848,
            "status": "PASS" if numeric is not None and numeric >= 0.848
            else "FAIL"},
        "adoption_floor": {
            "measured": summary.get("model_adoption_rate"), "target": 0.90,
            "status": "PASS" if (summary.get("model_adoption_rate") or 0)
            >= 0.90 else "FAIL"},
        "conceptual_discipline": {
            "measured": summary.get("conceptual_discipline"), "target": 1.0,
            "status": "PASS" if summary.get("conceptual_discipline") == 1.0
            else "FAIL"},
        "adversarial_handled": {
            "measured": summary.get("adversarial_handled_correctly"),
            "target": 0.96,
            "status": "PASS" if (summary.get("adversarial_handled_correctly")
                                 or 0) >= 0.96 else "FAIL"},
        "silent_mutations": {
            "measured": silent, "target": 0,
            "status": "PASS" if silent == 0 else "FAIL"},
        "fidelity_false_acceptance": {
            "measured": silent, "target": 0,
            "status": "PASS" if silent == 0 else "FAIL"},
        "pipeline_exceptions": {
            "measured": summary.get("pipeline_exception_count"), "target": 0,
            "status": "PASS" if not summary.get(
                "pipeline_exception_count") else "FAIL"},
        "ode_regression": {
            "measured": len(regressions), "target": 0,
            "status": "PASS" if not regressions else "FAIL"},
    }
    critical_fails = [k for k, g in gates.items() if g["status"] == "FAIL"]

    numeric_val = numeric or 0.0
    if not critical_fails:
        decision = "PROMOTE_SCICOMP_LAB"
    elif numeric_val >= 0.5 and critical_fails == ["numeric_floor"]:
        decision = "KEEP_SCICOMP_EXPERIMENTAL"
    elif "fidelity_false_acceptance" in critical_fails \
            or "silent_mutations" in critical_fails or numeric_val < 0.5:
        decision = "REJECT_SCICOMP"
    else:
        decision = "KEEP_SCICOMP_EXPERIMENTAL"

    doc = {
        "milestone": "T14R2.16-2.17 — promotion critical gates and decision",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_run": "evaluations/t14r2/runs/t14r2-scicomp-B3",
        "baseline_run": "evaluations/t14r/runs/t14r-scicomp-B2",
        "suite_sha256": summary.get("suite_sha256"),
        "numeric_accuracy": numeric,
        "t14r_numeric": 113 / 138,
        "promotion_floor": 0.848,
        "gates": gates,
        "critical_failures": critical_fails,
        "decision": decision,
        "decision_rule": ("all criticals pass -> PROMOTE; numeric >= 0.5 "
                          "with only the numeric floor failing -> KEEP; "
                          "silent mutation / fidelity false-acceptance / "
                          "numeric < 0.5 -> REJECT"),
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "training": "NONE",
        "ode_subset_replay": "evaluations/t14r2/ode_subset_replay.json",
    }
    OUT_DECISION.write_text(json.dumps(doc, indent=2, ensure_ascii=False)
                            + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision,
                      "numeric": numeric,
                      "critical_failures": critical_fails,
                      "six_recovered": subset_doc["six_recovered_count"],
                      "regressions": regressions}, indent=2))
    print(f"-> {OUT_DECISION}\n-> {OUT_SUBSET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())