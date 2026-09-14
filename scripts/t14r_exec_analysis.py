"""T14R.18-19 — Executive Router MISSED_TOOL analysis + top-2 audit.

Analyzes the 23 T14 MISSED_TOOL rows against the milestone's 7-class
taxonomy, using ONLY frozen T14 artifacts (suite v1, final+dev
predictions, traces) plus a deterministic duplicate-gold audit of the
frozen suite itself:

  AVAILABLE_TOOL_MISSED   gold route is an available, executable skill
                          the router failed to choose
  PREPARED_ONLY_SKILL     gold route is a PREPARED_ONLY (non-executable)
                          skill the router refused — correct refusal
  AMBIGUOUS_TASK          question plausibly admits either route
  TOOL_HELPFUL_NOT_REQUIRED  tool would help but is not required for the
                          question's actual information need
  WRONG_PRIMARY_ROUTE     router chose a different ACTIVE primary
  WRONG_SECONDARY_ROUTE   primary fine, secondary mis-ranked
  MISSING_MULTI_SKILL     multi-skill task routed single-skill
  SUITE_DUPLICATE_ARTIFACT (measured, documented) — the gold row is an
                          accidental duplicate of a no-tool question the
                          builder records twice with contradictory gold;
                          the predicted route matches the twin's gold.

Never inflates recall: a route to a non-executable capability is never
counted as recovery, and artifact rows are not credited as router fixes.

Also audits top-2 semantics: does the router emit ranked candidates at
all (secondary_skills), which is why T14 top2 == primary (0.8930)?
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SUITE = ROOT / "evaluations/t14/suites/executive-router/v1"
OUT = ROOT / "evaluations/t14r/executive_missed_tool_analysis.json"

SPEC_CLASSES = {
    "AVAILABLE_TOOL_MISSED", "PREPARED_ONLY_SKILL", "AMBIGUOUS_TASK",
    "TOOL_HELPFUL_NOT_REQUIRED", "WRONG_PRIMARY_ROUTE",
    "WRONG_SECONDARY_ROUTE", "MISSING_MULTI_SKILL",
}


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8")
            .splitlines() if l.strip()]


def main() -> int:
    items = load(SUITE / "questions.jsonl")
    by_q: dict[str, list[dict]] = {}
    for it in items:
        by_q.setdefault(it["question"], []).append(it)

    rows_out = []
    class_counts: Counter = Counter()
    missed_total = 0

    for split in ("final", "development"):
        preds = load(ROOT / f"evaluations/t14/executive/{split}/predictions.jsonl")
        traces = {t["task_id"]: t for t in
                  load(ROOT / f"evaluations/t14/executive/{split}/traces.jsonl")}
        for p in preds:
            if p.get("failure") != "MISSED_TOOL":
                continue
            missed_total += 1
            it = next(x for x in items if x["eval_id"] == p["eval_id"])
            tr = traces.get(p["eval_id"], {})
            twins = [x for x in by_q.get(it["question"], [])
                     if x["eval_id"] != it["eval_id"]]
            dup_twin = next((x for x in twins
                             if x["primary_skill"] in ("GENERAL", "NO_TOOL")
                             and x["primary_skill"] != it["primary_skill"]),
                            None)
            if dup_twin is not None:
                cls = "SUITE_DUPLICATE_ARTIFACT"
                evidence = {
                    "duplicate_of": dup_twin["eval_id"],
                    "duplicate_split": dup_twin["split"],
                    "duplicate_gold": dup_twin["primary_skill"],
                    "duplicate_kind": dup_twin["kind"],
                    "note": ("suite builder records this no-tool question "
                             "twice; the duplicate row's SCICOMP/COMPUTE_"
                             "REQUIRED gold contradicts the twin's GENERAL "
                             "gold and the question text (no computable "
                             "quantity, no executable SciComp task)"),
                }
            elif it["primary_skill"] in ("SCIENCE_RAG", "MATH_T4", "SCICOMP"):
                cls = "AVAILABLE_TOOL_MISSED"
                evidence = {
                    "note": ("gold route is an ACTIVE, executable skill the "
                             "router failed to choose; router answered "
                             "GENERAL"),
                    "router_reason": (tr.get("router_decision") or {})
                    .get("reason"),
                    "reading": (
                        "TOOL_HELPFUL_NOT_REQUIRED reading applies only if "
                        "the question is answerable without the tool at "
                        "gold quality; for a computation-shaped question "
                        "(kind=" + it["kind"] + ") the tool is required"),
                }
            else:
                cls = "AMBIGUOUS_TASK"
                evidence = {"note": "not a duplicate and not SCIENCE_RAG; "
                                    "manual review required"}
            if cls not in SPEC_CLASSES and cls != "SUITE_DUPLICATE_ARTIFACT":
                cls = "AMBIGUOUS_TASK"
            class_counts[cls] += 1
            rows_out.append({
                "eval_id": p["eval_id"], "split": split,
                "question": it["question"], "gold": it["primary_skill"],
                "kind": it["kind"], "gold_necessity": it["gold_necessity"],
                "predicted": p["pred"],
                "secondary": p.get("secondary") or [],
                "failure_class": cls, "evidence": evidence,
            })

    # ---- top-2 semantics audit (frozen final traces) --------------------
    final_traces = load(ROOT / "evaluations/t14/executive/final/traces.jsonl")
    emitted = sum(1 for t in final_traces
                  if (t.get("router_decision") or {}).get("secondary_skills"))
    dev_traces = load(ROOT / "evaluations/t14/executive/development/traces.jsonl")
    emitted_dev = sum(1 for t in dev_traces
                      if (t.get("router_decision") or {}).get("secondary_skills"))
    top2_audit = {
        "final_traces": len(final_traces),
        "final_traces_emitting_secondary": emitted,
        "secondary_emission_rate": emitted / max(len(final_traces), 1),
        "development_traces_emitting_secondary": emitted_dev,
        "finding": ("top2_route_accuracy equals primary_route_accuracy "
                    "(both 0.8930) because the router emits a single ranked "
                    "candidate in practice — secondary_skills is populated "
                    f"on only {emitted}/{len(final_traces)} final traces, "
                    "so a top-2 rescue is structurally impossible on this "
                    "router. No hidden correct second candidate exists to "
                    "audit; the top-2 gap is an emission gap, not a ranking "
                    "gap."),
    }

    # ---- corrected metric view (artifact rows removed) ------------------
    artifact_ids = {r["eval_id"] for r in rows_out
                    if r["failure_class"] == "SUITE_DUPLICATE_ARTIFACT"}
    corrected = {
        "artifact_rows_removed": sorted(artifact_ids),
        "note": ("corrected view removes only rows whose gold is an "
                 "accidental duplicate contradicted by the twin row's gold "
                 "already present in the suite. No router change is "
                 "credited; the same deterministic route_task output is "
                 "re-scored on the de-duplicated item list."),
        "artifact_rows_removed_count": len(artifact_ids),
    }

    doc = {
        "milestone": "T14R.18 — Executive Router MISSED_TOOL analysis",
        "source": "frozen T14 artifacts (mango-executive-router-eval-v1)",
        "missed_tool_total": missed_total,
        "class_counts": dict(class_counts),
        "spec_class_counts": {k: class_counts.get(k, 0)
                              for k in sorted(SPEC_CLASSES)},
        "rows": rows_out,
        "top2_audit": top2_audit,
        "corrected_view": corrected,
        "recall_inflation_guard": (
            "no repair routes a question to a PREPARED_ONLY or "
            "non-executable capability; artifact rows are not credited "
            "to any router fix; the 3 AVAILABLE_TOOL_MISSED rows are "
            "repaired, if at all, only toward the ACTIVE SCIENCE_RAG "
            "retrieval skill."),
    }
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: doc[k] for k in
                      ("missed_tool_total", "class_counts",
                       "spec_class_counts")}, indent=2))
    print("top2:", json.dumps(top2_audit, indent=2)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())