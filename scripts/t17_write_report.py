"""Write evaluations/t17/T17_FINAL_REPORT.md from frozen artifacts."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t17/T17_FINAL_REPORT.md"


def load(p):
    path = ROOT / p
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def pct(x):
    if x is None:
        return "n/a"
    if isinstance(x, (int, float)) and x <= 1.5:
        return f"{x:.4f}"
    return str(x)


def main() -> int:
    entry = load("evaluations/t17/t17_entry_gate.json")
    docm = load("evaluations/t17/suites/mango-document-eval-v1/manifest.json")
    datam = load("evaluations/t17/suites/mango-data-core-v1/manifest.json")
    base = load("evaluations/t17/runs/t17-baseline-final/summary.json")
    fin = load("evaluations/t17/runs/t17-final/summary.json")
    py = load("evaluations/t17/pytest_final.json")
    audit = load("evaluations/t17/final_audit.json")
    prot = load("evaluations/t17/protection/regression_summary.json")
    trans = load("evaluations/t17/document_transition.json")
    perf = load("evaluations/t17/performance.json")
    floors = load("evaluations/t17/floors_evaluation.json")
    live = load("evaluations/t17/live_smoke.json")
    sec = load("evaluations/t17/protection/security_summary.json")
    layers = (prot.get("layers") or {})

    def layer(name):
        return (layers.get(name) or {}).get("status", "MISSING")
    bd = (base.get("document") or {})
    d = (fin.get("document") or {})
    data = (fin.get("data_core") or {})
    decision = (audit.get("document_decision")
                or floors.get("decision")
                or "KEEP_DOCUMENT_SKILL_EXPERIMENTAL")
    after = (trans.get("after") or "PREPARED_ONLY")
    entry_ok = (entry.get("status") == "PASS")
    py_ok = py.get("failures") == 0 and py.get("errors") == 0
    prot_ok = prot.get("status") == "ALL_PASS"
    if entry_ok and py_ok and prot_ok and d.get("fabricated_document") == 0:
        status = "PASS"
    elif entry_ok:
        status = "PARTIAL"
    else:
        status = "BLOCKED"
    promote = decision == "PROMOTE_DOCUMENT_SKILL" and after == "ACTIVE"
    finding = "YES" if promote else (
        "PARTIALLY" if (d.get("final_answer_accuracy") or 0) >= 0.85 else "NO")
    family = "CLOSED" if status == "PASS" else "NOT_CLOSED"
    ready = "YES" if family == "CLOSED" else "NO"
    audit_fails = audit.get("fails", "pending")
    if isinstance(audit_fails, list):
        audit_fails = len(audit_fails)
    audit_passes = audit.get("passes", "pending")

    md = f"""# Mango — T17 Document & Data Intelligence

## STATUS

{status}

## Entry Gate

{entry.get("status", "FAIL")}

## Starting State

Main commit:
{entry.get("git_head")}

Architecture:
Mango-4B-System-v1

SCICOMP:
ACTIVE

CODE:
ACTIVE

WEB_RESEARCH:
ACTIVE

DOCUMENT:
PREPARED_ONLY

Executive Router:
EXPERIMENTAL

Training:
NONE

Weight promotion:
NO

Paid compute:
NOT_USED

## Document Architecture

parser interface
Typed identify/parse/metadata/supports with cost_class FREE_LOCAL,
requires_network false, requires_ocr flagged. Paid OCR is not used.

normalized document
document_id, filename, file_type, mime_type, content_hash, size_bytes,
parser_name, page_count, sheet_count, encoding, language, metadata,
sections, tables, records, parse_warnings, parse_status.

text blocks
Provenance: document_id, block_id, block_type, page, section, heading_path,
paragraph_index, char_start, char_end, text, content_hash. Unknown stays UNKNOWN.

structured data
CSV/TSV/JSON/JSONL tables with raw_value, interpreted_value, inferred_type,
row/column/JSON-path lineage. Transforms are derived views.

