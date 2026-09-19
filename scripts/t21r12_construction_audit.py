"""Data-only construction scanner for future T21R12 candidate files."""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r12"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r12"
SUITES_DIR = OUT_DIR / "suites"
CONTRACT_PATH = OUT_DIR / "holdout_construction_contract.json"
sys.path.insert(0, str(ROOT / "scripts"))

import t21r12_static_semantics as semantics  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(
        encoding="utf-8").splitlines() if line.strip()]


def load_candidate(corpus_dir: Path = CORPUS_DIR,
                   suites_dir: Path = SUITES_DIR) \
        -> tuple[list[dict], list[dict], dict[str, list[dict]]]:
    sources = _load_jsonl(corpus_dir / "sources.jsonl")
    chunks = _load_jsonl(corpus_dir / "chunks.jsonl")
    rows = {path.parent.name: _load_jsonl(path)
            for path in sorted(suites_dir.glob("*/holdout.jsonl"))}
    return sources, chunks, rows


def audit_material(sources: list[dict], chunks: list[dict],
                   rows_by_suite: dict[str, list[dict]]) -> dict:
    rows = [row for suite_rows in rows_by_suite.values() for row in suite_rows]
    annotation = semantics.scan_annotations(rows, chunks)
    declared_windows = [str(row.get("case_id")) for row in rows
                        if "initial_window_chunk_ids" in
                        (row.get("construction") or {})]
    case_ids = [str(row.get("case_id") or "") for row in rows]
    queries = [str((row.get("request") or {}).get("query") or "")
               for row in rows]
    source_ids = [str(source.get("source_id") or "") for source in sources]
    chunk_ids = [str(chunk.get("chunk_id") or "") for chunk in chunks]
    internal = {
        "duplicate_case_ids": len(case_ids) - len(set(case_ids)),
        "duplicate_exact_queries": len(queries) - len(set(queries)),
        "duplicate_source_ids": len(source_ids) - len(set(source_ids)),
        "duplicate_chunk_ids": len(chunk_ids) - len(set(chunk_ids)),
    }
    ie = sorted({str((row.get("construction") or {}).get("missing_component"))
                 for row in rows
                 if "partial_path_ie_stress" in
                 (row.get("construction_tags") or [])})
    ie_counts = {component: sum(
        1 for row in rows if "partial_path_ie_stress" in
        (row.get("construction_tags") or []) and str(
            (row.get("construction") or {}).get("missing_component")) ==
        component) for component in semantics.PARTIAL_PATH_COMPONENTS}
    multihop = [row for suite_id, suite_rows in rows_by_suite.items()
                if "-multihop-" in suite_id for row in suite_rows]
    crossdomain = [row for suite_id, suite_rows in rows_by_suite.items()
                   if "-crossdomain-" in suite_id for row in suite_rows]
    families: dict[tuple[str, str], int] = {}
    for row in multihop:
        path = (row.get("construction") or {}).get("gold_path") or {}
        if path.get("hop1_edge") and path.get("hop2_edge"):
            family = (str(path["hop1_edge"].get("relation")),
                      str(path["hop2_edge"].get("relation")))
            families[family] = families.get(family, 0) + 1
    surface_rows = [row for row in rows if "relation_surface_sensitive" in
                    (row.get("construction_tags") or [])]
    surface_mismatch = sum(not all((row.get("construction") or {}).get(
        "surface_match") or [True]) for row in surface_rows)
    multihop_surface_mismatch = sum(not all(
        (row.get("construction") or {}).get("surface_match") or [True])
        for row in multihop if "relation_surface_sensitive" in
        (row.get("construction_tags") or []))
    canonical_relations = {str(relation) for row in surface_rows
                           for relation in ((row.get("construction") or {}).get(
                               "canonical_relation") or [])}
    domain_pairs: dict[frozenset[str], int] = {}
    two_source_domain = 0
    for row in crossdomain:
        gold = row.get("gold") or {}
        sources_required = set(gold.get("required_sources") or [])
        domains_required = frozenset(gold.get("required_domains") or [])
        if len(sources_required) >= 2 and len(domains_required) >= 2:
            two_source_domain += 1
        domain_pairs[domains_required] = domain_pairs.get(domains_required, 0) + 1
    multisource = 0
    for row in [*multihop, *crossdomain]:
        annotation_row = row.get("construction") or {}
        path = annotation_row.get("gold_path") or {}
        edge_sources = {str(edge.get("source_id")) for edge in
                        (path.get("hop1_edge"), path.get("hop2_edge"))
                        if isinstance(edge, dict) and edge.get("source_id")}
        declared = {str(value) for value in
                    (annotation_row.get("path_required_sources") or [])}
        if "multisource_path" in (row.get("construction_tags") or []) and \
                len(edge_sources) >= 2 and declared == edge_sources:
            multisource += 1
    tag_counts = {tag: sum(tag in (row.get("construction_tags") or [])
                           for row in rows) for tag in (
        "partial_path_ie_stress", "source_injection_safe_fact",
        "query_injection_or_spoof", "safe_fact_with_directive")}
    violations = list(annotation["violations"])
    violations.extend({"case_id": case_id,
                       "reason": "builder-declared initial window is forbidden"}
                      for case_id in declared_windows)
    violations.extend({"case_id": "<candidate>", "reason": name}
                      for name, count in internal.items() if count)
    metrics = {
        "total_rows": len(rows),
        "suite_rows": {suite_id: len(suite_rows)
                       for suite_id, suite_rows in rows_by_suite.items()},
        "annotation_violations": len(violations),
        "declared_initial_windows": len(declared_windows),
        "partial_path_configurations": ie,
        "stress": {
            "multihop_rows": len(multihop),
            "multihop_chain_families": len(families),
            "multihop_largest_family_share": max(
                families.values(), default=0) / len(multihop)
            if multihop else 0.0,
            "multihop_relation_surface_mismatch_fraction":
                multihop_surface_mismatch / len(multihop) if multihop else 0.0,
            "crossdomain_rows": len(crossdomain),
            "crossdomain_two_source_two_domain": two_source_domain,
            "domain_pair_families": len(domain_pairs),
            "largest_domain_pair_share": max(
                domain_pairs.values(), default=0) / len(crossdomain)
            if crossdomain else 0.0,
            "multisource_path_rows": multisource,
            "partial_path_rows": tag_counts["partial_path_ie_stress"],
            "partial_path_configuration_counts": ie_counts,
            "relation_surface_rows": len(surface_rows),
            "canonical_relations": sorted(canonical_relations),
            "relation_surface_mismatch_fraction": surface_mismatch /
                len(surface_rows) if surface_rows else 0.0,
            "source_injection_rows": tag_counts[
                "source_injection_safe_fact"],
            "query_injection_or_spoof_rows": tag_counts[
                "query_injection_or_spoof"],
            "safe_fact_with_directive_rows": tag_counts[
                "safe_fact_with_directive"],
        },
        "runtime_execution_count": 0,
    }
    return {
        "artifact": "T21R12_CONSTRUCTION_AUDIT",
        "status": "PASS" if not violations else "FAIL",
        "metrics": metrics,
        "violations": violations,
        "internal": internal,
        "runtime_execution_count": 0,
    }


def main() -> int:
    sources, chunks, rows = load_candidate()
    report = audit_material(sources, chunks, rows)
    path = OUT_DIR / "construction_audit.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"],
                      "metrics": report["metrics"]}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


