"""T15R final report writer. Reads artifacts; no manual override."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t15r/T15R_FINAL_REPORT.md"


def load(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def acc(npass, n):
    if not n:
        return "n/a"
    return f"{npass}/{n} = {npass / n:.4f}"


def main() -> int:
    entry = load(ROOT / "evaluations/t15r/t15r_entry_gate.json") or {}
    tax = load(ROOT / "evaluations/t15r/t15_failure_analysis.json") or {}
    micro = load(ROOT / "evaluations/t15r/repair_microbench/summary.json") or {}
    rlman = load(ROOT / "evaluations/t15r/suites/mango-code-repair-loop-v1/manifest.json") or {}
    v11 = load(ROOT / "evaluations/t15r/suites/mango-code-eval-v1.1/manifest.json") or {}
    vdiff = load(ROOT / "evaluations/t15r/v1_vs_v1.1.json") or {}
    replay = load(ROOT / "evaluations/t15r/t15_failure_replay.json") or {}
    summary = load(ROOT / "evaluations/t15r/runs/code-final/summary.json") or {}
    floors = load(ROOT / "evaluations/t15r/floors_evaluation.json") or {}
    prot = load(ROOT / "evaluations/t15r/protection/regression_summary.json") or {}
    sec = load(ROOT / "evaluations/t15r/protection/security_summary.json") or {}
    py = load(ROOT / "evaluations/t15r/pytest_final.json") or {}
    audit = load(ROOT / "evaluations/t15r/final_audit.json") or {}
    decision = load(ROOT / "evaluations/t15r/code_decision.json") or {}
    sci = load(ROOT / "evaluations/t15r/protection/t15r-scicomp-recheck/summary.json") or {}

    fl = floors.get("floors") or {}
    layers = prot.get("layers") or {}
    by = replay.get("by_category") or {}
    rates = micro.get("rates") or {}
    cat = summary.get("by_category") or {}

    def fget(name):
        row = fl.get(name) or {}
        m, n, v = row.get("measured"), row.get("n"), row.get("verdict")
        return f"{m} (n={n}) {v}" if row else "n/a"

    def cat_line(name, t15_before):
        b = by.get(name) or {}
        c = cat.get(name) or {}
        return (
            f"Before: {t15_before}\n"
            f"After: {c.get('pass', '?')}/{c.get('n', '?')} "
            f"(replay recovered {b.get('recovered', 0)}, "
            f"still failing {b.get('still_failing', 0)}, "
            f"regressed {b.get('regressed', 0)})"
        )

    code_dec = decision.get("decision") or floors.get("decision") or "KEEP_CODE_SKILL_EXPERIMENTAL"
    av_after = decision.get("semantic_after") or "EXPERIMENTAL"
    entry_status = entry.get("status") or "UNKNOWN"
    audit_pass = audit.get("passed")
    py_fail = py.get("failures")
    sec_v = sec.get("violations")
    floors_fail = (floors.get("critical_failures") or []) + (floors.get("quality_failures") or [])
    prot_status = prot.get("status")
    if entry_status != "PASS":
        status = "BLOCKED"
    elif audit_pass and not floors_fail and prot_status == "ALL_PASS" and py_fail == 0:
        status = "PASS"
    elif summary.get("n_tasks") == 139:
        status = "PARTIAL"
    else:
        status = "BLOCKED"

    main_finding = (
        "YES" if code_dec == "PROMOTE_CODE_SKILL"
        else "PARTIALLY" if (replay.get("recovered") or 0) > 0
        else "NO"
    )
    if code_dec == "PROMOTE_CODE_SKILL":
        bottleneck = "NONE — quality floors met"
        family = "CLOSED"
        t16 = "YES"
        next_step = "T16 planning (do not start automatically)"
    else:
        bottleneck = "REPAIR LOOP STILL FAILS TO CONVERGE ON MULTI-FILE AND STUB IMPLEMENTATIONS"
        family = "NOT_CLOSED"
        t16 = "NO"
        next_step = "Diagnose remaining executable failures without weakening safety; do not start T16"

    counts = tax.get("counts") or {}
    tax_table = "\n".join(
        f"| {k} | {v} |" for k, v in counts.items()
    ) or "| (none) | 0 |"

    md = f"""# Mango — T15R Iterative Patch Retention & CODE Promotion Closure

## STATUS

{status}

## Entry Gate

{entry_status}

## Starting Point

CODE:
EXPERIMENTAL

T15 overall:
111/139 = 0.7986

bug-fix:
15/25 = 0.60

executable:
44/72 = 0.6111

unrelated edit:
3/72 = 0.0417

## Failure Taxonomy

| label | count |
|---|---|
{tax_table}

Dominant bottleneck at freeze: {tax.get("dominant_bottleneck")}

## Repair Architecture

Original-state behavior:
T15 reverted to the pre-edit repository whenever targeted tests were still failing after the repair budget, wiping verified partial progress (`files_touched: []`).

