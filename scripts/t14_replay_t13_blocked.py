"""T14.7 — replay frozen T13 NOT_NEEDED numeric rows on the T14 router."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    from sciencemath.scicomp.router import (
        COMPUTE_HELPFUL, COMPUTE_REQUIRED, INSUFFICIENT_INFORMATION,
        NO_COMPUTE, blocks_scicomp_invocation, compute_necessity)

    freeze = json.loads(
        (ROOT / "evaluations/t14/t13_router_failure_freeze.json")
        .read_text(encoding="utf-8"))
    blocked = [r for r in freeze["records"]
               if r["guard_blocked"]
               and r["numeric_conceptual_adversarial_class"]
               in ("numeric_oracle", "mixed")]
    rows = []
    for r in blocked:
        out = compute_necessity(r["question"])
        rows.append({
            "id": r["id"],
            "question": r["question"],
            "t13_necessity": r["current_necessity_decision"],
            "t13_correct": r["t13_correctness"],
            "t11_correct": r["t11_t12_t13_result_history"]["t11"]["correct"],
            "t14_necessity": out["necessity"],
            "t14_reason": out["reason"],
            "t14_blocks": blocks_scicomp_invocation(out["necessity"]),
            "expected_category": r["expected_category"],
            "operation_expected": r["operation_expected_if_known"],
        })
    counts = Counter(r["t14_necessity"] for r in rows)
    unblocked = sum(1 for r in rows if not r["t14_blocks"])
    doc = {
        "previously_blocked": len(rows),
        "now_COMPUTE_REQUIRED": counts.get(COMPUTE_REQUIRED, 0),
        "now_COMPUTE_HELPFUL": counts.get(COMPUTE_HELPFUL, 0),
        "still_NO_COMPUTE": counts.get(NO_COMPUTE, 0),
        "INSUFFICIENT_INFORMATION": counts.get(INSUFFICIENT_INFORMATION, 0),
        "unblocked": unblocked,
        "still_blocked": len(rows) - unblocked,
        "note": "Correctness (newly correct / still wrong / right→wrong) "
                "requires the T14 SciComp recheck (T14.8) with the frozen "
                "model; this file is the deterministic router replay only.",
        "rows": rows,
    }
    outp = ROOT / "evaluations/t14/t13_blocked_replay.json"
    outp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
