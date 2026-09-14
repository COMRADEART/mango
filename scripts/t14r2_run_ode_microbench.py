"""T14R2.12 — run the ODE planner microbench `mango-ode-planner-v1`
against the deterministic ODE intent layer, fully offline (no LLM, no
GPU).

Protocol per case:
  * simulate the frozen-failure planner behavior by presenting the layer
    with a WRONG-operation request (definite_integral / minimize, the
    two operations the six frozen failures actually chose);
  * POSITIVE case  -> the layer must fire, remap to solve_ode, and the
    constructed request must (a) pass the frozen repair + schema +
    fidelity gates, (b) match the hand-written oracle fields exactly
    (equations, initial_state, t_start, t_end, shape, order,
    parameters), (c) carry complete, non-invented provenance;
  * NEGATIVE case  -> the layer must NOT fire (no operation remapping
    outside the recognized IVP shape).

Pre-registered metric targets (T14R2.12):
  ivp_recognition_precision >= 0.98   ivp_recognition_recall >= 0.98
  schema_valid_rate >= 0.98           provenance_completeness == 1.0
  state_order_correct_rate == 1.0     parameter_invention_count == 0
  pipeline_exception_count == 0
"""
from __future__ import annotations

import ast
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.fidelity import (
    FIDELITY_FAIL, check_fidelity, validate_planner_request)
from sciencemath.scicomp.ode_intent import select_ode_operation
from sciencemath.scicomp.planner_repair import repair_planner_request

DIR = ROOT / "evaluations/t14r2/ode_microbench"
SUITE = DIR / "suite_v1.jsonl"
MANIFEST = DIR / "manifest.json"
OUT = ROOT / "evaluations/t14r2/ode_microbench_metrics.json"

ALLOWED_PROV = {"USER_GIVEN", "RETRIEVED_VERIFIED", "DETERMINISTIC_DERIVATION",
                "DEFAULT_DECLARED_BY_TOOL"}
PI_SENTINELS = {"PI/2": math.pi / 2, "PI": math.pi}
WRONG_OPS = ["definite_integral", "minimize"]


def within(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def wrong_request(i: int) -> dict:
    op = WRONG_OPS[i % len(WRONG_OPS)]
    return {"operation": op,
            "parameters": {"expression": "junk", "lower": 0, "upper": 1},
            "source_inputs": {"expression": "junk"},
            "parameter_provenance": {"expression": "USER_GIVEN"}}


def nums_in(text: str) -> list[float]:
    import re
    return [float(x) for x in
            re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text or "")]


def check_provenance(case: dict, req: dict) -> tuple[bool, list[str]]:
    """provenance_completeness: every field carries an allowed category,
    nothing invented, and every USER_GIVEN number is question-verbatim."""
    bad: list[str] = []
    prov = req.get("parameter_provenance") or {}
    params = req.get("parameters") or {}
    if not prov:
        return False, ["provenance_missing"]
    for field, cat in prov.items():
        if cat not in ALLOWED_PROV:
            bad.append(f"{field}:{cat}")
    if req.get("parameter_provenance") is None:
        bad.append("none")
    q = case["question"]
    for field, cat in prov.items():
        if cat != "USER_GIVEN":
            continue
        val = params.get(field)
        chunks = [json.dumps(val)] if not isinstance(val, str) else [val]
        for ch in chunks:
            for num in nums_in(ch):
                if num not in nums_in(q):
                    bad.append(f"{field}:nonverbatim:{num}")
    return (not bad), bad


def check_state_order(case: dict, req: dict) -> bool:
    """state_order_correct_rate: for multi-state positives the
    equations/initial_state ordering matches the oracle exactly (and
    vector shape is declared)."""
    e = case["expected"]
    params = req.get("parameters") or {}
    if len(e["equations"]) > 1:
        return (req.get("expected_result_type") == "vector"
                and params.get("equations") == e["equations"]
                and params.get("initial_state") == e["initial_state"])
    return True


def check_invention(case: dict, req: dict, prov_ok: bool) -> bool:
    """parameter_invention_count: any MODEL_INVENTED-style provenance,
    or a value field that is neither question-verbatim nor declared nor
    DETERMINISTIC_DERIVATION-labelled, counts as invention."""
    if not prov_ok:
        return False
    prov = req.get("parameter_provenance") or {}
    params = req.get("parameters") or {}
    q = case["question"]
    qnums = set(nums_in(q))
    for field, cat in prov.items():
        if cat == "DETERMINISTIC_DERIVATION":
            continue  # bounded evaluator / stated rate law / rename
        val = params.get(field)
        flat = json.dumps(val) if not isinstance(val, str) else val
        for num in nums_in(flat):
            if num not in qnums:
                return False
    return True


