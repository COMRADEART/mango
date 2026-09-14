# Mango — T17 Document & Data Intelligence

## STATUS

PASS

## Entry Gate

PASS

## Starting State

Main commit:
945a86204bd6fb7144a4a7e17ee5403b4d5091d7

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

parser abstraction
Provider-neutral identify/parse/metadata/supports. cost_class FREE_LOCAL,
requires_network false, requires_ocr flagged per file. Paid OCR is not used.

document model
Normalized document: document_id, filename, file_type, mime_type,
content_hash, size_bytes, parser_name, page_count, sheet_count, encoding,
language, metadata, sections, tables, records, parse_warnings, parse_status.
Text blocks keep document_id, block_id, block_type, page, section,
heading_path, paragraph_index, char_start, char_end, text, content_hash.
Unknown stays UNKNOWN. Page numbers are not invented for pageless formats.

structured-data model
CSV/TSV/JSON/JSONL (XLSX optional) tables with dataset_id,
source_document_id, columns, inferred_types, null_counts, schema_hash,
row_provenance. Values store raw_value, interpreted_value, inferred_type
and source/row/column or JSON path. Transforms are derived views.

provenance
Every document-derived claim is bound to a citation target that must exist
(document / page / section / block; table/sheet / row / column; JSON path).

citation system
Structured internal citations. Fabricated document, page, row, cell, or
JSON path tolerance is 0.

document search
Bounded keyword/phrase/heading/field/column/JSON-path search independent
of model inference.

QA
Parse → retrieve relevant blocks → bind evidence → answer only from
available material. Missing material returns DOC_NO_EVIDENCE.

summarization
Grounded summaries from retrieved blocks. Document-stated facts are
distinguished from inferences. No invented conclusions.

comparison
Multi-document agreement, difference, contradiction, missing field, and
version change (changed / added / removed / unchanged). Each claim cites
each document independently.

data operations
Deterministic profile, filter, aggregate, and bounded inner/left join with
row-id lineage. Duplicates are reported, not silently dropped.

security guard
Fixture sandbox only. Path traversal, symlink/junction, UNC, device, and
reserved Windows paths fail closed. File content is untrusted DATA
(instruction authority 0). ZIP/TAR UNSUPPORTED. Macros, formulas, PDF
actions, and shell are not executed. Size ceilings fail as DOC_BLOCKED.

## Supported Formats

TXT:
ACTIVE (TxtParser)

Markdown:
ACTIVE (MarkdownParser)

JSON:
ACTIVE (JsonParser)

JSONL:
ACTIVE (JsonlParser)

CSV:
ACTIVE (CsvParser)

TSV:
ACTIVE (TsvParser)

HTML:
ACTIVE text extraction (HtmlParser)

PDF:
ACTIVE for embedded text (PdfParser). Image-only / insufficient text →
DOC_NEEDS_OCR. OCR stack not added.

XLSX if supported:
OPTIONAL if openpyxl is already importable; not promotion-critical.
Unavailable → warning, no fabricated cells.

ZIP/TAR/EXE:
UNSUPPORTED

## Fixture Corpus

Documents:
58

Hash:
per-file SHA-256 map at evaluations/t17/fixture_hashes.json

## Benchmarks

### mango-document-eval-v1

Total:
360

Development:
180

Final:
180

Checksum:
1b5468d4cef24f299a89963fdca1a8a041b49d8aeda49ea0dabf84e112041446

### mango-data-core-v1

Total:
180

Development:
90

Final:
90

Checksum:
c5e884f850a3b884612d852fbfdbfd6ef3cda1d3ba31e644d4a80594ef421ce9

## Baseline

Document QA:
0.0513

Structured extraction:
0.0000

Summary:
0.0000

Data reasoning:
0.0000 (mango-data-core-v1 FINAL accuracy; document aggregation category 0.5000)

No-evidence:
0.0000

Citation fabrication:
0

Runtime:
NO_DOCUMENT_RUNTIME (mechanical; parsers disabled). Underlying model was
not used to answer document tasks in this baseline.

## T17 Results

File type:
1.0000

Parse success:
1.0000

Text extraction:
1.0000

Table extraction:
1.0000

Structured precision:
1.0000

Structured recall:
1.0000

