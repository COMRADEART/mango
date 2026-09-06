"""Evaluate pre-declared regression gates and record the promotion
decision for one curriculum checkpoint (T6.10/T6.11/T6.12).

Protocol:
  * gates come from configs/curriculum.yaml (declared BEFORE any
    curriculum training; never edited after seeing results)
  * baseline = the parent checkpoint's metrics.json on the SAME frozen
    suite; candidate = this checkpoint's metrics.json
  * decision KEEP/REJECT is appended to the promotion log; a REJECTed
    checkpoint is never promoted, and a later run may not overwrite a
    KEEP (validate_promotion_log enforces this)
  * Pareto view over the eight capability dimensions (T6.12)

Usage:
  python scripts/promote_checkpoint.py --candidate mango-v0.2-L1 \
      --baseline mango-v0.1 --parent-adapter training/adapters/sciencemath-v0.1-t3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from sciencemath.curriculum.gates import (  # noqa: E402
    balanced_best, capability_vector, evaluate_gates, load_gates,
    pareto_front, promotion_entry, append_promotion_log,
    validate_promotion_log,
)
from sciencemath.utils.io_utils import load_yaml  # noqa: E402

CORE_RESULTS = REPO / "evaluations" / "t6" / "core_results"
LOG = REPO / "training" / "curriculum" / "promotion_log.jsonl"


def load_metrics(label: str) -> dict:
    path = CORE_RESULTS / label / "metrics.json"
    if not path.exists():
        raise SystemExit(f"missing metrics for {label}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))["metrics"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--checkpoint-dir", type=Path, required=True,
                    help="candidate adapter dir (provenance)")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    gates = load_gates(REPO / "configs" / "curriculum.yaml")
    baseline = load_metrics(args.baseline)
    candidate = load_metrics(args.candidate)

    result = evaluate_gates(gates, baseline, candidate,
                            level=args.level,
                            checkpoint=args.candidate,
                            parent=args.baseline)

    # Pareto bookkeeping over every checkpoint measured so far
    vectors = {}
    for d in CORE_RESULTS.iterdir():
        mp = d / "metrics.json"
        if mp.exists():
            vectors[d.name] = capability_vector(
                json.loads(mp.read_text(encoding="utf-8"))["metrics"])
    front = pareto_front(vectors)
    balanced = balanced_best(vectors)

    entry = promotion_entry(result, metrics=candidate,
                            capability_vector=vectors.get(args.candidate),
                            notes=args.notes or
                            f"pareto_front={front}; balanced_best={balanced}")
    entry["pareto"] = {"front": front, "balanced_best": balanced,
                       "candidate_on_front": args.candidate in front}
    entry["checkpoint_dir"] = str(args.checkpoint_dir)

    prior_errors = validate_promotion_log(LOG) if LOG.exists() else []
    if prior_errors:
        print("promotion log already inconsistent:", prior_errors)
        return 1
    append_promotion_log(LOG, entry)
    write_summary = CORE_RESULTS / args.candidate / "gate_decision.json"
    write_summary.write_text(
        json.dumps(entry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")

    print(json.dumps({
        "checkpoint": args.candidate,
        "decision": result["decision"],
        "violated_gates": result["violated_gates"],
        "drops_pp": result["drops_pp"],
        "pareto_front": front,
        "balanced_best": balanced,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())