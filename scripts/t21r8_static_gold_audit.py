"""Data-only T21R8 static gold and construction audit.

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
OUT_DIR = ROOT / "evaluations" / "t21r8"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r8"
SUITES_DIR = OUT_DIR / "suites"
sys.path.insert(0, str(ROOT / "scripts"))

import t21r6_static_gold_audit as arithmetic  # noqa: E402
from t21r8_construction_audit import measure_candidate  # noqa: E402
from t21r8_construction_gate import (  # noqa: E402
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
    """Point the local arithmetic copy at R8 data and rebuild its index."""
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


def main() -> int:
    chunks = _load_jsonl(CORPUS_DIR / "chunks.jsonl")
    sources = _load_jsonl(CORPUS_DIR / "sources.jsonl")
    chunks_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    sources_by_id = {source["source_id"]: source for source in sources}
    rows_by_suite: dict[str, list[dict]] = {}
    for path in sorted(SUITES_DIR.glob("*/holdout.jsonl")):
        rows_by_suite[path.parent.name] = _load_jsonl(path)
    rows = [row for suite_rows in rows_by_suite.values() for row in suite_rows]
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
        for evidence_id in (row.get("construction") or {}).get(
                "attack_evidence_chunk_ids") or []:
            if evidence_id not in chunks_by_id:
                missing_refs.append(
                    f"{row['case_id']}: evidence chunk {evidence_id}")
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
                   if (chunk.get("metadata") or {}).get("fact_value")
                   is not None}
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

    # Complete gold paths: bridge identity, terminal identity, and both edges
    # must exist as structured agreeing edges in the candidate corpus.
    path_failures: list[str] = []
    for row in rows:
        path = (row.get("construction") or {}).get("gold_path")
        if not path:
            continue
        hop1, hop2 = path["hop1_edge"], path["hop2_edge"]
        ok = True
        for edge in (hop1, hop2):
            matches = [
                chunk for chunk in chunks
                if (chunk.get("metadata") or {}).get("fact_entity")
                == edge["subject_entity"]
                and str((chunk.get("metadata") or {}).get("fact_value"))
                == str(edge["object_value"])
            ]
            if not matches:
                ok = False
        if hop1["object_value"] != hop2["subject_entity"] \
                or hop2["object_value"] != path["terminal_value"] \
                or not ok:
            path_failures.append(row["case_id"])
    checks["gold_paths_resolve"] = {"checked": sum(
        1 for row in rows
        if (row.get("construction") or {}).get("gold_path")),
        "failures": len(path_failures)}
    failures.extend(f"gold path defect: {case_id}"
                    for case_id in path_failures[:40])

    # Cross-domain completeness: two distinct sources and two distinct domains,
    # and required domains must be backed by the topic tags of the cited
    # sources.
    domain_failures: list[str] = []
    for row in rows:
        gold = row["gold"]
        required_sources = gold.get("required_sources") or []
        if len(set(required_sources)) < 2:
            continue
        domains = set(gold.get("required_domains") or [])
        backed: set[str] = set()
        for source_id in required_sources:
            source = sources_by_id.get(source_id) or {}
            backed.update(source.get("topic_tags") or [])
        if len(set(required_sources)) < 2 or len(domains) < 2 \
                or not domains <= backed:
            domain_failures.append(row["case_id"])
    checks["required_domains_backed_by_source_tags"] = {
        "failures": len(domain_failures)}
    failures.extend(f"domain backing defect: {case_id}"
                    for case_id in domain_failures[:40])

    # IE rows: intentionally incomplete, gold INSUFFICIENT_EVIDENCE unless a
    # relevant unresolved contradiction requires CONFLICTING_EVIDENCE.
    ie_failures: list[str] = []
    for row in rows:
        if "partial_path_ie_stress" not in row.get(
                "construction_tags", []):
            continue
        annotation = row.get("construction") or {}
        if "gold_path" in annotation:
            ie_failures.append(f"{row['case_id']}: complete gold path")
        component = annotation.get("missing_component")
        status = row["gold"].get("expect_status")
        if component == "relevant_unresolved_conflict":
            if status != "CONFLICTING_EVIDENCE":
                ie_failures.append(f"{row['case_id']}: status {status}")
        elif status != "INSUFFICIENT_EVIDENCE":
            ie_failures.append(f"{row['case_id']}: status {status}")
    checks["ie_cases_intentionally_incomplete"] = {
        "failures": len(ie_failures)}
    failures.extend(f"IE defect: {failure}" for failure in ie_failures[:40])

    # Source-injection rows retain a safe factual sentence after the exact
    # frozen quarantine-pattern copy removes the directive sentence.
    exposure_misses: list[str] = []
    exposure_checked = 0
    for row in rows:
        if "source_injection_safe_fact" not in row.get(
                "construction_tags", []):
            continue
        exposure_checked += 1
        chunk = chunks_by_id[row["gold"]["gold_chunk_id"]]
        safe = arithmetic.quarantine_source_text(chunk["text"])
        fact_value = str(
            (chunk.get("metadata") or {}).get("fact_value", ""))
        if not safe or fact_value.casefold() not in safe.casefold():
            exposure_misses.append(row["case_id"])
    checks["source_injection_safe_fact_survives"] = {
        "checked": exposure_checked, "misses": len(exposure_misses)}
    failures.extend(f"source safe fact missing: {case_id}"
                    for case_id in exposure_misses[:40])

    spoof_misses = [row["case_id"] for row in rows
                    if row.get("category") == "citation_spoof"
                    and not arithmetic.spoof_flagged(
                        row["request"]["query"])]
    checks["citation_spoof_statically_flagged"] = {
        "misses": len(spoof_misses)}
    failures.extend(f"spoof not flagged: {case_id}"
                    for case_id in spoof_misses[:40])

    measured = measure_candidate()
    construction_section = build_audit_section(measured["metrics"])
    if measured["annotation_violation_details"]:
        failures.append("construction annotations contain violations")

    report = {
        "artifact": "T21R8 static gold and construction audit",
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