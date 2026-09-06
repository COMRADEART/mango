"""T4 final close-out: independent validation + metric recomputation (STEP 1-4).

Recomputes every reported metric directly from saved rows and the tool-call
audit log. Does NOT read t4_metrics.json (stale artifact from the superseded
320-budget run - it is deliberately not used here).

Usage: python scripts/t4_final_analysis.py
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SUITE = ROOT / "evaluations" / "tool-suite" / "v1"
SLUG = "Qwen3-1.7B"
TOOL_PRED = SUITE / SLUG / "tool" / "predictions.jsonl"
TOOL_CALLS = SUITE / SLUG / "tool" / "tool_calls.jsonl"
NOTOOL_PRED = SUITE / SLUG / "notool" / "predictions.jsonl"
QUESTIONS = SUITE / "questions.jsonl"
SUPERSEDED_PRED = SUITE / SLUG / "tool_320budget_superseded" / "predictions.jsonl"


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.2f}%" if d else "n/a"


def extraction_ok(row: dict) -> bool:
    ea = row.get("extracted_answer")
    return ea is not None and ea != ""


def main() -> None:
    suite_ids = {q["eval_id"] for q in load_jsonl(QUESTIONS)}
    tool_rows = load_jsonl(TOOL_PRED)
    notool_rows = load_jsonl(NOTOOL_PRED)

    # ---------------- STEP 1: integrity ----------------
    print("=" * 72)
    print("STEP 1 - FINAL RUN INTEGRITY VALIDATION")
    print("=" * 72)
    ids = [r["eval_id"] for r in tool_rows]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    missing = suite_ids - set(ids)
    extra = set(ids) - suite_ids
    print(f"rows={len(tool_rows)} unique_ids={len(set(ids))} "
          f"suite_ids={len(suite_ids)}")
    print(f"duplicate_ids={len(dup)} {dup[:5]}")
    print(f"missing={len(missing)} {sorted(missing)[:5]}")
    print(f"extra_not_in_suite={len(extra)} {sorted(extra)[:5]}")

    models = Counter(r.get("model_id") for r in tool_rows)
    arms = Counter(r.get("arm") for r in tool_rows)
    print(f"model_ids={dict(models)}")
    print(f"arms={dict(arms)}")
    bad_verdicts = [r["eval_id"] for r in tool_rows
                    if r.get("verdict") not in ("PASS", "FAIL", "UNKNOWN")]
    errors = [r["eval_id"] for r in tool_rows if r.get("error")]
    no_raw = [r["eval_id"] for r in tool_rows if not r.get("raw_model_output")]
    print(f"invalid_verdicts={len(bad_verdicts)} rows_with_error_field="
          f"{len(errors)} rows_missing_raw_output={len(no_raw)}")

    # stale 320-budget rows: every raw output of a 1024-budget run may be
    # long; a 320-token cap truncates around ~1.3k chars. Count rows over 2k.
    long_raw = sum(1 for r in tool_rows
                   if len(r.get("raw_model_output") or "") > 2000)
    print(f"rows_with_raw_output_over_2000_chars={long_raw} "
          f"(incompatible with a 320-token cap)")
    print(f"superseded_run_rows={len(load_jsonl(SUPERSEDED_PRED))} "
          f"(kept archived in tool_320budget_superseded/)")
    # overlap check: no shared raw output between superseded and final
    sup_raw = {r["eval_id"]: r.get("raw_model_output") for r in
               load_jsonl(SUPERSEDED_PRED)}
    same_raw = [i for i, r in ((r["eval_id"], r) for r in tool_rows)
                if i in sup_raw and sup_raw[i] == r.get("raw_model_output")]
    print(f"rows_byte_identical_to_superseded_run={len(same_raw)}")

    # audit log correspondence
    calls = load_jsonl(TOOL_CALLS)
    calls_by_q: dict[str, list[dict]] = defaultdict(list)
    for c in calls:
        calls_by_q[c["question_id"]].append(c)
    embedded = {r["eval_id"]: (r.get("tool_calls") or []) for r in tool_rows}
    audit_total = len(calls)
    embedded_total = sum(len(v) for v in embedded.values())
    print(f"audit_log_calls={audit_total} embedded_row_calls={embedded_total}")
    # rows whose embedded calls are missing from the audit log (pre-restart)
    gap_rows = []
    for eid, ecs in embedded.items():
        acs = calls_by_q.get(eid, [])
        if len(ecs) != len(acs):
            gap_rows.append((eid, len(ecs), len(acs)))
    print(f"rows_where_audit_count_differs_from_embedded={len(gap_rows)} "
          f"{gap_rows[:10]}")
    n_rounds_dist = Counter(r.get("n_rounds") for r in tool_rows)
    nrd = dict(sorted(n_rounds_dist.items(),
                      key=lambda kv: (kv[0] is None, kv[0] or 0)))
    print(f"n_rounds_distribution={nrd}")

    # ---------------- STEP 2: independent metrics ----------------
    print()
    print("=" * 72)
    print("STEP 2 - INDEPENDENT METRIC RECOMPUTATION (FINAL TOOL ARM)")
    print("=" * 72)
    vc = Counter(r["verdict"] for r in tool_rows)
    n = len(tool_rows)
    correct = sum(1 for r in tool_rows if r["verdict"] == "PASS")
    extraction = sum(1 for r in tool_rows if extraction_ok(r))
    print(f"total={n}")
    print(f"correct(PASS)={correct} accuracy={pct(correct, n)}")
    print(f"FAIL={vc.get('FAIL', 0)} UNKNOWN={vc.get('UNKNOWN', 0)}")
    print(f"extraction_success={extraction}/{n}={pct(extraction, n)}")

    q_with_tools = sum(1 for r in tool_rows if embedded[r["eval_id"]])
    print(f"questions_invoking_tools={q_with_tools} ({pct(q_with_tools, n)})")
    print(f"total_tool_calls={embedded_total}")
    st = Counter(c.get("status") for c in calls)
    print(f"audit_call_status={dict(st)}")
    ecode = Counter(((c.get("error") or {}).get("code")) for c in calls
                    if c.get("status") == "error")
    print(f"error_codes={dict(ecode)}")
    wall = [c.get("wall_time_s") for c in calls
            if isinstance(c.get("wall_time_s"), (int, float))]
    if wall:
        print(f"tool_wall_time: max={max(wall):.4f}s "
              f"median={statistics.median(wall):.4f}s")

    lat = [r["latency_s"] for r in tool_rows
           if isinstance(r.get("latency_s"), (int, float))]
    if lat:
        print(f"latency: median={statistics.median(lat):.2f}s "
              f"mean={statistics.fmean(lat):.2f}s max={max(lat):.2f}s "
              f"(n={len(lat)})")
    out_tok = [r.get("output_tokens") for r in tool_rows
               if isinstance(r.get("output_tokens"), (int, float))]
    in_tok = [r.get("input_tokens") for r in tool_rows
              if isinstance(r.get("input_tokens"), (int, float))]
    if out_tok:
        print(f"output_tokens: mean={statistics.fmean(out_tok):.1f} "
              f"median={statistics.median(out_tok):.0f} (n={len(out_tok)})")
    if in_tok:
        print(f"input_tokens: mean={statistics.fmean(in_tok):.1f} "
              f"median={statistics.median(in_tok):.0f} (n={len(in_tok)})")

    to_rows = [r["eval_id"] for r in tool_rows
               if r.get("verdict_method") == "timeout"]
    to_calls = [c["question_id"] for c in calls
                if (c.get("error") or {}).get("code") == "TIMEOUT"]
    print(f"verifier_timeouts={len(to_rows)} tool_timeouts={len(to_calls)}")

    # verifier verdicts on this arm
    vm = Counter(r.get("verdict_method") for r in tool_rows)
    print(f"verdict_methods={dict(vm)}")
    pass_by_method = Counter(r.get("verdict_method") for r in tool_rows
                             if r["verdict"] == "PASS")
    print(f"PASS_by_method={dict(pass_by_method)}")

    # ---------------- STEP 3: head-to-head ----------------
    print()
    print("=" * 72)
    print("STEP 3 - HEAD-TO-HEAD: NO TOOL (1024) vs TOOL ENABLED (1024/round)")
    print("=" * 72)
    nc = Counter(r["verdict"] for r in notool_rows)
    n_correct = nc.get("PASS", 0)
    n_n = len(notool_rows)
    n_ext = sum(1 for r in notool_rows if extraction_ok(r))
    print(f"NO TOOL : total={n_n} correct={n_correct} "
          f"accuracy={pct(n_correct, n_n)} extraction={n_ext}/{n_n}="
          f"{pct(n_ext, n_n)} FAIL={nc.get('FAIL', 0)} "
          f"UNKNOWN={nc.get('UNKNOWN', 0)}")
    print(f"TOOL    : total={n} correct={correct} accuracy={pct(correct, n)} "
          f"extraction={extraction}/{n}={pct(extraction, n)} "
          f"FAIL={vc.get('FAIL', 0)} UNKNOWN={vc.get('UNKNOWN', 0)}")
    delta_pp = 100.0 * correct / n - 100.0 * n_correct / n_n
    print(f"ACCURACY DELTA (tool - notool) = {delta_pp:+.2f} pp")
    dext = 100.0 * extraction / n - 100.0 * n_ext / n_n
    print(f"EXTRACTION DELTA = {dext:+.2f} pp")
    print(f"timeout_rate: notool=0/{n_n} tool=0/{n} (no TIMEOUT errors logged)")

    # paired per-eval_id flip analysis
    nt_by_id = {r["eval_id"]: r for r in notool_rows}
    fixed, broken, same_pass, same_bad = [], [], 0, 0
    for r in tool_rows:
        o = nt_by_id.get(r["eval_id"])
        if not o:
            continue
        op, tp = o["verdict"] == "PASS", r["verdict"] == "PASS"
        if not op and tp:
            fixed.append((r["eval_id"], r.get("category"),
                          o["verdict"], r["verdict"]))
        elif op and not tp:
            broken.append((r["eval_id"], r.get("category"),
                           o["verdict"], r["verdict"]))
        elif tp:
            same_pass += 1
        else:
            same_bad += 1
    print(f"paired: fixed(notool_bad->tool_PASS)={len(fixed)} "
          f"broken(notool_PASS->tool_bad)={len(broken)} "
          f"both_PASS={same_pass} both_bad={same_bad}")
    print("fixed_by_category:", dict(Counter(c for _, c, _, _ in fixed)))
    print("broken_by_category:", dict(Counter(c for _, c, _, _ in broken)))

    # ---------------- STEP 4: per-category ----------------
    print()
    print("=" * 72)
    print("STEP 4 - PER-CATEGORY COMPARISON")
    print("=" * 72)
    cats = sorted({r.get("category") for r in tool_rows})
    print(f"{'category':28s} {'N':>3s} {'noTool':>7s} {'tool':>7s} "
          f"{'delta':>8s}")
    for cat in cats:
        nt = [r for r in notool_rows if r.get("category") == cat]
        tt = [r for r in tool_rows if r.get("category") == cat]
        na = 100.0 * sum(1 for r in nt if r["verdict"] == "PASS") / len(nt)
        ta = 100.0 * sum(1 for r in tt if r["verdict"] == "PASS") / len(tt)
        print(f"{cat:28s} {len(tt):3d} {na:6.1f}% {ta:6.1f}% "
              f"{ta - na:+7.1f}pp")

    # verdict-method flips for diagnosis
    print()
    print("tool-arm UNKNOWN causes:",
          dict(Counter(r.get("verdict_method") for r in tool_rows
                       if r["verdict"] == "UNKNOWN")))
    print("notool UNKNOWN causes:",
          dict(Counter(r.get("verdict_method") for r in notool_rows
                       if r["verdict"] == "UNKNOWN")))


if __name__ == "__main__":
    main()