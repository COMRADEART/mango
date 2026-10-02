"""Contract-driven official evaluator for already-produced candidate rows."""
from __future__ import annotations

from typing import Any, Iterable

from .errors import ValidationError
from .taxonomy import validate_labels


def evaluate_rows(
    gold_rows: Iterable[dict[str, Any]],
    candidate_rows: Iterable[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> list[dict[str, Any]]:
    gold = list(gold_rows)
    candidate = list(candidate_rows)
    if len(gold) != len(candidate):
        raise ValidationError("candidate/gold row count mismatch")
    results: list[dict[str, Any]] = []
    for index, (gold_row, candidate_row) in enumerate(zip(gold, candidate)):
        if candidate_row.get("case_id") != gold_row.get("case_id"):
            raise ValidationError(f"candidate row order/identity mismatch at {index}")
        validate_labels(gold_row["gold"].get("required_domains", []), taxonomy, context=gold_row["case_id"])
        expected_status = gold_row["gold"]["expect_status"]
        status_match = candidate_row.get("status") == expected_status
        answer_match = expected_status != "ANSWER" or candidate_row.get("answer") == gold_row["gold"].get("expected_answer")
        counters = candidate_row.get("counters", {})
        if not isinstance(counters, dict) or any(not isinstance(value, int) for value in counters.values()):
            raise ValidationError(f"candidate counter schema mismatch: {gold_row['case_id']}")
        results.append(
            {
                "case_id": gold_row["case_id"],
                "suite_family": gold_row["suite_family"],
                "required_domains": gold_row["gold"].get("required_domains", []),
                "status_match": status_match,
                "answer_match": answer_match,
                "counters": counters,
                "correct": status_match and answer_match and not any(counters.values()),
            }
        )
    return results
