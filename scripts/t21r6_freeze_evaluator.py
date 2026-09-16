"""T21R6 — freeze the evaluator BEFORE any holdout data exists.

Records SHA-256 hashes of the evaluator source, the preregistered full
per-row raw-result schema (RAW_ANSWER_FIELDS / RAW_RETRIEVAL_FIELDS),
the scoring semantics, the floors, and the zero-tolerance definitions
into evaluations/t21r6/evaluator_freeze.json.

Refuses to freeze unless the qualification gate is green for THIS
evaluator source hash (qualification_passed == true,
uncaught_exceptions == 0, all paths exercised, all cases pass) — the
T21R6 lesson from T21R5_EVALUATOR_INVALID: the evaluator may not be
declared frozen while it is still unqualified.

Ordering invariant: this script must run AFTER
scripts/t21r6_freeze_runtime.py (runtime frozen first) and BEFORE
scripts/t21r6_world.py generates any holdout data. After this file
exists, NO evaluator semantics may change: denominators, numerators,
case inclusion rules, status mappings, claim classification rules,
citation counting, retrieval rank rules, conflict scoring, temporal
scoring, source diversity rules, required_domains semantics (normalized
topic_tags of the SOURCES ACTUALLY CITED), AND the raw_results.jsonl
per-row schema are all frozen.

Usage: python scripts/t21r6_freeze_evaluator.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r6"

EVALUATOR = ROOT / "scripts" / "t21r6_run_eval.py"
CONTRACT = OUT_DIR / "validation_contract.json"
RUNTIME_FREEZE = OUT_DIR / "runtime_freeze.json"
QUALIFICATION = OUT_DIR / "evaluator_qualification.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if not RUNTIME_FREEZE.exists():
        raise SystemExit(
            "runtime_freeze.json missing: freeze the runtime first "
            "(T21R6 runtime freeze precedes the evaluator freeze)")
    if not EVALUATOR.exists():
        raise SystemExit("evaluator source missing")
    if not CONTRACT.exists():
        raise SystemExit("validation contract missing")
    if not QUALIFICATION.exists():
        raise SystemExit(
            "evaluator_qualification.json missing: the evaluator may not "
            "be frozen unqualified (T21R5_EVALUATOR_INVALID rule)")

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    runtime_freeze = json.loads(RUNTIME_FREEZE.read_text(encoding="utf-8"))
    qualification = json.loads(QUALIFICATION.read_text(encoding="utf-8"))
    evaluator_sha = sha256_file(EVALUATOR)
    if not qualification.get("qualification_passed"):
        raise SystemExit("evaluator qualification did not pass")
    if qualification.get("uncaught_exceptions") != 0:
        raise SystemExit(
            "evaluator qualification recorded uncaught exceptions")
    if qualification.get("evaluator_source_sha256") != evaluator_sha:
        raise SystemExit(
            "evaluator qualification was recorded for a different "
            "evaluator source hash — re-run scripts/t21r6_qualify_evaluator.py")

    # Import ONLY the preregistered raw-schema constants from the frozen
    # evaluator source (module import executes no runtime code and no
    # holdout data exists yet, so this is a static extraction).
    sys.path.insert(0, str(ROOT / "scripts"))
    from t21r6_run_eval import (  # noqa: E402
        RAW_ANSWER_FIELDS,
        RAW_RETRIEVAL_FIELDS,
    )
    raw_schema = {
        "raw_answer_fields": list(RAW_ANSWER_FIELDS),
        "raw_retrieval_fields": list(RAW_RETRIEVAL_FIELDS),
    }

    def _h(obj) -> str:
        return hashlib.sha256(
            json.dumps(obj, sort_keys=True, ensure_ascii=False)
            .encode("utf-8")).hexdigest()

    doc = {
        "milestone": "T21R6 evaluator freeze (before holdout data)",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "runtime_freeze_recorded_at": runtime_freeze["recorded_at"],
        "ordering": "runtime freeze < evaluator freeze < holdout data "
                    "generation < HOLDOUT_FROZEN",
        "qualification_recorded_at": qualification["recorded_at"],
        "qualification_cases": {
            "n_cases": qualification["n_cases"],
            "n_passed": qualification["n_passed"],
        },
        "evaluator_source_sha256": evaluator_sha,
        "frozen_hashes": {
            "evaluator_source_sha256": evaluator_sha,
            "evaluator_path": "scripts/t21r6_run_eval.py",
            "validation_contract_sha256": sha256_file(CONTRACT),
            "scoring_semantics_sha256": _h(
                contract["scoring_semantics"]),
            "floors_sha256": _h(contract["floors"]),
            "suite_minimums_sha256": _h(contract["suite_minimums"]),
            "zero_tolerance_note_sha256": _h(
                {"zero_tolerance_note": contract["zero_tolerance_note"]}),
            "raw_results_schema_sha256": _h(raw_schema),
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
            "required_domains: set(required_domains) must be a subset of "
            "the union of normalized topic_tags of the SOURCES ACTUALLY "
            "CITED; labels must belong to the frozen DOMAIN_TAXONOMY "
            "(repairs the T21R5 evaluator crash at t21r5_run_eval.py:186)",
            "required_sources and required_domains are recorded per row "
            "(required_sources_ok participates in correctness; "
            "required_domains_ok is recorded but NOT in the correctness "
            "conjunction - identical to the T21R4 semantics)",
            "case inclusion: every row of every frozen suite is scored; no "
            "row may be dropped or added after freeze",
            "raw_results.jsonl: one immutable full-per-row line per row in "
            "the SAME run as holdout_results.json, with the preregistered "
            "raw_answer_fields / raw_retrieval_fields schema recorded here; "
            "the evaluator refuses to run if the file already exists",
        ],
        "raw_results_schema": raw_schema,
        "rule": "After this file exists NO evaluator semantics may change. "
                "If an evaluator bug is discovered after HOLDOUT_FROZEN or "
                "after the first evaluation starts: STOP; decision is "
                "T21R6_EVALUATOR_INVALID; the exposed holdout becomes "
                "non-promotional and a future milestone with another fresh "
                "holdout is required.",
    }
    out = OUT_DIR / "evaluator_freeze.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({"status": "EVALUATOR_FROZEN",
                      "out": out.as_posix(),
                      "evaluator_sha256": evaluator_sha},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())