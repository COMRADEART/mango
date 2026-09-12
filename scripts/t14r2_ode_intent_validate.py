"""T14R2.4-2.10 offline validation — prove the ODE intent layer recovers
the six frozen failures BEFORE any GPU/LLM run, and prove it does not
disturb anything else.

For every suite row this script:
  1. runs select_ode_operation(B2 recorded planner request, question)
     to see whether the deterministic layer fires;
  2. for every FIRING row, pushes the constructed solve_ode request
     through the frozen pipeline exactly as the runner will:
     repair_planner_request -> validate_planner_request ->
     check_fidelity -> invoke -> verified_envelope -> result_contract,
     and compares the contract's authoritative value against the FROZEN
     suite gold (atol/rtol) — no LLM, no GPU, no benchmark edits.

Required outcomes (all hard asserts):
  * each of the six frozen failures (ode_failure_freeze.json) fires,
    passes every gate, and reproduces the suite gold;
  * the T14R2.10 second-order audit row (msc-v1-0085) fires via
    SECOND_ORDER_SYSTEM_CONVERSION and reproduces its gold;
  * every previously-CORRECT row that fires must ALSO reproduce its
    gold (no material regression introduced by the layer);
  * previously-wrong non-firing rows are unchanged (out of scope).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.fidelity import (
    FIDELITY_FAIL, check_fidelity, validate_planner_request)
from sciencemath.scicomp.invocation import invoke
from sciencemath.scicomp.ode_intent import (
    construct_solve_ode_request, recognize_ode_ivp, select_ode_operation)
from sciencemath.scicomp.planner_repair import repair_planner_request
from sciencemath.scicomp.adoption import verified_envelope
from sciencemath.scicomp.result_contract import result_contract

SUITE = ROOT / "evaluations/t11/scicomp-suite/v1/questions.jsonl"
B2 = ROOT / "evaluations/t14r/runs/t14r-scicomp-B2/predictions.jsonl"
FREEZE = ROOT / "evaluations/t14r2/ode_failure_freeze.json"
OUT = ROOT / "evaluations/t14r2/ode_intent_offline_validation.json"


def load_jsonl(path: Path) -> dict[str, dict]:
    return {
        row["eval_id"]: row
        for row in (json.loads(ln) for ln in
                    path.read_text(encoding="utf-8").splitlines()
                    if ln.strip())
    }


def within(value, gold, atol, rtol) -> bool:
    return abs(value - gold) <= atol + rtol * abs(gold)


def run_pipeline(request: dict, question: str) -> dict:
    """The exact frozen gate chain the runner applies, offline."""
    rep = repair_planner_request(request, question)
    fixed = rep["request"]
    schema = validate_planner_request(fixed)
    out = {"repair_changed": rep["changed"], "schema_ok": schema["ok"],
           "schema_failures": schema["failures"]}
    if not schema["ok"]:
        out["stage"] = "schema"
        return out
    fid = check_fidelity(fixed, question)
    out["fidelity_status"] = fid.status
    out["fidelity_failures"] = fid.failures
    if fid.status == FIDELITY_FAIL:
        out["stage"] = "fidelity"
        return out
    result = invoke({"operation": fixed["operation"],
                     "inputs": fixed.get("parameters") or {}},
                    question=question)
    out["invoked"] = True
    out["envelope_status"] = result.envelope.get("status")
    env_doc = verified_envelope(result.envelope, fid.source_parameter_hash)
    out["binding"] = env_doc["binding"]
    contract = result_contract(env_doc, fixed, question,
                               fixed.get("expected_result_type"))
    out["contract"] = contract
    out["stage"] = "done"
    return out


def main() -> int:
    suite = load_jsonl(SUITE)
    b2 = load_jsonl(B2)
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    six = [c["task_id"] for c in freeze["cases"]]
    audit_id = "msc-v1-0085"

    rows: list[dict] = []
    fired_ids: list[str] = []

    for tid, s in suite.items():
        q = s.get("question") or ""
        req = (b2.get(tid) or {}).get("request")
        res = select_ode_operation(req, q)
        rec = {"task_id": tid, "kind": s.get("kind"),
               "b2_correct": (b2.get(tid) or {}).get("correct"),
               "recognized": recognize_ode_ivp(q) is not None,
               "fired": bool(res)}
        if res:
            fired_ids.append(tid)
            rec["fire_meta"] = res["meta"]
            rec["constructed"] = res["request"]
            pip = run_pipeline(res["request"], q)
            rec["pipeline_stage"] = pip["stage"]
            rec["schema_ok"] = pip["schema_ok"]
            rec["fidelity_status"] = pip.get("fidelity_status")
            rec["envelope_status"] = pip.get("envelope_status")
            rec["binding"] = pip.get("binding")
            gold = s.get("expected")
            auth = (pip.get("contract") or {}).get("authoritative_value")
            rec["gold"] = gold
            rec["authoritative_value"] = auth
            if isinstance(auth, (int, float)) and \
                    isinstance(gold, (int, float)):
                ok = within(float(auth), float(gold),
                            float(s.get("atol") or 0.0),
                            float(s.get("rtol") or 0.0))
            elif isinstance(auth, list) and isinstance(gold, (int, float)) \
                    and len(auth) == 1:
                ok = within(float(auth[0]), float(gold),
                            float(s.get("atol") or 0.0),
                            float(s.get("rtol") or 0.0))
            elif isinstance(auth, list) and isinstance(gold, (int, float)) \
                    and len(auth) == 2 and res["meta"]["order"] == 2:
                # second-order -> first-order system conversion: the
                # requested scalar is state component 0 (x itself)
                ok = within(float(auth[0]), float(gold),
                            float(s.get("atol") or 0.0),
                            float(s.get("rtol") or 0.0))
            else:
                ok = False
            rec["matches_gold"] = ok
            rec["previously_correct"] = bool(rec["b2_correct"])
        rows.append(rec)

    by_id = {r["task_id"]: r for r in rows}
    failures: list[str] = []

    for tid in six:
        r = by_id.get(tid)
        if r is None:
            failures.append(f"{tid}: not found in suite")
            continue
        if not r["fired"]:
            failures.append(f"{tid}: layer did NOT fire")
        for key, want in (("pipeline_stage", "done"),
                          ("schema_ok", True),
                          ("matches_gold", True)):
            if r.get(key) != want:
                failures.append(
                    f"{tid}: {key}={r.get(key)!r} (want {want!r}); "
                    f"detail={ {k: r.get(k) for k in (
                        'fidelity_status', 'envelope_status', 'binding',
                        'authoritative_value')} }")
        if r.get("fire_meta", {}).get("reason") != "WRONG_OPERATION_REMAPPED":
            failures.append(f"{tid}: unexpected fire reason "
                            f"{r.get('fire_meta', {}).get('reason')}")

    audit = by_id.get(audit_id)
    if audit is None or not audit["fired"]:
        failures.append(f"{audit_id}: second-order audit row did not fire")
    elif audit["fire_meta"].get("reason") != "SECOND_ORDER_SYSTEM_CONVERSION":
        failures.append(f"{audit_id}: expected SECOND_ORDER_SYSTEM_"
                        f"CONVERSION, got {audit['fire_meta'].get('reason')}")
    elif not audit.get("matches_gold"):
        failures.append(f"{audit_id}: constructed second-order system did "
                        f"not reproduce gold")

    # no material regression: any previously-correct row that fires must
    # still reproduce the frozen gold through the layer's request
    for r in rows:
        if r["fired"] and r["previously_correct"] \
                and not r.get("matches_gold"):
            failures.append(
                f"{r['task_id']}: REGRESSION RISK — previously correct, "
                f"layer fired, constructed request does not match gold "
                f"(auth={r.get('authoritative_value')!r} "
                f"gold={r.get('gold')!r})")

    n_prev_correct_fired = sum(
        1 for r in rows if r["fired"] and r["previously_correct"])

    doc = {
        "milestone": "T14R2.4-2.10 — ODE intent layer offline validation",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "method": "deterministic replay of the constructed requests "
                  "through the frozen gate chain (repair -> schema -> "
                  "fidelity -> invoke -> verified_envelope -> "
                  "result_contract) over every suite row; no LLM, no GPU",
        "suite_rows": len(rows),
        "fired_rows": fired_ids,
        "fired_count": len(fired_ids),
        "previously_correct_firing_rows": n_prev_correct_fired,
        "six_case_results": {tid: {
            k: by_id[tid].get(k) for k in (
                "fired", "pipeline_stage", "schema_ok", "fidelity_status",
                "envelope_status", "binding", "gold",
                "authoritative_value", "matches_gold", "fire_meta")}
            for tid in six},
        "audit_row_result": {k: by_id.get(audit_id, {}).get(k)
                             for k in ("fired", "fire_meta", "gold",
                                       "authoritative_value",
                                       "matches_gold")},
        "rows": rows,
        "hard_failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }

    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({"status": doc["status"],
                      "fired": fired_ids,
                      "six_ok": all(by_id[t].get("matches_gold")
                                    for t in six),
                      "audit_ok": (audit or {}).get("matches_gold"),
                      "failures": failures[:10]}, indent=2))
    print(f"-> {OUT}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())