"""T14.9 — SciComp promotion decision from frozen gates only.

Does not average metrics. One critical failure means no promotion.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUM = ROOT / "evaluations/t14/runs/t14a-scicomp-B/summary.json"
FID = ROOT / "evaluations/t14/runs/t14a-fidelity-B/summary.json"
OUT = ROOT / "evaluations/t14/scicomp_decision.json"

NUMERIC_FLOOR = 0.848
ADOPTION_FLOOR = 0.90
CONCEPTUAL_FLOOR = 1.0
ADVERSARIAL_FLOOR = 0.92
T11_NUMERIC = 0.8478260869565217
T12_NUMERIC = 0.7028985507246377
T13_NUMERIC = 0.7463768115942029


def main() -> int:
    if not SUM.exists():
        raise SystemExit(f"missing {SUM}")
    s = json.loads(SUM.read_text(encoding="utf-8"))
    fid = json.loads(FID.read_text(encoding="utf-8")) if FID.exists() else {}
    silent = fid.get("silent_mutation_pass_count")
    if silent is None:
        silent = 0
        pred = ROOT / "evaluations/t14/runs/t14a-scicomp-B/predictions.jsonl"
        if pred.exists():
            for line in pred.read_text(encoding="utf-8").splitlines():
                if line.strip() and json.loads(line).get("silent_mutation_pass"):
                    silent += 1
    false_accept = silent  # mutated request executed to PASS
    gates = [
        {"gate": "numeric_floor", "critical": True,
         "measured": s.get("numeric_accuracy"),
         "floor": NUMERIC_FLOOR,
         "pass": (s.get("numeric_accuracy") or 0) >= NUMERIC_FLOOR},
        {"gate": "adoption", "critical": True,
         "measured": s.get("model_adoption_rate"),
         "floor": ADOPTION_FLOOR,
         "pass": (s.get("model_adoption_rate") or 0) >= ADOPTION_FLOOR},
        {"gate": "conceptual_discipline", "critical": True,
         "measured": s.get("conceptual_discipline"),
         "floor": CONCEPTUAL_FLOOR,
         "pass": (s.get("conceptual_discipline") or 0) >= CONCEPTUAL_FLOOR - 1e-12},
        {"gate": "adversarial_handled", "critical": True,
         "measured": s.get("adversarial_handled_correctly"),
         "floor": ADVERSARIAL_FLOOR,
         "pass": (s.get("adversarial_handled_correctly") or 0) >= ADVERSARIAL_FLOOR},
        {"gate": "silent_mutation", "critical": True,
         "measured": silent,
         "floor": 0,
         "pass": silent == 0},
        {"gate": "fidelity_false_acceptance", "critical": True,
         "measured": false_accept,
         "floor": 0,
         "pass": false_accept == 0},
        {"gate": "pipeline_exceptions", "critical": True,
         "measured": s.get("pipeline_exception_count", 0),
         "floor": 0,
         "pass": (s.get("pipeline_exception_count") or 0) == 0},
    ]
    critical_fails = [g["gate"] for g in gates if g["critical"] and not g["pass"]]
    if critical_fails:
        if (s.get("numeric_accuracy") or 0) < 0.5:
            decision = "REJECT_SCICOMP"
        else:
            decision = "KEEP_SCICOMP_EXPERIMENTAL"
    else:
        decision = "PROMOTE_SCICOMP_LAB"
    doc = {
        "milestone": "T14.9 SciComp decision",
        "decision": decision,
        "weight_promotion": "NO",
        "t11_numeric": T11_NUMERIC,
        "t12_numeric": T12_NUMERIC,
        "t13_numeric": T13_NUMERIC,
        "t14_numeric": s.get("numeric_accuracy"),
        "adoption": s.get("model_adoption_rate"),
        "conceptual": s.get("conceptual_discipline"),
        "adversarial": s.get("adversarial_handled_correctly"),
        "adversarial_false_answer_rate": s.get("adversarial_false_answer_rate"),
        "silent_mutations": silent,
        "exceptions": s.get("pipeline_exception_count", 0),
        "valid_call_rate": s.get("valid_call_rate"),
        "engine_success": s.get("compute_success_rate"),
        "over_compute": s.get("over_compute_rate"),
        "invocations": s.get("invocations"),
        "suite_sha256": s.get("suite_sha256"),
        "model": s.get("model"),
        "label": s.get("label"),
        "gates": gates,
        "critical_fails": critical_fails,
        "rule": "One critical failure means no promotion. No averaging.",
        "fidelity_suite_present": FID.exists(),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items() if k != "gates"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
