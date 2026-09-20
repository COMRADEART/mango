"""Generate test-failure summaries and applicability from one artifact."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .errors import ValidationError

ALLOWED_CLASSIFICATIONS = frozenset(
    {"OBSOLETE_HISTORICAL_ASSERTION", "SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE", "ENVIRONMENT_ONLY_FAILURE", "LIVE", "UNKNOWN"}
)


def classification_summary(entries: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for entry in entries:
        nodeid = entry.get("nodeid")
        classification = entry.get("classification")
        if not isinstance(nodeid, str) or not nodeid:
            raise ValidationError("adjudication entry has no nodeid")
        if classification not in ALLOWED_CLASSIFICATIONS:
            raise ValidationError(f"unknown adjudication classification: {classification}")
        counts[classification] += 1
    return {name: counts.get(name, 0) for name in sorted(ALLOWED_CLASSIFICATIONS)}


def validate_adjudication(document: dict[str, Any]) -> dict[str, Any]:
    computed = classification_summary(document.get("entries", []))
    if document.get("classification_summary") != computed:
        raise ValidationError("declared adjudication summary differs from computed summary")
    if computed["LIVE"] or computed["UNKNOWN"]:
        raise ValidationError("LIVE or UNKNOWN full-suite failure remains")
    return {"status": "PASS", "classification_summary": computed, "registered_failures": sum(computed.values())}


def generate_applicability(document: dict[str, Any]) -> dict[str, Any]:
    report = validate_adjudication(document)
    deselect = sorted(
        entry["nodeid"]
        for entry in document["entries"]
        if entry["classification"] not in {"LIVE", "UNKNOWN"}
    )
    return {**report, "deselect_nodeids": deselect}
