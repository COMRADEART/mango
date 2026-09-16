"""Prepare T21R7 scoring semantics and unchanged promotion contract floors."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.evaluator_semantics import (  # noqa: E402
    SCORING_SEMANTICS,
    scoring_semantics_sha256,
)


OUT_DIR = ROOT / "evaluations" / "t21r7"
SEMANTICS_PATH = OUT_DIR / "scoring_semantics.json"
CONTRACT_PATH = OUT_DIR / "validation_contract.json"
R6_CONTRACT = ROOT / "evaluations" / "t21r6" / "validation_contract.json"


def main() -> int:
    source = json.loads(R6_CONTRACT.read_text(encoding="utf-8"))
    semantics_hash = scoring_semantics_sha256()
    semantics_doc = {
        "milestone": "T21R7",
        "scoring_semantics_sha256": semantics_hash,
        "definition": SCORING_SEMANTICS,
    }
    contract = {
        "milestone": "T21R7 blind-validation contract",
        "recorded_at": date.today().isoformat(),
        "note": (
            "Prepared before any T21R7 holdout exists. All 32 T21R6 "
            "promotion floors are preserved byte-for-value; none lowered."
        ),
        "scoring_semantics_path": (
            "evaluations/t21r7/scoring_semantics.json"
        ),
        "scoring_semantics_sha256": semantics_hash,
        "scoring_semantics": SCORING_SEMANTICS,
        "floors": source["floors"],
        "suite_minimums": {
            key.replace("t21r6", "t21r7"): value
            for key, value in source["suite_minimums"].items()
        },
        "zero_tolerance_note": source["zero_tolerance_note"],
    }
    if contract["floors"] != source["floors"]:
        raise AssertionError("T21R7 promotion floors changed")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SEMANTICS_PATH.write_text(
        json.dumps(semantics_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    CONTRACT_PATH.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    print(semantics_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
