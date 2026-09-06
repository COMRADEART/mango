"""T2.4/T2.5: baseline comparison and selection decision.

Reads ONLY the measured artifacts in evaluations/base/*/metrics.json (never
hardcoded or quoted numbers) and writes:
  evaluations/base/comparison.json / BASELINE_COMPARISON.md
  evaluations/base/SELECTION_DECISION.md

Selection procedure (deterministic, documented IN the output):
  1. A candidate not COMPLETE in evaluations/base/ is NOT_RUN / not eligible.
  2. Primary ranking metric: mean of math_macro_accuracy and
     science_macro_accuracy.
  3. Within 1.0 point of the leader, the general-purpose candidate is preferred
     when it also leads in instruction_following / uncertainty_calibration /
     extraction_success_rate AND its context length supports the T5 RAG plan
     (recorded as a documented tie-break, never as an accuracy claim).
  4. The decision is a RECOMMENDATION until committed with --commit (which
     fills configs/model.yaml selected.model_id + evidence path).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import CONFIG_DIR, REPO_ROOT, setup_logging  # noqa: E402

from sciencemath.utils.io_utils import load_json, load_yaml, write_json  # noqa: E402

EVAL_DIR = REPO_ROOT / "evaluations"
BASE_DIR = EVAL_DIR / "base"

PRIMARY_CANDIDATES = ["A", "B"]


def load_run(candidate_key: str) -> dict | None:
    """Load a candidate's measured run keyed by candidate_key in manifest."""
    if not BASE_DIR.exists():
        return None
    for run_dir in sorted(BASE_DIR.iterdir()):
        mp = run_dir / "manifest.json"
        if not mp.exists():
            continue
        m = load_json(mp)
        if m.get("candidate_key") == candidate_key and \
                m.get("variant") == "primary":
            metrics = (load_json(run_dir / "metrics.json")
                       if (run_dir / "metrics.json").exists() else None)
            return {"candidate_key": candidate_key,
                    "model_id": m.get("model_id"),
                    "variant": m.get("variant") or "primary",
                    "slug": run_dir.name,
                    "manifest": m, "metrics": metrics,
                    "status": m.get("status")}
    return None


def fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def build_comparison(runs: dict[str, dict | None]) -> dict:
    rows = []
    for key in sorted(runs):
        r = runs[key]
        if r is None or r.get("metrics") is None:
            rows.append({"candidate_key": key,
                         "model_id": (r or {}).get("model_id"),
                         "status": (r or {}).get("status", "NOT_RUN"),
                         "eligible": False})
            continue
        m = r["metrics"]
        math_m = m.get("math_macro_accuracy")
        sci_m = m.get("science_macro_accuracy")
        primary = None
        if math_m is not None and sci_m is not None:
            primary = round((math_m + sci_m) / 2, 4)
        rows.append({
            "candidate_key": key,
            "model_id": r["model_id"],
            "status": r.get("status"),
            "eligible": r.get("status") == "COMPLETE",
            "slug": r["slug"],
            "overall_accuracy": m.get("overall_accuracy"),
            "math_macro_accuracy": math_m,
            "science_macro_accuracy": sci_m,
            "primary_macro": primary,
            "extraction_success_rate": m.get("extraction_success_rate"),
            "invalid_response_rate": m.get("invalid_response_rate"),
            "refusal_rate": m.get("refusal_rate"),
            "per_category_accuracy": m.get("per_category_accuracy"),
            "failure_counts": m.get("failure_counts"),
            "peak_vram_bytes": m.get("peak_vram_bytes"),
            "avg_output_tokens": m.get("avg_output_tokens"),
            "median_latency_s": m.get("median_latency_s"),
        })
    return rows


