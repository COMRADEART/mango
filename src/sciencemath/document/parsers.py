"""Format parsers. Never invent content. Unknown stays UNKNOWN."""
from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from sciencemath.document.identify import identify_file
from sciencemath.document.injection import scan_injection, strip_instructions
from sciencemath.document.limits import PARSER_VERSION, DocumentLimits
from sciencemath.document.models import (
    PARSE_BLOCKED, PARSE_EMPTY, PARSE_MALFORMED, PARSE_NEEDS_OCR,
    PARSE_OK, PARSE_UNSUPPORTED, PARSE_WARNING, UNKNOWN, CellValue,
    ColumnSpec, Dataset, NormalizedDocument, TextBlock, content_sha,
)
from sciencemath.document.pdfparse import extract_pdf_pages
from sciencemath.document.safety import formula_like, size_allowed
from sciencemath.document import typesys

_MD_H = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_MD_OL = re.compile(r"^(\s*)\d+\.\s+(.*)$")


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[tuple[str, str]] = []
        self._skip = 0
        self._heading = None
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = tag
        if tag == "table":
            self._table = []
        if tag == "tr" and self._table is not None:
            self._row = []
        if tag in ("td", "th") and self._row is not None:
            self._cell = []
        if tag == "br":
            self.parts.append(("text", "\n"))

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = None
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        if tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
        if tag == "p":
            self.parts.append(("text", "\n"))

    def handle_data(self, data):
        if self._skip:
            return
        t = data
        if self._cell is not None:
            self._cell.append(t)
            return
        if self._heading:
            self.parts.append(("heading", t.strip()))
            if self._heading == "h1" and not self.title:
                self.title = t.strip()
            return
        if t.strip():
            self.parts.append(("text", t))


def _decode(data: bytes) -> tuple[str, str, list[str]]:
    warnings = []
    for enc in ("utf-8", "utf-8-sig"):
        try:
            return data.decode(enc), enc, warnings
        except UnicodeDecodeError:
            continue
    text = data.decode("utf-8", errors="replace")
    warnings.append("bad_utf8_replaced")
    return text, "utf-8-replace", warnings


def _blocks_from_paragraphs(doc_id: str, text: str, *, page=UNKNOWN,
                            heading_path=()) -> list[TextBlock]:
    blocks = []
    idx = 0
    pos = 0
    for para in re.split(r"\n\s*\n", text):
        raw = para.strip("\n")
        if not raw.strip():
            pos += len(para) + 2
            continue
        bid = f"{doc_id}-b{idx:04d}"
        start = text.find(raw, pos)
        if start < 0:
            start = pos
        end = start + len(raw)
        blocks.append(TextBlock(
            document_id=doc_id, block_id=bid, block_type="paragraph",
            text=raw, page=page, heading_path=heading_path,
            paragraph_index=idx, char_start=start, char_end=end,
        ))
        idx += 1
        pos = end
    return blocks


def _empty_doc(ident: dict, status: str, warnings: list[str],
               filename: str, data: bytes, parser: str) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=_doc_id(filename, data),
        filename=filename,
        file_type=ident.get("file_type") or "unknown",
        mime_type=ident.get("mime_type") or "application/octet-stream",
        content_hash=content_sha(data),
        size_bytes=len(data),
        parser_name=parser,
        parse_status=status,
        parse_warnings=warnings,
        raw_bytes=data,
        text="",
        page_count=UNKNOWN,
        sheet_count=UNKNOWN,
    )


def _doc_id(filename: str, data: bytes) -> str:
    h = content_sha(data)[:12]
    stem = Path(filename or "doc").stem[:40] or "doc"
    return f"doc-{stem}-{h}"


