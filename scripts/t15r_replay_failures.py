"""T15R.22 — compare frozen T15 executable failures to the T15R FINAL run."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "evaluations/t15r/t15_failure_freeze.json"
PRED = ROOT / "evaluations/t15r/runs/code-final/predictions.jsonl"
OUT = ROOT / "evaluations/t15r/t15_failure_replay.json"

CATS = ("multi_fix", "data_xform", "refactor", "algo", "feature",
        "test_repair", "other")


def main() -> int:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    failed = freeze.get("failures") or freeze.get("rows") or []
    if isinstance(failed, dict):
        failed = failed.get("rows") or []
    pred = {json.loads(l)["task_id"]: json.loads(l)
            for l in PRED.read_text(encoding="utf-8").splitlines()
            if l.strip()}
    rec = []
    by = {c: {"recovered": 0, "still_failing": 0, "regressed": 0,
              "before_fail": 0, "after_fail": 0, "n": 0} for c in CATS}
    recovered = still = 0
    rounds = []
    retained = 0
    full_rev = 0
    unsafe_rev = 0
    for row in failed:
        tid = row.get("task_id")
        cat = row.get("category")
        if cat not in by:
            cat = "other"
        by[cat]["n"] += 1
        by[cat]["before_fail"] += 1
        p = pred.get(tid)
        if not p:
            rec.append({"task_id": tid, "category": cat, "status": "MISSING"})
            still += 1
            by[cat]["still_failing"] += 1
            by[cat]["after_fail"] += 1
            continue
        ok = bool(p.get("pass"))
        rp = p.get("repair") or {}
        rounds.append(rp.get("repair_rounds") or 0)
        if rp.get("best_retained"):
            retained += 1
        if rp.get("full_revert"):
            full_rev += 1
        if rp.get("unsafe_revert"):
            unsafe_rev += 1
        if ok:
            recovered += 1
            by[cat]["recovered"] += 1
        else:
            still += 1
            by[cat]["still_failing"] += 1
            by[cat]["after_fail"] += 1
        rec.append({"task_id": tid, "category": cat, "pass": ok,
                    "status": p.get("status"), "repair": rp,
                    "reasons": p.get("reasons")})
    # newly regressed: T15 pass -> T15R fail among executable cats
    t15 = ROOT / "evaluations/t15/runs/code-final/predictions.jsonl"
    old = {json.loads(l)["task_id"]: json.loads(l)
           for l in t15.read_text(encoding="utf-8").splitlines() if l.strip()}
    EXEC = {"single_fix", "multi_fix", "test_repair", "feature", "refactor",
            "config", "import_err", "type_err", "algo", "data_xform",
            "api_compat"}
    newly = []
    for tid, p in pred.items():
        if p.get("category") not in EXEC:
            continue
        o = old.get(tid)
        if o and o.get("pass") and not p.get("pass"):
            newly.append(tid)
            cat = p.get("category") if p.get("category") in by else "other"
            by[cat]["regressed"] += 1
    rounds_sorted = sorted(rounds)
    out = {
        "n_frozen_failures": len(failed),
        "recovered": recovered,
        "still_failing": still,
        "newly_regressed": len(newly),
        "regressed_ids": newly,
        "by_category": by,
        "average_repair_rounds": (sum(rounds) / len(rounds)) if rounds else 0,
        "median_repair_rounds": (rounds_sorted[len(rounds_sorted) // 2]
                                 if rounds_sorted else 0),
        "best_state_retained_count": retained,
        "full_revert_count": full_rev,
        "unsafe_revert_count": unsafe_rev,
        "rows": rec,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in out if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
