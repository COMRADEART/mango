"""Data-only T21R8 holdout uniqueness audit.

The construction scanner performs the preregistered eight-world comparison.
This audit adds internal identity checks, revalidates every construction gate,
and writes the freeze prerequisite without importing or executing Mango.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r8"
SUITES_DIR = OUT_DIR / "suites"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r8"
sys.path.insert(0, str(ROOT / "scripts"))

from t21r8_construction_audit import measure_candidate  # noqa: E402
from t21r8_construction_gate import build_audit_section  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duplicates(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return {value: count for value, count in counts.items() if count > 1}


def main() -> int:
    suite_paths = sorted(SUITES_DIR.glob("*/holdout.jsonl"))
    rows = [row for path in suite_paths for row in _load_jsonl(path)]
    chunks = _load_jsonl(CORPUS_DIR / "chunks.jsonl")
    sources = _load_jsonl(CORPUS_DIR / "sources.jsonl")

    row_identities = [json.dumps(
        {key: value for key, value in row.items() if key != "case_id"},
        sort_keys=True, ensure_ascii=False) for row in rows]
    internal = {
        "duplicate_case_ids": len(_duplicates(
            [str(row["case_id"]) for row in rows])),
        "duplicate_exact_queries": len(_duplicates(
            [str(row["request"]["query"]) for row in rows])),
        "duplicate_rows_excluding_case_id": len(_duplicates(row_identities)),
        "duplicate_source_ids": len(_duplicates(
            [str(source["source_id"]) for source in sources])),
        "duplicate_chunk_ids": len(_duplicates(
            [str(chunk["chunk_id"]) for chunk in chunks])),
        "duplicate_exact_source_text": len(_duplicates(
            [str(chunk["text"]) for chunk in chunks])),
    }

    measured = measure_candidate()
    construction = build_audit_section(measured["metrics"])
    independence = measured["metrics"]["independence"]
    overlap_total = sum(
        int(count)
        for milestone in independence.values()
        for count in milestone.values()
    )
    ok = (
        all(value == 0 for value in internal.values())
        and not measured["annotation_violation_details"]
        and overlap_total == 0
        and construction["status"] == "PASS"
    )
    report = {
        "audit": "t21r8_holdout_uniqueness",
        "verdict": "UNIQUE" if ok else "OVERLAP_DETECTED",
        "comparison_milestones": list(independence),
        "zero_overlap_dimensions": [
            "case_ids", "entity_identities", "source_ids", "chunk_ids",
            "exact_queries", "exact_answers", "exact_source_text",
            "verbatim_attacks",
        ],
        "total_rows": len(rows),
        "corpus": {"sources": len(sources), "chunks": len(chunks)},
        "internal_checks": internal,
        "prior_world_overlap_counts": independence,
        "prior_world_overlap_total": overlap_total,
        "construction_requirements_evaluated": construction[
            "requirements_evaluated"],
        "construction_requirements_passed": construction[
            "requirements_passed"],
        "annotation_violations": measured["annotation_violation_details"],
        "suite_sha256": {
            path.parent.name: _sha256(path) for path in suite_paths
        },
        "runtime_execution_count": 0,
    }
    (OUT_DIR / "holdout_uniqueness.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({
        "verdict": report["verdict"],
        "rows": len(rows),
        "internal_violations": sum(internal.values()),
        "prior_world_overlaps": overlap_total,
        "runtime_execution_count": 0,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())