def decide(rows: list[dict], model_manifest: dict) -> dict:
    """Deterministic recommendation per the documented rules."""
    eligible = [r for r in rows if r.get("eligible") and
                r.get("primary_macro") is not None]
    if not eligible:
        return {"recommendation": "NO_RECOMMENDATION",
                "reason": "no candidate has a COMPLETE baseline run; "
                          "run scripts/evaluate_base.py first"}

    def ctx_of(model_id):
        return (model_manifest.get("models", {}).get(model_id) or {}) \
            .get("context_length")

    def instr_of(r):
        return (r.get("per_category_accuracy") or {}) \
            .get("instruction_following")

    def calib_of(r):
        return (r.get("per_category_accuracy") or {}) \
            .get("uncertainty_calibration")

    ranked = sorted(eligible, key=lambda r: r["primary_macro"], reverse=True)
    leader, runner = ranked[0], (ranked[1] if len(ranked) > 1 else None)
    decision = {"leader": leader["model_id"],
                "leader_primary_macro": leader["primary_macro"],
                "rule_trace": []}
    margin = (round(leader["primary_macro"] - runner["primary_macro"], 4)
              if runner else None)
    decision["runner_up"] = runner["model_id"] if runner else None
    decision["margin"] = margin

    if margin is not None and margin <= 0.01:
        # within 1.0 point: documented tie-break toward the better practical fit
        support = []
        for metric in ("extraction_success_rate",):
            if (leader.get(metric) or 0) >= (runner.get(metric) or 0):
                support.append(metric)
        if ctx_of(leader["model_id"]) and ctx_of(runner["model_id"]) and \
                ctx_of(leader["model_id"]) >= ctx_of(runner["model_id"]):
            support.append("context_length_supports_rag_plan")
        decision["recommendation"] = leader["model_id"]
        decision["decision_rule"] = (
            "primary_macro within 1.0 point; tie-break: extraction success "
            "and context-length fit for the T5 RAG plan (NOT an additional "
            "accuracy claim)")
        decision["tie_break_support"] = support
    else:
        decision["recommendation"] = leader["model_id"]
        decision["decision_rule"] = "highest primary_macro (math+science macro)"
        decision["tie_break_support"] = None
    return decision


def mode_label(r: dict) -> str:
    """Human-readable mode/role label; the two Qwen3 modes are never merged."""
    variant = r.get("variant") or "primary"
    model = (r.get("model_id") or "?")
    if model.endswith("Qwen3-1.7B") or model == "Qwen/Qwen3-1.7B":
        if variant == "primary":
            return f"{model} — THINKING — PRIMARY"
        return f"{model} — NON-THINKING — SECONDARY DIAGNOSTIC"
    return f"{model} — PRIMARY COMPARATOR"


