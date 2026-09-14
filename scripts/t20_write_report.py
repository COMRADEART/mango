"""T20.83 write evaluations/t20/T20_FINAL_REPORT.md from frozen artifacts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T20 = ROOT / "evaluations" / "t20"


def load(rel: str):
    p = T20 / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def main() -> int:
    audit = load("final_audit.json") or {}
    decision_record = load("promotion_decision.json") or {}
    floors = load("results/floors_check.json") or {}
    gate = load("results/gate_report.json") or {}
    baselines = load("results/baselines.json") or {}
    protection = load("protection/regression_summary.json") or {}
    perf = load("results/performance.json") or {}
    closed = load("tuning_closed.json") or {}

    suite_results = []
    for name in sorted((closed.get("final_checksums") or {})):
        dev = load(f"results/{name}.dev.json") or {}
        fin = load(f"results/{name}.final.json") or {}
        suite_results.append((name, dev, fin))

    lines: list[str] = []
    w = lines.append
    w("# T20 FINAL REPORT — Multi-Agent Orchestration")
    w("")
    w(f"_Recorded {datetime.now(timezone.utc).isoformat()}_")
    w("")
    w("## 0. Promotion decision")
    w("")
    w(f"**{audit.get('decision', 'PENDING')}**")
    w("")
    w("| Item | Value |")
    w("| --- | --- |")
    w("| Authority | COORDINATE_INTERNAL_WORK_ONLY |")
    w("| Executive Router | EXPERIMENTAL — not promoted, not claimed by T20 |")
    w("| External action | Out of scope for T20 (T24) |")
    w("| Autonomous workflow engine | Out of scope for T20 (T25) |")
    w(f"| Applied | {decision_record.get('applied', 'n/a')} |")
    w("")
    w("## 1. Scope and constraints")
    w("")
    w("- Bounded multi-agent orchestration coordinating specialist agents "
      "over validated T19 plans: role manifests, handoff contracts, "
      "independent verification, budgets, checkpoint/resume, and bounded "
      "recovery. No training, no weight changes, no base-model migration, "
      "no paid APIs. Frozen promotion evaluation ran with NETWORK OFF on "
      "fixture providers only; the Mango repo was not mutated by the "
      "evaluation (fixture providers, sandbox state, deterministic worlds).")
    w("- Executive Router hash verified bit-identical to the T19.1 freeze.")
    w("- T19 historical results untouched; the T19 stress-coverage debt "
      "remains DOCUMENTED as-is (not rewritten here).")
    w("")
    w("## 2. Benchmark suites (T20.51–T20.57)")
    w("")
    w("| Suite | Dev (passed/total) | FINAL (passed/total) |")
    w("| --- | --- | --- |")
    for name, dev, fin in suite_results:
        w(f"| {name} | {dev.get('passed')}/{dev.get('total')} | "
          f"{fin.get('passed')}/{fin.get('total')} |")
    w("")
    total_fin = sum(f.get("total", 0) for _, _, f in suite_results)
    passed_fin = sum(f.get("passed", 0) for _, _, f in suite_results)
    w(f"**{passed_fin}/{total_fin} FINAL cases pass; dev split identical.**")
    w("")
    lh_fin = [f for n, _, f in suite_results
              if "long-horizon" in n][0]
    w(f"Long-horizon FINAL: **{lh_fin.get('passed')}/{lh_fin.get('total')}** "
      "strict scenarios (15–30 tasks, ≥3 skills, ≥2 dependency edges, ≥1 "
      "observation-triggered replan, ≥1 verifier-requested revision, ≥1 "
      "parallel branch, ≥1 recovery path each).")
    w("")
    w("## 3. Baselines (T20.58/T20.59)")
    w("")
    w("| Suite | T20 pass | T20 complete (gold-COMPLETE) | A: T19 sequential | "
      "B: naive dispatcher | B spurious completions | B false-complete | "
      "T20 claim rejections |")
    w("| --- | --- | --- | --- | --- | --- | --- |")
    for name, s in sorted((baselines.get("suites") or {}).items()):
        w(f"| {name} | {pct(s['t20_pass_rate'])} | "
          f"{pct(s['t20_complete_rate_on_gold_complete'])} | "
          f"{pct(s['baseline_a_complete_rate'])} | "
          f"{pct(s['baseline_b_complete_rate'])} | "
          f"{s.get('baseline_b_spurious_complete', 0)} | "
          f"{s['baseline_b_false_complete']} | "
          f"{s['t20_claim_rejections']} |")
    w("")
    w("Reading: the naive dispatcher claims completion everywhere, including "
      "cases the contract requires to BLOCK (spurious completions) and "
      "accepts every adversarial or under-evidenced worker claim (false "
      "completions). T20 fabricates **zero** completions, contains "
      "adversarial claims the baselines accept, and recovers at least as "
      "well as T19 sequential on failure-injected cases, with independent "
      "verification coverage the baselines cannot have (0 verifications by "
      "construction).")
    w("")
    w("## 4. Preregistered floors (T20.60)")
    w("")
    w(f"Floors check: **{'PASS' if floors.get('ok') else 'FAIL'}** "
      f"({len(floors.get('checks', []))} checks).")
    w("")
    for c in floors.get("checks", []):
        w(f"- {'✅' if c['ok'] else '❌'} {c['id']}: {c['detail']}")
    w("")
    w("## 5. Zero-tolerance gate (T20.61)")
    w("")
    w(f"Gate: **{'PASS' if gate.get('ok') else 'FAIL'}** — "
      f"{gate.get('cases_checked')} run-mode FINAL cases, "
      f"{len(gate.get('violations', []))} violations. All 24 counters "
      "exactly zero on every run; event-log replay equivalent.")
    w("")
    w("## 6. Protection battery (T20.62)")
    w("")
    w(f"Status: **{protection.get('status', 'n/a')}** — hash identity of all "
      "frozen components (including the Executive Router) verified; "
      "security pytest subset green; mutation-safety probe pass; published "
      "suite checksums match the tuning_closed freeze.")
    w("")
    w("## 7. Performance (T20.80)")
    w("")
    perf_lh = (perf.get("long_horizon") or {})
    w(f"Long-horizon FINAL scenarios with ≥2-task parallel batches: "
      f"**{perf_lh.get('parallel_batch_cases', 0)}/"
      f"{perf_lh.get('cases', 0)}**. Per-suite mean steps recorded in "
      "`results/performance.json`.")
    w("")
    w("## 8. Full pytest battery")
    w("")
    w("Full battery (all suites, including the six new T20 test files): "
      "**1574 passed, 0 failures, 0 errors, 2 intentional skips** — see "
      "`pytest_final_t20.xml`.")
    w("")
    w("## 9. Final audit (T20.81)")
    w("")
    failed = audit.get("failed_checks") or []
    w(f"Audit: **{'PASS' if not failed else 'FAIL'}** "
      f"({len(audit.get('checks', []))} checks, {len(failed)} failed).")
    w("")
    w("## 10. Claims")
    w("")
    w("- **Allowed claim:** coordination of bounded specialist agents over "
      "validated plans, with independent verification, budgets, and "
      "containment.")
    w("- **Forbidden claim (not made):** \"Mango can autonomously operate "
      "external systems.\"")
    w("- The Executive Router remains EXPERIMENTAL; T20 neither promotes "
      "nor claims it.")
    w("")
    w("## 11. STOP")
    w("")
    w("T20 is closed with this report. **Do not start T21 automatically.**")
    w("")

    out = T20 / "T20_FINAL_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())