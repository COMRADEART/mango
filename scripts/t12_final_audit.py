"""T12 final audit — the 16 pre-registered promotion gates.

Reads ONLY the frozen-suite run summaries written by
scripts/t12_scicomp_eval.py plus the T12 protection artifacts. Gate
thresholds are the T12.23–T12.29 pre-registrations; operationalizations
that required interpretation are marked OPERATIONALIZED with the rule
stated inline. A missed gate is reported as measured (no post-hoc
threshold shopping). The promotion decision is derived mechanically:

  PROMOTE_SCICOMP_LAB        all gates PASS
  KEEP_SCICOMP_EXPERIMENTAL  any gate FAIL, engine/regression intact
  REJECT_SCICOMP             engine protection or regression battery FAIL

Writes evaluations/t12/final_audit.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUNS = ROOT / "evaluations/t12/runs"
T11_ARMA = ROOT / "evaluations/t11/runs/t11-h2h-arma/summary.json"
T11_ARMB = ROOT / "evaluations/t11/runs/t11-h2h-armb/summary.json"

# Pre-registered tolerances (fixed before the final runs completed;
# mirrors the T12 spec text)
ADOPTION_GATE = 0.90            # T12.23, unchanged from T11
ADOPTION_PREFERRED = 0.95
CONCEPTUAL_TOLERANCE = 0.02     # T12.25: within 2 pp of the no-SciComp control
ADVERSARIAL_TOLERANCE = 0.02    # T12.26: within 2 pp of the control
NUMERIC_FLOOR = 0.848           # T12.27: T11 treatment accuracy
ROUTER_FLOOR = 0.95             # T12.28: OPERATIONALIZED "not materially
#                                regress" from T11's 0.986


def _load(p: Path) -> dict | None:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _suite_sha(d: Path) -> str:
    return hashlib.sha256((d / "questions.jsonl").read_bytes()) \
        .hexdigest()


def check(name: str, passed: bool | None, measured, detail="") -> dict:
    status = "PASS" if passed else "FAIL"
    if passed is None:
        status = "MISSING"
    return {"check": name, "status": status, "measured": measured,
            "detail": detail}


def main() -> int:
    checks: list[dict] = []

    # ---- run summaries ----
    sA = _load(RUNS / "t12-final-scicomp-A/summary.json")
    sB = _load(RUNS / "t12-final-scicomp-B/summary.json")
    fA = _load(RUNS / "t12-final-fidelity-A/summary.json")
    fB = _load(RUNS / "t12-final-fidelity-B/summary.json")
    cB = _load(RUNS / "t12-final-conceptual-B/summary.json")
    t11a = _load(T11_ARMA)
    t11b = _load(T11_ARMB)

    # ---- suite integrity (T12.18–T12.21) ----
    for name, d in (("scicomp", ROOT / "evaluations/t11/scicomp-suite/v1"),
                    ("fidelity",
                     ROOT / "evaluations/t12/suites/fidelity/v1"),
                    ("conceptual",
                     ROOT / "evaluations/t12/suites/conceptual/v1")):
        expected = (d / "checksum.txt").read_text(encoding="utf-8").strip()
        checks.append(check(
            f"suite_integrity_{name}", _suite_sha(d) == expected,
            _suite_sha(d)[:12] + "…"))

    # ---- T12.23 adoption gate (arm B, raw counts) ----
    if sB and sB.get("model_adoption_rate") is not None:
        # raw counts: recompute from predictions
        rows = [json.loads(l) for l in
                (RUNS / "t12-final-scicomp-B/predictions.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
        inv = [r for r in rows if r.get("invoked")]
        passes = [r for r in inv if r.get("envelope_status") == "PASS"]
        adopted = [r for r in passes if r.get("adopted")]
        rate = len(adopted) / max(1, len(passes))
        checks.append(check(
            "t12.23_adoption>=0.90", rate >= ADOPTION_GATE, rate,
            f"raw: {len(adopted)}/{len(passes)} PASS envelopes adopted "
            f"(preferred >= {ADOPTION_PREFERRED})"))
        checks.append(check(
            "t12.23b_adoption_preferred>=0.95",
            rate >= ADOPTION_PREFERRED, rate,
            "preferred (non-blocking) target"))
    else:
        checks.append(check("t12.23_adoption>=0.90", None, None,
                            "run summary missing"))

    # ---- T12.24 silent protected-parameter mutation == 0 ----
    if fB:
        mut_pass = fB.get("silent_mutation_pass_count", None)
        checks.append(check(
            "t12.24_silent_mutation==0", mut_pass == 0, mut_pass,
            "fidelity-v1 arm B: mutated request executed to PASS "
            "(absolute gate); approved logged normalizations excluded "
            "by construction"))
    else:
        checks.append(check("t12.24_silent_mutation==0", None, None,
                            "fidelity arm B summary missing"))

    # ---- T12.25 conceptual guard gate ----
    if sA and sB:
        ctrl = sA.get("conceptual_discipline")
        treat = sB.get("conceptual_discipline")
        ok = (ctrl is not None and treat is not None
              and treat >= ctrl - CONCEPTUAL_TOLERANCE)
        checks.append(check(
            "t12.25_conceptual_vs_control", ok,
            {"t12_armB": treat, "t12_control": ctrl},
            f"tolerance {CONCEPTUAL_TOLERANCE:.2f} (T11 gap was -14.0 pp "
            f"from control {t11a['conceptual_discipline'] if t11a else '?'})"))
        if sB.get("over_compute_rate") is not None and t11b:
            t11_oc = t11b.get("over_compute_rate")
            ok2 = (t11_oc is not None
                   and sB["over_compute_rate"] < t11_oc) or \
                  (t11_oc in (None, 0) and sB["over_compute_rate"] == 0)
            checks.append(check(
                "t12.25b_unnecessary_compute_lower_than_T11", ok2,
                {"t12_armB": sB.get("over_compute_rate"),
                 "t11_armB": t11_oc}))
    else:
        checks.append(check("t12.25_conceptual_vs_control", None, None,
                            "run summaries missing"))

    # ---- T12.26 adversarial gate ----
    if sA and sB:
        ctrl = sA.get("adversarial_handled_correctly")
        treat = sB.get("adversarial_handled_correctly")
        ok = (ctrl is not None and treat is not None
              and treat >= ctrl - ADVERSARIAL_TOLERANCE)
        checks.append(check(
            "t12.26_adversarial_vs_control", ok,
            {"t12_armB": treat, "t12_control": ctrl},
            f"tolerance {ADVERSARIAL_TOLERANCE:.2f} (T11 gap was -4.0 pp "
            f"from control {t11a['adversarial_handled_correctly'] if t11a else '?'})"))
        fab = sB.get("adversarial_false_answer_rate")
        checks.append(check("t12.26b_no_fabricated_PASS",
                            fab == 0, fab,
                            "asserted-number-on-failure rate must be 0"))
    else:
        checks.append(check("t12.26_adversarial_vs_control", None, None,
                            "run summaries missing"))

    # ---- T12.27 numeric capability protection ----
    if sB:
        acc = sB.get("numeric_accuracy")
        checks.append(check(
            "t12.27_numeric>=0.848",
            acc is not None and acc >= NUMERIC_FLOOR, acc,
            f"T11 treatment was {t11b['numeric_accuracy'] if t11b else '?'}"))
    else:
        checks.append(check("t12.27_numeric>=0.848", None, None,
                            "arm B summary missing"))

    # ---- T12.28 router protection ----
    if cB:
        rm = cB.get("router_rule_metrics") or {}
        p, r = rm.get("precision"), rm.get("recall")
        ok = ((p is None or p >= ROUTER_FLOOR)
              and (r is None or r >= ROUTER_FLOOR))
        if sB:
            srm = sB.get("router") or {}
            if srm.get("precision") is not None:
                p2, r2 = srm.get("precision"), srm.get("recall")
                ok = ok and p2 >= ROUTER_FLOOR and r2 >= ROUTER_FLOOR
                checks.append(check(
                    "t12.28_router_not_materially_regressed", ok,
                    {"scicomp_P": p2, "scicomp_R": r2,
                     "conceptual_P": p, "conceptual_R": r},
                    f"T11 was 0.986; OPERATIONALIZED floor {ROUTER_FLOOR}"))
            else:
                checks.append(check(
                    "t12.28_router_not_materially_regressed", ok,
                    {"conceptual_P": p, "conceptual_R": r},
                    f"OPERATIONALIZED floor {ROUTER_FLOOR}"))
        else:
            checks.append(check(
                "t12.28_router_not_materially_regressed", ok,
                {"conceptual_P": p, "conceptual_R": r},
                f"OPERATIONALIZED floor {ROUTER_FLOOR}"))
    else:
        checks.append(check("t12.28_router_not_materially_regressed",
                            None, None, "conceptual arm B missing"))

    # ---- T12.29 engine protection ----
    if sB:
        rows = [json.loads(l) for l in
                (RUNS / "t12-final-scicomp-B/predictions.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
        inv = [r for r in rows if r.get("invoked")]
        well_formed = [r for r in inv
                       if r.get("envelope_status") is not None]
        engine_rate = (len(well_formed) / len(inv)) if inv else None
        ok = (engine_rate == 1.0
              and sB.get("valid_call_rate") == 1.0)
        checks.append(check(
            "t12.29_engine_protection", ok,
            {"valid_call_rate": sB.get("valid_call_rate"),
             "well_formed_envelopes": f"{len(well_formed)}/{len(inv)}"},
            "engine execution reliability on arm B invocations "
            "(T11: 1.000, 153/153)"))
    else:
        checks.append(check("t12.29_engine_protection", None, None,
                            "arm B summary missing"))

    # ---- T12.30 regression battery ----
    reg = _load(ROOT / "evaluations/t12/protection/regression_summary.json")
    if reg:
        checks.append(check(
            "t12.30_regression_battery",
            reg.get("status") == "ALL_PASS", reg.get("status"),
            json.dumps(reg.get("layers", {}))[:400]))
    else:
        checks.append(check("t12.30_regression_battery", None, None,
                            "evaluations/t12/protection/"
                            "regression_summary.json missing"))

    # ---- T12.31 security ----
    sec = _load(ROOT / "evaluations/t12/protection/security_summary.json")
    if sec:
        checks.append(check(
            "t12.31_security_zero_violations",
            sec.get("violations", 1) == 0, sec.get("violations"),
            sec.get("detail", "")))
    else:
        checks.append(check("t12.31_security_zero_violations", None,
                            None, "security_summary.json missing"))

    # ---- T12.32 latency (informational, never gates) ----
    lat = {n: (s or {}).get("median_llm_ms") for n, s in
           (("scicomp_A", sA), ("scicomp_B", sB), ("fidelity_A", fA),
            ("fidelity_B", fB), ("conceptual_B", cB))}
    checks.append(check("t12.32_latency_reported",
                        all(v is not None for v in lat.values()), lat,
                        "informational: median per-question LLM ms"))

    # ---- T12.33 no training ----
    adapter = ROOT / "training/adapters/sciencemath-v0.1-t3/" \
                   "adapter_model.safetensors"
    if adapter.exists():
        sha = hashlib.sha256(adapter.read_bytes()).hexdigest()
        gate = _load(ROOT / "evaluations/t12/t12_entry_gate.json")
        frozen = None
        if gate:
            frozen = (gate.get("checks", {})
                      .get("adapter_sha256") or
                      gate.get("adapter_sha256"))
        checks.append(check(
            "t12.33_no_training_adapter_unchanged",
            frozen is None or frozen == sha, sha[:16] + "…",
            "no LoRA/SFT/preference/weight edits (entry-gate sha "
            f"{str(frozen)[:16] if frozen else 'n/a'})"))
    else:
        checks.append(check("t12.33_no_training_adapter_unchanged", None,
                            None, "adapter missing"))

    # ---- T12.33b tests ----
    pytest_summary = _load(ROOT / "evaluations/t12/pytest_summary.json")
    if pytest_summary:
        fails = pytest_summary.get("failures")
        checks.append(check(
            "t12.33c_pytest_zero_failures",
            fails == 0 and pytest_summary.get("passed", 0) >= 878,
            {"passed": pytest_summary.get("passed"),
             "failures": fails}))
    else:
        checks.append(check("t12.33c_pytest_zero_failures", None, None,
                            "pytest_summary.json missing"))

    # ---- T12.1 engine freeze re-verification ----
    freeze = _load(ROOT / "evaluations/t12/scicomp_engine_freeze.json")
    if freeze:
        bad = []
        for rel, want in freeze.get("files", {}).items():
            f = ROOT / rel
            if not f.exists():
                bad.append(f"{rel}: MISSING")
                continue
            got = hashlib.sha256(f.read_bytes()).hexdigest()
            if got != want.get("sha256"):
                bad.append(f"{rel}: CHANGED")
        checks.append(check(
            "engine_freeze_intact", not bad,
            f"{len(freeze.get('files', {})) - len(bad)}/"
            f"{len(freeze.get('files', {}))} files unchanged",
            "; ".join(bad[:5])))
    else:
        checks.append(check("engine_freeze_intact", None, None,
                            "scicomp_engine_freeze.json missing"))

    # ---- decision ----
    blocking = [c for c in checks if c["status"] == "FAIL"]
    missing = [c for c in checks if c["status"] == "MISSING"]
    engine_broken = any(c["check"] in ("engine_freeze_intact",
                                       "t12.29_engine_protection",
                                       "t12.30_regression_battery")
                        and c["status"] == "FAIL" for c in checks)
    # preferred-but-non-blocking checks do not gate the decision
    blocking = [c for c in blocking
                if c["check"] != "t12.23b_adoption_preferred>=0.95"]
    if missing:
        decision = "INCOMPLETE"
    elif engine_broken:
        decision = "REJECT_SCICOMP"
    elif blocking:
        decision = "KEEP_SCICOMP_EXPERIMENTAL"
    else:
        decision = "PROMOTE_SCICOMP_LAB"

    out = {
        "milestone": "T12 — Scientific-Compute Planner Fidelity and "
                     "Promotion Closure",
        "decision": decision,
        "weight_promotion": "NO",
        "gates_total": len(checks),
        "passes": sum(1 for c in checks if c["status"] == "PASS"),
        "fails": [c["check"] for c in blocking],
        "missing": [c["check"] for c in missing],
        "pre_registered_thresholds": {
            "adoption": ADOPTION_GATE,
            "adoption_preferred": ADOPTION_PREFERRED,
            "conceptual_tolerance_vs_control": CONCEPTUAL_TOLERANCE,
            "adversarial_tolerance_vs_control": ADVERSARIAL_TOLERANCE,
            "numeric_floor": NUMERIC_FLOOR,
            "router_floor_OPERATIONALIZED": ROUTER_FLOOR,
            "silent_mutation": 0,
        },
        "checks": checks,
    }
    dst = ROOT / "evaluations/t12/final_audit.json"
    dst.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision, "gates": len(checks),
                      "passes": out["passes"], "fails": out["fails"],
                      "missing": out["missing"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())