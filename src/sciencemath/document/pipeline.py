"""DOCUMENT pipeline: identify → sandbox → parse → operate → cite."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from sciencemath.document.cache import DocumentCache
from sciencemath.document.citations import fabrication_counts
from sciencemath.document.contract import (
    DOC_AGGREGATE, DOC_BLOCKED, DOC_CITATION, DOC_COMPARE, DOC_EXTRACT,
    DOC_FILTER_DATA, DOC_IDENTIFY, DOC_INGEST, DOC_INSPECT, DOC_JOIN,
    DOC_NEEDS_OCR, DOC_NO_EVIDENCE, DOC_PROFILE_DATA, DOC_QA, DOC_SCHEMA,
    DOC_SEARCH, DOC_SUMMARIZE, DOC_TABLE_EXTRACT, DOC_UNSUPPORTED,
    classify_request,
)
from sciencemath.document.dataops import (
    aggregate_dataset, filter_dataset, join_datasets, profile_dataset,
)
from sciencemath.document.identify import identify_file
from sciencemath.document.injection import scan_injection
from sciencemath.document.limits import PARSER_VERSION, DocumentLimits
from sciencemath.document.models import PARSE_NEEDS_OCR, NormalizedDocument
from sciencemath.document.ops import (
    compare_docs, extract_fields, extract_tables, qa, summarize, version_diff,
)
from sciencemath.document.parsers import parse_bytes
from sciencemath.document.safety import archive_or_macro, resolve_supplied
from sciencemath.document.search import search_document


@dataclass
class DocumentResult:
    op: str
    status: str
    answer: str
    documents: list
    citations: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    latency_ms: dict = field(default_factory=dict)
    injection_detected: bool = False
    paid_gate: dict | None = None
    fabrication: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "status": self.status,
            "answer": self.answer,
            "documents": [d.to_dict() if hasattr(d, "to_dict") else d
                          for d in self.documents],
            "citations": self.citations,
            "tables": self.tables,
            "extra": self.extra,
            "latency_ms": self.latency_ms,
            "injection_detected": self.injection_detected,
            "paid_gate": self.paid_gate,
            "fabrication": self.fabrication,
            "parser_version": PARSER_VERSION,
        }


def default_sandbox() -> list[Path]:
    root = Path(__file__).resolve().parents[3]
    return [
        (root / "evaluations" / "t17" / "fixtures").resolve(),
    ]


def ingest_path(path: str, *, sandbox_roots: list[Path] | None = None,
                cache: DocumentCache | None = None,
                limits: DocumentLimits | None = None) -> NormalizedDocument:
    limits = limits or DocumentLimits()
    sandbox_roots = sandbox_roots or default_sandbox()
    gate = resolve_supplied(path, sandbox_roots=sandbox_roots)
    if not gate["ok"]:
        from sciencemath.document.models import PARSE_BLOCKED, content_sha
        return NormalizedDocument(
            document_id="blocked",
            filename=str(path),
            file_type="unknown",
            mime_type="application/octet-stream",
            content_hash=content_sha(b""),
            size_bytes=0,
            parser_name="NONE",
            parse_status=PARSE_BLOCKED,
            parse_warnings=[gate["reason"] or "path_escape"],
            metadata={"path_escape": True, "reason": gate["reason"]},
        )
    p: Path = gate["path"]
    reason = archive_or_macro(p.name)
    if not p.exists() or not p.is_file():
        from sciencemath.document.models import PARSE_MALFORMED, content_sha
        return NormalizedDocument(
            document_id="missing",
            filename=p.name,
            file_type="unknown",
            mime_type="application/octet-stream",
            content_hash=content_sha(b""),
            size_bytes=0,
            parser_name="NONE",
            parse_status=PARSE_MALFORMED,
            parse_warnings=["missing_file"],
        )
    data = p.read_bytes()
    if reason:
        from sciencemath.document.models import PARSE_UNSUPPORTED, content_sha
        return NormalizedDocument(
            document_id="unsupported",
            filename=p.name,
            file_type="unsupported",
            mime_type="application/octet-stream",
            content_hash=content_sha(data),
            size_bytes=len(data),
            parser_name="NONE",
            parse_status=PARSE_UNSUPPORTED,
            parse_warnings=[reason],
        )
    ident_hash = None
    if cache is not None:
        from sciencemath.document.models import content_sha
        ident_hash = content_sha(data)
        hit = cache.get(ident_hash)
        if hit is not None:
            return hit
    doc = parse_bytes(data, p.name, limits=limits)
    if cache is not None:
        cache.put(doc)
    return doc


def analyze(question: str, files: list[str] | None = None, *,
            sandbox_roots: list[Path] | None = None,
            cache: DocumentCache | None = None,
            limits: DocumentLimits | None = None,
            filter_clause: dict | None = None,
            aggregate: dict | None = None,
            join: dict | None = None,
            extract_keys: list[str] | None = None,
            search_mode: str = "keyword",
            baseline: bool = False) -> DocumentResult:
    t0 = time.perf_counter()
    limits = limits or DocumentLimits()
    cache = cache or DocumentCache()
    op = classify_request(question)
    files = list(files or [])

    if baseline:
        return DocumentResult(
            op=op, status="NO_DOCUMENT_RUNTIME",
            answer="Baseline: DOCUMENT runtime disabled.",
            documents=[], extra={"baseline": True},
            latency_ms={"end_to_end": round((time.perf_counter() - t0) * 1000, 3)},
            fabrication={"fabricated_document": 0, "fabricated_page": 0,
                         "fabricated_row": 0, "fabricated_cell": 0,
                         "fabricated_json_path": 0},
        )

    if op == DOC_BLOCKED:
        return DocumentResult(
            op=op, status="DOC_BLOCKED",
            answer="Request blocked (unsafe document action).",
            documents=[])
    if op == DOC_UNSUPPORTED and not files:
        return DocumentResult(
            op=op, status="DOC_UNSUPPORTED",
            answer="Archive and executable formats are unsupported.",
            documents=[])
    if op == DOC_NO_EVIDENCE and not files:
        return DocumentResult(
            op=op, status="DOC_NO_EVIDENCE",
            answer="No document required or no file supplied.",
            documents=[])

    docs: list[NormalizedDocument] = []
    inj = False
    from sciencemath.document.corpus import supplied_path
    for f in files:
        d = ingest_path(supplied_path(f), sandbox_roots=sandbox_roots,
                        cache=cache, limits=limits)
        docs.append(d)
        if d.metadata.get("injection") or "prompt_injection_detected" in (
                d.parse_warnings or []):
            inj = True
        if scan_injection(d.text or "").get("detected"):
            inj = True

    lat = {"end_to_end": 0.0}
    extra: dict = {}
    citations: list = []
    tables = [t.to_dict() for d in docs for t in d.tables]
    answer = ""
    status = "OK"

    blocked = [d for d in docs if d.parse_status == "BLOCKED"]
    if blocked:
        path_esc = any(d.metadata.get("path_escape") for d in blocked)
        oversized = any("oversized" in (d.parse_warnings or [])
                        for d in blocked)
        return DocumentResult(
            op=DOC_BLOCKED, status="DOC_BLOCKED",
            answer="path_escape" if path_esc else "DOC_BLOCKED: resource-limit",
            documents=docs,
            extra={"path_escape": path_esc, "resource_limit": oversized},
            injection_detected=inj,
            fabrication=_fab(docs),
        )
    if any(d.parse_status == PARSE_NEEDS_OCR for d in docs) and op in (
            DOC_QA, DOC_SUMMARIZE, DOC_EXTRACT, DOC_INGEST):
        ocr = [d for d in docs if d.parse_status == PARSE_NEEDS_OCR]
        if ocr and not any((d.text or "").strip() for d in docs):
            return DocumentResult(
                op=DOC_NEEDS_OCR, status="DOC_NEEDS_OCR",
                answer="DOC_NEEDS_OCR: image-only or insufficient embedded text.",
                documents=docs, injection_detected=inj,
                fabrication=_fab(docs),
            )

    if op == DOC_IDENTIFY:
        extra["ident"] = [identify_file(data=d.raw_bytes, filename=d.filename)
                          for d in docs]
        answer = ", ".join(d.file_type for d in docs)
    elif op == DOC_INGEST:
        answer = ",".join(d.parse_status for d in docs)
        extra["parse_status"] = [d.parse_status for d in docs]
    elif op == DOC_INSPECT:
        extra["inspect"] = [{
            "filename": d.filename, "file_type": d.file_type,
            "parser_name": d.parser_name, "page_count": d.page_count,
            "sheet_count": d.sheet_count, "encoding": d.encoding,
            "size_bytes": d.size_bytes, "parse_status": d.parse_status,
            "sections": d.sections, "warnings": d.parse_warnings,
        } for d in docs]
        answer = str(extra["inspect"])
    elif op == DOC_SEARCH:
        extra["hits"] = []
        for d in docs:
            extra["hits"].extend(search_document(d, question, mode=search_mode))
        answer = f"{len(extra['hits'])} hits"
    elif op == DOC_TABLE_EXTRACT:
        extra["tables_extract"] = [extract_tables(d) for d in docs]
        answer = f"{sum(len(d.tables) for d in docs)} tables"
    elif op == DOC_EXTRACT:
        keys = extract_keys or _fields_from_question(question)
        extra["fields"] = [extract_fields(d, keys) for d in docs]
        answer = str(extra["fields"])
    elif op == DOC_SUMMARIZE:
        extra["summaries"] = [summarize(d) for d in docs]
        answer = "\n\n".join(s["summary"] for s in extra["summaries"])
        citations = extra["summaries"][0]["citations"] if extra["summaries"] else []
    elif op == DOC_COMPARE:
        if len(docs) >= 2 and "version" in question.lower():
            extra["diff"] = version_diff(docs[0], docs[1])
            answer = str({k: extra["diff"][k] for k in
                          ("added", "removed", "unchanged_count")})
        elif len(docs) >= 2:
            extra["compare"] = compare_docs(docs)
            answer = str({k: extra["compare"].get(k) for k in
                          ("agreement", "contradictions", "only_in")})
            citations = []
            for clist in (extra["compare"].get("citations") or {}).values():
                citations.extend(clist)
        else:
            status = "DOC_NO_EVIDENCE"
            answer = "Need two documents to compare."
    elif op == DOC_SCHEMA:
        extra["schema"] = [
            {"document_id": d.document_id,
             "tables": [{"name": t.table_name, "types": t.inferred_types,
                         "schema_hash": t.schema_hash,
                         "pk": t.primary_key_candidate}
                        for t in d.tables]}
            for d in docs]
        answer = str(extra["schema"])
    elif op == DOC_PROFILE_DATA:
        extra["profile"] = [profile_dataset(t) for d in docs for t in d.tables]
        answer = str(extra["profile"])
    elif op == DOC_FILTER_DATA:
        clause = filter_clause or _clause_from_question(question, docs)
        extra["filtered"] = []
        for d in docs:
            for t in d.tables:
                extra["filtered"].append(filter_dataset(t, clause).to_dict())
        answer = str(extra["filtered"])
    elif op == DOC_AGGREGATE:
        spec = aggregate or _agg_from_question(question, docs)
        extra["aggregates"] = []
        for d in docs:
            for t in d.tables:
                extra["aggregates"].append(aggregate_dataset(
                    t, metric=spec.get("metric", "count"),
                    column=spec.get("column"),
                    group_by=spec.get("group_by")))
        answer = str(extra["aggregates"])
    elif op == DOC_JOIN:
        if join is None and len(docs) >= 2 and docs[0].tables and docs[1].tables:
            join = _join_from_question(question, docs)
        if join and len(docs) >= 2 and docs[0].tables and docs[1].tables:
            extra["join"] = join_datasets(
                docs[0].tables[0], docs[1].tables[0],
                left_on=join["left_on"], right_on=join["right_on"],
                how=join.get("how", "inner"))
            ds = extra["join"].pop("dataset", None)
            extra["join"]["row_count"] = extra["join"].get("row_count")
            if ds is not None:
                extra["join"]["rows"] = ds.row_count
            answer = str(extra["join"])
        else:
            status = "DOC_NO_EVIDENCE"
            answer = "Join requires two tabular documents and keys."
    elif op == DOC_CITATION:
        extra["locations"] = [
            {"document_id": d.document_id, "blocks": [b.block_id for b in d.blocks]}
            for d in docs]
        answer = str(extra["locations"])
    else:
        r = qa(docs, question)
        status = r["status"]
        answer = r["answer"]
        citations = r.get("citations") or []
        extra["qa"] = {k: r[k] for k in r if k != "citations"}
        op = r.get("op") or op

    lat["end_to_end"] = round((time.perf_counter() - t0) * 1000, 3)
    return DocumentResult(
        op=op, status=status, answer=answer, documents=docs,
        citations=citations, tables=tables, extra=extra,
        latency_ms=lat, injection_detected=inj,
        fabrication=_fab(docs, citations),
    )


def _fab(docs, citations=None) -> dict:
    from sciencemath.document.citations import DocCitation
    cits = []
    for c in citations or []:
        if isinstance(c, dict):
            cits.append(DocCitation(**{k: c[k] for k in (
                "document_id", "claim_id", "block_id", "page", "section",
                "row", "column", "json_path", "span_text", "valid",
                "invalid_reason") if k in c}))
        else:
            cits.append(c)
    base = fabrication_counts(cits)
    base["path_escape"] = int(any(d.metadata.get("path_escape") for d in docs))
    base["silent_source_mutation"] = 0
    base["macro_execution"] = 0
    base["arbitrary_code_execution"] = 0
    base["unauthorized_network"] = 0
    base["unauthorized_paid_compute"] = 0
    base["prompt_injection_success"] = 0
    base["secret_exfiltration"] = 0
    return base


def _fields_from_question(q: str) -> list[str]:
    m = re_fields(q)
    return m or ["title"]


def re_fields(q: str) -> list[str]:
    import re
    found = re.findall(r"field[s]?\s+([a-zA-Z0-9_.$]+)", q, re.I)
    found += re.findall(r"\b([A-Za-z_][\w.]*)\s+field", q)
    return found[:16]


def _clause_from_question(q: str, docs) -> dict:
    import re
    m = re.search(
        r"where\s+(\w+)\s*(=|!=|>|<|eq|neq|gt|lt|gte|lte|contains)\s*"
        r"(?:'([^']+)'|\"([^\"]+)\"|(\S+))",
        q, re.I)
    if m:
        opmap = {"=": "eq", "==": "eq", "!=": "neq", ">": "gt", "<": "lt",
                 "eq": "eq", "neq": "neq", "gt": "gt", "lt": "lt",
                 "gte": "gte", "lte": "lte", "contains": "contains"}
        val = (m.group(3) or m.group(4) or m.group(5) or "").strip()
        try:
            if "." in val:
                val = float(val)
            else:
                val = int(val)
        except ValueError:
            pass
        return {"column": m.group(1), "op": opmap.get(m.group(2).lower(), "eq"),
                "value": val}
    if docs and docs[0].tables:
        col = docs[0].tables[0].columns[0].name
        return {"column": col, "op": "not_null"}
    return {"column": "id", "op": "not_null"}


def _agg_from_question(q: str, docs) -> dict:
    import re
    metric = "count"
    for name in ("sum", "mean", "median", "min", "max", "count"):
        if re.search(rf"\b{name}\b", q, re.I):
            metric = name
            break
    col = None
    m = re.search(r"\b(?:of|column)\s+(\w+)", q, re.I)
    if m:
        col = m.group(1)
    elif docs and docs[0].tables:
        for spec in docs[0].tables[0].columns:
            if spec.inferred_type in ("INTEGER", "FLOAT"):
                col = spec.name
                break
    g = None
    mg = re.search(r"group(?:ed)? by\s+(\w+)", q, re.I)
    if mg:
        g = mg.group(1)
    return {"metric": metric, "column": col, "group_by": g}


def _join_from_question(q: str, docs) -> dict | None:
    import re
    how = "left" if re.search(r"\bleft join\b", q, re.I) else "inner"
    m = re.search(r"\bon\s+(\w+)", q, re.I)
    key = m.group(1) if m else None
    if key is None:
        left_cols = {c.name for c in docs[0].tables[0].columns}
        right_cols = {c.name for c in docs[1].tables[0].columns}
        common = sorted(left_cols & right_cols)
        key = common[0] if common else None
    if not key:
        return None
    return {"left_on": key, "right_on": key, "how": how}
