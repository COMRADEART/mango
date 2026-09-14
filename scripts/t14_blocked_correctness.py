"""T14.7 correctness overlay — requires the T14A SciComp recheck."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRED = ROOT / "evaluations/t14/runs/t14a-scicomp-B/predictions.jsonl"
REPLAY = ROOT / "evaluations/t14/t13_blocked_replay.json"
OUT = ROOT / "evaluations/t14/t13_blocked_correctness.json"


def main() -> int:
    if not PRED.exists():
        raise SystemExit(f"missing {PRED}")
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    preds = {}
    silent = 0
    exceptions = 0
    for line in PRED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        preds[r["eval_id"]] = r
        if r.get("silent_mutation_pass"):
            silent += 1
        if r.get("pipeline_exception"):
            exceptions += 1
    newly_correct = []
    still_wrong = []
    right_to_wrong = []
    still_correct = []
    missing = []
    rows = []
    for r in replay["rows"]:
        p = preds.get(r["id"])
        if p is None:
            missing.append(r["id"])
            continue
        t13 = bool(r["t13_correct"])
        t14 = bool(p.get("correct"))
        rec = {
            "id": r["id"],
            "t13_correct": t13,
            "t14_correct": t14,
            "t14_necessity": r["t14_necessity"],
            "t14_invoked": p.get("invoked"),
            "t14_guard_blocked": p.get("guard_blocked"),
            "envelope_status": p.get("envelope_status"),
            "fidelity_status": p.get("fidelity_status"),
        }
        rows.append(rec)
        if (not t13) and t14:
            newly_correct.append(r["id"])
        elif t13 and (not t14):
            right_to_wrong.append(r["id"])
        elif t13 and t14:
            still_correct.append(r["id"])
        else:
            still_wrong.append(r["id"])
    doc = {
        "previously_blocked": replay["previously_blocked"],
        "now_COMPUTE_REQUIRED": replay["now_COMPUTE_REQUIRED"],
        "now_COMPUTE_HELPFUL": replay["now_COMPUTE_HELPFUL"],
        "still_NO_COMPUTE": replay["still_NO_COMPUTE"],
        "INSUFFICIENT_INFORMATION": replay["INSUFFICIENT_INFORMATION"],
        "unblocked": replay["unblocked"],
        "still_blocked": replay["still_blocked"],
        "predictions_present": len(preds),
        "missing_ids": missing,
        "newly_correct": len(newly_correct),
        "still_wrong": len(still_wrong),
        "right_to_wrong": len(right_to_wrong),
        "still_correct": len(still_correct),
        "newly_correct_ids": newly_correct,
        "still_wrong_ids": still_wrong,
        "right_to_wrong_ids": right_to_wrong,
        "scicomp_silent_mutation_pass_count": silent,
        "scicomp_pipeline_exceptions_in_rows": exceptions,
        "rows": rows,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
