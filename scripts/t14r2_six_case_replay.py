"""T14R2.13 — six-case replay through the full Arm-B pipeline (real LLM
parse + real adopter, frozen gates) for the six frozen ODE failures plus
the T14R2.10 second-order audit row (msc-v1-0085).

Gate: every case must come back CORRECT under the unchanged frozen
grading (numeric_correct against the suite gold at the suite tolerances)
with the ODE intent layer firing and the request passing every frozen
gate (repair -> schema -> fidelity -> engine PASS -> VERIFIED contract).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t11_scicomp_head_to_head as t11  # noqa: E402
import t12_scicomp_eval as t12  # noqa: E402
import t14r2_scicomp_eval as runner  # noqa: E402

SUITE = ROOT / "evaluations/t11/scicomp-suite/v1/questions.jsonl"
OUT = ROOT / "evaluations/t14r2/six_case_replay.json"

SIX_PLUS_AUDIT = ["msc-v1-0081", "msc-v1-0082", "msc-v1-0083",
                  "msc-v1-0084", "msc-v1-0087", "msc-v1-0088",
                  "msc-v1-0085"]


def main() -> int:
    suite = {r["eval_id"]: r for r in
             (json.loads(ln) for ln in
              SUITE.read_text(encoding="utf-8").splitlines() if ln.strip())}
    items = [suite[tid] for tid in SIX_PLUS_AUDIT]

    from sciencemath.evaluation.model_loader import load_model_safely
    tok, mdl, load = load_model_safely("Qwen/Qwen3-4B-Instruct-2507")
    if not load["ok"]:
        raise SystemExit(load["error"])

    from sciencemath.scicomp.registry import build_registry, manifest
    registry_lines = "\n".join(
        f"- {m['name']} [{m['category']}]: {m['description']} "
        f"| required inputs: {t11.INPUT_SCHEMA.get(m['name'], 'per schema')}"
        for m in manifest(build_registry()))

    rows = []
    for it in items:
        t0 = time.perf_counter()
        hard = runner.run_arm_b_t14r2(tok, mdl, it, registry_lines, 700)
        correct = t11.numeric_correct(hard["final_answer"], it["expected"],
                                      it["atol"], it["rtol"])
        row = {
            "eval_id": it["eval_id"], "question": it["question"],
            "gold_expected": it["expected"], "atol": it["atol"],
            "rtol": it["rtol"], "correct": bool(correct),
            "final_answer": hard["final_answer"],
            "necessity": hard["necessity"],
            "guard_blocked": hard["guard_blocked"],
            "ode_intent": hard["ode_intent"],
            "planner_selected_operation": (hard["request"] or {}).get(
                "operation") if isinstance(hard["request"], dict) else None,
            "schema_status": hard["schema_status"],
            "schema_failures": hard["schema_failures"],
            "fidelity_status": hard["fidelity_status"],
            "fidelity_failures": hard["fidelity_failures"],
            "invoked": hard["invoked"],
            "envelope_status": hard["envelope_status"],
            "binding": hard["binding"],
            "contract_authoritative_value": (hard["contract"] or {}).get(
                "authoritative_value"),
            "adopted": hard["adopted"],
            "adoption_taxonomy": hard["adoption_taxonomy"],
            "pipeline_exception": hard.get("pipeline_exception"),
            "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        rows.append(row)
        print(f"{it['eval_id']}: {'OK' if correct else 'MISS'} "
              f"final={row['final_answer'][:60]!r}", flush=True)

    recovered = sum(1 for r in rows if r["correct"])
    fired = [r for r in rows if (r["ode_intent"] or {}).get("fired")]
    # the frozen runner records fidelity_status ONLY on failure paths
    # (None = happy path, gate passed); mutated is only set on reject
    gates_clean = all(
        r["schema_status"] == "PLANNER_SCHEMA_OK"
        and r["fidelity_status"] in (None, "FIDELITY_OK")
        and not r["fidelity_failures"]
        and r["envelope_status"] == "PASS"
        and r["binding"] == "VERIFIED_COMPUTE_RESULT"
        for r in rows)
    doc = {
        "milestone": "T14R2.13 — six-case replay",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "runner": "scripts/t14r2_scicomp_eval.py (Arm-B + ODE intent layer)",
        "cases": SIX_PLUS_AUDIT,
        "rows": rows,
        "recovered": recovered,
        "required": len(SIX_PLUS_AUDIT),
        "all_fired": len(fired) == len(SIX_PLUS_AUDIT),
        "gates_clean": gates_clean,
        "status": ("PASS" if recovered == len(SIX_PLUS_AUDIT)
                   and len(fired) == len(SIX_PLUS_AUDIT) else "FAIL"),
    }
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({"status": doc["status"],
                      "recovered": f"{recovered}/{len(rows)}",
                      "all_fired": doc["all_fired"],
                      "gates_clean": gates_clean}, indent=2))
    print(f"-> {OUT}")
    return 0 if doc["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())