"""T14R.14 — replay recovery report.

Compares the T14R full replay (evaluations/t14r/runs/t14r-scicomp-B)
against the frozen T14 run row-by-row and reports, per T14 failure
category (t14r_failure_forensics taxonomy):

* recovered  — incorrect in T14, correct in T14R
* unchanged_wrong — incorrect in both
* regressed  — correct in T14, incorrect in T14R (must be 0 for any
  claim of an additive-only repair)

Out-of-scope honesty: categories the repair layer does not claim to
fix are reported separately (NO_INVOCATION planner behavior, gold-vs-
given benchmark artifacts).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

T14 = ROOT / "evaluations/t14/runs/t14a-scicomp-B/predictions.jsonl"
T14R = ROOT / "evaluations/t14r/runs/t14r-scicomp-B/predictions.jsonl"
FORENSICS = ROOT / "evaluations/t14r/t14_numeric_failure_analysis.json"
OUT = ROOT / "evaluations/t14r/replay_recovery_report.json"


def main() -> int:
    t14 = {r["eval_id"]: r for r in
           (json.loads(l) for l in T14.read_text(encoding="utf-8")
            .splitlines() if l.strip())}
    t14r = {r["eval_id"]: r for r in
            (json.loads(l) for l in T14R.read_text(encoding="utf-8")
             .splitlines() if l.strip())}
    forensics = json.loads(FORENSICS.read_text(encoding="utf-8"))
    cls = {row["task_id"]: row["failure_class"]
           for row in forensics["rows"]}

    numeric = [eid for eid, r in t14.items()
               if r.get("kind") in ("numeric_oracle", "mixed")]
    bad14 = [eid for eid in numeric if not t14[eid].get("correct")]

    recovered, unchanged, regressed = [], [], []
    for eid in numeric:
        was = bool(t14[eid].get("correct"))
        now = bool(t14r[eid].get("correct"))
        if not was and now:
            recovered.append(eid)
        elif not was and not now:
            unchanged.append(eid)
        elif was and not now:
            regressed.append(eid)

    by_cat: dict[str, dict] = defaultdict(
        lambda: {"incorrect_in_T14": 0, "recovered": 0,
                 "unchanged_wrong": 0})
    for eid in bad14:
        c = cls.get(eid, "OTHER")
        by_cat[c]["incorrect_in_T14"] += 1
        if eid in recovered:
            by_cat[c]["recovered"] += 1
        elif eid in unchanged:
            by_cat[c]["unchanged_wrong"] += 1

    n14 = len(numeric)
    acc14 = sum(1 for eid in numeric if t14[eid].get("correct")) / n14
    acc14r = sum(1 for eid in numeric if t14r[eid].get("correct")) / n14

    def _rate(pred):
        from collections import Counter
        tax = Counter(r.get("adoption_taxonomy") for r in t14r.values()
                      if r.get("adoption_taxonomy"))
        return dict(tax)

    doc = {
        "milestone": "T14R.14 — replay recovery report",
        "numeric_rows": n14,
        "numeric_accuracy_T14": acc14,
        "numeric_accuracy_T14R": acc14r,
        "recovered": sorted(recovered),
        "recovered_count": len(recovered),
        "unchanged_wrong": sorted(unchanged),
        "unchanged_wrong_count": len(unchanged),
        "regressed": sorted(regressed),
        "regressed_count": len(regressed),
        "recovery_by_T14_failure_class": {
            k: v for k, v in sorted(by_cat.items())},
        "adoption_taxonomy_T14R": _rate(None),
        "note": "T14R scope claim: planner provenance + verified-result "
                "interpretation + deterministic formatting. NO_INVOCATION "
                "and benchmark-artifact rows are out of scope.",
    }
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items()
                      if k not in ("recovered", "unchanged_wrong")},
                     indent=2)[:2400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())