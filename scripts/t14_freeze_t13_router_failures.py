"""T14.1 — freeze T13 SciComp rows currently classified NOT_NEEDED.

Read-only over historical T11/T12/T13 prediction artifacts and the
frozen mango-scicomp-eval-v1 suite. Does not alter those rows.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.router import compute_necessity, route  # noqa: E402

SUITE = ROOT / "evaluations/t11/scicomp-suite/v1/questions.jsonl"
T11 = ROOT / "evaluations/t11/runs/t11-h2h-armb/predictions.jsonl"
T12 = ROOT / "evaluations/t12/runs/t12-final-scicomp-B/predictions.jsonl"
T13 = ROOT / "evaluations/t12/runs/t13-t17-scicomp-B/predictions.jsonl"


def load_jsonl(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[rec["eval_id"]] = rec
    return out


def main() -> int:
    items = [json.loads(l) for l in SUITE.read_text(encoding="utf-8")
             .splitlines() if l.strip()]
    t11 = load_jsonl(T11)
    t12 = load_jsonl(T12)
    t13 = load_jsonl(T13)
    suite_sha = hashlib.sha256(SUITE.read_bytes()).hexdigest()

    records = []
    numeric_blocked = []
    for it in items:
        eid = it["eval_id"]
        r13 = t13[eid]
        nec = r13.get("necessity")
        if nec != "NOT_NEEDED":
            continue
        q = it["question"]
        live = compute_necessity(q)
        routed = route(q)
        kind = r13.get("kind")
        numeric = kind in ("numeric_oracle", "mixed")
        expected_compute = bool(it.get("needs_compute"))
        rec = {
            "id": eid,
            "question": q,
            "expected_category": it.get("category"),
            "numeric_conceptual_adversarial_class": kind,
            "current_necessity_decision": nec,
            "live_necessity_decision": live.get("necessity"),
            "live_features": live.get("features"),
            "expected_compute_requirement": expected_compute,
            "was_compute_invoked": bool(r13.get("invoked")),
            "guard_blocked": bool(r13.get("guard_blocked")),
            "t13_correctness": r13.get("correct"),
            "t11_t12_t13_result_history": {
                "t11": {
                    "invoked": (t11.get(eid) or {}).get("invoked"),
                    "envelope_status": (t11.get(eid) or {}).get(
                        "envelope_status"),
                    "correct": (t11.get(eid) or {}).get("numeric_correct")
                    if kind in ("numeric_oracle", "mixed")
                    else (t11.get(eid) or {}).get("conceptual_correct")
                    if kind == "conceptual"
                    else (t11.get(eid) or {}).get("adversarial_correct"),
                    "adopted": (t11.get(eid) or {}).get("adopted"),
                },
                "t12": {
                    "necessity": (t12.get(eid) or {}).get("necessity"),
                    "guard_blocked": (t12.get(eid) or {}).get("guard_blocked"),
                    "invoked": (t12.get(eid) or {}).get("invoked"),
                    "correct": (t12.get(eid) or {}).get("correct"),
                    "envelope_status": (t12.get(eid) or {}).get(
                        "envelope_status"),
                },
                "t13": {
                    "necessity": nec,
                    "guard_blocked": r13.get("guard_blocked"),
                    "invoked": r13.get("invoked"),
                    "correct": r13.get("correct"),
                    "envelope_status": r13.get("envelope_status"),
                    "schema_status": r13.get("schema_status"),
                    "fidelity_status": r13.get("fidelity_status"),
                },
            },
            "reason_currently_given_by_router": {
                "necessity": nec,
                "features": live.get("features"),
                "route_confidence": routed.get("confidence"),
                "matched_term": routed.get("matched_term"),
            },
            "route_chosen": routed.get("route"),
            "operation_expected_if_known": (
                (it.get("compute_request") or {}).get("operation")),
            "gold_route": r13.get("gold_route") or it.get("expected_route"),
            "needs_compute": expected_compute,
        }
        records.append(rec)
        if numeric:
            numeric_blocked.append(rec)

    doc = {
        "milestone": "T14.1 — T13 router failure freeze",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "policy": "Read-only freeze of T13 SciComp rows classified "
                  "NOT_NEEDED. Rows are not altered. T13 fidelity "
                  "classifier is not reopened.",
        "suite": "mango-scicomp-eval-v1",
        "suite_sha256": suite_sha,
        "t13_run": "evaluations/t12/runs/t13-t17-scicomp-B",
        "t13_commit": "a57b66d40da31dc7e13c6183b130b34d25cb8b7d",
        "counts": {
            "suite_rows": len(items),
            "not_needed_all": len(records),
            "not_needed_numeric_or_mixed": len(numeric_blocked),
            "not_needed_numeric_oracle": sum(
                1 for r in numeric_blocked
                if r["numeric_conceptual_adversarial_class"]
                == "numeric_oracle"),
            "not_needed_mixed": sum(
                1 for r in numeric_blocked
                if r["numeric_conceptual_adversarial_class"] == "mixed"),
            "guard_blocked_numeric": sum(
                1 for r in numeric_blocked if r["guard_blocked"]),
            "needs_compute_true": sum(
                1 for r in numeric_blocked if r["needs_compute"]),
            "t13_correct_among_numeric_not_needed": sum(
                1 for r in numeric_blocked if r["t13_correctness"]),
            "t11_correct_among_numeric_not_needed": sum(
                1 for r in numeric_blocked
                if (r["t11_t12_t13_result_history"]["t11"]["correct"])),
        },
        "numeric_rows_blocked_by_not_needed": [
            r["id"] for r in numeric_blocked],
        "records": records,
    }
    out = ROOT / "evaluations/t14/t13_router_failure_freeze.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(doc["counts"], indent=2))
    print("numeric_ids:", ", ".join(r["id"] for r in numeric_blocked))
    print("T14_T13_ROUTER_FAILURE_FREEZE_WRITTEN", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
