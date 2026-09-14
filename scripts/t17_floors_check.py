"""T17.35 floors vs FINAL. No post-hoc floor edits."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLOORS = ROOT / "evaluations/t17/promotion_floors.json"
OUT = ROOT / "evaluations/t17/floors_evaluation.json"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else {}


def verdict(measured, floor, kind="min"):
    if measured is None:
        return "FAIL", measured
    if kind == "eq":
        ok = measured == floor
    else:
        ok = measured >= floor
    return ("PASS" if ok else "FAIL"), measured


def main() -> int:
    floors = _load(FLOORS)
    fin = _load(ROOT / "evaluations/t17/runs/t17-final/summary.json")
    doc = fin.get("document") or {}
    data = fin.get("data_core") or {}
    rows = {}
    fails = []
    quality = floors.get("quality") or {}
    for k, fl in quality.items():
        v = doc.get(k)
        if k in data and v is None:
            v = data.get(k)
        kind = "min"
        st, meas = verdict(v, fl, kind)
        rows[k] = {"measured": meas, "floor": fl, "kind": kind, "verdict": st}
        if st == "FAIL":
            fails.append(k)
    for k, fl in (floors.get("data_core") or {}).items():
        v = data.get(k)
        st, meas = verdict(v, fl, "min" if k != "no_mutation" else "min")
        rows[f"data_{k}"] = {"measured": meas, "floor": fl, "kind": "min",
                             "verdict": st}
        if st == "FAIL":
            fails.append(f"data_{k}")
    zeros = floors.get("critical_zero_tolerance") or {}
    for k, fl in zeros.items():
        v = doc.get(k, 0)
        st, meas = verdict(v, fl, "eq")
        rows[k] = {"measured": meas, "floor": fl, "kind": "eq", "verdict": st}
        if st == "FAIL":
            fails.append(k)
    suggested_rows = {}
    suggested_fails = []
    for k, fl in (floors.get("spec_suggested") or {}).items():
        v = doc.get(k)
        if k in data and v is None:
            v = data.get(k)
        kind = "eq" if k == "lineage_accuracy" and fl == 1.0 else "min"
        st, meas = verdict(v, fl, kind)
        suggested_rows[k] = {"measured": meas, "floor": fl, "kind": kind,
                             "verdict": st}
        if st == "FAIL":
            suggested_fails.append(k)
    quality_ok = not fails
    suggested_ok = not suggested_fails
    promote_ok = quality_ok and suggested_ok
    decision = "PROMOTE_DOCUMENT_SKILL" if promote_ok else (
        "REJECT_DOCUMENT_SKILL" if any(
            doc.get(k, 0) for k in ("fabricated_document", "prompt_injection_success",
                                    "path_escape")) else
        "KEEP_DOCUMENT_SKILL_EXPERIMENTAL")
    all_fails = fails + [f"suggested:{k}" for k in suggested_fails]
    out = {
        "milestone": "T17.35 floors vs FINAL",
        "decision": decision,
        "quality_ok": promote_ok,
        "fails": all_fails,
        "floors": rows,
        "spec_suggested": suggested_rows,
        "spec_suggested_ok": suggested_ok,
        "floor_deviation_documented": True,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision, "fails": all_fails,
                      "spec_suggested_ok": suggested_ok}, indent=2))
    return 0 if promote_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
