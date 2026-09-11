"""T14R.3-11 probe — replay every incorrect T14 numeric row through the
repaired planner-request path WITHOUT the LLM.

For each of the 37 failure rows: take the RECORDED planner request and
question, apply repair_planner_request (deterministic), then run the
frozen gates exactly as run_arm_b does (validate_planner_request →
check_fidelity → invoke → verified_envelope). The adopter LLM is not
run; the engine envelope status + payload are the probe evidence.

Output: evaluations/t14r/repair_probe.json (per-row outcome + summary).
No frozen file is modified.
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
OUT = ROOT / "evaluations/t14r/repair_probe.json"


def main() -> int:
    from sciencemath.scicomp.adoption import (
        verified_envelope)
    from sciencemath.scicomp.fidelity import (
        FIDELITY_FAIL, SCHEMA_FAIL, check_fidelity, validate_planner_request)
    from sciencemath.scicomp.invocation import invoke
    from sciencemath.scicomp.planner_repair import repair_planner_request

    rows = [json.loads(ln) for ln in
            PRED.read_text(encoding="utf-8").splitlines() if ln.strip()]
    suite = {}
    for ln in SUITE.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            d = json.loads(ln)
            suite[d["eval_id"]] = d

    bad = [r for r in rows
           if r.get("kind") in ("numeric_oracle", "mixed")
           and not r.get("correct")]

    out_rows = []
    for r in bad:
        eid = r["eval_id"]
        req = r.get("request") or {}
        q = r.get("question") or suite.get(eid, {}).get("question", "")
        rec: dict = {"task_id": eid,
                     "operation": req.get("operation"),
                     "t14_failure_class": None}
        rep = repair_planner_request(req, q)
        rec["repair_changed"] = rep["changed"]
        rec["bindings"] = rep["bindings"]
        rec["unknown_provenance"] = rep["unknown_provenance"]
        fixed = rep["request"]

        schema = validate_planner_request(fixed)
        rec["schema_ok"] = schema["ok"]
        if not schema["ok"]:
            rec["schema_failures"] = schema["failures"]
            rec["outcome"] = "STILL_SCHEMA_FAIL"
        else:
            fid = check_fidelity(fixed, q)
            rec["fidelity_status"] = fid.status
            if fid.status == FIDELITY_FAIL:
                rec["fidelity_failures"] = fid.failures[:6]
                rec["outcome"] = "STILL_FIDELITY_FAIL"
            else:
                res = invoke({"operation": fixed["operation"],
                              "inputs": fixed.get("parameters") or {}},
                             question=q)
                env = res.envelope
                rec["envelope_status"] = env.get("status")
                if env.get("status") != "PASS":
                    rec["outcome"] = "ENGINE_NOT_PASS"
                    rec["envelope"] = {k: env.get(k) for k in
                                       ("status", "message", "result")}
                else:
                    doc = verified_envelope(env, fid.source_parameter_hash)
                    rec["authoritative"] = doc["binding"] == "VERIFIED"
                    rec["result"] = env.get("result")
                    want = suite.get(eid, {}).get("expected")
                    rec["expected"] = want
                    rec["outcome"] = (
                        "ENGINE_PASS_NONNUMERIC" if want is None else
                        "ENGINE_PASS" if _match(
                            env.get("result"), want,
                            suite.get(eid, {}).get("atol"),
                            suite.get(eid, {}).get("rtol"))
                        else "ENGINE_PASS_VALUE_MISMATCH")
        out_rows.append(rec)

    hist = Counter(r["outcome"] for r in out_rows)
    doc = {
        "milestone": "T14R.3-11 repair probe (no LLM)",
        "rows_probed": len(out_rows),
        "outcome_histogram": dict(hist),
        "note": "ENGINE_PASS = repaired request passes frozen gates, "
                "engine returns PASS, and payload matches the suite "
                "expectation within atol/rtol. The adopter LLM is not "
                "run; T14R.14 replays the full pipeline.",
        "rows": out_rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(doc["outcome_histogram"], indent=1))
    for r in out_rows:
        if r["outcome"] not in ("ENGINE_PASS",):
            print(f"  {r['task_id']}: {r['outcome']} "
                  f"(op={r.get('operation')})")
    print(f"-> {OUT}")
    return 0


def _match(got, want, atol, rtol) -> bool:
    """Mirror the suite grader's per-value pairing closely enough to
    label the probe; the authoritative grade is the T14R.14 replay."""
    if got is None:
        return False

    def leaves(v, out):
        if isinstance(v, dict):
            for e in v.values():
                leaves(e, out)
        elif isinstance(v, list):
            for e in v:
                leaves(e, out)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))

    def flat(v):
        if isinstance(v, dict):
            for key in ("value", "integral", "root", "final_state",
                        "row_count", "optimum_x", "optimum_value", "mean",
                        "determinant", "t_statistic", "norm"):
                if key in v:
                    return flat(v[key])
            if isinstance(v.get("parameters"), dict):
                return flat(v["parameters"])
            nums_only: list = []
            leaves(v, nums_only)
            return nums_only
        if isinstance(v, (list, tuple)):
            out = []
            for e in v:
                out.extend(flat(e))
            return out
        if isinstance(v, bool):
            return []
        if isinstance(v, (int, float)):
            return [float(v)]
        return []

    g = flat(got)
    w = flat(want) if want is not None else None
    if not g:
        s = json.dumps(got)
        return s == json.dumps(want)
    if not w or len(g) != len(w):
        return False
    for a, b in zip(g, w):
        tol = (atol or 0.0) + (rtol or 0.0) * abs(b)
        if abs(a - b) > max(tol, 1e-12):
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())