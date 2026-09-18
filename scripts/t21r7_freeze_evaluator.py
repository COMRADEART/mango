"""Freeze the qualified T21R7 evaluator before blind-world construction."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r7"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from sciencemath.knowledge.evaluator_semantics import (  # noqa: E402
    SCORING_SEMANTICS,
    scoring_semantics_sha256,
)
import t21r7_run_eval as evaluator  # noqa: E402


EVALUATOR = ROOT / "scripts" / "t21r7_run_eval.py"
CONTRACT = OUT_DIR / "validation_contract.json"
CONSTRUCTION_CONTRACT = OUT_DIR / "holdout_construction_contract.json"
RUNTIME_FREEZE = OUT_DIR / "runtime_freeze.json"
QUALIFICATION = OUT_DIR / "evaluator_qualification.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_object(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    if (ROOT / "rag" / "gk_holdout_t21r7").exists() or \
            (OUT_DIR / "HOLDOUT_FROZEN").exists():
        raise SystemExit("evaluator must freeze before T21R7 holdout data")
    for path in (EVALUATOR, CONTRACT, CONSTRUCTION_CONTRACT,
                 RUNTIME_FREEZE, QUALIFICATION):
        if not path.exists():
            raise SystemExit(f"evaluator freeze prerequisite missing: {path}")

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    runtime_freeze = json.loads(RUNTIME_FREEZE.read_text(encoding="utf-8"))
    qualification = json.loads(QUALIFICATION.read_text(encoding="utf-8"))
    evaluator_sha = _sha256(EVALUATOR)
    if not qualification.get("qualification_passed") or \
            not qualification.get("all_paths_exercised") or \
            qualification.get("uncaught_exceptions") != 0 or \
            qualification.get("n_cases", 0) < 45:
        raise SystemExit("evaluator qualification gate is not PASS")
    if qualification.get("evaluator_source_sha256") != evaluator_sha:
        raise SystemExit("qualification does not match evaluator source")
    expected_semantics = scoring_semantics_sha256()
    if contract.get("scoring_semantics") != SCORING_SEMANTICS or \
            contract.get("scoring_semantics_sha256") != expected_semantics or \
            qualification.get("scoring_semantics_sha256") != expected_semantics:
        raise SystemExit("evaluator/contract/qualification semantics differ")
    if sum(len(group) for group in contract["floors"].values()) != 32:
        raise SystemExit("validation contract must contain exactly 32 floors")

    raw_schema = {
        "raw_answer_fields": list(evaluator.RAW_ANSWER_FIELDS),
        "raw_retrieval_fields": list(evaluator.RAW_RETRIEVAL_FIELDS),
    }
    document = {
        "milestone": "T21R7 evaluator freeze (before blind holdout)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "runtime_freeze_recorded_at": runtime_freeze["recorded_at"],
        "ordering": (
            "runtime freeze < evaluator freeze < blind holdout generation "
            "< static/uniqueness/blindness audits < HOLDOUT_FROZEN"
        ),
        "qualification_recorded_at": qualification["recorded_at"],
        "qualification_cases": {
            "n_cases": qualification["n_cases"],
            "n_passed": qualification["n_passed"],
            "all_paths_exercised": qualification["all_paths_exercised"],
            "uncaught_exceptions": qualification["uncaught_exceptions"],
        },
        "evaluator_source_sha256": evaluator_sha,
        "scoring_semantics": SCORING_SEMANTICS,
        "scoring_semantics_sha256": expected_semantics,
        "frozen_hashes": {
            "evaluator_source_sha256": evaluator_sha,
            "evaluator_path": "scripts/t21r7_run_eval.py",
            "validation_contract_sha256": _sha256(CONTRACT),
            "construction_contract_sha256": _sha256(CONSTRUCTION_CONTRACT),
            "floors_sha256": _hash_object(contract["floors"]),
            "suite_minimums_sha256": _hash_object(contract["suite_minimums"]),
            "zero_tolerance_note_sha256": _hash_object(
                contract["zero_tolerance_note"]),
            "raw_results_schema_sha256": _hash_object(raw_schema),
        },
        "raw_results_schema": raw_schema,
        "correctness_rule": SCORING_SEMANTICS,
        "rule": (
            "After this file exists no evaluator semantics or raw schema may "
            "change. Any defect discovered after HOLDOUT_FROZEN or official "
            "evaluation start invalidates T21R7; no repair or rerun."
        ),
    }
    evaluator.validate_semantics_artifacts(contract, document)
    path = OUT_DIR / "evaluator_freeze.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps({"status": "EVALUATOR_FROZEN", "path": str(path),
                      "evaluator_sha256": evaluator_sha}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