def parse_bytes(data: bytes, filename: str, *,
                limits: DocumentLimits | None = None) -> NormalizedDocument:
    limits = limits or DocumentLimits()
    ident = identify_file(data=data, filename=filename)
    ft = ident["file_type"]
    cap = size_allowed(len(data), ft, limits)
    if not cap["ok"]:
        return _empty_doc(ident, PARSE_BLOCKED, ["oversized"], filename, data,
                          ident.get("parser_name") or "NONE")
    if ident.get("unsupported"):
        return _empty_doc(ident, PARSE_UNSUPPORTED,
                          [ident.get("reason") or "unsupported"],
                          filename, data, "NONE")
    if ident.get("requires_ocr") and ft == "image":
        d = _empty_doc(ident, PARSE_NEEDS_OCR, ["image_only"], filename, data,
                       "NONE")
        return d
    if not data:
        d = _empty_doc(ident, PARSE_EMPTY, ["zero_byte"], filename, data,
                       ident.get("parser_name") or "NONE")
        return d
    parser = ident.get("parser_name")
    if parser == "TxtParser":
        return _parse_txt(data, filename, ident)
    if parser == "MarkdownParser":
        return _parse_md(data, filename, ident)
    if parser == "JsonParser":
        return _parse_json(data, filename, ident, limits)
    if parser == "JsonlParser":
        return _parse_jsonl(data, filename, ident, limits)
    if parser == "CsvParser":
        return _parse_csv(data, filename, ident, limits, delim=",")
    if parser == "TsvParser":
        return _parse_csv(data, filename, ident, limits, delim="\t")
    if parser == "HtmlParser":
        return _parse_html(data, filename, ident)
    if parser == "PdfParser":
        return _parse_pdf(data, filename, ident)
    if parser == "XlsxParser":
        return _parse_xlsx(data, filename, ident, limits)
    return _empty_doc(ident, PARSE_UNSUPPORTED, ["no_parser"], filename, data,
                      "NONE")


def _base(ident, filename, data, parser) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=_doc_id(filename, data),
        filename=filename,
        file_type=ident["file_type"],
        mime_type=ident["mime_type"],
        content_hash=content_sha(data),
        size_bytes=len(data),
        parser_name=parser,
        parser_version=PARSER_VERSION,
        parse_status=PARSE_OK,
        raw_bytes=data,
        encoding=UNKNOWN,
        language="en",
    )


def _parse_txt(data, filename, ident) -> NormalizedDocument:
    text, enc, warns = _decode(data)
    inj = scan_injection(text)
    doc = _base(ident, filename, data, "TxtParser")
    doc.encoding = enc
    doc.parse_warnings.extend(warns)
    if inj["detected"]:
        doc.parse_warnings.append("prompt_injection_detected")
        doc.metadata["injection"] = inj
        text_use = strip_instructions(text)
    else:
        text_use = text
    doc.text = text_use
    doc.page_count = UNKNOWN
    doc.blocks = _blocks_from_paragraphs(doc.document_id, text_use)
    if warns:
        doc.parse_status = PARSE_WARNING
    return doc


