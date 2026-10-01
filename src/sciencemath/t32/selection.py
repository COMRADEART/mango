"""T32 Phase 8 selection (rules PREDECLARED in DEV_PROTOCOL.md §5/§6).

Reads the dev metrics files written by sciencemath.t32.dev_eval for the
anchors (base, t30-anchor) and every trained candidate, applies the
eligibility gates and the selection rule, and writes
evaluations/t32/development/T32_PHASE8_SELECTION.json.

Selection NEVER reads T31 evaluation scores.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, "src")

OUT = Path("evaluations/t32/development")

# DEV_PROTOCOL §5
GATE_MATH_PP = 5.0
GATE_MC_PP = 3.0
GATE_SCIQ_PP = 3.0
EXPERIMENT_INDEX = {"A": 1, "B": 2, "C": 3}  # §6 tie-break (c): §8 order A,B,C


def arm_metrics(name: str) -> dict:
    path = OUT / f"{name}_metrics.json"
    if not path.exists():
        return {"missing": True}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {"missing": False, **d}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="t32-A,t32-B,t32-C")
    args = ap.parse_args()
    names = [s.strip() for s in args.candidates.split(",") if s.strip()]
    missing_candidates = [n for n in names if arm_metrics(n)["missing"]]
    if missing_candidates:
        raise ValueError(f"All declared candidates must be evaluated: {missing_candidates}")

    base = arm_metrics("base")
    t30 = arm_metrics("t30-anchor")
    missing = [n for n, m in (("base", base), ("t30-anchor", t30))
               if m["missing"]]
    if missing:
        print(f"anchors not measured yet: {missing}; run dev_eval first")
        return 1

    report = {"anchors": {
        "base": {"math_dev_mean": base.get("math_dev_mean"),
                 "acc_mc_dev": base.get("acc_mc_dev"),
                 "acc_sciq_dev": base.get("acc_sciq_dev")},
        "t30-anchor": {"math_dev_mean": t30.get("math_dev_mean"),
                       "acc_mc_dev": t30.get("acc_mc_dev"),
                       "acc_sciq_dev": t30.get("acc_sciq_dev")}},
        "candidates": {}, "eligible": [], "not_eligible": []}

    for c in names:
        m = arm_metrics(c)
        if m["missing"]:
            print(f"candidate {c}: metrics missing; skipped")
            report["candidates"][c] = {"missing": True}
            continue
        d_math = round(100 * ((m.get("math_dev_mean") or 0.0)
                       - (t30.get("math_dev_mean") or 0.0)), 4)
        d_mc = round(100 * ((m.get("acc_mc_dev") or 0.0)
                     - (t30.get("acc_mc_dev") or 0.0)), 4)
        d_sciq = round(100 * ((m.get("acc_sciq_dev") or 0.0)
                       - (t30.get("acc_sciq_dev") or 0.0)), 4)
        gates = {
            "g1_math_restoration": d_math >= GATE_MATH_PP,
            "g2_mc_preservation": d_mc >= -GATE_MC_PP,
            "g3_sciq_preservation": d_sciq >= -GATE_SCIQ_PP,
            # g4 contamination + g5 manifest recorded in the candidate's
            # mixture manifest / training summary; asserted here from files
        }
        g4 = _contamination_ok(c)
        g5 = _manifest_ok(c)
        gates["g4_contamination_clean"] = g4
        gates["g5_training_manifest_recorded"] = g5
        eligible = all(gates.values())
        entry = {
            "math_dev_mean": m.get("math_dev_mean"),
            "acc_gsm8k_dev": m.get("acc_gsm8k_dev"),
            "acc_math_dev": m.get("acc_math_dev"),
            "acc_mc_dev": m.get("acc_mc_dev"),
            "acc_sciq_dev": m.get("acc_sciq_dev"),
            "delta_math_dev_mean_vs_t30": d_math,
            "delta_mc_dev_vs_t30": d_mc,
            "delta_sciq_dev_vs_t30": d_sciq,
            "gates": gates, "eligible": eligible,
            "experiment_index": EXPERIMENT_INDEX.get(
                c.split("-")[-1][0]), }
        report["candidates"][c] = entry
        (report["eligible"] if eligible
         else report["not_eligible"]).append(c)

    # §6: highest math_dev_mean among eligible; tie-breaks mc, sciq, index
    selected = selected_rule = None
    if report["eligible"]:
        pool = [(c, report["candidates"][c]) for c in report["eligible"]]
        pool.sort(key=lambda kv: (
            -(kv[1]["math_dev_mean"] or 0.0),
            abs(kv[1]["delta_mc_dev_vs_t30"]),
            abs(kv[1]["delta_sciq_dev_vs_t30"]),
            kv[1]["experiment_index"] or 99))
        selected = pool[0][0]
        selected_rule = "highest math_dev_mean among eligible (DEV_PROTOCOL §6)"
    else:
        pool = [(c, report["candidates"][c]) for c in report["candidates"]
                if not report["candidates"][c].get("missing")]
        if pool:
            pool.sort(key=lambda kv: -(kv[1]["math_dev_mean"] or 0.0))
            if pool:
                selected = pool[0][0]
                selected_rule = (
                    "NO candidate eligible; final locked evaluation runs the "
                    "highest math_dev_mean overall (DEV_PROTOCOL §6 fallback)")

    report["selected"] = selected
    report["selection_rule_applied"] = selected_rule
    report["gate_thresholds"] = {"math_restoration_pp": GATE_MATH_PP,
                                 "mc_preservation_pp": GATE_MC_PP,
                                 "sciq_preservation_pp": GATE_SCIQ_PP}

    path = OUT / "T32_PHASE8_SELECTION.json"
    path.write_text(json.dumps(report, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps({"selected": selected, "rule": selected_rule,
                      "eligible": report["eligible"],
                      "not_eligible": report["not_eligible"],
                      "written": str(path)}, indent=2))
    return 0


def _contamination_ok(cand: str) -> bool:
    """Gate 4: the candidate's mixture manifest records clean gates."""
    name = {"A": "t32-A-math-restore", "B": "t32-B-task-balanced",
            "C": "t32-C-conservative"}.get(cand.removeprefix("t32-"))
    if not name:
        return False
    path = Path("training/t32/candidates") / name / "manifest.json"
    if not path.exists():
        return False
    m = json.loads(path.read_text(encoding="utf-8"))
    gates = m.get("gates", {})
    if int(gates.get("new_record_near_gate_removed", 1)) != 0:
        return False
    if int(gates.get("t30_replay_near_matches_disclosed", 1)) != 0:
        return False
    report = Path("training/t32/pools/contamination_report.json")
    if not report.exists():
        return False
    r = json.loads(report.read_text(encoding="utf-8"))
    return (int(r.get("direct_leakage_found", 1)) == 0
            and int(r.get("near_leakage_found", 1)) == 0)


