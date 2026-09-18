"""Data-only T21R7 static gold and construction audit.

The audit mirrors frozen lexical retrieval arithmetic but imports no runtime
or evaluator module.  It executes no holdout query through Mango.  It also
derives every construction-contract metric directly from candidate files and
embeds the complete machine-validated construction gate in its report.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r7"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r7"
SUITES_DIR = OUT_DIR / "suites"
sys.path.insert(0, str(ROOT / "scripts"))

import t21r6_static_gold_audit as arithmetic  # noqa: E402
from t21r7_construction_audit import measure_candidate  # noqa: E402
from t21r7_construction_gate import (  # noqa: E402
    build_audit_section,
    validate_static_audit,
)


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install_candidate_arithmetic(chunks: list[dict],
                                  sources: list[dict]) -> None:
    """Point the local arithmetic copy at R7 data and rebuild its index."""
    arithmetic._CHUNKS = chunks
    arithmetic._CHUNKS_BY_ID = {chunk["chunk_id"]: chunk for chunk in chunks}
    arithmetic._SOURCES_BY_ID = {source["source_id"]: source
                                 for source in sources}
    arithmetic._DOCS = []
    arithmetic._DOC_LEN = []
    arithmetic._INV = {}
    for position, chunk in enumerate(chunks):
        tokens = arithmetic.tokenize(chunk["text"])
        frequencies: dict[str, int] = {}
        for token in tokens:
            frequencies[token] = frequencies.get(token, 0) + 1
        arithmetic._DOCS.append(frequencies)
        arithmetic._DOC_LEN.append(len(tokens))
        for token, frequency in frequencies.items():
            arithmetic._INV.setdefault(token, {})[position] = frequency
    arithmetic._N_DOCS = len(arithmetic._DOCS)
    arithmetic._AVG_LEN = (
        sum(arithmetic._DOC_LEN) / arithmetic._N_DOCS
        if arithmetic._N_DOCS else 0.0
    )


def _base_category(row: dict) -> str:
    return str(row.get("category", "")).removesuffix("_fresh_variant")


def main() -> int:
    chunks = _load_jsonl(CORPUS_DIR / "chunks.jsonl")
    sources = _load_jsonl(CORPUS_DIR / "sources.jsonl")
    chunks_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    sources_by_id = {source["source_id"]: source for source in sources}
    rows = [row for path in sorted(SUITES_DIR.glob("*/holdout.jsonl"))
            for row in _load_jsonl(path)]
    _install_candidate_arithmetic(chunks, sources)

    failures: list[str] = []
    checks: dict[str, dict] = {}
    windows: dict[str, list[str]] = {}

    def window(query: str) -> list[str]:
        if query not in windows:
            windows[query] = arithmetic.final_window(query)
        return windows[query]

    # Structural identity and references.
    case_ids = [row["case_id"] for row in rows]
    queries = [row["request"]["query"] for row in rows]
    duplicate_ids = len(case_ids) - len(set(case_ids))
    duplicate_queries = len(queries) - len(set(queries))
    checks["internal_identity"] = {
        "duplicate_case_ids": duplicate_ids,
        "duplicate_queries": duplicate_queries,
    }
    if duplicate_ids or duplicate_queries:
        failures.append("candidate contains duplicate case IDs or queries")

    missing_refs: list[str] = []
    for row in rows:
        gold = row["gold"]
        chunk_id = gold.get("gold_chunk_id")
        if chunk_id and chunk_id not in chunks_by_id:
            missing_refs.append(f"{row['case_id']}: chunk {chunk_id}")
        for source_id in gold.get("required_sources") or []:
            if source_id not in sources_by_id:
                missing_refs.append(f"{row['case_id']}: source {source_id}")
    checks["gold_references_resolve"] = {"failures": len(missing_refs)}
    failures.extend(missing_refs[:40])

    # Frozen lexical retrieval arithmetic: every declared gold chunk must be
    # inside the final top-8 evidence window.
    window_misses: list[str] = []
    rank_histogram: dict[str, int] = {}
    for row in rows:
        chunk_id = row["gold"].get("gold_chunk_id")
        if not chunk_id or chunk_id not in chunks_by_id:
            continue
        result = window(row["request"]["query"])
        if chunk_id not in result:
            window_misses.append(row["case_id"])
        else:
            rank = str(result.index(chunk_id) + 1)
            rank_histogram[rank] = rank_histogram.get(rank, 0) + 1
    checks["gold_in_final_window"] = {
        "checked": sum(bool(row["gold"].get("gold_chunk_id")) for row in rows),
        "misses": len(window_misses),
        "rank_histogram": rank_histogram,
    }
    failures.extend(f"gold not in final window: {case_id}"
                    for case_id in window_misses[:60])

    # Every expected answer must exist as an exact structured fact value and
    # in source text.  Multi-hop answers may live outside the hop-1 gold chunk.
    fact_values = {str((chunk.get("metadata") or {}).get("fact_value"))
                   for chunk in chunks
                   if (chunk.get("metadata") or {}).get("fact_value") is not None}
    answer_misses: list[str] = []
    for row in rows:
        for answer in row["gold"].get("expect_answer_contains") or []:
            if str(answer) not in fact_values or not any(
                    str(answer).casefold() in chunk["text"].casefold()
                    for chunk in chunks):
                answer_misses.append(f"{row['case_id']}: {answer}")
    checks["answers_exist_in_structured_evidence"] = {
        "failures": len(answer_misses)}
    failures.extend(answer_misses[:40])

    # Bridge rows: the creator's birthplace must be statically retrievable in
    # the frozen hop-2 top-3 window.
    bridge_categories = {
        "two_hop_bridge", "art_to_biography", "technology_to_biography",
        "literature_to_biography", "civic_writings_to_biography",
    }
    hop2_misses: list[str] = []
    for row in rows:
        if _base_category(row) not in bridge_categories:
            continue
        gold_chunk = chunks_by_id[row["gold"]["gold_chunk_id"]]
        creator = str(gold_chunk["metadata"]["fact_value"])
        birthplace = [chunk for chunk in chunks
                      if (chunk.get("metadata") or {}).get("fact_entity") == creator
                      and (chunk.get("metadata") or {}).get("fact_attribute")
                      == "birthplace"]
        query = f"{creator} born birthplace"
        ranked = arithmetic.bm25_search(query, 9)
        reranked = arithmetic.rerank(ranked, query, 3)
        hop2 = [chunk_id for chunk_id, _score in arithmetic.select_window(
            arithmetic.dedup_chunks(reranked), 3)]
        if not birthplace or birthplace[0]["chunk_id"] not in hop2:
            hop2_misses.append(row["case_id"])
    checks["hop2_birthplace_retrievable"] = {"misses": len(hop2_misses)}
    failures.extend(f"hop2 not statically retrievable: {case_id}"
                    for case_id in hop2_misses[:40])

    # Source-injection rows retain a safe factual sentence after the exact
    # frozen quarantine-pattern copy removes the directive sentence.
    exposure_misses: list[str] = []
    exposure_checked = 0
    for row in rows:
        if "source_injection_safe_fact" not in row.get("construction_tags", []):
            continue
        exposure_checked += 1
        chunk = chunks_by_id[row["gold"]["gold_chunk_id"]]
        safe = arithmetic.quarantine_source_text(chunk["text"])
        fact_value = str((chunk.get("metadata") or {}).get("fact_value", ""))
        if not safe or fact_value.casefold() not in safe.casefold():
            exposure_misses.append(row["case_id"])
    checks["source_injection_safe_fact_survives"] = {
        "checked": exposure_checked, "misses": len(exposure_misses)}
    failures.extend(f"source safe fact missing: {case_id}"
                    for case_id in exposure_misses[:40])

    spoof_misses = [row["case_id"] for row in rows
                    if _base_category(row) == "citation_spoof"
                    and not arithmetic.spoof_flagged(row["request"]["query"])]
    checks["citation_spoof_statically_flagged"] = {
        "misses": len(spoof_misses)}
    failures.extend(f"spoof not flagged: {case_id}"
                    for case_id in spoof_misses[:40])

    measured = measure_candidate()
    construction_section = build_audit_section(measured["metrics"])
    if measured["annotation_violation_details"]:
        failures.append("construction annotations contain violations")

    report = {
        "artifact": "T21R7 static gold and construction audit",
        "status": "PASS" if not failures and
                  construction_section["status"] == "PASS" else "FAIL",
        "rows": len(rows),
        "corpus": {"sources": len(sources), "chunks": len(chunks)},
        "checks": checks,
        "construction_contract": construction_section,
        "annotation_violation_details": measured[
            "annotation_violation_details"],
        "failures": failures,
        "input_hashes": {
            "corpus_manifest": _sha256(CORPUS_DIR / "corpus_manifest.json"),
            **{
                path.parent.name: _sha256(path)
                for path in sorted(SUITES_DIR.glob("*/holdout.jsonl"))
            },
        },
        "runtime_execution_count": 0,
    }
    if report["status"] == "PASS":
        validate_static_audit(report)
    path = OUT_DIR / "static_gold_audit.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": report["status"], "rows": report["rows"],
        "failures": len(failures),
        "construction_requirements": construction_section[
            "requirements_evaluated"],
        "construction_passed": construction_section[
            "requirements_passed"],
        "runtime_execution_count": 0,
    }, indent=2))
    if failures:
        for failure in failures[:80]:
            print(" -", failure)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