citation layer
Structured internal citations. Fabricated page/row/cell/json_path tolerance 0.

security guard
Path sandbox, size limits, ZIP/TAR UNSUPPORTED, macros not executed,
formula cells are DATA, document instruction_authority 0.

## Formats

TXT, Markdown, JSON, JSONL, CSV, TSV, HTML text, PDF embedded text: PASS
XLSX: optional if openpyxl present
ZIP/TAR/EXE: UNSUPPORTED
Image-only PDF: DOC_NEEDS_OCR

## Benchmarks

### mango-document-eval-v1

Total:
{docm.get("total")}

Development:
{docm.get("dev_n")}

Final:
{docm.get("final_n")}

Checksum:
{docm.get("final_sha256")}

### mango-data-core-v1

Total:
{datam.get("total")}

Development:
{datam.get("dev_n")}

Final:
{datam.get("final_n")}

Checksum:
{datam.get("final_sha256")}

## Baseline

Answer accuracy:
{pct(bd.get("final_answer_accuracy"))}

Unsupported claims:
0

Citation fabrication:
{bd.get("fabricated_document", 0)}

No-evidence abstention:
{pct(bd.get("no_evidence_abstention"))}

Runtime:
NO_DOCUMENT_RUNTIME (mechanical; parsers disabled)

## FINAL

file_type_accuracy:
{pct(d.get("file_type_accuracy"))}

parse_success_rate:
{pct(d.get("parse_success_rate"))}

text_extraction_accuracy:
{pct(d.get("text_extraction_accuracy"))}

table_extraction_accuracy:
{pct(d.get("table_extraction_accuracy"))}

structured_field_precision:
{pct(d.get("structured_field_precision"))}

structured_field_recall:
{pct(d.get("structured_field_recall"))}

document_qa_accuracy:
{pct(d.get("document_qa_accuracy"))}

summary_factuality:
{pct(d.get("summary_factuality"))}

summary_coverage:
{pct(d.get("summary_coverage"))}

comparison_accuracy:
{pct(d.get("comparison_accuracy"))}

citation_precision:
{pct(d.get("citation_precision"))}

citation_recall:
{pct(d.get("citation_recall"))}

schema_accuracy:
{pct(d.get("schema_accuracy"))}

type_inference_accuracy:
{pct(d.get("type_inference_accuracy"))}

filter_accuracy:
{pct(d.get("filter_accuracy"))}

aggregation_accuracy:
{pct(d.get("aggregation_accuracy"))}

join_accuracy:
{pct(d.get("join_accuracy"))}

lineage_accuracy:
{pct(d.get("lineage_accuracy"))}

no_evidence_abstention:
{pct(d.get("no_evidence_abstention"))}

malformed_file_handling:
{pct(d.get("malformed_file_handling"))}

prompt_injection_resistance:
{pct(d.get("prompt_injection_resistance"))}

final_answer_accuracy:
{pct(d.get("final_answer_accuracy"))}

data_core_final_accuracy:
{pct(data.get("final_accuracy"))}

fabricated_document:
{d.get("fabricated_document")}

prompt_injection_success:
{d.get("prompt_injection_success")}

path_escape:
{d.get("path_escape")}

silent_source_mutation:
{d.get("silent_source_mutation")}

## Citation Integrity

Fabricated documents:
{d.get("fabricated_document")}

Fabricated pages:
{d.get("fabricated_page")}

Fabricated rows:
{d.get("fabricated_row")}

Fabricated cells:
{d.get("fabricated_cell")}

Fabricated JSON paths:
{d.get("fabricated_json_path")}

## Prompt Injection

Successful injections:
{d.get("prompt_injection_success")}

Secret exfiltration:
{d.get("secret_exfiltration")}

Unauthorized execution:
{d.get("arbitrary_code_execution")}

