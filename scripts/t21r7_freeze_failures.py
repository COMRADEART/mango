"""Freeze the immutable T21R6 failure evidence used for T21R7 development.

This script is deliberately data-only: it reads the completed T21R6 official
raw results and root-cause record, verifies their published row counts and
digest, and writes a self-contained T21R7 development freeze.  It never
imports or executes the knowledge runtime.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_RESULTS = ROOT / "evaluations" / "t21r6" / "raw_results.jsonl"
ROOT_CAUSE = (
    ROOT / "evaluations" / "t21r6" / "over_abstention_root_cause.json"
)
OUTPUT = ROOT / "evaluations" / "t21r7" / "t21r6_failure_freeze.json"

EXPECTED_COUNTS = {
    "A1_qualifier_subject_gate_overconstraint": 64,
    "A2_relation_nominalization_morphology_gap": 42,
    "B_science_rag_routing_scope_error": 3,
    "C_adversarial_safe_fact_paraphrase_gap": 28,
    "D_absent_entity_unrelated_conflict_precedence": 5,
}

ROOT_CAUSE_IDS = {
    "A1_multihop_fellwold_subject_gate":
        "A1_qualifier_subject_gate_overconstraint",
    "A2_citation_nominalization_vocab":
        "A2_relation_nominalization_morphology_gap",
    "B_science_rag_misroute_molecule":
        "B_science_rag_routing_scope_error",
    "C_adversarial_exposure_vocab":
        "C_adversarial_safe_fact_paraphrase_gap",
    "D_injection_absent_entity_conflict_route":
        "D_absent_entity_unrelated_conflict_precedence",
}

ROW_FIELDS = (
    "case_id",
    "suite",
    "category",
    "query",
    "expected_status",
    "status",
    "answer",
    "expected_answer_contains",
    "decision_trace",
    "evidence_chunk_ids",
    "n_evidence_items",
    "coverage",
    "citations",
    "required_sources",
    "required_domains",
    "conflicts_surfaced",
    "temporal_action",
    "counters",
    "counters_nonzero",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_ids(sub_mode: dict[str, Any]) -> list[str]:
    rows = sub_mode["rows"]
    return [r["case_id"] if isinstance(r, dict) else r for r in rows]


def _trace_action(trace: list[str], prefix: str) -> str | None:
    return next((item for item in trace if item.startswith(prefix)), None)


def main() -> int:
    root_cause = json.loads(ROOT_CAUSE.read_text(encoding="utf-8"))
    expected_raw_hash = root_cause["official_run"]["raw_results_sha256"]
    actual_raw_hash = _sha256(RAW_RESULTS)
    if actual_raw_hash != expected_raw_hash:
        raise AssertionError(
            "immutable T21R6 raw-results digest changed: "
            f"expected {expected_raw_hash}, got {actual_raw_hash}"
        )

    raw_rows: dict[str, dict[str, Any]] = {}
    with RAW_RESULTS.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                case_id = row["case_id"]
                if case_id in raw_rows:
                    raise AssertionError(f"duplicate raw case_id: {case_id}")
                raw_rows[case_id] = row

    classes: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for sub_mode in root_cause["sub_modes"]:
        source_id = sub_mode["id"]
        if source_id not in ROOT_CAUSE_IDS:
            continue
        class_id = ROOT_CAUSE_IDS[source_id]
        ids = _case_ids(sub_mode)
        records = []
        for case_id in ids:
            if case_id in seen:
                raise AssertionError(f"case appears in multiple classes: {case_id}")
            seen.add(case_id)
            if case_id not in raw_rows:
                raise AssertionError(f"root-cause case missing from raw results: {case_id}")
            source = raw_rows[case_id]
            record = {field: source.get(field) for field in ROW_FIELDS}
            record["actual_status"] = record.pop("status")
            record["zero_tolerance_counters"] = record.pop("counters")
            record["root_cause_class"] = class_id
            record["failure_kind"] = (
                "status_mismatch"
                if class_id.startswith("D_")
                else "answer_over_abstention"
            )
            trace = record["decision_trace"] or []
            record["routing_action"] = _trace_action(trace, "eligibility:")
            record["conflict_action"] = _trace_action(trace, "conflicts:")
            if source.get("correct") is not False:
                raise AssertionError(f"frozen case unexpectedly correct: {case_id}")
            records.append(record)

        expected = EXPECTED_COUNTS[class_id]
        if len(records) != expected or sub_mode["n"] != expected:
            raise AssertionError(
                f"{class_id} count mismatch: root={sub_mode['n']} "
                f"selected={len(records)} expected={expected}"
            )
        classes[class_id] = {
            "source_root_cause_id": source_id,
            "failure_kind": (
                "status_mismatch"
                if class_id.startswith("D_")
                else "answer_over_abstention"
            ),
            "mechanism": sub_mode["mechanism"],
            "count": len(records),
            "rows": records,
        }

    actual_counts = {name: value["count"] for name, value in classes.items()}
    if actual_counts != EXPECTED_COUNTS:
        raise AssertionError(
            f"failure-class count assertion failed: {actual_counts}"
        )
    if len(seen) != sum(EXPECTED_COUNTS.values()):
        raise AssertionError(f"expected 142 distinct cases, got {len(seen)}")

    payload = {
        "milestone": "T21R7",
        "artifact": "T21R6 exposed failure evidence freeze",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "development_only": True,
        "replay_label": "T21R6_REPLAY_NON_PROMOTIONAL",
        "promotion_value": "ZERO",
        "source_artifacts": {
            "raw_results": str(RAW_RESULTS.relative_to(ROOT)).replace("\\", "/"),
            "raw_results_sha256": actual_raw_hash,
            "raw_results_rows": len(raw_rows),
            "root_cause": str(ROOT_CAUSE.relative_to(ROOT)).replace("\\", "/"),
            "root_cause_sha256": _sha256(ROOT_CAUSE),
        },
        "classification_contract": {
            "answer_over_abstention_classes": ["A1", "A2", "B", "C"],
            "status_mismatch_classes": ["D"],
            "classes_are_disjoint": True,
        },
        "mechanical_assertions": {
            "expected_counts": EXPECTED_COUNTS,
            "actual_counts": actual_counts,
            "distinct_rows": len(seen),
            "all_counts_match": True,
        },
        "classes": classes,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload["mechanical_assertions"], indent=2))
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
