"""T21R4.10 — freeze the evaluator BEFORE any holdout data exists.

Records SHA-256 hashes of the evaluator source, the preregistered metric
definitions, the validation contract, and the zero-tolerance definitions
into evaluations/t21r4/evaluator_freeze.json.

Ordering invariant: this script must run AFTER scripts/t21r4_freeze_runtime.py
(runtime frozen first) and BEFORE scripts/t21r4_world.py generates any
holdout data. After this file exists, NO evaluator semantics may change:
denominators, numerators, case inclusion rules, status mappings, claim
classification rules, citation counting, retrieval rank rules, conflict
scoring, temporal scoring, and source diversity rules are all frozen.

Usage: python scripts/t21r4_freeze_evaluator.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r4"

EVALUATOR = ROOT / "scripts" / "t21r4_run_eval.py"
CONTRACT = OUT_DIR / "validation_contract.json"
RUNTIME_FREEZE = OUT_DIR / "runtime_freeze.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not RUNTIME_FREEZE.exists():
        raise SystemExit(
            "runtime_freeze.json missing: freeze the runtime first "
            "(T21R4.B1 precedes T21R4.10)")
    if not EVALUATOR.exists():
        raise SystemExit("evaluator source missing")
    if not CONTRACT.exists():
        raise SystemExit("validation contract missing")

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    runtime_freeze = json.loads(RUNTIME_FREEZE.read_text(encoding="utf-8"))

    doc = {
        "milestone": "T21R4.10 evaluator freeze (before holdout data)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "runtime_freeze_recorded_at": runtime_freeze["recorded_at"],
        "ordering": "runtime freeze < evaluator freeze < holdout data "
                    "generation < HOLDOUT_FROZEN",
        "frozen_hashes": {
            "evaluator_source_sha256": sha256_file(EVALUATOR),
            "evaluator_path": "scripts/t21r4_run_eval.py",
            "validation_contract_sha256": sha256_file(CONTRACT),
            "metric_definitions_sha256": hashlib.sha256(
                json.dumps(contract["metric_definitions"],
                           sort_keys=True, ensure_ascii=False)
                .encode("utf-8")).hexdigest(),
            "zero_tolerance_definitions_sha256": hashlib.sha256(
                json.dumps({"zero_tolerance_gates":
                            contract["zero_tolerance_gates"],
                            "zero_tolerance_rule":
                            contract["zero_tolerance_rule"]},
                           sort_keys=True, ensure_ascii=False)
                .encode("utf-8")).hexdigest(),
            "floors_sha256": hashlib.sha256(
                json.dumps(contract["floors"], sort_keys=True,
                           ensure_ascii=False).encode("utf-8")).hexdigest(),
        },
        "frozen_semantics": [
            "citation metric denominator: gold-ANSWER-mode rows",
            "citation metric numerators: resolvability/validity/precision "
            "over answered rows; coverage and supported-claim rate over "
            "claim verdict counts",
            "retrieval rank rules: rank of gold chunk in final "
            "reranked+deduplicated order, 1-based, not found = 0",
            "abstention/conflict scoring over the conflict-abstention suite",
            "temporal scoring categories and denominators",
            "source diversity: required-multi-source pass rate over "
            "multihop + crossdomain rows",
            "case inclusion: every row of every frozen suite is scored; no "
            "row may be dropped or added after freeze",
        ],
        "rule": "After this file exists NO evaluator semantics may change. "
                "If an evaluator bug is discovered after HOLDOUT_FROZEN or "
                "after the first evaluation starts: STOP; decision is "
                "T21R4_EVALUATOR_INVALID; the exposed holdout becomes "
                "non-promotional and a future milestone with another fresh "
                "holdout is required.",
    }
    out = OUT_DIR / "evaluator_freeze.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({"status": "EVALUATOR_FROZEN",
                      "out": out.as_posix(),
                      "evaluator_sha256":
                          doc["frozen_hashes"]["evaluator_source_sha256"]},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())