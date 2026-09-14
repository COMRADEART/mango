"""Parse real on-disk fixture files (not in-memory records)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.document.corpus import sandbox_roots, supplied_path
from sciencemath.document.pipeline import ingest_path
from sciencemath.document.safety import resolve_supplied

FILES = [
    "sci_helium.txt",
    "policy_retention.md",
    "finance_q2.csv",
    "ids_leading_zero.tsv",
    "api_widgets.json",
    "research_efficacy.jsonl",
    "tech_config.html",
    "planck.pdf",
    "image_only.pdf",
    "nested.json",
]


def main() -> int:
    sb = sandbox_roots()
    rows = []
    for name in FILES:
        p = supplied_path(name)
        gate = resolve_supplied(p, sandbox_roots=sb)
        exists = Path(p).is_file()
        doc = ingest_path(p, sandbox_roots=sb)
        rows.append({
            "filename": name,
            "path": str(p),
            "exists_on_disk": exists,
            "path_ok": bool(gate.get("ok")),
            "file_type": doc.file_type,
            "parse_status": doc.parse_status,
            "parser_name": doc.parser_name,
            "size_bytes": doc.size_bytes,
            "page_count": doc.page_count,
            "content_hash": doc.content_hash,
            "text_chars": len(doc.text or ""),
        })
    ok = all(r["exists_on_disk"] and r["path_ok"] for r in rows)
    image = next(r for r in rows if r["filename"] == "image_only.pdf")
    text_pdf = next(r for r in rows if r["filename"] == "planck.pdf")
    image_ok = image["parse_status"] in ("NEEDS_OCR", "DOC_NEEDS_OCR") or \
        image["parse_status"] == "NEEDS_OCR"
    from sciencemath.document.models import PARSE_NEEDS_OCR
    image_ok = image["parse_status"] == PARSE_NEEDS_OCR
    text_ok = text_pdf["parse_status"] in ("OK", "WARNING") and text_pdf["text_chars"] > 0
    out = {
        "milestone": "T17 live fixture smoke",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "n": len(rows),
        "all_exist_on_disk": ok,
        "image_only_needs_ocr": image_ok,
        "text_pdf_extracted": text_ok,
        "passed": ok and image_ok and text_ok,
        "files": rows,
        "note": "These are real sandbox files, not in-memory records.",
    }
    dest = ROOT / "evaluations/t17/live_smoke.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "passed", "all_exist_on_disk", "image_only_needs_ocr",
        "text_pdf_extracted", "n")}, indent=2))
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
