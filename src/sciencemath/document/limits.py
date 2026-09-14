"""T17 resource limits and parser cost classes."""
from __future__ import annotations

from dataclasses import dataclass

FREE_LOCAL = "FREE_LOCAL"
FREE_NETWORK = "FREE_NETWORK"
PAID_NETWORK = "PAID_NETWORK"
PAID_COMPUTE_GATE_REQUIRED = "PAID_COMPUTE_GATE_REQUIRED"

MAX_TEXT_BYTES = 25 * 1024 * 1024
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_CSV_BYTES = 100 * 1024 * 1024
MAX_JSON_BYTES = 50 * 1024 * 1024
MAX_HTML_BYTES = 25 * 1024 * 1024
MAX_ROWS = 100_000
MAX_BLOCKS = 20_000
MAX_JOIN_OUTPUT_ROWS = 20_000
MAX_JOIN_EXPANSION = 50
MAX_EXTRACT_FIELDS = 64
MAX_SEARCH_HITS = 50
MAX_SUMMARY_CHARS = 4_000
PARSER_VERSION = "t17-document-v1"


@dataclass(frozen=True)
class DocumentLimits:
    max_text_bytes: int = MAX_TEXT_BYTES
    max_pdf_bytes: int = MAX_PDF_BYTES
    max_csv_bytes: int = MAX_CSV_BYTES
    max_json_bytes: int = MAX_JSON_BYTES
    max_html_bytes: int = MAX_HTML_BYTES
    max_rows: int = MAX_ROWS
    max_blocks: int = MAX_BLOCKS
    max_join_output_rows: int = MAX_JOIN_OUTPUT_ROWS
    max_join_expansion: int = MAX_JOIN_EXPANSION
    max_extract_fields: int = MAX_EXTRACT_FIELDS
    max_search_hits: int = MAX_SEARCH_HITS
    max_summary_chars: int = MAX_SUMMARY_CHARS


def paid_gate(*, provider: str, estimated_cost: str, reason: str,
              free_alternative: str, expected_benefit: str) -> dict:
    return {
        "status": PAID_COMPUTE_GATE_REQUIRED,
        "provider": provider,
        "estimated_cost": estimated_cost,
        "reason": reason,
        "free_alternative": free_alternative,
        "expected_benefit": expected_benefit,
        "action": "STOP",
    }
