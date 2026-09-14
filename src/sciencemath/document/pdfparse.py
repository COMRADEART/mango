"""Local PDF text extraction. No OCR. Image-only → NEEDS_OCR.

Fixtures are generated with this writer so extraction is exact.
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path

from sciencemath.document.models import PARSE_MALFORMED, PARSE_NEEDS_OCR, PARSE_OK


def write_text_pdf(pages: list[str], *, title: str = "fixture") -> bytes:
    """Write a simple uncompressed text PDF (one content stream per page)."""
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    # placeholders; we rebuild with offsets
    font_id = 0
    page_ids: list[int] = []
    content_ids: list[int] = []
    kids: list[int] = []

    # We'll construct in order: catalog, pages, font, then page/content pairs
    # Simpler: sequential objects
    # 1 catalog, 2 pages, 3 font, then (page, content)*
    n = max(1, len(pages))
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    # pages object built later
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    page_objs = []
    content_objs = []
    for i, text in enumerate(pages or [""]):
        lines = (text or "").split("\n")
        cmds = ["BT", "/F1 12 Tf", "72 720 Td"]
        for j, line in enumerate(lines[:80]):
            esc = (line.replace("\\", "\\\\").replace("(", "\\(")
                   .replace(")", "\\)"))[:200]
            if j:
                cmds.append("0 -16 Td")
            cmds.append(f"({esc}) Tj")
        cmds.append("ET")
        stream = "\n".join(cmds).encode("latin-1", errors="replace")
        content_objs.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream")
        page_objs.append(None)  # filled after ids known

    # object numbers:
    # 1 catalog, 2 pages, 3 font, then for i: page=4+2i, content=5+2i
    font_n = 3
    kids_refs = []
    body_parts = []
    for i in range(n):
        page_n = 4 + 2 * i
        content_n = 5 + 2 * i
        kids_refs.append(f"{page_n} 0 R")
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_n} 0 R /Resources << /Font << /F1 {font_n} 0 R >> >> >>"
        ).encode()
        body_parts.append((page_n, page))
        body_parts.append((content_n, content_objs[i]))

    pages_obj = (
        f"<< /Type /Pages /Kids [{' '.join(kids_refs)}] /Count {n} >>"
    ).encode()

    ordered = [(1, catalog), (2, pages_obj), (3, font)] + body_parts
    ordered.sort()
    out = [b"%PDF-1.4\n"]
    offsets = [0]
    pos = len(out[0])
    for num, payload in ordered:
        header = f"{num} 0 obj\n".encode()
        block = header + payload + b"\nendobj\n"
        offsets.append(pos)
        out.append(block)
        pos += len(block)
    xref_pos = pos
    xref = [f"xref\n0 {len(ordered)+1}\n", "0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n")
    trailer = (
        f"trailer\n<< /Size {len(ordered)+1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    )
    return b"".join(out) + "".join(xref).encode() + trailer.encode()


def write_image_only_pdf() -> bytes:
    """Page with a filled rectangle and no text operators."""
    stream = b"200 200 100 100 re f"
    content = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    catalog = b"<< /Type /Catalog /Pages 2 0 R >>"
    pages = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    page = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>")
    # tiny fake image xobject (not a real bitmap; parser only checks /Subtype /Image)
    img = b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\nstream\n\x00\nendstream"
    parts = [(1, catalog), (2, pages), (3, page), (4, content), (5, img)]
    out = [b"%PDF-1.4\n"]
    offsets = [0]
    pos = len(out[0])
    for num, payload in parts:
        header = f"{num} 0 obj\n".encode()
        block = header + payload + b"\nendobj\n"
        offsets.append(pos)
        out.append(block)
        pos += len(block)
    xref_pos = pos
    xref = [f"xref\n0 {len(parts)+1}\n", "0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n")
    trailer = (
        f"trailer\n<< /Size {len(parts)+1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    )
    return b"".join(out) + "".join(xref).encode() + trailer.encode()


_TJstr = re.compile(r"\((?:\\.|[^\\)])*\)")
_TJhex = re.compile(r"<([0-9A-Fa-f]+)>")


def _unescape_pdf_literal(s: str) -> str:
    s = s[1:-1]
    s = s.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
    s = s.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
    return s


def _decode_stream(raw: bytes, filters: list[str]) -> bytes:
    data = raw
    for f in filters:
        if f in ("/FlateDecode", "FlateDecode"):
            try:
                data = zlib.decompress(data)
            except zlib.error:
                return raw
    return data


def extract_pdf_pages(data: bytes) -> dict:
    """Return {status, pages: list[str], warnings, page_count, needs_ocr}."""
    warnings: list[str] = []
    if not data.startswith(b"%PDF"):
        return {"status": PARSE_MALFORMED, "pages": [], "warnings": ["not_pdf"],
                "page_count": 0, "needs_ocr": False}
    truncated = b"%%EOF" not in data[-1024:]
    if truncated:
        warnings.append("truncated_pdf")
    has_image = b"/Subtype /Image" in data or b"/Subtype/Image" in data
    # split content streams
    streams = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        streams.append(m.group(1))
    pages_text: list[str] = []
    # decode each stream independently; page order ≈ stream order
    for st in streams:
        decoded = st
        if decoded.startswith(b"x\x9c") or decoded.startswith(b"x\x01") or decoded.startswith(b"x\xda"):
            try:
                decoded = zlib.decompress(st)
            except zlib.error:
                pass
        try:
            textish = decoded.decode("latin-1", errors="replace")
        except Exception:
            textish = ""
        chunks = []
        for lit in _TJstr.findall(textish):
            chunks.append(_unescape_pdf_literal(lit))
        for hx in _TJhex.findall(textish):
            try:
                raw = bytes.fromhex(hx)
                if raw.startswith(b"\xfe\xff"):
                    chunks.append(raw[2:].decode("utf-16-be", errors="replace"))
                else:
                    chunks.append(raw.decode("latin-1", errors="replace"))
            except ValueError:
                continue
        joined = "\n".join(c for c in chunks if c)
        # skip the fake image stream (binary)
        if joined.strip():
            pages_text.append(joined)
    text_len = sum(len(p.strip()) for p in pages_text)
    needs_ocr = text_len == 0 and has_image
    status = PARSE_NEEDS_OCR if needs_ocr else (
        PARSE_MALFORMED if truncated and text_len == 0 else PARSE_OK)
    if truncated and text_len > 0:
        status = PARSE_OK
        warnings.append("truncated_but_text_extracted")
    page_count = max(len(pages_text), data.count(b"/Type /Page"), 1 if data else 0)
    if needs_ocr:
        page_count = max(1, data.count(b"/Type /Page"))
        pages_text = []
    if not pages_text and not needs_ocr and not truncated:
        page_count = max(1, data.count(b"/Type /Page"))
        pages_text = [""] * page_count
    return {
        "status": status,
        "pages": pages_text,
        "warnings": warnings,
        "page_count": page_count if pages_text or needs_ocr else 0,
        "needs_ocr": needs_ocr,
        "text": "\n\n".join(pages_text),
    }


def write_pdf_file(path: Path, pages: list[str], *, title: str = "fixture") -> Path:
    path.write_bytes(write_text_pdf(pages, title=title))
    return path
