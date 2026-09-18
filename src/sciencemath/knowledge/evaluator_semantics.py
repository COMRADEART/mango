"""Single machine-readable T21R7 evaluator scoring-semantics definition."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping


SCORING_SEMANTICS = {
    "version": "t21r7-scoring-v1",
    "answer_row_correctness": {
        "applies_when": "gold expect_status is ANSWER",
        "conjunction": [
            "status_match",
            "contains_ok",
            "citations_ok",
            "required_sources_ok",
            "required_domains_ok",
            "claims_supported",
            "zero_tolerance_all_zero",
        ],
        "required_domains_ok": {
            "participates_in_correctness": True,
            "applies_when": (
                "gold expect_status is ANSWER and required_domains is nonempty"
            ),
            "evidence_scope": "sources_actually_cited",
            "source_field": "KnowledgeSourceRecord.topic_tags",
            "normalization": "strip_casefold_whitespace_hyphen_to_underscore",
            "unknown_domain_policy": "evaluator_invalid",
        },
    },
    "non_answer_row_correctness": {
        "applies_when": "gold expect_status is not ANSWER",
        "conjunction": [
            "status_match",
            "zero_tolerance_all_zero",
        ],
        "answer_only_fields": (
            "contains_ok, citations_ok, required_sources_ok, "
            "required_domains_ok, and claims_supported are not applicable"
        ),
    },
    "citation_denominator": "all gold ANSWER rows",
    "source_diversity_denominator": (
        "multihop and crossdomain rows declaring at least two required sources"
    ),
    "zero_tolerance_policy": "any nonzero counter makes the row incorrect",
}


def canonical_semantics_json() -> str:
    return json.dumps(SCORING_SEMANTICS, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)


def scoring_semantics_sha256() -> str:
    return hashlib.sha256(canonical_semantics_json().encode("utf-8")).hexdigest()


def answer_row_correct(raw: Mapping[str, object]) -> bool:
    """Apply the status-specific machine-readable correctness conjunction."""
    if raw.get("expected_status", "ANSWER") != "ANSWER":
        return bool(
            raw.get("status_match")
            and not (raw.get("counters_nonzero") or [])
        )
    return bool(
        raw.get("status_match")
        and raw.get("contains_ok")
        and raw.get("citations_ok")
        and raw.get("required_sources_ok")
        and raw.get("required_domains_ok")
        and raw.get("claims_supported")
        and not (raw.get("counters_nonzero") or [])
    )