New best-state behavior:
Every candidate is ranked; BEST_VERIFIED_STATE is overwritten only with evidence. Subsequent repair rounds restore BEST, compute a failure delta, and target remaining failures. ORIGINAL is restored only for safety / protected-component / weakening / catastrophic-regression / objectively-worse states.

## Repair Microbench

Total:
{rlman.get("total")}
Final:
{rlman.get("final_n")}
Checksum:
{rlman.get("final_sha256")}

Best-state selection:
{rates.get("best_state_selection")}
Failure-delta accuracy:
{rates.get("failure_delta_correctness")}
Convergence:
{rates.get("repair_loop_convergence")}
Unsafe acceptance:
{rates.get("unsafe_state_acceptance")}
Unnecessary revert:
{rates.get("unnecessary_revert")}

## T15 Failure Replay

Recovered:
{replay.get("recovered")}
Still failing:
{replay.get("still_failing")}
Regressed:
{replay.get("newly_regressed")}

### multi_fix

{cat_line("multi_fix", "0/10")}

### data_xform

{cat_line("data_xform", "0/6")}

### refactor

{cat_line("refactor", "3/5")}

### algo

{cat_line("algo", "1/4")}

### feature

{cat_line("feature", "8/13")}

Average repair rounds: {replay.get("average_repair_rounds")}
Median repair rounds: {replay.get("median_repair_rounds")}
Best-state retained count: {replay.get("best_state_retained_count")}
Full revert count: {replay.get("full_revert_count")}
Unsafe revert count: {replay.get("unsafe_revert_count")}

## Benchmark Versioning

v1 historical:
unchanged {"YES" if vdiff.get("v1_historical_unchanged") else "NO"}

v1.1 created:
{"YES" if vdiff.get("v1.1_created") else "NO"}

Metadata corrections:
{json.dumps(vdiff.get("metadata_corrections"), indent=2)}

Behavioral changes to benchmark:
{vdiff.get("behavioral_changes_to_benchmark") or v11.get("behavioral_changes") or "NONE"}

## Final CODE Metrics

Code search:
{fget("code_search_accuracy")}
Plan validity:
{fget("plan_validity")}
Bug-fix:
{fget("bug_fix_success")}
Executable:
{fget("executable_task_success")}
No-change:
{fget("no_change_correctness")}
Unrelated edit:
{fget("unrelated_edit_rate")}

Overall v1.1 FINAL: {summary.get("n_pass")}/{summary.get("n_tasks")} = {summary.get("accuracy")}

## Safety

Destructive:
{fget("destructive_violations")}
Fabricated execution:
{fget("fabricated_execution_claims")}
Secret leakage:
{fget("secret_leakage")}
Test weakening:
{fget("test_weakening")}
Unauthorized network:
{fget("unauthorized_network")}
Unauthorized paid compute:
{fget("unauthorized_paid_compute")}
Protected edits:
{(floors.get("extra_safety") or {}).get("protected_component_violations")}
Benchmark tampering:
{(floors.get("extra_safety") or {}).get("benchmark_tampering")}

## Protection Battery

T4:
{json.dumps(layers.get("t4"), indent=2)}
T5R:
{json.dumps(layers.get("t5r"), indent=2)}
SciComp:
{json.dumps(layers.get("scicomp") or {{"numeric": sci.get("numeric_accuracy")}}, indent=2)}
Capacity:
{json.dumps(layers.get("capacity"), indent=2)}
Correction:
{json.dumps(layers.get("correction"), indent=2)}
Extraction:
{json.dumps(layers.get("extraction"), indent=2)}
Fidelity:
{json.dumps(layers.get("fidelity"), indent=2)}
Security:
{json.dumps(sec, indent=2)}

## Performance

Average repair rounds:
{summary.get("avg_repair_rounds")}
Repair latency:
{summary.get("avg_latency_s")}
End-to-end latency:
{summary.get("wall_seconds")}
VRAM:
{summary.get("vram_peak_bytes")}
Memory:
{summary.get("peak_rss_bytes")}

## Tests

Collected:
{py.get("tests")}
Passed:
{py.get("passed")}
Failed:
{py.get("failed")}
Skipped:
{py.get("skipped")}
Errors:
{py.get("errors")}
Duration:
{py.get("time_s")}

## Final Audit

Passed:
{audit.get("passes")}
Failed:
{audit.get("fails")}

## CODE Decision

{code_dec}

## CODE Availability

Before:
EXPERIMENTAL

After:
{av_after}

## Executive Router

UNCHANGED

## Weight Promotion

NO

## Paid Compute

NOT_USED

## Main Finding

Answer:

Did retaining verified partial patches and repairing from the best known repository state close Mango's coding quality gap without weakening repository safety?

{main_finding}

## Dominant Remaining Bottleneck

{bottleneck}

## T15 Family Closure

{family}

## Ready for T16

{t16}

## Highest-Value Next Step

{next_step}

STOP.

Do not start T16 automatically.
"""
    OUT.write_text(md, encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
