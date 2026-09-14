"""Grounded QA, summarization, comparison, extraction. No invented content."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from sciencemath.document.citations import cite
from sciencemath.document.contract import DOC_NO_EVIDENCE
from sciencemath.document.models import NormalizedDocument, UNKNOWN
from sciencemath.document.search import search_document


def qa(docs: list[NormalizedDocument], question: str) -> dict:
    q = (question or "").strip()
    if re.search(r"\b(in general|from your (own )?knowledge|as a language model)\b",
                 q, re.I):
        outside = True
    else:
        outside = False
    hits = []
    page_m = re.search(r"\bpage\s+(\d+)\b", q, re.I)
    for d in docs:
        if page_m:
            from sciencemath.document.search import lookup_page
            hits.extend(lookup_page(d, page_m.group(1)))
        hits.extend(search_document(d, _query_terms(q), mode="keyword"))
        # also phrase pieces
        for tok in _query_terms(q).split():
            if len(tok) > 3:
                hits.extend(search_document(d, tok, mode="keyword"))
    # unique by block
    seen = set()
    uniq = []
    for h in hits:
        k = (h.get("document_id"), h.get("block_id"), h.get("text"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    if not uniq:
        # try table cells
        for d in docs:
            for t in d.tables:
                for i, row in enumerate(t.rows):
                    blob = " ".join(str(c.raw_value) for c in row.values())
                    if _overlap(q, blob):
                        uniq.append({
                            "document_id": d.document_id, "block_id": UNKNOWN,
                            "text": blob, "row": i, "table": t.table_name,
                            "page": UNKNOWN,
                        })
    if not uniq and not outside:
        return {
            "op": DOC_NO_EVIDENCE,
            "status": "DOC_NO_EVIDENCE",
            "answer": "DOC_NO_EVIDENCE: the supplied documents do not contain "
                      "evidence for this question.",
            "citations": [],
            "evidence": [],
            "inferences": [],
            "document_states": [],
        }
    evidence = uniq[:8]
    # bind answer from evidence text only
    snippets = [e.get("text") or "" for e in evidence]
    answer = _answer_from_evidence(q, snippets)
    citations = []
    by_id = {d.document_id: d for d in docs}
    for e in evidence:
        d = by_id.get(e.get("document_id"))
        if d is None:
            continue
        citations.append(cite(
            d, answer, block_id=e.get("block_id"),
            page=e.get("page"), span=(e.get("text") or "")[:280],
            row=e.get("row"),
        ))
    return {
        "op": "DOC_QA",
        "status": "OK",
        "answer": answer,
        "citations": [c.to_dict() for c in citations],
        "evidence": evidence,
        "inferences": [],
        "document_states": snippets[:5],
        "outside_knowledge_used": outside,
    }


def _query_terms(q: str) -> str:
    q = re.sub(r"\b(what|who|when|where|how|many|does|the|a|an|of|in|is|are|"
               r"according|to|document|file|pdf|csv)\b", " ", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip()


def _overlap(q: str, blob: str) -> bool:
    qt = set(re.findall(r"[a-z0-9]{3,}", q.lower()))
    bt = set(re.findall(r"[a-z0-9]{3,}", blob.lower()))
    return bool(qt & bt)


def _answer_from_evidence(question: str, snippets: list[str]) -> str:
    blob = "\n".join(snippets)
    # numeric / code-like tokens in evidence often are the answer
    qlow = question.lower()
    # prefer a sentence containing the densest query overlap
    sents = re.split(r"(?<=[.!?])\s+|\n+", blob)
    best = ""
    best_n = -1
    qtoks = set(re.findall(r"[a-z0-9]{2,}", qlow))
    for s in sents:
        n = sum(1 for t in qtoks if t in s.lower())
        if n > best_n and s.strip():
            best_n = n
            best = s.strip()
    if not best:
        best = snippets[0][:400] if snippets else ""
    return best[:800]


def summarize(doc: NormalizedDocument, *, max_chars: int = 4000) -> dict:
    headings = [b.text for b in doc.blocks if b.block_type == "heading"]
    paras = [b.text for b in doc.blocks if b.block_type in (
        "paragraph", "list_item") and b.text.strip()]
    facts = []
    for p in paras[:12]:
        facts.append(p.strip()[:240])
    coverage = headings[:]
    body = []
    if headings:
        body.append("Document states (sections): " + "; ".join(headings[:12]))
    for f in facts[:8]:
        body.append(f)
    text = "\n".join(body)[:max_chars]
    return {
        "op": "DOC_SUMMARIZE",
        "status": "OK",
        "summary": text,
        "document_states": facts,
        "inferences": [],
        "section_coverage": coverage,
        "citations": [
            cite(doc, text, block_id=b.block_id, page=b.page,
                 span=b.text[:200]).to_dict()
            for b in doc.blocks[:6]
        ],
    }


def compare_docs(docs: list[NormalizedDocument]) -> dict:
    if len(docs) < 2:
        return {"op": "DOC_COMPARE", "status": "DOC_NO_EVIDENCE",
                "answer": "Need at least two documents."}
    facts = []
    for d in docs:
        toks = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-%/]{1,}", d.text or ""))
        facts.append((d, toks))
    a_doc, a = facts[0]
    b_doc, b = facts[1]
    agree = sorted(a & b)
    only_a = sorted(a - b)
    only_b = sorted(b - a)
    # crude numeric contradictions
    cons = []
    nums_a = {m.group(0) for m in re.finditer(r"\d+(?:\.\d+)?", a_doc.text or "")}
    nums_b = {m.group(0) for m in re.finditer(r"\d+(?:\.\d+)?", b_doc.text or "")}
    if nums_a and nums_b and nums_a != nums_b:
        cons.append({
            "nature": "numeric_difference",
            "a": sorted(nums_a)[:12],
            "b": sorted(nums_b)[:12],
        })
    return {
        "op": "DOC_COMPARE",
        "status": "OK",
        "agreement": agree[:40],
        "only_in": {
            a_doc.document_id: only_a[:40],
            b_doc.document_id: only_b[:40],
        },
        "contradictions": cons,
        "missing_fields": [],
        "citations": {
            a_doc.document_id: [cite(a_doc, "compare",
                                     block_id=(a_doc.blocks[0].block_id if a_doc.blocks else UNKNOWN)
                                     ).to_dict()],
            b_doc.document_id: [cite(b_doc, "compare",
                                     block_id=(b_doc.blocks[0].block_id if b_doc.blocks else UNKNOWN)
                                     ).to_dict()],
        },
        "newer_not_automatically_correct": True,
    }


def version_diff(old: NormalizedDocument, new: NormalizedDocument) -> dict:
    a = (old.text or "").splitlines()
    b = (new.text or "").splitlines()
    sm = SequenceMatcher(a=a, b=b)
    added, removed, changed, unchanged = [], [], [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            unchanged.extend(a[i1:i2])
        elif tag == "insert":
            added.extend(b[j1:j2])
        elif tag == "delete":
            removed.extend(a[i1:i2])
        else:
            changed.append({"from": a[i1:i2], "to": b[j1:j2]})
    return {
        "op": "DOC_COMPARE",
        "kind": "version_diff",
        "added": added[:50],
        "removed": removed[:50],
        "changed": changed[:50],
        "unchanged_count": len(unchanged),
        "newer_not_automatically_correct": True,
        "old_id": old.document_id,
        "new_id": new.document_id,
    }


def extract_fields(doc: NormalizedDocument, fields: list[str]) -> dict:
    found = {}
    for field in fields:
        found[field] = {"value": None, "status": "NOT_FOUND",
                        "citation": None}
        # JSON path
        if field.startswith("$"):
            for rec in doc.records:
                if isinstance(rec, dict) and rec.get("json_path") == field:
                    found[field] = {
                        "value": rec.get("raw_value"),
                        "status": "OK",
                        "json_path": field,
                    }
                    break
            continue
        # heading / key: value lines
        pat = re.compile(rf"^{re.escape(field)}\s*[:=]\s*(.+)$", re.I | re.M)
        m = pat.search(doc.text or "")
        if m:
            found[field] = {"value": m.group(1).strip(), "status": "OK"}
            continue
        # table column
        for t in doc.tables:
            if field in t.inferred_types and t.rows:
                found[field] = {
                    "value": t.rows[0][field].raw_value,
                    "status": "OK",
                    "row": 0, "column": field, "table": t.table_name,
                }
                break
        if found[field]["status"] == "NOT_FOUND":
            hits = search_document(doc, field, mode="keyword")
            if hits:
                found[field] = {
                    "value": hits[0].get("text"),
                    "status": "OK",
                    "block_id": hits[0].get("block_id"),
                }
    return {"op": "DOC_EXTRACT", "fields": found, "guessed": False}


def extract_tables(doc: NormalizedDocument) -> dict:
    return {
        "op": "DOC_TABLE_EXTRACT",
        "tables": [t.to_dict() for t in doc.tables],
        "count": len(doc.tables),
    }
