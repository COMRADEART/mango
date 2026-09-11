"""T14R.17 — SciComp promotion decision from frozen gates only.

Mirrors scripts/t14_scicomp_decision.py; reads the T14R replay
(t14r-scicomp-B) and the frozen adoption microbench. Does not average
metrics. ONE failed critical gate = no promotion.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUM = ROOT / "evaluations/t14r/runs/t14r-scicomp-B/summary.json"
OUT = ROOT / "evaluations/t14r/scicomp_decision.json"

NUMERIC_FLOOR = 0.848
ADOPTION_FLOOR = 0.90
CONCEPTUAL_FLOOR = 1.0
ADVERSARIAL_FLOOR = 0.96
T14_NUMERIC = 0.7318840579710145
T14_ADOPTION = 0.9863013698630136


def main() -> int:
    if not SUM.exists():
        raise SystemExit(f"missing {SUM} — replay not finished")
    s = json.loads(SUM.read_text(encoding="utf-8"))
    silent = s.get("silent_mutation_pass_count", 0) or 0
    if not silent:
        pred = ROOT / "evaluations/t14r/runs/t14r-scicomp-B/predictions.jsonl"
        if pred.exists():
            silent = sum(
                1 for line in pred.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("silent_mutation_pass"))
    false_accept = silent
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
    critical_fails = [g["gate"] for g in gates
                      if g["critical"] and not g["pass"]]
    if critical_fails:
        if (s.get("numeric_accuracy") or 0) < 0.5:
            decision = "REJECT_SCICOMP"
        else:
            decision = "KEEP_SCICOMP_EXPERIMENTAL"
    else:
        decision = "PROMOTE_SCICOMP_LAB"
    doc = {
        "milestone": "T14R.17 SciComp decision",
        "decision": decision,
        "weight_promotion": "NO",
        "paid_compute": "NOT_USED",
        "t14_numeric": T14_NUMERIC,
        "t14r_numeric": s.get("numeric_accuracy"),
        "t14_adoption": T14_ADOPTION,
        "t14r_adoption": s.get("model_adoption_rate"),
        "gates": gates,
        "critical_fails": critical_fails,
        "rule": ("One failed critical gate = no promotion. REJECT only "
                 "when numeric < 0.5; KEEP otherwise."),
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision,
                      "critical_fails": critical_fails,
                      "t14r_numeric": s.get("numeric_accuracy"),
                      "t14r_adoption": s.get("model_adoption_rate")},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())