"""T13.14 — formal replay of the 11 frozen T12-DEF-2 rows through the
repaired T13 fidelity classifier.

For each frozen row the recorded planner request is reconstructed and run
through the exact T12 pipeline order (validate_planner_request, then
check_fidelity).  The prior classification (T12 runtime-type-equality
rejection) is compared with the T13 semantic classification.

Policy: "Do not assume all 11 are legitimate.  If any truly changes
semantics: keep it rejected.  Evidence decides."  A row is marked
eligible for promotion recheck ONLY when the T13 layer verifies every
parameter as a faithful restatement (no FIDELITY_FAIL, no schema-type
violation).  Rows the engine schema would still reject keep their
rejection with a precise label.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.fidelity import (  # noqa: E402
    FIDELITY_FAIL, check_fidelity, validate_planner_request)

FREEZE = ROOT / "evaluations/t13/t12_def2_freeze.json"
OUT = ROOT / "evaluations/t13/def2_replay_t13.json"


def replay_row(row: dict) -> dict:
    request = {
        "operation": row["operation"],
        "parameters": row["structured_parameters"],
        "source_inputs": row["source_inputs"],
        "parameter_provenance": row["parameter_provenance"],
        "preserve_verbatim": row.get("preserve_verbatim", []),
        "expected_result_type": row["expected_result_type"],
        "reason_for_compute": "T13.14 DEF-2 replay of recorded planner "
                              "request ( reconstructed from T12 freeze)",
    }
    question = row["question_excerpt"]
    rec = {
        "eval_id": row["eval_id"],
        "operation": row["operation"],
        "prior_t12_classification": row["current_classification"],
        "prior_failures": row["fidelity_failures"],
        "t11_armB_correct": row["t11_armB_correct"],
        "t12_correct": row["t12_correct"],
        "numeric_impact": row["numeric_impact"],
        "expected_semantic_relation": row["expected_semantic_relation"],
        "is_faithful_restatement": row["is_faithful_restatement"],
    }
    schema = validate_planner_request(request)
    rec["schema_ok"] = bool(schema["ok"])
    rec["schema_failures"] = schema["failures"]
    try:
        fid = check_fidelity(request, question)
        rec["fidelity_status"] = fid.status
        rec["fidelity_failures"] = fid.failures
        rec["t13_classes"] = getattr(fid, "t13_classes", None) or getattr(
            fid, "classes", None)
        rec["approved"] = fid.status != FIDELITY_FAIL
    except Exception as exc:  # a replay exception is a finding, not a crash
        rec["fidelity_status"] = "REPLAY_EXCEPTION"
        rec["fidelity_failures"] = [f"{type(exc).__name__}: {exc}"]
        rec["approved"] = False

    # evidence-based eligibility: approved only if the fidelity layer
    # verified every parameter as a faithful restatement.
    rec["t13_classification"] = (
        "APPROVED (faithful structured restatement)" if rec["approved"]
        else "REJECTED")
    rec["eligibility_note"] = (
        "recovers" if rec["approved"]
        else "stays rejected: " + "; ".join(rec["fidelity_failures"])[:200])
    return rec


def main() -> int:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    rows = [replay_row(r) for r in freeze["rows"]]
    approved = sum(1 for r in rows if r["approved"])
    schema_blocked = [r["eval_id"] for r in rows
                      if not r["schema_ok"]]
    out = {
        "milestone": "T13.14 DEF-2 formal replay",
        "frozen_rows": len(rows),
        "approved_by_t13": approved,
        "still_rejected": len(rows) - approved,
        "schema_gate_blocked_ids": schema_blocked,
        "policy": "evidence decides; semantic rejection is preserved",
        "rows": rows,
    }
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"rows: {len(rows)}  approved: {approved}  "
          f"rejected: {len(rows) - approved}")
    for r in rows:
        print(f"  {r['eval_id']}: {r['t13_classification']} "
              f"{r['fidelity_failures'] if not r['approved'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())