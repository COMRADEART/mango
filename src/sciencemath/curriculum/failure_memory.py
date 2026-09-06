"""T6.19 — Structured failure memory for Mango.

NOT persistent AGI memory: a curated, append-only failure log that records
every measured evaluation failure with enough structure (error type,
routing needs, verification evidence) to become input to future
procedural-memory / self-improvement milestones (T11/T13).

Error taxonomy (fixed closed set, classification order in classify()):
  CONCEPT_ERROR, ALGEBRA_ERROR, ARITHMETIC_ERROR, TOOL_ROUTING_ERROR,
  RETRIEVAL_ROUTING_ERROR, EVIDENCE_MISUSE, UNIT_ERROR, EXTRACTION_ERROR,
  MULTI_HOP_FAILURE, UNSUPPORTED_CLAIM, OVERCONFIDENCE
plus the T2 evaluation taxonomy passthrough categories (see
evaluation.taxonomy) for generation-level failures.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ERROR_TYPES = (
    "CONCEPT_ERROR", "ALGEBRA_ERROR", "ARITHMETIC_ERROR",
    "TOOL_ROUTING_ERROR", "RETRIEVAL_ROUTING_ERROR", "EVIDENCE_MISUSE",
    "UNIT_ERROR", "EXTRACTION_ERROR", "MULTI_HOP_FAILURE",
    "UNSUPPORTED_CLAIM", "OVERCONFIDENCE",
)

REQUIRED_FIELDS = (
    "problem_id", "suite", "domain", "capability_track", "error_type",
    "tool_needed", "retrieval_needed", "expected_answer",
    "actual_wrong_answer", "verification_evidence", "checkpoint",
)
OPTIONAL_FIELDS = ("corrected_strategy", "notes", "recorded_at")


def classify_error_type(record: dict) -> str:
    """Deterministic first-pass classification from recorded run fields.
    Deliberately conservative: routing/misuse errors are detected from
    structured flags; everything else falls back to CONCEPT_ERROR for
    graded-wrong answers (refined later by analysis scripts, never
    reclassified silently)."""
    if record.get("failure") in ("EXTRACTION_FAILURE",):
        return "EXTRACTION_ERROR"
    if record.get("routing_label") == "INSUFFICIENT_INFO" \
            and not record.get("signalled_insufficient") \
            and record.get("correct") is False:
        return "OVERCONFIDENCE"
    if record.get("routing_label") == "TOOL" \
            and not record.get("invoked_tool") and record.get("correct") is False:
        return "TOOL_ROUTING_ERROR"
    if record.get("routing_label") == "RETRIEVAL" \
            and not record.get("invoked_retrieval") \
            and record.get("correct") is False:
        return "RETRIEVAL_ROUTING_ERROR"
    if record.get("routing_label") == "BOTH" \
            and record.get("correct") is False:
        if not record.get("invoked_tool"):
            return "TOOL_ROUTING_ERROR"
        if not record.get("invoked_retrieval"):
            return "RETRIEVAL_ROUTING_ERROR"
    if record.get("citations_fabricated"):
        return "UNSUPPORTED_CLAIM"
    if record.get("multi_hop") and record.get("correct") is False:
        return "MULTI_HOP_FAILURE"
    if record.get("unit_error_evidence"):
        return "UNIT_ERROR"
    if record.get("numeric_mismatch_evidence"):
        return "ARITHMETIC_ERROR"
    return "CONCEPT_ERROR"


def make_record(*, problem_id: str, suite: str, domain: str,
                capability_track: str, tool_needed: bool,
                retrieval_needed: bool, expected_answer: str,
                actual_wrong_answer: str | None, checkpoint: str,
                run_record: dict, verification_evidence: str = "",
                corrected_strategy: str | None = None) -> dict:
    rec = {
        "problem_id": problem_id,
        "suite": suite,
        "domain": domain,
        "capability_track": capability_track,
        "error_type": classify_error_type(run_record),
        "tool_needed": bool(tool_needed),
        "retrieval_needed": bool(retrieval_needed),
        "expected_answer": expected_answer,
        "actual_wrong_answer": actual_wrong_answer,
        "verification_evidence": verification_evidence,
        "checkpoint": checkpoint,
        "corrected_strategy": corrected_strategy,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    missing = [f for f in REQUIRED_FIELDS if rec.get(f) in (None, "")
               and f != "actual_wrong_answer"]
    if missing:
        raise ValueError(f"failure record missing fields: {missing}")
    return rec


def append_failures(path: Path, records: list[dict]) -> int:
    """Append-only JSONL; flush each line. Returns count written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            validate_record(r)
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        f.flush()
    return len(records)


def validate_record(rec: dict) -> list[str]:
    errors = []
    for f in REQUIRED_FIELDS:
        if f not in rec:
            errors.append(f"missing field {f}")
    if rec.get("error_type") not in ERROR_TYPES:
        errors.append(f"error_type {rec.get('error_type')!r} not in taxonomy")
    for f in ("tool_needed", "retrieval_needed"):
        if f in rec and not isinstance(rec[f], bool):
            errors.append(f"{f} must be boolean")
    return errors


def summarize(path: Path) -> dict:
    """Aggregate the failure log: counts by error type / domain / routing."""
    by_type: Counter = Counter()
    by_domain: Counter = Counter()
    by_track: Counter = Counter()
    n = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            n += 1
            by_type[rec.get("error_type")] += 1
            by_domain[rec.get("domain")] += 1
            by_track[rec.get("capability_track")] += 1
    return {
        "total_failures": n,
        "by_error_type": dict(by_type.most_common()),
        "by_domain": dict(by_domain.most_common()),
        "by_capability_track": dict(by_track.most_common()),
    }