def _parse_md(data, filename, ident) -> NormalizedDocument:
    text, enc, warns = _decode(data)
    inj = scan_injection(text)
    doc = _base(ident, filename, data, "MarkdownParser")
    doc.encoding = enc
    doc.parse_warnings.extend(warns)
    if inj["detected"]:
        doc.parse_warnings.append("prompt_injection_detected")
        doc.metadata["injection"] = inj
    lines = text.splitlines()
    blocks = []
    headings: list[str] = []
    path: list[str] = []
    para = []
    idx = 0
    pos = 0
    table_rows: list[list[str]] = []

    def flush_para():
        nonlocal idx, para
        if not para:
            return
        raw = "\n".join(para).strip()
        para = []
        if not raw:
            return
        blocks.append(TextBlock(
            document_id=doc.document_id, block_id=f"{doc.document_id}-b{idx:04d}",
            block_type="paragraph", text=raw, heading_path=tuple(path),
            paragraph_index=idx,
        ))
        idx += 1

    for line in lines:
        mh = _MD_H.match(line)
        if mh:
            flush_para()
            level = len(mh.group(1))
            title = mh.group(2).strip()
            path = path[: level - 1] + [title]
            headings.append(title)
            blocks.append(TextBlock(
                document_id=doc.document_id,
                block_id=f"{doc.document_id}-h{idx:04d}",
                block_type="heading", text=title,
                heading_path=tuple(path), paragraph_index=idx,
            ))
            idx += 1
            continue
        ul = _MD_UL.match(line) or _MD_OL.match(line)
        if ul:
            flush_para()
            item = ul.group(2)
            blocks.append(TextBlock(
                document_id=doc.document_id,
                block_id=f"{doc.document_id}-l{idx:04d}",
                block_type="list_item", text=item,
                heading_path=tuple(path), paragraph_index=idx,
            ))
            idx += 1
            continue
        if re.match(r"^\s*\|.+\|\s*$", line) and not re.match(r"^\s*\|?\s*-+", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            table_rows.append(cells)
            continue
        if re.match(r"^\s*\|?\s*-+", line):
            continue
        if line.strip() == "":
            flush_para()
        else:
            para.append(line)
    flush_para()
    if table_rows:
        headers = table_rows[0]
        body = table_rows[1:]
        ds = typesys.dataset_from_rows(
            doc.document_id, "markdown_table", headers, body, filename)
        doc.tables.append(ds)
        blocks.append(TextBlock(
            document_id=doc.document_id,
            block_id=f"{doc.document_id}-t0000",
            block_type="table", text=" | ".join(headers),
            heading_path=tuple(path),
        ))
    doc.blocks = blocks
    doc.sections = headings
    doc.text = text
    doc.page_count = UNKNOWN
    if warns:
        doc.parse_status = PARSE_WARNING
    return doc


def _walk_json(value, path: str, records: list, blocks: list, doc_id: str,
               n: list[int], limits: DocumentLimits):
    if n[0] >= limits.max_blocks:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{path}.{k}" if path != "$" else f"$.{k}"
            _walk_json(v, p, records, blocks, doc_id, n, limits)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            p = f"{path}[{i}]"
            _walk_json(v, p, records, blocks, doc_id, n, limits)
    else:
        text = "" if value is None else str(value)
        bid = f"{doc_id}-j{n[0]:04d}"
        blocks.append(TextBlock(
            document_id=doc_id, block_id=bid, block_type="json_value",
            text=text, heading_path=(path,),
        ))
        records.append({
            "json_path": path, "raw_value": value,
            "missing_kind": "NULL" if value is None else "PRESENT",
        })
        n[0] += 1


def _parse_json(data, filename, ident, limits) -> NormalizedDocument:
    text, enc, warns = _decode(data)
    doc = _base(ident, filename, data, "JsonParser")
    doc.encoding = enc
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        doc.parse_status = PARSE_MALFORMED
        doc.parse_warnings.append(f"invalid_json:{e.msg}")
        doc.text = text
        return doc
    records = []
    blocks = []
    _walk_json(obj, "$", records, blocks, doc.document_id, [0], limits)
    doc.records = records
    doc.blocks = blocks
    doc.text = text
    doc.metadata["json_root_type"] = type(obj).__name__
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        keys = []
        for x in obj:
            for k in x:
                if k not in keys:
                    keys.append(k)
        rows = [[("" if r.get(k) is None and k in r else
                  (UNKNOWN if k not in r else r.get(k))) for k in keys]
                for r in obj]
        # preserve None as null
        body = []
        for r in obj:
            body.append([r[k] if k in r else "__NOT_PRESENT__" for k in keys])
        ds = typesys.dataset_from_rows(
            doc.document_id, "json_array", keys, body, filename,
            not_present_token="__NOT_PRESENT__")
        doc.tables.append(ds)
    elif isinstance(obj, dict):
        keys = list(obj.keys())
        body = [[obj[k] for k in keys]]
        ds = typesys.dataset_from_rows(
            doc.document_id, "json_object", keys, body, filename)
        doc.tables.append(ds)
    inj = scan_injection(text)
    if inj["detected"]:
        doc.parse_warnings.append("prompt_injection_detected")
        doc.metadata["injection"] = inj
    doc.parse_warnings.extend(warns)
    doc.page_count = UNKNOWN
    return doc


def _parse_jsonl(data, filename, ident, limits) -> NormalizedDocument:
    text, enc, warns = _decode(data)
    doc = _base(ident, filename, data, "JsonlParser")
    doc.encoding = enc
    rows_obj = []
    keys: list[str] = []
    malformed = 0
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            warns.append(f"bad_jsonl_line:{i+1}")
            continue
        if not isinstance(obj, dict):
            obj = {"value": obj}
        rows_obj.append(obj)
        for k in obj:
            if k not in keys:
                keys.append(k)
        if len(rows_obj) >= limits.max_rows:
            warns.append("row_limit")
            break
    body = []
    for r in rows_obj:
        body.append([r[k] if k in r else "__NOT_PRESENT__" for k in keys])
    if keys:
        ds = typesys.dataset_from_rows(
            doc.document_id, "jsonl", keys, body, filename,
            not_present_token="__NOT_PRESENT__")
        doc.tables.append(ds)
    doc.records = rows_obj
    doc.text = text
    doc.blocks = _blocks_from_paragraphs(doc.document_id, text)
    doc.parse_warnings.extend(warns)
    if malformed and not rows_obj:
        doc.parse_status = PARSE_MALFORMED
    elif malformed:
        doc.parse_status = PARSE_WARNING
    doc.page_count = UNKNOWN
    return doc


def _parse_csv(data, filename, ident, limits, delim=",") -> NormalizedDocument:
    text, enc, warns = _decode(data)
    inj = scan_injection(text)
    parser_name = "CsvParser" if delim == "," else "TsvParser"
    doc = _base(ident, filename, data, parser_name)
    doc.encoding = enc
    if inj["detected"]:
        doc.parse_warnings.append("prompt_injection_detected")
        doc.metadata["injection"] = inj
    f = io.StringIO(text)
    try:
        reader = csv.reader(f, delimiter=delim)
        all_rows = []
        for i, row in enumerate(reader):
            all_rows.append(row)
            if i + 1 >= limits.max_rows + 1:
                warns.append("row_limit")
                break
    except csv.Error as e:
        doc.parse_status = PARSE_MALFORMED
        doc.parse_warnings.append(f"csv_error:{e}")
        doc.text = text
        return doc
    if not all_rows:
        doc.parse_status = PARSE_EMPTY
        doc.parse_warnings.append("no_rows")
        doc.text = text
        return doc
    headers = [h if h != "" else f"UNNAMED_{i}" for i, h in enumerate(all_rows[0])]
    seen = {}
    dup = False
    fixed = []
    for h in headers:
        if h in seen:
            seen[h] += 1
            fixed.append(f"{h}_{seen[h]}")
            dup = True
        else:
            seen[h] = 1
            fixed.append(h)
    if dup:
        warns.append("duplicate_headers")
    body = all_rows[1:]
    widths = {len(r) for r in all_rows}
    if len(widths) > 1:
        warns.append("ragged_csv")
        n = len(fixed)
        padded = []
        for r in body:
            if len(r) < n:
                padded.append(r + ["__NOT_PRESENT__"] * (n - len(r)))
            else:
                padded.append(r[:n])
        body = padded
    ds = typesys.dataset_from_rows(
        doc.document_id, Path(filename).stem or "table", fixed, body, filename,
        not_present_token="__NOT_PRESENT__", original_headers=all_rows[0])
    if dup:
        ds.warnings.append("duplicate_headers")
    doc.tables.append(ds)
    doc.text = text
    doc.blocks = _blocks_from_paragraphs(doc.document_id, text)
    doc.parse_warnings.extend(warns)
    if warns:
        doc.parse_status = PARSE_WARNING
    doc.page_count = UNKNOWN
    doc.sheet_count = 1
    return doc


def _parse_html(data, filename, ident) -> NormalizedDocument:
    text, enc, warns = _decode(data)
    inj = scan_injection(text)
    doc = _base(ident, filename, data, "HtmlParser")
    doc.encoding = enc
    if inj["detected"]:
        doc.parse_warnings.append("prompt_injection_detected")
        doc.metadata["injection"] = inj
    p = _HTMLText()
    try:
        p.feed(text)
        p.close()
    except Exception as e:  # noqa: BLE001
        doc.parse_status = PARSE_MALFORMED
        doc.parse_warnings.append(f"html_error:{e}")
        doc.text = text
        return doc
    blocks = []
    path: list[str] = []
    idx = 0
    buf = []
    for kind, t in p.parts:
        if kind == "heading":
            if buf:
                raw = "".join(buf).strip()
                if raw:
                    blocks.append(TextBlock(
                        document_id=doc.document_id,
                        block_id=f"{doc.document_id}-b{idx:04d}",
                        block_type="paragraph", text=raw,
                        heading_path=tuple(path), paragraph_index=idx,
                    ))
                    idx += 1
                buf = []
            path = [t]
            doc.sections.append(t)
            blocks.append(TextBlock(
                document_id=doc.document_id,
                block_id=f"{doc.document_id}-h{idx:04d}",
                block_type="heading", text=t, heading_path=tuple(path),
            ))
            idx += 1
        else:
            buf.append(t)
    if buf:
        raw = re.sub(r"[ \t]+", " ", "".join(buf)).strip()
        if raw:
            blocks.append(TextBlock(
                document_id=doc.document_id,
                block_id=f"{doc.document_id}-b{idx:04d}",
                block_type="paragraph", text=raw,
                heading_path=tuple(path), paragraph_index=idx,
            ))
    doc.blocks = blocks
    plain = "\n".join(b.text for b in blocks)
    doc.text = plain
    for ti, table in enumerate(p.tables):
        if not table:
            continue
        headers = table[0]
        body = table[1:] if len(table) > 1 else []
        ds = typesys.dataset_from_rows(
            doc.document_id, f"html_table_{ti}", headers, body, filename)
        doc.tables.append(ds)
    doc.parse_warnings.extend(warns)
    doc.page_count = UNKNOWN
    return doc


def _parse_pdf(data, filename, ident) -> NormalizedDocument:
    extracted = extract_pdf_pages(data)
    doc = _base(ident, filename, data, "PdfParser")
    doc.parse_status = extracted["status"]
    doc.parse_warnings.extend(extracted["warnings"])
    doc.page_count = extracted["page_count"]
    doc.text = extracted.get("text") or ""
    inj = scan_injection(doc.text)
    if inj["detected"]:
        doc.parse_warnings.append("prompt_injection_detected")
        doc.metadata["injection"] = inj
        doc.text = strip_instructions(doc.text)
    blocks = []
    for pi, page in enumerate(extracted["pages"], start=1):
        for b in _blocks_from_paragraphs(doc.document_id, page, page=str(pi)):
            b.page = str(pi)
            b.block_id = f"{doc.document_id}-p{pi}-b{len(blocks):04d}"
            blocks.append(b)
        if page.strip():
            doc.sections.append(f"page_{pi}")
    doc.blocks = blocks
    if extracted["needs_ocr"]:
        doc.parse_status = PARSE_NEEDS_OCR
        doc.metadata["ocr"] = "DOC_NEEDS_OCR"
    return doc


def _parse_xlsx(data, filename, ident, limits) -> NormalizedDocument:
    """Optional: only if openpyxl is already importable. Never fake cells."""
    doc = _base(ident, filename, data, "XlsxParser")
    try:
        import openpyxl  # noqa: WPS433
        from io import BytesIO
        wb = openpyxl.load_workbook(BytesIO(data), data_only=True, read_only=True)
    except ImportError:
        doc.parse_status = PARSE_UNSUPPORTED
        doc.parse_warnings.append("xlsx_optional_unavailable")
        return doc
    except Exception as e:  # noqa: BLE001
        doc.parse_status = PARSE_MALFORMED
        doc.parse_warnings.append(f"xlsx_error:{e}")
        return doc
    doc.sheet_count = len(wb.sheetnames)
    for si, name in enumerate(wb.sheetnames):
        ws = wb[name]
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            rows.append(["" if c is None else c for c in row])
            if i >= limits.max_rows:
                doc.parse_warnings.append("row_limit")
                break
        if not rows:
            continue
        headers = [str(h) if h != "" else f"UNNAMED_{j}"
                   for j, h in enumerate(rows[0])]
        ds = typesys.dataset_from_rows(
            doc.document_id, name, headers, rows[1:], filename)
        doc.tables.append(ds)
    doc.page_count = UNKNOWN
    return doc
