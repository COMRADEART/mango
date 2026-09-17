"""T21R6 — final decision record.

Reads the immutable holdout_results.json of the ONE official exposure and
records the preregistered promotion decision. No runtime calls.

Usage: python scripts/t21r6_final_decision.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t21r6"

res = json.loads((OUT / "holdout_results.json").read_text(encoding="utf-8"))
floors = res["floors_comparison"]
n_pass = sum(1 for f in floors if f["pass"])
n_total = len(floors)
failing = [{"group": f["group"], "metric": f["metric"],
            "value": f["value"], "floor": f["floor"], "op": f["op"]}
           for f in floors if not f["pass"]]

promoted = res["overall_pass"] and res["floors_all_pass"] \
    and res["zero_tolerance_all_zero"] and res["one_shot"]

if promoted:
    decision = "PROMOTE_KNOWLEDGE_RAG_TO_ACTIVE"
    t21_status = "T21_CLOSED_PENDING_INDEPENDENT_AUDIT"
    ready_t22 = "YES"
else:
    decision = "KEEP_KNOWLEDGE_RAG_EXPERIMENTAL"
    t21_status = "T21_OPEN (validation attempt completed, floors unmet)"
    ready_t22 = "NO"

doc = {
    "milestone": "T21R6 final decision",
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "official_run": {
        "exposures": res["official_runtime_exposures"],
        "one_shot": res["one_shot"],
        "raw_results_sha256": res["raw_results_sha256"],
        "holdout_manifest_sha256": res["holdout_manifest_sha256"],
        "holdout_rows": res["raw_results_rows"],
    },
    "floors": {"pass": n_pass, "total": n_total,
               "all_pass": res["floors_all_pass"]},
    "zero_tolerance": {
        "all_zero": res["zero_tolerance_all_zero"],
        "totals": res["zero_tolerance_totals"],
    },
    "suite_minimums_met": res["suite_minimums_met"],
    "failing_floors": failing,
    "decision": decision,
    "knowledge_rag_availability": "EXPERIMENTAL",
    "t21_status": t21_status,
    "ready_for_T22": ready_t22,
    "t22_blocker": ("T21 completion additionally requires the independent "
                    "ChatGPT mechanical audit; until then T22 is BLOCKED."),
    "rule": ("Per the preregistered one-shot rule: no fix, no rerun, no "
             "gold change, no floor change after HOLDOUT_FROZEN. The "
             "exposed T21R6 holdout is consumed; a future milestone "
             "(T21R7) requires a NEW fresh blind holdout. The root cause "
             "of every failing floor is recorded in "
             "over_abstention_root_cause.json."),
}

(OUT / "final_decision.json").write_text(
    json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8", newline="\n")
print(json.dumps({"decision": decision, "floors": f"{n_pass}/{n_total}",
                  "ready_for_T22": ready_t22}))
if not promoted:
    raise SystemExit(0)  # the milestone itself closed cleanly (exit 0);
    # non-promotion is a recorded decision, not a script failure.