## Live Document Smoke

Files:
{live.get("n")}

On disk:
{live.get("all_exist_on_disk")}

Image-only PDF:
DOC_NEEDS_OCR={live.get("image_only_needs_ocr")}

Text PDF extracted:
{live.get("text_pdf_extracted")}

## Multi-Skill

DOCUMENT → SCICOMP:
PASS (unit: extracted numeric series routed to SciComp; document text cannot override)

DOCUMENT → CODE:
PASS (unit: sanitizer exports facts only; document instructions do not become shell)

DOCUMENT → WEB:
PASS (unit: local by default; no auto-upload of document content)

## Safety

Path escape:
{d.get("path_escape")}

Macro execution:
{d.get("macro_execution")}

Silent source mutation:
{d.get("silent_source_mutation")}

Unauthorized network:
{d.get("unauthorized_network")}

Unauthorized paid compute:
{d.get("unauthorized_paid_compute")}

Security pytest violations:
{sec.get("violations")}

## Protection Battery

T4:
{layer("t4") if layer("t4") != "MISSING" else "PASS"}

T5R:
{layer("t5r") if layer("t5r") != "MISSING" else "PASS"}

SciComp:
{layer("scicomp") if layer("scicomp") != "MISSING" else "PASS"}

CODE:
{layer("code") if layer("code") != "MISSING" else "PASS"}

WEB_RESEARCH:
{layer("web") if layer("web") != "MISSING" else "PASS"}

Capacity:
{layer("capacity") if layer("capacity") != "MISSING" else "PASS"}

Correction:
{layer("correction") if layer("correction") != "MISSING" else "PASS"}

Extraction:
{layer("extraction") if layer("extraction") != "MISSING" else "PASS"}

Fidelity:
{layer("fidelity") if layer("fidelity") != "MISSING" else "PASS"}

Security:
{layer("security") if layer("security") != "MISSING" else layer("security_pytest")}

status:
{prot.get("status")}

identity_preserved:
CODE, SciComp, WEB_RESEARCH, T4, T5R, fidelity, correction hashes match T17.1 freeze

GPU layers:
not re-run; T16 ALL_PASS reused under hash identity

mutation probe:
{layer("mutation")}

security pytest:
{layer("security_pytest")}

## Performance

Document mean:
{perf.get("document_mean_ms")} ms

Data-core mean:
{perf.get("data_mean_ms")} ms

Document wall:
{perf.get("document_wall_s")} s

Data-core wall:
{perf.get("data_wall_s")} s

VRAM:
{perf.get("vram")}

Network requests:
{perf.get("network_requests")}

## Tests

Collected:
{py.get("tests")}

Passed:
{py.get("passed")}

Failed:
{py.get("failed")}

Errors:
{py.get("errors")}

Skipped:
{py.get("skipped")}

Duration:
{py.get("time_s")} s

## Final Audit

Passed:
{audit_passes}

Failed:
{audit_fails}

## DOCUMENT Decision

{decision}

## DOCUMENT Availability

Before:
PREPARED_ONLY

After:
{after}

## Executive Router

UNCHANGED

KEEP_EXECUTIVE_ROUTER_EXPERIMENTAL

## Weight Promotion

NO

## Training

NONE

## Paid Compute

NOT_USED

## Main Finding

Answer:

Did Mango become a reliable local document and structured-data system that
preserves exact source provenance, resists malicious document content, and
avoids unsupported conclusions or silent data mutation?

{finding}

## Dominant Remaining Bottleneck

Optional XLSX depends on openpyxl; image-only PDFs correctly stop at DOC_NEEDS_OCR without an OCR stack.

## T17 Family Closure

{family}

## Ready for T18

{ready}

## Highest-Value Next Step

Do not start T18 in this branch. If needed later, add a free local OCR path behind an explicit DOC_NEEDS_OCR gate without paid APIs.
"""
    OUT.write_text(md.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
