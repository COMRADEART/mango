"""T20.60 preregistered floors check.

Reads evaluations/t20/floors.json (preregistered) and checks it against
the frozen FINAL-split results and the baselines comparison. Exit 0 =
all floors met. Any miss is a promotion blocker unless explicitly waived
in the final report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "evaluations" / "t20" / "results"
FLOORS_PATH = ROOT / "evaluations" / "t20" / "floors.json"


def main(argv: list[str]) -> int:
    floors = json.loads(FLOORS_PATH.read_text(encoding="utf-8"))
    checks: list[dict] = []

    for suite, sf in sorted(floors["suite_floors"].items()):
        dev_path = RESULTS_DIR / f"{suite}.dev.json"
        fin_path = RESULTS_DIR / f"{suite}.final.json"
        if not fin_path.exists():
            checks.append({"check": f"cases:{suite}", "ok": False,
                           "detail": "missing results file"})
            continue
        fin = json.loads(fin_path.read_text(encoding="utf-8"))
        dev = json.loads(dev_path.read_text(encoding="utf-8")) \
            if dev_path.exists() else fin
        # directive suite minimums count the whole suite (dev + final)
        total = fin["total"] + dev["total"]
        passed = fin["passed"] + dev["passed"]
        pass_rate = passed / total if total else 0.0
        ok = total >= sf["min_cases"] and pass_rate >= sf["min_pass_rate"]
        checks.append({
            "ok": ok, "id": f"suite:{suite}",
            "detail": f"total={total}>={sf['min_cases']} "
                      f"pass_rate={pass_rate:.3f}"
                      f">={sf['min_pass_rate']}"})

    bl_path = RESULTS_DIR / "baselines.json"
    if not bl_path.exists():
        checks.append({"ok": False, "id": "baselines",
                       "detail": "baselines.json missing"})
    else:
        bl = json.loads(bl_path.read_text(encoding="utf-8"))
        cmp_floors = floors["comparison_floors"]
        for suite, s in sorted(bl["suites"].items()):
            if cmp_floors.get("t20_false_complete_le_baseline_b"):
                ok = s["t20_false_complete_cases"] <= \
                    s["baseline_b_false_complete"]
                checks.append({
                    "ok": ok, "id": f"false_complete_le_b:{suite}",
                    "detail": f"t20={s['t20_false_complete_cases']} "
                              f"baseline_b={s['baseline_b_false_complete']}"})
            if cmp_floors.get("t20_claim_rejections_gt_zero_on_adversarial") \
                    and s["adversarial_cases"] > 0:
                ok = s["adversarial_contained"] == s["adversarial_cases"]
                checks.append({
                    "ok": ok, "id": f"adversarial_contained:{suite}",
                    "detail": f"{s['adversarial_contained']}/"
                              f"{s['adversarial_cases']} contained"})
            if cmp_floors.get(
                    "t20_parallel_batches_gt_zero_on_long_horizon_final") \
                    and "long-horizon" in suite:
                ok = s["t20_parallel_batch_cases"] > 0
                checks.append({
                    "ok": ok, "id": f"parallel_batches:{suite}",
                    "detail": f"batch_cases={s['t20_parallel_batch_cases']}"})
            if cmp_floors.get(
                    "t20_complete_rate_ge_baseline_a_on_recovery_suites") \
                    and suite in cmp_floors.get("recovery_suites", []):
                ok = s["t20_complete_rate_on_gold_complete"] >= \
                    s["baseline_a_complete_rate"] - 1e-9
                checks.append({
                    "ok": ok, "id": f"recovery_ge_a:{suite}",
                    "detail": f"t20={s['t20_complete_rate_on_gold_complete']:.3f}"
                              f" baseline_a={s['baseline_a_complete_rate']:.3f}"})

    failed = [c for c in checks if not c["ok"]]
    out = {"ok": not failed, "checks": checks, "failed": failed}
    (RESULTS_DIR / "floors_check.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))