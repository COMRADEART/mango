"""Real T21R12 data-only static gold audit with derived retrieval windows."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r12"
CORPUS_DIR = ROOT / "rag" / "gk_holdout_t21r12"
SUITES_DIR = OUT_DIR / "suites"
sys.path.insert(0, str(ROOT / "scripts"))

import t21r12_construction_audit as construction  # noqa: E402
import t21r12_construction_gate as gate  # noqa: E402
import t21r12_static_semantics as semantics  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_material(sources: list[dict], chunks: list[dict],
                   rows_by_suite: dict[str, list[dict]],
                   *, miniature: bool = False) -> dict:
    rows = [row for suite_rows in rows_by_suite.values() for row in suite_rows]
    source_ids = {str(source.get("source_id")) for source in sources}
    chunk_ids = {str(chunk.get("chunk_id")) for chunk in chunks}
    failures: list[str] = []
    path_results: dict[str, dict] = {}
    spoof_results: dict[str, dict] = {}
    for row in rows:
        case_id = str(row.get("case_id"))
        gold = row.get("gold") or {}
        annotation = row.get("construction") or {}
        for chunk_id in gold.get("required_chunk_ids") or []:
            if str(chunk_id) not in chunk_ids:
                failures.append(f"{case_id}: unresolved required chunk")
        gold_chunk = gold.get("gold_chunk_id")
        if gold_chunk and str(gold_chunk) not in chunk_ids:
            failures.append(f"{case_id}: unresolved gold chunk")
        for source_id in [*(gold.get("required_sources") or []),
                          *(annotation.get("path_required_sources") or [])]:
            if str(source_id) not in source_ids:
                failures.append(f"{case_id}: unresolved required source")
        if annotation.get("gold_path"):
            result = semantics.audit_path_row(row, sources, chunks)
            path_results[case_id] = result
            if result["status"] != "PASS":
                failures.append(f"{case_id}: derived-window path failure")
        if "query_injection_or_spoof" in (row.get("construction_tags") or []):
            result = semantics.audit_spoof_row(row, sources, chunks)
            spoof_results[case_id] = result
            if result["status"] != "PASS":
                failures.append(f"{case_id}: spoof structure failure")

    construction_report = construction.audit_material(
        sources, chunks, rows_by_suite)
    contract = json.loads(construction.CONTRACT_PATH.read_text(
        encoding="utf-8"))
    gate_report = gate.build_gate_report(
        contract, construction_report["metrics"], miniature=miniature)
    if construction_report["status"] != "PASS":
        failures.append("construction audit failed")
    if gate_report["status"] != "PASS":
        failures.append("construction gate failed")
    return {
        "artifact": "T21R12_STATIC_GOLD_AUDIT",
        "status": "PASS" if not failures else "FAIL",
        "rows": len(rows),
        "corpus": {"sources": len(sources), "chunks": len(chunks)},
        "path_results": path_results,
        "spoof_results": spoof_results,
        "construction": construction_report,
        "gate": gate_report,
        "failures": failures,
        "retrieval_windows_derived": True,
        "builder_declared_windows_authoritative": False,
        "runtime_execution_count": 0,
    }


def main() -> int:
    sources, chunks, rows = construction.load_candidate()
    report = audit_material(sources, chunks, rows)
    report["input_hashes"] = {
        "sources.jsonl": _sha(CORPUS_DIR / "sources.jsonl"),
        "chunks.jsonl": _sha(CORPUS_DIR / "chunks.jsonl"),
        **{path.parent.name: _sha(path)
           for path in sorted(SUITES_DIR.glob("*/holdout.jsonl"))},
    }
    path = OUT_DIR / "static_gold_audit.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "rows": report["rows"],
                      "failures": len(report["failures"]),
                      "runtime_execution_count": 0}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