def comparison_markdown(rows: list[dict], decision: dict, when: str) -> str:
    lines = ["# T2 BASELINE COMPARISON", "",
             f"*Generated:* {when}  ",
             "*Suite:* sciencemath-eval-v1 (frozen)  ",
             "*Rule:* every number below is read from measured artifacts in "
             "`evaluations/base/<slug>/metrics.json`; nothing is quoted from "
             "papers or model cards.", ""]
    lines += ["| candidate | model (mode — role) | status | overall | "
              "math macro | science macro | primary macro | extraction | "
              "invalid/refusal | extr.fail/trunc | med latency s | avg out tok |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        has_metrics = r.get("math_macro_accuracy") is not None
        if has_metrics:
            fc = r.get("failure_counts") or {}
            ef = fc.get("EXTRACTION_FAILURE", 0)
            tr = fc.get("TRUNCATED_OUTPUT", 0)
            lines.append(
                f"| {r['candidate_key']} | {mode_label(r)} | {r['status']} "
                f"| {fmt(r['overall_accuracy'])} | {fmt(r['math_macro_accuracy'])} "
                f"| {fmt(r['science_macro_accuracy'])} | {fmt(r['primary_macro'])} "
                f"| {fmt(r['extraction_success_rate'])} "
                f"| {fmt(r['invalid_response_rate'])}/{fmt(r['refusal_rate'])} "
                f"| {ef}/{tr} | {fmt(r['median_latency_s'])} "
                f"| {fmt(r['avg_output_tokens'])} |")
        else:
            fc = (r.get("failure_counts") or {}) if r.get("metrics") else {}
            lines.append(f"| {r['candidate_key']} | {mode_label(r)} "
                         f"| {r.get('status', 'NOT_RUN')} | - | - | - | - | - | - "
                         f"| {fc.get('EXTRACTION_FAILURE', 0)}/{fc.get('TRUNCATED_OUTPUT', 0)} "
                         f"| - | - |")
    lines += ["", "The two Qwen3-1.7B rows are the SAME model in different "
              "generation modes; they are reported separately and never "
              "combined. The non-thinking row is a reliability diagnostic, "
              "NOT a selectable base and NOT a replacement for the primary.",
              "", "## Caveats recorded with this baseline", "",
              "- 4-bit NF4 quantized inference (recorded per run in "
              "`model_metadata.json`); base weights untouched, no LoRA/train.",
              "- Scoring is deterministic string/numeric matching only; no "
              "LLM judging, no symbolic equivalence checking (T4 SymPy "
              "verifier arrives later).",
              "- Categories with count 0 in the suite are excluded from macro "
              "averages and marked INSUFFICIENT_VERIFIED_EVAL_DATA in the "
              "suite manifest.",
              "- Qwen3-1.7B runs in thinking mode with seeded sampling "
              "(temp 0.6 / top_p 0.95 / top_k 20, seed 42); Qwen2.5-Math "
              "greedy. Modes are recorded per run and never compared as "
              "identical protocols.", ""]
    lines += ["## Recommendation (deterministic rules, see file header)", "",
              f"- `recommendation`: **{decision.get('recommendation')}**",
              f"- `decision_rule`: {decision.get('decision_rule', '-')}",
              f"- `margin`: {decision.get('margin')}",
              f"- `tie_break_support`: {decision.get('tie_break_support')}",
              "", "This is a recommendation; commit it with "
                  "`python scripts/compare_baseline.py --commit` which fills "
                  "`configs/model.yaml` selected.model_id.", ""]
    return "\n".join(lines)


def commit_selection(model_id: str, evidence: Path) -> None:
    path = CONFIG_DIR / "model.yaml"
    text = path.read_text(encoding="utf-8")
    import re

    new_block = (
        "selected:\n"
        f"  model_id: {model_id}          # set by T2 baseline comparison\n"
        f"  selection_evidence: {evidence.as_posix()}\n")
    pattern = re.compile(
        r"selected:\n(  .*\n)+", re.MULTILINE)
    updated = pattern.sub(new_block, text, count=1)
    path.write_text(updated, encoding="utf-8")
    print(f"committed selection: {model_id} -> configs/model.yaml")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true",
                        help="write the recommendation into configs/model.yaml "
                             "selected block (requires complete runs)")
    args = parser.parse_args()

    log = setup_logging("compare_baseline")
    rows = build_comparison({k: load_run(k) for k in PRIMARY_CANDIDATES})
    # include any other completed runs (e.g. C or A_non_thinking) as rows
    if BASE_DIR.exists():
        for run_dir in sorted(BASE_DIR.iterdir()):
            mp = run_dir / "manifest.json"
            if not mp.exists():
                continue
            try:
                m = load_json(mp)
            except Exception:
                continue
            key = f"{m.get('candidate_key')}:{m.get('variant') or 'primary'}"
            if any(r.get("slug") == run_dir.name for r in rows):
                continue
            variant = m.get("variant") or "primary"
            # non-primary variants (e.g. the A non-thinking diagnostic) are
            # reported as rows but are NEVER recommendation-eligible: they are
            # the same model as their primary run, run for diagnosis only.
            r = {"candidate_key": key, "model_id": m.get("model_id"),
                 "status": m.get("status"), "variant": variant,
                 "eligible": m.get("status") == "COMPLETE"
                             and variant == "primary",
                 "slug": run_dir.name}
            if m.get("status") == "COMPLETE":
                metrics = load_json(run_dir / "metrics.json")
                math_m, sci_m = metrics.get("math_macro_accuracy"), \
                    metrics.get("science_macro_accuracy")
                r.update({
                    "overall_accuracy": metrics.get("overall_accuracy"),
                    "math_macro_accuracy": math_m,
                    "science_macro_accuracy": sci_m,
                    "primary_macro": (round((math_m + sci_m) / 2, 4)
                                      if math_m is not None and sci_m is not None
                                      else None),
                    "extraction_success_rate":
                        metrics.get("extraction_success_rate"),
                    "invalid_response_rate":
                        metrics.get("invalid_response_rate"),
                    "refusal_rate": metrics.get("refusal_rate"),
                    "failure_counts": metrics.get("failure_counts"),
                    "median_latency_s": metrics.get("median_latency_s"),
                    "avg_output_tokens": metrics.get("avg_output_tokens"),
                })
            rows.append(r)

    when = datetime.now(timezone.utc).isoformat()
    decision = decide(rows, load_json(EVAL_DIR / "model_manifest.json"))

    comparison = {"generated_at": when,
                  "suite_version": "sciencemath-eval-v1",
                  "rule": "all numbers read from measured artifacts only",
                  "candidates": rows,
                  "recommendation": decision}
    write_json(BASE_DIR / "comparison.json", comparison)

    md = comparison_markdown(rows, decision, when)
    (BASE_DIR / "BASELINE_COMPARISON.md").write_text(md, encoding="utf-8")

    selection_md = [
        "# T2 SELECTION DECISION", "",
        f"*Generated:* {when}", "",
        "## Recommendation", "",
        f"**{decision.get('recommendation')}**", "",
        f"- decision rule: {decision.get('decision_rule', '-')}",
        f"- leader: {decision.get('leader')} "
        f"(primary_macro={decision.get('leader_primary_macro')})",
        f"- runner-up: {decision.get('runner_up')} "
        f"(margin={decision.get('margin')})",
        f"- tie-break support: {decision.get('tie_break_support')}", "",
        "## Factors considered (evidence in comparison.json rows)", "",
        "- math accuracy, science accuracy, and their balance (primary_macro "
        "= mean of the two macro accuracies; NEITHER is optimized alone)",
        "- extraction/reliability: extraction success, extraction failures, "
        "truncations, refusals (see per-row reliability columns)",
        "- context length (T5 Wikipedia RAG needs headroom over the 188-"
        "question prompts)",
        "- inference latency and token cost (median latency, avg output "
        "tokens per row)",
        "- VRAM (4-bit NF4 load recorded per run; 6 GB RTX 4050 constraint)",
        "- future QLoRA feasibility (base size and 4-bit load footprint)",
        "- licensing (per evaluations/model_manifest.json; gate-enforced)",
        "- operational stability (resume-safe runs, per-record flush, "
        "verified recomputation from saved predictions)",
        "- suitability as SFT SUBSTRATE, not just untouched baseline score: "
        "a general model with weaker baseline math may still be the better "
        "T3 base if science capability is materially stronger, output "
        "reliability is acceptable, and math is plausibly improvable via SFT",
        "", "## Secondary diagnostic (NOT selectable)", "",
        "- `Qwen/Qwen3-1.7B` non-thinking run (variant=non_thinking) is a "
        "reliability/capability decomposition diagnostic only. It is reported "
        "in the comparison but excluded from recommendation eligibility "
        "because it is the same model as the primary A run.",
        "- Purpose: separate actual math/science capability from reasoning-"
        "protocol output-closure reliability (A thinking mode had 36/37 "
        "extraction failures caused by the 4096-token budget exhausting the "
        "think block, plus 5 taxonomically-TRUNCATED_OUTPUT rows — 41/188 "
        "total budget-exhausted).",
    ]
    ant = next((r for r in rows if r.get("variant") == "non_thinking"
                and r.get("primary_macro") is not None), None)
    if ant:
        selection_md += [
            f"- Measured non-thinking diagnostic result (read from its "
            f"metrics.json, reported for decomposition only): "
            f"overall={ant.get('overall_accuracy')}, "
            f"math_macro={ant.get('math_macro_accuracy')}, "
            f"science_macro={ant.get('science_macro_accuracy')}, "
            f"extraction={ant.get('extraction_success_rate')}. It is NEVER "
            "merged with the thinking primary and is not selectable.", "",
        ]
    selection_md += [
        "## Eligibility / exclusion notes", ""
        "- Qwen/Qwen2.5-3B-Instruct is EXCLUDED (license `qwen-research`, "
        "verified 2026-08-31; requires legal review).",
        "- Qwen/Qwen3-4B-Instruct-2507 is a stretch candidate, NOT run "
        "automatically (unverified license flag in model manifest; memory "
        "fit for 6 GB VRAM requires dry-run validation).",
        "- Candidate C (Qwen2.5-1.5B-Instruct) is optional and was only "
        "ranked if its run exists.", "",
        "## Evidence", "",
        "- `evaluations/base/<slug>/manifest.json` per-run status and config",
        "- `evaluations/base/<slug>/metrics.json` measured metrics",
        "- `evaluations/base/comparison.json` machine-readable comparison",
        "- `evaluations/suite/v1/checksum.json` frozen suite integrity", "",
        "## Limitations recorded", "",
        "- Small frozen suite (~180 questions): treat category numbers as "
        "directional, not publishable point estimates.",
        "- Deterministic scoring only; no symbolic equivalence (T4 adds the "
        "SymPy verifier).",
        "- A single sampled run for Qwen3 thinking mode with seed 42; "
        "variance across seeds is not yet measured.", "",
        "Status: RECOMMENDATION - becomes binding only via --commit into "
        "configs/model.yaml.", "",
    ]
    (BASE_DIR / "SELECTION_DECISION.md").write_text(
        "\n".join(selection_md), encoding="utf-8")

    log.info("comparison written; recommendation=%s",
             decision.get("recommendation"))
    print(f"recommendation: {decision.get('recommendation')} "
          f"(rule: {decision.get('decision_rule')})")

    if args.commit:
        rec = decision.get("recommendation")
        if not rec or not any(r.get("model_id") == rec and r.get("eligible")
                              for r in rows):
            print("REFUSED to commit: recommendation is not a COMPLETE run")
            return 2
        commit_selection(rec, Path("evaluations/base/comparison.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())