"""T14R.21 — executive router frozen recheck (v1) + corrected recheck (v2).

The executive router is deterministic CPU code (route_task), so both
rechecks run on CPU while the SciComp replay holds the GPU.

* v1 (FROZEN, official): re-run the frozen mango-executive-router-eval-v1
  FINAL split through the unchanged router and verify the frozen T14
  metrics reproduce (deterministic); decision B applies this rule.
* v2 (corrected, supporting): same router, same thresholds, on the
  de-duplicated v2 suite — isolates the benchmark-artifact contribution.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from t14_executive_metrics import evaluate, load_items  # noqa: E402

OUT = ROOT / "evaluations/t14r/executive_recheck.json"


def main() -> int:
    # ---- frozen v1 FINAL recheck (checksum-pinned) ----------------------
    v1 = ROOT / "evaluations/t14/suites/executive-router/v1"
    path = v1 / "final.jsonl"
    pinned = (v1 / "final_checksum.txt").read_text(encoding="utf-8").strip()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != pinned:
        raise SystemExit("frozen v1 final checksum mismatch")
    m1 = evaluate(load_items(path))
    rows1 = m1.pop("rows")
    traces1 = m1.pop("traces")

    v1_out = ROOT / "evaluations/t14r/executive/v1_final"
    v1_out.mkdir(parents=True, exist_ok=True)
    (v1_out / "metrics.json").write_text(
        json.dumps(m1, indent=2) + "\n", encoding="utf-8")

    frozen_t14 = json.loads(
        (ROOT / "evaluations/t14/executive/final/metrics.json")
        .read_text(encoding="utf-8"))
    keys = ["primary_route_accuracy", "top2_route_accuracy",
            "tool_required_recall", "no_tool_specificity",
            "unavailable_capability_rejection", "hallucinated_tools",
            "unauthorized_paid_route", "unavailable_skill_presented_as_executed",
            "permission_bypass", "route_depth_violations",
            "multi_skill_accuracy", "multi_skill_ordering_correctness"]
    bit_identical = all(
        m1.get(k) == frozen_t14.get(k) for k in keys if k in frozen_t14)

    # ---- corrected v2 recheck -------------------------------------------
    v2 = ROOT / "evaluations/t14r/suites/executive-router/v2"
    items2 = load_items(v2 / "questions.jsonl")
    m2 = evaluate(items2)
    m2.pop("rows")
    m2.pop("traces")

    doc = {
        "milestone": "T14R.21 — executive router recheck",
        "router_change": "NONE (deterministic route_task unchanged)",
        "v1_frozen_recheck": {
            "suite": "mango-executive-router-eval-v1 FINAL",
            "suite_sha256": digest,
            "metrics": m1,
            "bit_identical_to_T14": bit_identical,
        },
        "v2_corrected_recheck": {
            "suite": "mango-executive-router-eval-v2 (20 duplicate-gold "
                     "rows removed; thresholds unchanged)",
            "metrics": m2,
        },
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bit_identical_to_T14": bit_identical,
                      "v1_top2": m1.get("top2_route_accuracy"),
                      "v1_tool_recall": m1.get("tool_required_recall"),
                      "v2_top2": m2.get("top2_route_accuracy"),
                      "v2_tool_recall": m2.get("tool_required_recall"),
                      "v2_primary": m2.get("primary_route_accuracy"),
                      "v2_no_tool_specificity":
                          m2.get("no_tool_specificity")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())