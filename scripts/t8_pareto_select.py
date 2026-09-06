"""T8.13/T8.18 — Pareto selection + migration recommendation.

Consumes evaluations/t8/runs/<label>/model/summary.json (capability
vectors) and evaluations/t8/model_manifest.json (license/hardware gates),
produces evaluations/t8/pareto_analysis.json:
  - capability vectors per candidate
  - Pareto front + deterministic ranking (balance, not single-dimension wins)
  - per-dimension winners
  - hardware efficiency (capability gain per GB VRAM / per second)
  - migration_decision() recommendation per candidate vs control

Usage: python scripts/t8_pareto_select.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.evaluation.capacity import (  # noqa: E402
    CAPACITY_DIMENSIONS, license_gate, migration_decision, pareto_front,
    pareto_rank, validate_capability_vector)

RUNS = REPO / "evaluations" / "t8" / "runs"
MANIFEST = REPO / "evaluations" / "t8" / "model_manifest.json"
OUT = REPO / "evaluations" / "t8" / "pareto_analysis.json"
CONTROL_LABEL = "qwen3-1.7b-control"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = {e["model_id"]: e for e in manifest["candidates"]}

    vectors: dict[str, dict] = {}
    hardware: dict[str, dict] = {}
    for sum_path in sorted(RUNS.glob("*/model/summary.json")):
        s = json.loads(sum_path.read_text(encoding="utf-8"))
        if not s.get("ok"):
            continue
        label = s["label"]
        vectors[label] = {"model": s["model"],
                          **s["capability_vector"]}
        vectors[label].pop("retrieval_routing", None)
        vectors[label]["retrieval_routing"] = \
            s["capability_vector"].get("retrieval_routing")
        hardware[label] = {"model": s["model"], **s.get("hardware", {})}

    if not vectors:
        print("no completed runs found under", RUNS)
        return 1

    comparable = {k: v for k, v in vectors.items()
                  if not validate_capability_vector(v)}
    for k, v in vectors.items():
        errs = validate_capability_vector(v)
        if errs:
            print(f"note: {k} vector has {len(errs)} validation issue(s) "
                  "(excluded from Pareto):", errs)

    front = pareto_front(comparable)
    rank = pareto_rank(comparable)
    winners = {}
    for d in CAPACITY_DIMENSIONS:
        vals = {k: v.get(d) for k, v in vectors.items()
                if isinstance(v.get(d), (int, float))}
        if vals:
            winners[d] = max(vals, key=vals.get)

    control = vectors.get(CONTROL_LABEL)
    migration = {}
    for label, vec in comparable.items():
        if label == CONTROL_LABEL:
            continue
        mid = vec["model"]
        e = entries.get(mid, {})
        status, _ = license_gate(e)
        fits = e.get("fits_6gb", True)
        dec, reason = migration_decision(vec, control or vec,
                                         license_status=status,
                                         fits_vram=fits)
        migration[label] = {"model": mid, "decision": dec, "reason": reason,
                            "license_gate": status}

    # hardware efficiency: capability gain per GB VRAM / per second
    ctrl_vram = hardware.get(CONTROL_LABEL, {}).get("disk_size_gb")
    efficiency = {}
    for label, hw in hardware.items():
        vec = vectors.get(label, {})
        gain = None
        if control:
            gains = [(vec.get(d) or 0) - (control.get(d) or 0)
                     for d in ("overall", "math_macro", "science_macro",
                               "compositional", "counterfactual")]
            gain = round(sum(gains) / len(gains), 4)
        eff = {"mean_capability_gain": gain}
        if gain is not None and hw.get("disk_size_gb"):
            eff["capability_gain_per_gb_vram"] = round(
                gain / hw["disk_size_gb"], 4)
        if gain is not None and hw.get("mean_tokens_per_s"):
            eff["capability_gain_per_second_per_1k_tps"] = round(
                gain / (hw["mean_tokens_per_s"] / 1000), 4)
        efficiency[label] = eff

    analysis = {
        "analysis": "evaluations/t8/pareto_analysis.json",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "suite": "mango-capacity-eval-v1",
        "arm": "model-only (T8.6: executive scaffolding disabled)",
        "capability_vectors": vectors,
        "pareto_front": front,
        "pareto_rank": rank,
        "dimension_winners": winners,
        "migration_recommendations": migration,
        "hardware_efficiency": efficiency,
        "note": "Pareto dimensions = all capability-vector dimensions; "
                "candidates win on BALANCE, not single-dimension strength "
                "(T8.13). Missing dims count as 0 for dominance.",
    }
    OUT.write_text(json.dumps(analysis, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(json.dumps({"front": front, "rank": rank, "winners": winners,
                      "migration": migration}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())