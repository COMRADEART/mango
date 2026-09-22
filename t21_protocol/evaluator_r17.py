"""T21R17 official row-evidence evaluator.

Produces one explicit per-row evidence record per holdout case — the single
row-evidence source every registered metric implementation consumes. The
accuracy semantics (status_match, answer_match, zero-tolerance counters)
are identical to the frozen T21R16 kernel evaluator; the record additionally
carries the citation, claim, retrieval-rank, and routing evidence the
explicit scorer requires. No metric value is computed here.
"""
from __future__ import annotations

from typing import Any, Iterable

from .errors import ValidationError
from .taxonomy import validate_labels

EVIDENCE_ROW_FIELDS = (
    "case_id",
    "suite_family",
    "mode",
    "construction_tag",
    "query",
    "expected_status",
    "status",
    "status_match",
    "answer_match",
    "answer",
    "expected_answer",
    "required_domains",
    "required_sources",
    "chunk_ids",
    "citations",
    "n_citations",
    "cited_chunk_ids",
    "cited_source_ids",
    "citation_report_ok",
    "citation_verdicts",
    "claim_counts",
    "claims_supported",
    "counters",
    "counters_nonzero",
    "rank",
    "n_returned",
    "correct",
)
REQUIRED_CANDIDATE_FIELDS = ("status", "answer", "counters", "citations", "citation_report", "claim_review")


def _candidate_evidence(candidate_row: dict[str, Any], case_id: str) -> dict[str, Any]:
    missing = [field for field in REQUIRED_CANDIDATE_FIELDS if field not in candidate_row]
    if missing:
        raise ValidationError(f"candidate evidence schema mismatch (v2 serialization required): {case_id} missing {missing}")
    citation_report = candidate_row["citation_report"]
    claim_review = candidate_row["claim_review"]
    if not isinstance(citation_report, dict) or not isinstance(claim_review, dict):
        raise ValidationError(f"candidate evidence schema mismatch: {case_id}")
    return {
        "citations": [dict(citation) for citation in candidate_row["citations"]],
        "citation_report_ok": bool(citation_report.get("ok", False)),
        "citation_verdicts": [
            verdict.get("status") for verdict in citation_report.get("verdicts", []) if isinstance(verdict, dict)
        ],
        "claim_counts": dict(claim_review.get("counts") or {}),
        "claims_supported": bool(claim_review.get("all_claims_supported", False)),
        "evidence_pack": dict(candidate_row.get("evidence_pack") or {}),
        "eligibility": dict(candidate_row.get("eligibility") or {}),
    }


def _retrieval_rank(gold_chunk_ids: list[str], citations: list[dict[str, Any]]) -> int:
    """Rank of the registered gold chunk in the candidate's final evidence
    order (the order of the candidate's emitted citations); 0 when absent."""
    order = [citation.get("chunk_id") for citation in citations]
    for chunk_id in gold_chunk_ids:
        if chunk_id in order:
            return order.index(chunk_id) + 1
    return 0


def evaluate_evidence_rows(
    gold_rows: Iterable[dict[str, Any]],
    candidate_rows: Iterable[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate sealed gold rows against v2 candidate rows into evidence records."""
    gold = list(gold_rows)
    candidate = list(candidate_rows)
    if len(gold) != len(candidate):
        raise ValidationError("candidate/gold row count mismatch")
    results: list[dict[str, Any]] = []
    for index, (gold_row, candidate_row) in enumerate(zip(gold, candidate)):
        if candidate_row.get("case_id") != gold_row.get("case_id"):
            raise ValidationError(f"candidate row order/identity mismatch at {index}")
        case_id = gold_row["case_id"]
        gold_evidence = gold_row["gold"]
        validate_labels(gold_evidence.get("required_domains", []), taxonomy, context=case_id)
        expected_status = gold_evidence["expect_status"]
        status = candidate_row.get("status")
        status_match = status == expected_status
        answer_match = expected_status != "ANSWER" or candidate_row.get("answer") == gold_evidence.get("expected_answer")
        counters = candidate_row.get("counters", {})
        if not isinstance(counters, dict) or any(not isinstance(value, int) for value in counters.values()):
            raise ValidationError(f"candidate counter schema mismatch: {case_id}")
        evidence = _candidate_evidence(candidate_row, case_id)
        citations = evidence["citations"]
        chunk_ids = list(gold_evidence.get("chunk_ids") or [])
        required_sources = list(gold_evidence.get("source_ids") or [])
        counters_nonzero = [key for key, value in counters.items() if value]
        results.append(
            {
                "case_id": case_id,
                "suite_family": gold_row["suite_family"],
                "mode": gold_row.get("mode", "answer"),
                "construction_tag": gold_row.get("construction_tag"),
                "query": gold_row.get("query"),
                "expected_status": expected_status,
                "status": status,
                "status_match": status_match,
                "answer_match": answer_match,
                "answer": candidate_row.get("answer"),
                "expected_answer": gold_evidence.get("expected_answer"),
                "required_domains": gold_evidence.get("required_domains", []),
                "required_sources": required_sources,
                "chunk_ids": chunk_ids,
                "citations": citations,
                "n_citations": len(citations),
                "cited_chunk_ids": [citation.get("chunk_id") for citation in citations],
                "cited_source_ids": [citation.get("source_id") for citation in citations],
                "citation_report_ok": evidence["citation_report_ok"],
                "citation_verdicts": evidence["citation_verdicts"],
                "claim_counts": evidence["claim_counts"],
                "claims_supported": evidence["claims_supported"],
                "counters": counters,
                "counters_nonzero": counters_nonzero,
                "rank": _retrieval_rank(chunk_ids, citations),
                "n_returned": len(citations),
                "correct": status_match and answer_match and not any(counters.values()),
            }
        )
    return results


def kernel_evaluator_parity(
    gold_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    """Prove the evidence evaluator's accuracy semantics are identical to the
    frozen T21R16 kernel evaluator (status_match, answer_match, counters,
    correct, required_domains) row for row."""
    from .evaluator import evaluate_rows

    legacy = evaluate_rows(gold_rows, candidate_rows, taxonomy)
    evidence = evaluate_evidence_rows(gold_rows, candidate_rows, taxonomy)
    differences = [
        {"case_id": legacy_row["case_id"], "field": field}
        for legacy_row, evidence_row in zip(legacy, evidence)
        for field in ("case_id", "suite_family", "required_domains", "status_match", "answer_match", "counters", "correct")
        if legacy_row[field] != evidence_row[field]
    ]
    return {"status": "PASS" if not differences else "FAIL", "rows": len(legacy), "semantic_differences": differences}