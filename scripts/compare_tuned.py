"""T3 base-vs-tuned comparison + failure analysis.

Reads the frozen T2 Qwen3 non-thinking baseline metrics (the reference
declared in configs/training.yaml before the tuned evaluation) and the T3
tuned metrics recomputed from predictions.jsonl, writes:

  evaluations/tuned/t3_comparison.json
  evaluations/tuned/T3_COMPARISON.md
  evaluations/tuned/T3_FAILURE_ANALYSIS.md

The catastrophic-forgetting gate (SCIENCE_REGRESSION) is evaluated here with
the threshold declared in the config — never invented after seeing results.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REPO_ROOT, load_configs, setup_logging  # noqa: E402

from sciencemath.utils.io_utils import load_json, read_jsonl, write_json  # noqa: E402

TUNED_DIR = REPO_ROOT / "evaluations" / "tuned" / "sciencemath-v0.1-t3"

MATH_CATEGORIES = {"arithmetic", "algebra", "geometry",
                   "trigonometry_precalculus", "probability_statistics", "calculus"}
SCIENCE_CATEGORIES = {"general_science", "physics", "chemistry", "biology",
                      "astronomy_earth_science"}
PRIMARY_CATEGORIES = MATH_CATEGORIES | SCIENCE_CATEGORIES


def macro(per_cat: dict, names: set) -> float | None:
    vals = [per_cat[n] for n in sorted(names) if n in per_cat]
    return sum(vals) / len(vals) if vals else None


def build_comparison(tuned_metrics: dict, base_metrics: dict) -> dict:
    keys = ["overall_accuracy", "extraction_success_rate",
            "invalid_response_rate", "refusal_rate",
            "median_latency_s", "avg_latency_s", "avg_output_tokens",
            "avg_input_tokens"]
    cmp_: dict = {"metrics": {}}
    for k in keys:
        b, t = base_metrics.get(k), tuned_metrics.get(k)
        entry = {"base": b, "tuned": t}
        if isinstance(b, (int, float)) and isinstance(t, (int, float)):
            entry["delta"] = round(t - b, 4)
            entry["delta_pp"] = round((t - b) * 100, 4) if k.endswith("rate") or "accuracy" in k else round(t - b, 2)
        cmp_["metrics"][k] = entry

    per_cat_delta = {}
    for cat in sorted(set(base_metrics.get("per_category_accuracy", {}))
                      | set(tuned_metrics.get("per_category_accuracy", {}))):
        b = base_metrics.get("per_category_accuracy", {}).get(cat)
        t = tuned_metrics.get("per_category_accuracy", {}).get(cat)
        per_cat_delta[cat] = {"base": b, "tuned": t,
                              "delta_pp": (round((t - b) * 100, 2)
                                           if None not in (b, t) else None)}
    cmp_["per_category"] = per_cat_delta

    for name, cats in (("math_macro", MATH_CATEGORIES),
                       ("science_macro", SCIENCE_CATEGORIES),
                       ("primary_macro", PRIMARY_CATEGORIES)):
        b = base_metrics.get(f"{name}_accuracy")
        t = tuned_metrics.get(f"{name}_accuracy")
        # compute_metrics emits math/science macros but never primary_macro —
        # derive any missing macro from per-category accuracy
        if b is None:
            b = macro(base_metrics.get("per_category_accuracy", {}), cats)
        if t is None:
            t = macro(tuned_metrics.get("per_category_accuracy", {}), cats)
        cmp_[name] = {"base": b, "tuned": t,
                      "delta_pp": round((t - b) * 100, 2)
                      if None not in (b, t) else None}
    return cmp_


def forgetting_gate(cfg: dict, cmp_: dict) -> dict:
    gate_cfg = cfg.get("catastrophic_forgetting", {})
    threshold = float(gate_cfg.get("science_macro_drop_threshold_pp", 5.0))
    reference = gate_cfg.get("reference_science_macro")
    tuned_science = cmp_["science_macro"]["tuned"]
    if tuned_science is None:
        return {"flag": "NOT_EVALUABLE", "threshold_pp": threshold,
                "reason": "science macro missing from tuned metrics"}
    drop_pp = (reference - tuned_science) * 100.0
    flagged = drop_pp > threshold
    return {
        "flag_name": gate_cfg.get("flag_name", "SCIENCE_REGRESSION"),
        "flag": "SCIENCE_REGRESSION" if flagged else "PASS",
        "reference_science_macro": reference,
        "tuned_science_macro": tuned_science,
        "drop_pp": round(drop_pp, 2),
        "threshold_pp": threshold,
        "declared_in": "configs/training.yaml (fixed before tuned evaluation)",
    }


def failure_analysis(tuned_dir: Path) -> dict:
    preds = read_jsonl(tuned_dir / "predictions.jsonl")
    fails = [p for p in preds if not p.get("correct")]
    by_failure: dict = defaultdict(Counter)
    for p in fails:
        by_failure[p.get("failure")][p.get("category")] += 1
    failure_totals = Counter(p.get("failure") for p in fails)
    truncations = [p for p in preds if p.get("finish_reason") == "length"]
    extraction_fail = [p for p in fails if p.get("failure") == "EXTRACTION_FAILURE"]
    excessive = [p for p in preds if (p.get("output_tokens") or 0) > 1024]

    def examples(rows, n=3):
        return [{"eval_id": r["eval_id"], "category": r.get("category"),
                 "expected": r.get("expected_answer"),
                 "extracted": (str(r.get("extracted_answer"))[:80]
                               if r.get("extracted_answer") else None),
                 "output_preview": (r.get("raw_model_output") or "")[:200]}
                for r in rows[:n]]

    by_cat_accuracy = {}
    for cat in sorted({p.get("category") for p in preds} - {None}):
        rows = [p for p in preds if p.get("category") == cat]
        by_cat_accuracy[cat] = {
            "n": len(rows),
            "accuracy": round(sum(1 for r in rows if r.get("correct")) / len(rows), 4),
            "failed_eval_ids": [r["eval_id"] for r in rows if not r.get("correct")][:20],
        }
    return {
        "total": len(preds),
        "failures_total": len(fails),
        "failures_by_type": dict(failure_totals),
        "failure_type_by_category": {k: dict(v) for k, v in by_failure.items()},
        "truncations": {"count": len(truncations),
                        "eval_ids": [r["eval_id"] for r in truncations][:20]},
        "extraction_failures": {
            "count": failure_totals.get("EXTRACTION_FAILURE", 0),
            "eval_ids": [p["eval_id"] for p in fails
                         if p.get("failure") == "EXTRACTION_FAILURE"][:20]},
        "excessive_generation": {
            "count": len(excessive),
            "eval_ids": [r["eval_id"] for r in excessive][:20]},
        "per_category": by_cat_accuracy,
        "representative_examples": {
            "wrong_answer": examples([p for p in fails
                                      if p.get("failure") == "WRONG_ANSWER"]),
            "extraction": examples([p for p in fails
                                    if p.get("failure") == "EXTRACTION_FAILURE"]),
            "truncation": examples(truncations),
        },
        "regression_vs_base_by_category": None,   # filled by caller
    }


def markdown(tuned_slug: str, base_slug: str, cmp_: dict, gate: dict) -> str:
    m = cmp_["metrics"]
    lines = [
        "# T3 BASE vs TUNED COMPARISON",
        "",
        f"*Generated:* {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- Base reference: `{base_slug}` (T2 non-thinking diagnostic — the "
        f"declared reference baseline; NOT merged with the thinking run)",
        f"- Tuned: `{tuned_slug}` (Qwen3-1.7B + T3 LoRA adapter, unmerged)",
        "- Same frozen suite (sciencemath-eval-v1, 188 questions), same "
        "generation protocol, deterministic scoring.",
        "",
        "## Headline metrics",
        "",
        "| metric | base | tuned | delta (pp) |",
        "|---|---|---|---|",
    ]
    def pct(v):
        return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else str(v)
    for key, label in (("overall_accuracy", "Overall accuracy"),
                       ("math_macro", "Math macro"),
                       ("science_macro", "Science macro"),
                       ("primary_macro", "Primary macro (math+science)"),
                       ("extraction_success_rate", "Extraction success"),
                       ("invalid_response_rate", "Invalid outputs"),
                       ("refusal_rate", "Refusals")):
        e = cmp_.get(key) or cmp_["metrics"].get(key) or {}
        if isinstance(e, dict) and "base" in e:
            b, t, d = e.get("base"), e.get("tuned"), e.get("delta_pp")
            lines.append(f"| {label} | {pct(b) if key.endswith('rate') or 'macro' in key or 'accuracy' in key else b} | "
                         f"{pct(t) if key.endswith('rate') or 'macro' in key or 'accuracy' in key else t} | "
                         f"{d if d is not None else '—'} |")
    lines += ["", "## Per-category accuracy (delta in percentage points)", "",
              "| category | base | tuned | delta |", "|---|---|---|---|"]
    for cat, row in cmp_["per_category"].items():
        b, t = row["base"], row["tuned"]
        lines.append(f"| {cat} | {pct(b) if b is not None else '—'} | "
                     f"{pct(t) if t is not None else '—'} | "
                     f"{row['delta_pp'] if row['delta_pp'] is not None else '—'} |")
    lines += ["", "## Catastrophic forgetting gate", "",
              f"- Result: **{gate['flag']}**",
              f"- Reference science macro: {gate.get('reference_science_macro')}",
              f"- Tuned science macro: {gate.get('tuned_science_macro')}",
              f"- Drop: {gate.get('drop_pp', '—')} pp "
              f"(threshold {gate.get('threshold_pp', '—')} pp, declared in "
              f"configs/training.yaml before evaluation)", ""]
    return "\n".join(lines)


def failure_markdown(fa: dict, tuned_metrics: dict) -> str:
    lines = [
        "# T3 FAILURE ANALYSIS",
        "",
        f"*Generated:* {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- Failures: {fa['failures_total']} / {fa['total']}",
        f"- Failure types: {fa['failures_by_type']}",
        f"- Truncations: {fa['truncations']['count']}",
        f"- Extraction failures: {fa['extraction_failures']['count']}",
        f"- Excessive generations (>1024 tok): {fa['excessive_generation']['count']}",
        "",
        "## Per-category detail (accuracy, failed eval_ids)",
        "",
        "| category | n | accuracy | failed eval_ids (first 20) |",
        "|---|---|---|---|",
    ]
    for cat, row in sorted(fa["per_category"].items()):
        ids = ", ".join(row["failed_eval_ids"][:8])
        more = " …" if len(row["failed_eval_ids"]) > 8 else ""
        lines.append(f"| {cat} | {row['n']} | {row['accuracy']:.3f} | {ids}{more} |")
    lines += ["", "## Representative examples (predictions untouched)", ""]
    for kind, rows in fa["representative_examples"].items():
        lines.append(f"### {kind}")
        for r in rows:
            lines.append(f"- `{r['eval_id']}` ({r['category']}): expected="
                         f"{r['expected']!r} extracted={r['extracted']!r} "
                         f"output[:120]={r['output_preview'][:120]!r}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    log = setup_logging("compare_tuned")
    cfg = load_configs().get("training", {})

    tuned_metrics_path = TUNED_DIR / "metrics.json"
    if not tuned_metrics_path.exists():
        print("REFUSED: no tuned metrics at", tuned_metrics_path)
        return 91
    tuned_metrics = load_json(tuned_metrics_path)

    base_ref_rel = cfg.get("catastrophic_forgetting", {}).get(
        "reference_baseline",
        "evaluations/base/qwen3-1.7b_non_thinking/metrics.json")
    base_metrics = load_json(REPO_ROOT / base_ref_rel)

    cmp_ = build_comparison(tuned_metrics, base_metrics)
    gate = forgetting_gate(cfg, cmp_)

    fa = failure_analysis(TUNED_DIR)
    # annotate which categories regressed vs base
    regressions = {cat: row["delta_pp"] for cat, row in cmp_["per_category"].items()
                   if row["delta_pp"] is not None and row["delta_pp"] < -5.0}
    fa["regression_vs_base_by_category_pp"] = regressions
    fa["science_regression_gate"] = gate

    write_json(REPO_ROOT / "evaluations" / "tuned" / "t3_comparison.json",
               {"generated_at": datetime.now(timezone.utc).isoformat(),
                "base_reference": base_ref_rel,
                "suite": "sciencemath-eval-v1",
                **cmp_,
                "catastrophic_forgetting_gate": gate})

    base_slug = Path(base_ref_rel).parent.name
    with open(REPO_ROOT / "evaluations" / "tuned" / "T3_COMPARISON.md", "w",
              encoding="utf-8") as f:
        f.write(markdown("sciencemath-v0.1-t3", base_slug, cmp_, gate))
    with open(TUNED_DIR / "T3_FAILURE_ANALYSIS.md", "w", encoding="utf-8") as f:
        f.write(failure_markdown(fa, tuned_metrics))
    write_json(TUNED_DIR / "failure_analysis.json", fa)

    print(json.dumps({
        "overall": {"base": cmp_["metrics"]["overall_accuracy"]["base"],
                    "tuned": cmp_["metrics"]["overall_accuracy"]["tuned"],
                    "delta_pp": cmp_["metrics"]["overall_accuracy"]["delta"] * 100
                    if cmp_["metrics"]["overall_accuracy"].get("delta") is not None else None},
        "math_macro": cmp_["math_macro"],
        "science_macro": cmp_["science_macro"],
        "primary_macro": cmp_["primary_macro"],
        "forgetting_gate": gate["flag"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())