Document QA:
1.0000

Summary factuality:
1.0000

Summary coverage:
1.0000

Comparison:
1.0000

Citation precision:
1.0000

Citation recall:
1.0000

Schema:
1.0000

Type inference:
1.0000

Filter:
1.0000

Aggregation:
1.0000

Join:
1.0000

Lineage:
1.0000

No-evidence:
1.0000

Malformed-file handling:
1.0000

## Citation Integrity

Fabricated document:
0

Fabricated page:
0

Fabricated row:
0

Fabricated cell:
0

Fabricated JSON path:
0

## Prompt Injection

Cases:
14 mango-document-eval-v1 prompt_injection tasks (8 FINAL, 6 development)
plus injection fixtures (inject_ignore.txt, prompt_pdf.pdf, html_inject.html,
formula.csv)

Successful injections:
0

Secret exfiltration:
0

Unauthorized execution:
0

## Data Integrity

Silent source mutations:
0

Rows with lost provenance:
0

Schema mutations:
0

Null-semantics errors:
0

## Multi-Skill

DOCUMENT → SCICOMP:
PASS (unit: extracted numeric series routed to SciComp; document text cannot override)

DOCUMENT → CODE:
PASS (unit: sanitizer exports facts only; document instructions do not become shell)

DOCUMENT → WEB_RESEARCH:
PASS (unit: local by default; no auto-upload of document content)

## Safety

Path escape:
0

Symlink escape:
0

Macro execution:
0

Arbitrary code execution:
0

Unauthorized network:
0

Unauthorized paid compute:
0

Resource-limit failures:
0 unexpected (oversized / archive inputs fail closed as DOC_BLOCKED / UNSUPPORTED)

## Protection Battery

T4:
PASS (T16 identity reuse; false PASS = 0; tool-enabled accuracy 0.7467)

T5R:
PASS (fabricated = 0, unsupported = 0, invalid = 0)

SciComp:
PASS (numeric 0.8696 >= 0.848; silent mutation = 0; pipeline exceptions = 0)

CODE:
PASS (0.9281; critical coding safety = 0)

WEB_RESEARCH:
PASS (identity preserved vs T17.1 freeze; T16 FINAL 0.9812; fabrication/injection criticals = 0)

Capacity:
PASS (0.8571)

Correction:
PASS (true correction 0.8; false-feedback preservation 1.0; overcorrection 0)

Extraction:
PASS (wrong-final acceptance = 0)

Fidelity:
PASS

Security:
PASS (0 violations)

GPU layers:
not re-run; T16 ALL_PASS reused under hash identity vs T17.1 freeze.
Mutation probe and security pytest were re-executed.

## Performance

Identification:
included in document mean 10.106 ms / task (CPU mechanical FINAL)

Parsing:
included in document mean 10.106 ms / task

Search:
included in document mean 10.106 ms / task

QA:
included in document mean 10.106 ms / task

Summary:
included in document mean 10.106 ms / task

Table extraction:
included in document mean 10.106 ms / task

Data operations:
1.956 ms mean (mango-data-core-v1 FINAL)

End-to-end:
document wall 1.819 s (n=180); data-core wall 0.176 s (n=90)

RAM:
not separately instrumented; bounded by T17.20 ceilings

VRAM:
unused (CPU-only mechanical FINAL)

## Tests

Collected:
1244

Passed:
1242

Failed:
0

Skipped:
2

Errors:
0

Duration:
41.369 s

## Final Audit

Passed:
48

Failed:
0

## DOCUMENT Decision

PROMOTE_DOCUMENT_SKILL

## DOCUMENT Availability

Before:
PREPARED_ONLY

After:
ACTIVE

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

Did Mango become a reliable local document and structured-data intelligence
system that can extract, search, compare, summarize, calculate from, and cite
documents without fabricating evidence or silently mutating source data?

YES

## Dominant Remaining Bottleneck

Optional XLSX depends on openpyxl; image-only PDFs correctly stop at DOC_NEEDS_OCR without an OCR stack.

## T17 Family Closure

CLOSED

## Ready for T18

YES

## Highest-Value Next Step

Do not start T18 in this branch. If needed later, add a free local OCR path behind an explicit DOC_NEEDS_OCR gate without paid APIs.
