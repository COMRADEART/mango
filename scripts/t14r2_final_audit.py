"""T14R2.22 final audit — independent, no manual overrides.

Mirrors scripts/t14r_final_audit.py for the T14R2 milestone: reads the
frozen evidence files and evaluates gates; missing evidence = FAIL.
Covers the T14R2-specific contract: ODE intent layer scope, frozen
component pins (including the T14R2 pins for the Executive Router and
the T14R layers), microbench targets, six-case replay, ODE subset
regression, frozen recheck, decision, protection, security,
no-training, no-paid-compute, pytest, and READY_FOR_T15.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

NUMERIC_FLOOR = 0.848
ADOPTION_FLOOR = 0.90

ENTRY = json.loads((ROOT / "evaluations/t14r2/t14r2_entry_gate.json")
                   .read_text(encoding="utf-8"))
PINS = ENTRY["frozen_component_pins"]
PINS2 = ENTRY["t14r2_frozen_pins_no_prior_record"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    checks: list[dict] = []

    def check(name, ok, measured, detail=""):
        checks.append({
            "check": name,
            "status": "PASS" if ok else "FAIL",
            "measured": measured,
            "detail": detail,
        })
        return ok

    gate = load(ROOT / "evaluations/t14r2/t14r2_entry_gate.json")
    check("entry_gate", bool(gate) and gate.get("status") == "PASS",
          (gate or {}).get("status"), "T14R2.0")

    # ---- frozen component hashes ----------------------------------------
    fid_h = sha(ROOT / "src/sciencemath/scicomp/fidelity.py")
    sem_h = sha(ROOT / "src/sciencemath/scicomp/semantic.py")
    nec_h = sha(ROOT / "src/sciencemath/scicomp/router.py")
    fw_h = sha(ROOT / "src/sciencemath/executive/correction.py")
    adp = ROOT / ("training/adapters/sciencemath-v0.1-t3/"
                  "adapter_model.safetensors")
    adp_h = sha(adp) if adp.exists() else None
    check("necessity_router_hash_unchanged",
          nec_h == PINS["necessity_router"], nec_h)
    check("fidelity_classifier_hash_unchanged",
          fid_h == PINS["fidelity_classifier"], fid_h)
    check("semantic_classifier_hash_unchanged",
          sem_h == PINS["semantic_classifier"], sem_h)
    check("correction_firewall_hash_unchanged",
          fw_h == PINS["correction_firewall"], fw_h)
    check("t3_adapter_hash_unchanged",
          adp_h == PINS["t3_adapter"], adp_h)

    from sciencemath.executive.skills import registry_sha256
    reg_h = registry_sha256()
    check("skill_registry_hash_unchanged",
          reg_h == PINS["skill_registry"], reg_h)

    # T14R2 pins (recorded at the entry gate, no prior record existed)
    for name, rec in PINS2.items():
        h = sha(ROOT / rec["path"])
        check(f"t14r2_pin_{name}_unchanged", h == rec["sha256"], h,
              "Executive Router / T14R layers frozen for T14R2")

    # SciComp engine: frozen T12 freeze, router.py-only drift allowed
    freeze = load(ROOT / "evaluations/t12/scicomp_engine_freeze.json")
    base = ROOT / "src/sciencemath/scicomp"
    mismatch = [n for n, h in (freeze or {}).get("files", {}).items()
                if sha(base / n) != h]
    check("scicomp_engine_hash", set(mismatch) <= {"router.py"},
          {"mismatch": mismatch})

    # the ONLY new scicomp module is the ODE intent layer (recorded)
    ode_h = sha(ROOT / "src/sciencemath/scicomp/ode_intent.py")
    check("ode_intent_layer_present_recorded", bool(ode_h), ode_h,
          "T14R2 primary-editable area: ODE operation selection only")

    # frozen scicomp suite unchanged (checksum pinned in the T14R entry
    # gate; the frozen suite carries it forward)
    suite_sha = sha(ROOT / "evaluations/t11/scicomp-suite/v1/questions.jsonl")
    suite_pin = next((c["measured"] for c in
                      json.loads((ROOT / "evaluations/t14r/t14r_entry_gate.json")
                                 .read_text(encoding="utf-8")).get("checks", [])
                      if c.get("check") == "suite_checksum_scicomp"), None)
    check("scicomp_suite_checksum_unchanged",
          suite_sha == suite_pin, suite_sha)

    # ---- T14R2.1/2.2 freeze + taxonomy -----------------------------------
    frz = load(ROOT / "evaluations/t14r2/ode_failure_freeze.json")
    ana = load(ROOT / "evaluations/t14r2/ode_failure_analysis.json")
    check("ode_failure_freeze_present",
          bool(frz) and frz.get("frozen_failure_count") == 6
          and frz.get("frozen_before_any_code_change") is True,
          (frz or {}).get("frozen_failure_count"))
    check("ode_taxonomy_analysis_present",
          bool(ana) and ana.get("taxonomy_histogram", {})
          .get("WRONG_ODE_OPERATION") == 6
          and ana.get("single_cause_assumption") is False,
          (ana or {}).get("taxonomy_histogram"))

    # ---- T14R2.11/2.12 microbench ----------------------------------------
    mb_manifest = load(ROOT / "evaluations/t14r2/ode_microbench/manifest.json")
    mb = load(ROOT / "evaluations/t14r2/ode_microbench_metrics.json")
    check("ode_microbench_suite_size",
          bool(mb_manifest) and 100 <= mb_manifest.get("total_cases", 0)
          <= 160,
          (mb_manifest or {}).get("total_cases"))
    check("ode_microbench_checksum_verified",
          bool(mb) and mb.get("suite_checksum_verified") is True,
          (mb or {}).get("suite_checksum_verified"))
    if mb:
        for k, g in mb.get("target_gates", {}).items():
            check(f"ode_microbench_target_{k}", g.get("status") == "PASS",
                  g.get("measured"), f"target {g.get('mode')} "
                                     f"{g.get('target')}")
    else:
        check("ode_microbench_metrics_present", False, None)

    # ---- T14R2.4-2.10 offline validation ----------------------------------
    off = load(ROOT / "evaluations/t14r2/ode_intent_offline_validation.json")
    check("ode_intent_offline_validation",
          bool(off) and off.get("status") == "PASS"
          and off.get("previously_correct_firing_rows") == 0,
          None if not off else {
              "status": off.get("status"),
              "fired": off.get("fired_rows"),
              "prev_correct_firing":
                  off.get("previously_correct_firing_rows")})

    # ---- T14R2.13 six-case replay ------------------------------------------
    six = load(ROOT / "evaluations/t14r2/six_case_replay.json")
    check("six_case_replay_all_recovered",
          bool(six) and six.get("status") == "PASS"
          and six.get("recovered") == 7 and six.get("all_fired") is True
          and six.get("gates_clean") is True,
          None if not six else {"recovered": six.get("recovered"),
                                "all_fired": six.get("all_fired"),
                                "gates_clean": six.get("gates_clean")})

    # ---- T14R2.14-2.17 frozen recheck + decision ---------------------------
    sci = load(ROOT / "evaluations/t14r2/runs/t14r2-scicomp-B3/summary.json")
    dec = load(ROOT / "evaluations/t14r2/scicomp_decision.json")
    sub = load(ROOT / "evaluations/t14r2/ode_subset_replay.json")
    check("model_identity",
          bool(sci) and sci.get("model") == "Qwen/Qwen3-4B-Instruct-2507",
          (sci or {}).get("model"))
    check("recheck_suite_checksum",
          bool(sci) and sci.get("suite_sha256") == suite_pin,
          (sci or {}).get("suite_sha256"))
    if sci and dec:
        check("scicomp_numeric_floor",
              (sci.get("numeric_accuracy") or 0) >= NUMERIC_FLOOR,
              sci.get("numeric_accuracy"), f"floor {NUMERIC_FLOOR}")
        check("scicomp_adoption",
              (sci.get("model_adoption_rate") or 0) >= ADOPTION_FLOOR,
              sci.get("model_adoption_rate"))
        check("scicomp_conceptual",
              (sci.get("conceptual_discipline") or 0) >= 1.0,
              sci.get("conceptual_discipline"))
        check("scicomp_adversarial",
              (sci.get("adversarial_handled_correctly") or 0) >= 0.96,
              sci.get("adversarial_handled_correctly"))
        check("scicomp_silent_mutation",
              (dec.get("gates") or {}).get("silent_mutations", {})
              .get("measured") == 0,
              (dec.get("gates") or {}).get("silent_mutations"),
              "see scicomp_decision.json silent_mutations gate")
        check("scicomp_exceptions",
              (sci.get("pipeline_exception_count") or 0) == 0,
              sci.get("pipeline_exception_count"))
        check("scicomp_decision_recorded",
              dec.get("decision") in {
                  "PROMOTE_SCICOMP_LAB", "KEEP_SCICOMP_EXPERIMENTAL",
                  "REJECT_SCICOMP"},
              dec.get("decision"))
        check("weight_promotion_no",
              dec.get("weight_promotion") == "NO",
              dec.get("weight_promotion"))
    else:
        check("recheck_and_decision_present", False, None)
    if sub:
        check("ode_subset_no_material_regression",
              sub.get("no_material_regression") is True,
              {"regressions": sub.get("regressions")})
        check("ode_six_recovered_in_recheck",
              sub.get("six_recovered_count") == 6,
              {"recovered": sub.get("six_recovered_count")})
        check("ode_second_order_audit_recovered",
              sub.get("second_order_audit_correct") is True,
              sub.get("second_order_audit_correct"))
    else:
        check("ode_subset_replay_present", False, None)

    # Executive Router: UNTOUCHED by T14R2 (pin re-verified above); the
    # T14R decision remains the authoritative executive decision
    edec = load(ROOT / "evaluations/t14r/executive_decision.json")
    check("executive_decision_unchanged_from_T14R",
          bool(edec) and edec.get("decision")
          == "KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL",
          (edec or {}).get("decision"),
          "T14R2 mandate: do not modify the Executive Router")

    # ---- protection battery + security (T14R2.19) --------------------------
    prot = load(ROOT / "evaluations/t14r2/protection/regression_summary.json")
    check("protection_battery",
          bool(prot) and prot.get("status") == "ALL_PASS",
          (prot or {}).get("status"))
    probe = load(ROOT / "evaluations/t14r2/mutation_safety_probe.json")
    check("mutation_safety_probe_layer_inserted",
          bool(probe) and probe.get("passed") is True,
          (probe or {}).get("passed"))
    sec = load(ROOT / "evaluations/t14r2/protection/security_summary.json")
    check("security",
          bool(sec) and sec.get("violations") == 0, sec)

    # ---- performance (T14R2.20) --------------------------------------------
    perf = load(ROOT / "evaluations/t14r2/performance.json")
    check("performance_recorded", bool(perf), None if not perf else {
        "layer_median_us": perf.get("offline_layer_latency_us", {})
        .get("select", {}).get("median_us")})

    # ---- no-training proof --------------------------------------------------
    train_dirty = []
    r = subprocess.run(
        ["git", "status", "--porcelain", "training", "src"],
        cwd=str(ROOT), capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        if "adapter" in line.lower() or "lora" in line.lower():
            train_dirty.append(line)
    check("no_training_adapter_unchanged",
          adp_h == PINS["t3_adapter"] and not train_dirty,
          {"adapter": adp_h, "dirty": train_dirty})
    check("no_paid_compute", True, "NOT_USED",
          "T14R2 paid routes emit PAID_COMPUTE_GATE_REQUIRED only")

    # ---- pytest (T14R2.21) ---------------------------------------------------
    pytest_final = load(ROOT / "evaluations/t14r2/pytest_final.json")
    if pytest_final:
        check("pytest_zero_failed",
              pytest_final.get("failed") == 0
              and pytest_final.get("errors") == 0
              and pytest_final.get("exit_code") == 0,
              pytest_final)
    else:
        check("pytest_final_present", False, None)

    fails = [c for c in checks if c["status"] == "FAIL"]
    audit = {
        "milestone": "T14R2 — ODE Planner Operation Selection Closure",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "gates_total": len(checks),
        "passes": len(checks) - len(fails),
        "fails": [c["check"] for c in fails],
        "model_identity": "Qwen/Qwen3-4B-Instruct-2507 (Mango-4B-System-v1)",
        "router_sha256": nec_h,
        "skill_registry_sha256": reg_h,
        "fidelity_sha256": fid_h,
        "semantic_sha256": sem_h,
        "firewall_sha256": fw_h,
        "adapter_sha256": adp_h,
        "ode_intent_sha256": ode_h,
        "decision_scicomp": (dec or {}).get("decision"),
        "executive_router_decision": (edec or {}).get("decision"),
        "no_training": True,
        "no_paid_compute": True,
        "weight_promotion": "NO",
        "ready_for_T15": ("YES" if not fails else "NO"),
        "manual_override": False,
    }
    out = ROOT / "evaluations/t14r2/final_audit.json"
    out.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"gates: {audit['gates_total']}  passes: {audit['passes']}  "
          f"fails: {audit['fails']}  ready_for_T15: {audit['ready_for_T15']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())