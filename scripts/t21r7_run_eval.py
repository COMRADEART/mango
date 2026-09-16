"""T21R7 evaluator core, qualified before any T21R7 holdout exists.

The stable metric implementations are reused from the completed T21R6
evaluator.  Answer-row correctness is deliberately recomputed from the one
machine-readable T21R7 scoring-semantics definition so evaluator, contract,
and future freeze metadata cannot drift apart.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import t21r6_run_eval as _r6  # noqa: E402
from sciencemath.knowledge.evaluator_semantics import (  # noqa: E402
    SCORING_SEMANTICS,
    answer_row_correct,
    scoring_semantics_sha256,
)


OUT_DIR = ROOT / "evaluations" / "t21r7"
SUITES_DIR = OUT_DIR / "suites"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r7"
CONTRACT_PATH = OUT_DIR / "validation_contract.json"
SEMANTICS_PATH = OUT_DIR / "scoring_semantics.json"

SUITES = [
    "mango-t21r7-retrieval-holdout-v1",
    "mango-t21r7-singlehop-holdout-v1",
    "mango-t21r7-multihop-holdout-v1",
    "mango-t21r7-crossdomain-holdout-v1",
    "mango-t21r7-citation-claim-holdout-v1",
    "mango-t21r7-conflict-abstention-holdout-v1",
    "mango-t21r7-temporal-holdout-v1",
    "mango-t21r7-adversarial-holdout-v1",
]

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


def run_answer_row(row: dict, corpus) -> tuple[dict, object]:
    """Execute the runtime and score with the canonical T21R7 conjunction."""
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
            "T21R7_EVALUATOR_INVALID: contract semantics definition differs "
            "from evaluator semantics"
        )
    contract_hash = contract.get("scoring_semantics_sha256")
    if contract_hash != expected:
        raise ValueError(
            f"T21R7_EVALUATOR_INVALID: contract semantics {contract_hash} "
            f"!= evaluator semantics {expected}"
        )
    if freeze is not None:
        if freeze.get("scoring_semantics") != SCORING_SEMANTICS:
            raise ValueError(
                "T21R7_EVALUATOR_INVALID: freeze semantics definition differs "
                "from evaluator semantics"
            )
        freeze_hash = freeze.get("scoring_semantics_sha256")
        if freeze_hash != expected:
            raise ValueError(
                f"T21R7_EVALUATOR_INVALID: freeze semantics {freeze_hash} "
                f"!= evaluator semantics {expected}"
            )
    return expected


def main() -> int:
    if not CONTRACT_PATH.exists() or not SEMANTICS_PATH.exists():
        raise SystemExit(
            "T21R7_EVALUATOR_NOT_READY: prepare and qualify evaluator before "
            "holdout construction"
        )
    raise SystemExit(
        "T21R7_BLIND_HOLDOUT_NOT_CONSTRUCTED: development phase only; "
        "official evaluation is intentionally unavailable"
    )


if __name__ == "__main__":
    raise SystemExit(main())
