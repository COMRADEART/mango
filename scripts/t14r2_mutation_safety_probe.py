"""T14R2 (layer inserted) mutation-safety probe — the repair layer must NOT weaken
the frozen fidelity gates.

Replays every fidelity-v1 mutation (params = mutated_inputs, srcs =
faithful_inputs, exactly as t13_replay_fidelity_suite.py constructs
them) through repair_planner_request FIRST, then the frozen
validate_planner_request + check_fidelity. Every mutation must still be
rejected; faithful rows must classify without exception.

Also replays the fidelity-transform suite the same way.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.fidelity import (  # noqa: E402
    FIDELITY_FAIL, P_USER_GIVEN, check_fidelity, validate_planner_request)
from sciencemath.scicomp.ode_intent import select_ode_operation  # noqa: E402
from sciencemath.scicomp.planner_repair import (  # noqa: E402
    repair_planner_request)


def t14r2_layer_then_repair(request: dict, question: str) -> dict:
    """The exact T14R2 runner order: ODE intent layer FIRST, then the
    frozen repair. Proves the new layer does not weaken the gates."""
    res = select_ode_operation(request, question)
    if res is not None:
        request = res["request"]
    return repair_planner_request(request, question)

SUITES = [
    ("fidelity", ROOT / "evaluations/t12/suites/fidelity/v1"),
    ("fidelity_transform",
     ROOT / "evaluations/t13/suites/fidelity-transform/v1"),
]
OUT = ROOT / "evaluations/t14r2/mutation_safety_probe.json"


def replay_suite(name: str, suite_dir: Path) -> dict:
    rows = [json.loads(l) for l in
            (suite_dir / "questions.jsonl").read_text(encoding="utf-8")
            .splitlines() if l.strip()]
    muts, faithful, exceptions = [], [], []
    for it in rows:
        if it.get("mutating_inputs"):
            request = {
                "operation": it["operation"],
                "compute_required": True,
                "parameters": it["mutating_inputs"],
                "source_inputs": it["faithful_inputs"],
                "parameter_provenance": {k: P_USER_GIVEN
                                         for k in it["mutating_inputs"]},
                "expected_result_type": "scalar",
                "reason_for_compute": "T14R2 mutation-safety probe",
            }
            try:
                rep = t14r2_layer_then_repair(request, it["question"])
                sch = validate_planner_request(rep["request"])
                if sch["ok"]:
                    r = check_fidelity(rep["request"], it["question"])
                    rejected = r.status == FIDELITY_FAIL
                    failures = r.failures[:4]
                else:
                    rejected = True   # schema gate rejection is a reject
                    failures = sch["failures"][:4]
                muts.append({"eval_id": it["eval_id"],
                             "category": it["category"],
                             "rejected": rejected,
                             "failures": failures})
            except Exception as exc:
                exceptions.append(f"{it['eval_id']}: "
                                  f"{type(exc).__name__}: {exc}")
        elif it.get("faithful_inputs"):
            request = {
                "operation": it["operation"],
                "compute_required": True,
                "parameters": it["faithful_inputs"],
                "source_inputs": it["faithful_inputs"],
                "parameter_provenance": {k: P_USER_GIVEN
                                         for k in it["faithful_inputs"]},
                "expected_result_type": "scalar",
                "reason_for_compute": "T14R2 mutation-safety probe",
            }
            try:
                rep = t14r2_layer_then_repair(request, it["question"])
                sch = validate_planner_request(rep["request"])
                if sch["ok"]:
                    r = check_fidelity(rep["request"], it["question"])
                    status = r.status
                else:
                    status = "SCHEMA_FAIL:" + ";".join(
                        sch["failures"][:2])
                faithful.append({"eval_id": it["eval_id"],
                                 "kind": it["kind"], "status": status})
            except Exception as exc:
                exceptions.append(f"{it['eval_id']} faithful: "
                                  f"{type(exc).__name__}: {exc}")
    n_rej = sum(1 for m in muts if m["rejected"])
    return {"suite": name, "n_mutations": len(muts),
            "mutations_still_rejected": n_rej,
            "faithful_n": len(faithful),
            "exceptions": exceptions,
            "mutation_results": muts,
            "faithful_results": faithful,
            "passed": n_rej == len(muts) and not exceptions}


def main() -> int:
    out = {"milestone": "T14R2 (layer inserted) mutation-safety probe",
           "suites": [], "passed": True}
    for name, d in SUITES:
        r = replay_suite(name, d)
        out["suites"].append(r)
        print(f"{name}: mutations {r['mutations_still_rejected']}/"
              f"{r['n_mutations']} rejected, faithful {r['faithful_n']}, "
              f"exceptions {len(r['exceptions'])} -> "
              f"{'PASS' if r['passed'] else 'FAIL'}")
        if not r["passed"]:
            for m in r["mutation_results"]:
                if not m["rejected"]:
                    print("  SLIPPED:", m["eval_id"], m["category"],
                          m["failures"])
            for e in r["exceptions"]:
                print("  EXC:", e)
    out["passed"] = all(s["passed"] for s in out["suites"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("overall:", "PASS" if out["passed"] else "FAIL", "->", OUT)
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())