def equations_equivalent(a: list, b: list, params: dict) -> bool | None:
    """Semantic equation comparison: evaluate each RHS at y0 = 1 and
    y0 = 2 with declared parameters substituted; equal within 1e-6
    relative. None when either side is not evaluable (caller falls back
    to exact string equality)."""
    if len(a) != len(b):
        return False
    env = {"__builtins__": {}, "pi": math.pi, "e": math.e, "tau": math.tau}
    vals = []
    for rhs_list in (a, b):
        row = []
        for y0 in (1.0, 2.0):
            e = dict(env)
            e["y0"] = y0
            e.update(params or {})
            try:
                row.append([eval(compile(ast.parse(s, mode="eval"),
                                         "<eq>", "eval"), e)  # noqa: S307
                            for s in rhs_list])
            except Exception:
                return None
        vals.append(row)
    for i in range(2):
        for j in range(len(a)):
            va, vb = vals[0][i][j], vals[1][i][j]
            if not (isinstance(va, (int, float))
                    and isinstance(vb, (int, float))):
                return None
            if abs(va - vb) > 1e-6 * max(1.0, abs(va), abs(vb)):
                return False
    return True


def fields_match(case: dict, req: dict) -> tuple[bool, list[str]]:
    e = case["expected"]
    params = req.get("parameters") or {}
    prov = req.get("parameter_provenance") or {}
    bad = []
    eq_ok = equations_equivalent(params.get("equations") or [],
                                 e["equations"],
                                 params.get("parameters") or {})
    if eq_ok is None:
        eq_ok = params.get("equations") == e["equations"]
    if not eq_ok:
        bad.append(f"equations {params.get('equations')!r}")
    if params.get("initial_state") != e["initial_state"]:
        bad.append(f"initial_state {params.get('initial_state')!r}")
    if not within(float(params.get("t_start", "nan")), float(e["t_start"])):
        bad.append(f"t_start {params.get('t_start')!r}")
    e_end = e["t_end"]
    e_end_val = PI_SENTINELS.get(e_end, e_end)
    if not within(float(params.get("t_end", "nan")), float(e_end_val)):
        bad.append(f"t_end {params.get('t_end')!r}")
    # the request declares the SHAPE THE OPERATION RETURNS; a second-
    # order system conversion integrates a 2-state system, so the tool
    # result is a vector whose component 0 is the requested scalar
    want_shape = ("vector" if e["order"] == 2
                  else e["expected_result_type"])
    if req.get("expected_result_type") != want_shape:
        bad.append(f"shape {req.get('expected_result_type')!r}")
    if prov.get("t_start") != e["t_start_provenance"]:
        bad.append(f"t_start_prov {prov.get('t_start')!r}")
    if prov.get("t_end") != e["t_end_provenance"]:
        bad.append(f"t_end_prov {prov.get('t_end')!r}")
    if prov.get("initial_state") != "USER_GIVEN":
        bad.append(f"initial_state_prov {prov.get('initial_state')!r}")
    if prov.get("equations") != "DETERMINISTIC_DERIVATION":
        bad.append(f"equations_prov {prov.get('equations')!r}")
    exp_params = e.get("parameters")
    if exp_params is not None and params.get("parameters") != exp_params:
        bad.append(f"parameters {params.get('parameters')!r}")
    if exp_params is None and "parameters" in params:
        bad.append(f"unexpected parameters {params.get('parameters')!r}")
    return (not bad), bad


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    body = SUITE.read_text(encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert sha == manifest["suite_sha256"], "suite checksum drift"

    cases = [json.loads(ln) for ln in body.splitlines() if ln.strip()]
    per_case: list[dict] = []
    exceptions = 0

    for i, case in enumerate(cases):
        rec = {"eval_id": case["eval_id"], "family": case["family"],
               "split": case["split"],
               "positive": case["is_ivp_positive"]}
        try:
            res = select_ode_operation(wrong_request(i), case["question"])
            fired = bool(res)
            rec["fired"] = fired
            if case["is_ivp_positive"]:
                if not fired:
                    rec["result"] = "FN_not_fired"
                else:
                    req_out = res["request"]
                    rep = repair_planner_request(req_out, case["question"])
                    fixed = rep["request"]
                    schema = validate_planner_request(fixed)
                    rec["schema_valid"] = bool(schema["ok"])
                    fid = None
                    if schema["ok"]:
                        fid = check_fidelity(fixed, case["question"])
                        rec["fidelity_ok"] = fid.status != FIDELITY_FAIL
                    else:
                        rec["fidelity_ok"] = False
                    prov_ok, prov_bad = check_provenance(case, req_out)
                    order_ok = check_state_order(case, req_out)
                    inv_ok = check_invention(case, req_out, prov_ok)
                    fm_ok, fm_bad = fields_match(case, req_out)
                    rec.update({"provenance_complete": prov_ok,
                                "provenance_bad": prov_bad,
                                "state_order_ok": order_ok,
                                "no_invention": inv_ok,
                                "fields_ok": fm_ok, "fields_bad": fm_bad})
                    if not (schema["ok"] and rec["fidelity_ok"] and prov_ok
                            and order_ok and inv_ok and fm_ok):
                        rec["result"] = "FP_wrong_construction"
                    else:
                        rec["result"] = "TP"
            else:
                rec["result"] = "TN" if not fired else "FP_fired"
        except Exception as exc:  # noqa: BLE001 — counted, never fatal
            exceptions += 1
            rec["result"] = "EXCEPTION"
            rec["exception"] = f"{type(exc).__name__}: {exc}"
        per_case.append(rec)

    def rate(pred, sub) -> float:
        d = [r for r in per_case if sub(r)]
        return (sum(1 for r in d if pred(r)) / len(d)) if d else 0.0

    tp = sum(1 for r in per_case if r["result"] == "TP")
    tn = sum(1 for r in per_case if r["result"] == "TN")
    fp = sum(1 for r in per_case if r["result"] == "FP_fired")
    fn = sum(1 for r in per_case if r["result"] == "FN_not_fired")
    bad_construct = sum(
        1 for r in per_case if r["result"] == "FP_wrong_construction")
    schema_denom = [r for r in per_case if r.get("schema_valid") is not None]

    metrics = {
        "ivp_recognition_precision": (tp / (tp + fp + bad_construct))
        if (tp + fp + bad_construct) else 0.0,
        "ivp_recognition_recall": (tp / (tp + fn)) if (tp + fn) else 0.0,
        "schema_valid_rate": (sum(1 for r in schema_denom
                                  if r["schema_valid"]) / len(schema_denom))
        if schema_denom else 0.0,
        "provenance_completeness": rate(
            lambda r: r.get("provenance_complete") is True,
            lambda r: r["result"] in ("TP", "FP_wrong_construction")),
        "state_order_correct_rate": rate(
            lambda r: r.get("state_order_ok") is True,
            lambda r: r["result"] in ("TP", "FP_wrong_construction")),
        "parameter_invention_count": sum(
            1 for r in per_case if r.get("no_invention") is False),
        "pipeline_exception_count": exceptions,
        "confusion": {"TP": tp, "TN": tn, "FP_fired": fp,
                      "FP_wrong_construction": bad_construct,
                      "FN_not_fired": fn,
                      "EXCEPTION": exceptions},
    }

    split_metrics = {}
    for split in ("dev", "final"):
        sub = [r for r in per_case if r["split"] == split]
        stp = sum(1 for r in sub if r["result"] == "TP")
        sfp = sum(1 for r in sub if r["result"] in ("FP_fired",
                                                    "FP_wrong_construction"))
        sfn = sum(1 for r in sub if r["result"] == "FN_not_fired")
        sden = [r for r in sub if r.get("schema_valid") is not None]
        split_metrics[split] = {
            "cases": len(sub),
            "precision": (stp / (stp + sfp)) if (stp + sfp) else 0.0,
            "recall": (stp / (stp + sfn)) if (stp + sfn) else 0.0,
            "schema_valid_rate": (sum(1 for r in sden if r["schema_valid"])
                                  / len(sden)) if sden else 0.0,
            "provenance_completeness": (
                sum(1 for r in sub if r.get("provenance_complete") is True)
                / max(1, sum(1 for r in sub if r["result"] in
                             ("TP", "FP_wrong_construction")))),
            "state_order_correct_rate": (
                sum(1 for r in sub if r.get("state_order_ok") is True)
                / max(1, sum(1 for r in sub if r["result"] in
                             ("TP", "FP_wrong_construction")))),
            "parameter_invention_count": sum(
                1 for r in sub if r.get("no_invention") is False),
            "pipeline_exception_count": sum(
                1 for r in sub if r["result"] == "EXCEPTION"),
        }

    TARGETS = {
        "ivp_recognition_precision": ("ge", 0.98),
        "ivp_recognition_recall": ("ge", 0.98),
        "schema_valid_rate": ("ge", 0.98),
        "provenance_completeness": ("eq", 1.0),
        "state_order_correct_rate": ("eq", 1.0),
        "parameter_invention_count": ("eq", 0),
        "pipeline_exception_count": ("eq", 0),
    }
    gate_results = {}
    for k, (mode, want) in TARGETS.items():
        v = metrics[k]
        ok = (v >= want) if mode == "ge" else (v == want)
        gate_results[k] = {"measured": v, "target": want,
                           "mode": mode, "status": "PASS" if ok else "FAIL"}

    doc = {
        "milestone": "T14R2.12 — ODE planner microbench metrics",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "bench": "mango-ode-planner-v1",
        "suite_sha256": sha,
        "suite_checksum_verified": sha == manifest["suite_sha256"],
        "total_cases": len(cases),
        "mode": "fully offline (deterministic layer under simulated "
                "wrong-operation planner requests; no LLM, no GPU)",
        "metrics": metrics,
        "split_metrics": split_metrics,
        "target_gates": gate_results,
        "all_targets_met": all(g["status"] == "PASS"
                               for g in gate_results.values()),
        "failing_cases": [r for r in per_case
                          if r["result"] not in ("TP", "TN")],
        "per_case": per_case,
    }
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({"status": "PASS" if doc["all_targets_met"]
                      else "FAIL",
                      "metrics": metrics,
                      "split_final": split_metrics["final"]}, indent=2))
    print(f"-> {OUT}")
    return 0 if doc["all_targets_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())