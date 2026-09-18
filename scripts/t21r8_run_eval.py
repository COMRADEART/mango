"""T21R8 evaluator core, qualified before any T21R8 holdout exists.

The stable metric implementations are reused from the completed T21R6
evaluator (the same lineage T21R7 used).  Answer-row correctness is derived
from the ONE machine-readable T21R8 scoring-semantics definition
(``evaluations/t21r8/scoring_semantics.json``) so evaluator, contract,
qualification, and later freeze artifacts cannot drift apart: the semantics
dict is loaded from that single file and the correctness conjunction is
applied exactly as recorded there.  Any unknown conjunction term or a
missing semantics file is T21R8_EVALUATOR_INVALID, never a silent PASS.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r6_run_eval as _r6  # noqa: E402


OUT_DIR = ROOT / "evaluations" / "t21r8"
SUITES_DIR = OUT_DIR / "suites"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r8"
CONTRACT_PATH = OUT_DIR / "validation_contract.json"
SEMANTICS_PATH = OUT_DIR / "scoring_semantics.json"

SUITES = [
    "mango-t21r8-retrieval-holdout-v1",
    "mango-t21r8-singlehop-holdout-v1",
    "mango-t21r8-multihop-holdout-v1",
    "mango-t21r8-crossdomain-holdout-v1",
    "mango-t21r8-citation-claim-holdout-v1",
    "mango-t21r8-conflict-abstention-holdout-v1",
    "mango-t21r8-temporal-holdout-v1",
    "mango-t21r8-adversarial-holdout-v1",
]

# The semantics file must exist BEFORE the evaluator is importable: it is the
# single preregistered scoring contract, written before any blind data.
if not SEMANTICS_PATH.exists():
    raise SystemExit(
        "T21R8_EVALUATOR_INVALID: scoring_semantics.json is missing; the "
        "evaluator refuses to score without the preregistered semantics")
_SEMANTICS_DOCUMENT = json.loads(SEMANTICS_PATH.read_text(encoding="utf-8"))
SCORING_SEMANTICS = _SEMANTICS_DOCUMENT["definition"]

DOMAIN_TAXONOMY = _r6.DOMAIN_TAXONOMY
RAW_ANSWER_FIELDS = _r6.RAW_ANSWER_FIELDS + ("scoring_semantics_sha256",)
RAW_RETRIEVAL_FIELDS = _r6.RAW_RETRIEVAL_FIELDS

normalize_domain = _r6.normalize_domain
source_domains = _r6.source_domains
validate_domain_labels = _r6.validate_domain_labels
required_domains_ok = _r6.required_domains_ok
run_retrieval_row = _r6.run_retrieval_row
retrieval_metrics = _r6.retrieval_metrics
answer_correctness = _r6.answer_correctness
citation_metrics = _r6.citation_metrics
abstention_metrics = _r6.abstention_metrics
temporal_metrics = _r6.temporal_metrics
security_metrics = _r6.security_metrics
compare_floors = _r6.compare_floors
aggregate_zero_totals = _r6.aggregate_zero_totals
aggregate_metrics = _r6.aggregate_metrics
suite_minimums_met = _r6.suite_minimums_met
_multisource_diversity = _r6._multisource_diversity


def canonical_semantics_json() -> str:
    return json.dumps(SCORING_SEMANTICS, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)


def scoring_semantics_sha256() -> str:
    return hashlib.sha256(canonical_semantics_json().encode("utf-8")
                          ).hexdigest()


def _check_conjunction(conjunction, raw: dict) -> bool:
    """Apply one machine-readable correctness conjunction to a raw record."""
    result = True
    for conjunct in conjunction:
        if conjunct == "zero_tolerance_all_zero":
            result = result and not (raw.get("counters_nonzero") or [])
        elif conjunct == "status_match":
            result = result and bool(raw.get("status_match"))
        elif conjunct in raw:
            result = result and bool(raw.get(conjunct))
        else:
            raise SystemExit(
                "T21R8_EVALUATOR_INVALID: scoring semantics requires conjunct "
                f"'{conjunct}' which the raw record does not carry")
    return bool(result)


def answer_row_correct(raw: dict) -> bool:
    """Apply the status-specific conjunction exactly as preregistered in
    scoring_semantics.json."""
    semantics = SCORING_SEMANTICS
    if raw.get("expected_status", "ANSWER") != "ANSWER":
        return _check_conjunction(
            semantics["non_answer_row_correctness"]["conjunction"], raw)
    return _check_conjunction(
        semantics["answer_row_correctness"]["conjunction"], raw)


def run_answer_row(row: dict, corpus) -> tuple[dict, object]:
    """Execute the runtime and score with the canonical T21R8 conjunction."""
    raw, result = _r6.run_answer_row(row, corpus)
    raw["correct"] = answer_row_correct(raw)
    raw["scoring_semantics_sha256"] = scoring_semantics_sha256()
    return raw, result


def validate_semantics_artifacts(contract: dict, freeze: dict | None = None) \
        -> str:
    """Require evaluator, contract, and (when present) freeze hash identity."""
    expected = scoring_semantics_sha256()
    if contract.get("scoring_semantics") != SCORING_SEMANTICS:
        raise ValueError(
            "T21R8_EVALUATOR_INVALID: contract semantics definition differs "
            "from evaluator semantics"
        )
    contract_hash = contract.get("scoring_semantics_sha256")
    if contract_hash != expected:
        raise ValueError(
            f"T21R8_EVALUATOR_INVALID: contract semantics {contract_hash} "
            f"!= evaluator semantics {expected}"
        )
    if freeze is not None:
        if freeze.get("scoring_semantics") != SCORING_SEMANTICS:
            raise ValueError(
                "T21R8_EVALUATOR_INVALID: freeze semantics definition differs "
                "from evaluator semantics"
            )
        freeze_hash = freeze.get("scoring_semantics_sha256")
        if freeze_hash != expected:
            raise ValueError(
                f"T21R8_EVALUATOR_INVALID: freeze semantics {freeze_hash} "
                f"!= evaluator semantics {expected}"
            )
    return expected


def main() -> int:
    if not CONTRACT_PATH.exists() or not SEMANTICS_PATH.exists():
        raise SystemExit(
            "T21R8_EVALUATOR_NOT_READY: prepare and qualify evaluator before "
            "holdout construction"
        )
    raise SystemExit(
        "T21R8_BLIND_HOLDOUT_NOT_CONSTRUCTED: preregistration phase only; "
        "official evaluation runs exclusively via "
        "python scripts/t21r8_official_eval.py after HOLDOUT_FROZEN"
    )


if __name__ == "__main__":
    raise SystemExit(main())