def _manifest_ok(cand: str) -> bool:
    """Gate 5: a training summary with the adapter sha exists."""
    name = {"A": "Mango-T32-A-math-restore", "B": "Mango-T32-B-task-balanced",
            "C": "Mango-T32-C-conservative"}.get(cand.removeprefix("t32-"))
    if not name:
        return False
    p = OUT / f"train_{name}.json"
    if not p.exists():
        return False
    d = json.loads(p.read_text(encoding="utf-8"))
    import hashlib
    adapter_name = {"A": "t32-A-math-restore", "B": "t32-B-task-balanced", "C": "t32-C-conservative"}[cand.removeprefix("t32-")]
    adapter = Path("training/adapters") / adapter_name
    manifest = adapter / "training_manifest.json"
    weights = adapter / "adapter_model.safetensors"
    if not manifest.is_file() or not weights.is_file():
        return False
    m = json.loads(manifest.read_text(encoding="utf-8"))
    if not m.get("dataset", {}).get("checksums") or not m.get("training_config") or m.get("seed") is None:
        return False
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    receipt = OUT / f"{cand}_artifact_hash.json"
    receipt.write_text(json.dumps({"adapter_sha256": digest, "training_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}, indent=2) + "\n", encoding="utf-8")
    return d.get("summary", {}).get("status") == "COMPLETE" \
        and d.get("summary", {}).get("reload_ok") is True


if __name__ == "__main__":
    raise SystemExit(main())
