"""T17.2 — typed DOCUMENT skill contract.

Do not route every file task into mutation. Documents are untrusted DATA.
"""
from __future__ import annotations

import re

DOC_IDENTIFY = "DOC_IDENTIFY"
DOC_INGEST = "DOC_INGEST"
DOC_INSPECT = "DOC_INSPECT"
DOC_SEARCH = "DOC_SEARCH"
DOC_EXTRACT = "DOC_EXTRACT"
DOC_QA = "DOC_QA"
DOC_SUMMARIZE = "DOC_SUMMARIZE"
DOC_COMPARE = "DOC_COMPARE"
DOC_TABLE_EXTRACT = "DOC_TABLE_EXTRACT"
DOC_SCHEMA = "DOC_SCHEMA"
DOC_PROFILE_DATA = "DOC_PROFILE_DATA"
DOC_FILTER_DATA = "DOC_FILTER_DATA"
DOC_AGGREGATE = "DOC_AGGREGATE"
DOC_JOIN = "DOC_JOIN"
DOC_CITATION = "DOC_CITATION"
DOC_NO_EVIDENCE = "DOC_NO_EVIDENCE"
DOC_NEEDS_OCR = "DOC_NEEDS_OCR"
DOC_UNSUPPORTED = "DOC_UNSUPPORTED"
DOC_BLOCKED = "DOC_BLOCKED"

DOC_OPS = (
    DOC_IDENTIFY, DOC_INGEST, DOC_INSPECT, DOC_SEARCH, DOC_EXTRACT,
    DOC_QA, DOC_SUMMARIZE, DOC_COMPARE, DOC_TABLE_EXTRACT, DOC_SCHEMA,
    DOC_PROFILE_DATA, DOC_FILTER_DATA, DOC_AGGREGATE, DOC_JOIN,
    DOC_CITATION, DOC_NO_EVIDENCE, DOC_NEEDS_OCR, DOC_UNSUPPORTED,
    DOC_BLOCKED,
)

_BLOCKED = re.compile(
    r"\b(run (the |this )?(macro|vba|javascript)|execute (the )?formula|"
    r"unpack (the )?(zip|tar)|open (my )?(ssh|id_rsa)|"
    r"scan (the )?(home|entire disk)|upload (this )?document to the web)\b",
    re.I)
_UNSUPPORTED = re.compile(
    r"\b(unzip|untar|extract (the )?archive|open (the )?(zip|tar|exe))\b",
    re.I)
_MATH = re.compile(
    r"^\s*(what('s| is)|calculate|compute|evaluate)?\s*"
    r"[\d\.\s\+\-\*\/\^\(\)]+\s*\??\s*$", re.I)
_IDENTIFY = re.compile(
    r"\b(what (type|kind|format) of file|identify (this |the )?file|"
    r"file type|mime type|which parser)\b", re.I)
_INGEST = re.compile(
    r"\b(ingest|load (this |the )?file|open (this |the )?(document|file)|"
    r"parse (this |the )?(file|document))\b", re.I)
_INSPECT = re.compile(
    r"\b(inspect|metadata|how many (pages|sheets|rows|columns)|"
    r"page count|encoding|parser name)\b", re.I)
_SEARCH = re.compile(
    r"\b(search (the )?(document|file|csv|json)|find (the )?(phrase|heading|"
    r"keyword)|keyword search|json path)\b", re.I)
_TABLE = re.compile(
    r"\b(extract (the )?table|table extract|html table|csv table)\b", re.I)
_EXTRACT = re.compile(
    r"\b(extract (the )?(field|fields|value|section)|structured field|"
    r"pull (the )?value of)\b", re.I)
_SUM = re.compile(r"\b(summarize|summary of|tl;dr|overview of (the )?document)\b",
                  re.I)
_COMPARE = re.compile(
    r"\b(compare (these |the )?(two |three )?documents|version (diff|change)|"
    r"what changed between|side[- ]by[- ]side documents)\b", re.I)
_SCHEMA = re.compile(
    r"\b(schema|column types|inferred types|recognize (the )?schema)\b", re.I)
_PROFILE = re.compile(
    r"\b(profile (the )?(data|dataset|table|csv)|null counts|"
    r"unique counts|describe (the )?dataset)\b", re.I)
_FILTER = re.compile(
    r"\b(filter (rows|where|the data)|rows where|select rows)\b", re.I)
_AGG = re.compile(
    r"\b(aggregate|group by|sum of|mean of|median of|count rows|"
    r"total (revenue|amount|value))\b", re.I)
_JOIN = re.compile(r"\b(join (the )?(tables|csv|datasets)|inner join|left join)\b",
                   re.I)
_CITE = re.compile(r"\b(cite|citation|provenance|which page|which row)\b", re.I)
_QA = re.compile(
    r"\b(what (does|is|are)|according to (the )?(document|pdf|csv|file)|"
    r"in (the )?(document|pdf|file)|who |when |where |how many )\b", re.I)


def needs_document(text: str) -> bool:
    op = classify_request(text)
    return op not in (DOC_NO_EVIDENCE, DOC_BLOCKED)


def classify_request(text: str) -> str:
    """Map a natural-language request to exactly one DOCUMENT operation."""
    q = (text or "").strip()
    if not q:
        return DOC_NO_EVIDENCE
    if _BLOCKED.search(q):
        return DOC_BLOCKED
    if _UNSUPPORTED.search(q):
        return DOC_UNSUPPORTED
    if _MATH.match(q):
        return DOC_NO_EVIDENCE
    if _COMPARE.search(q):
        return DOC_COMPARE
    if _JOIN.search(q):
        return DOC_JOIN
    if _AGG.search(q):
        return DOC_AGGREGATE
    if _FILTER.search(q):
        return DOC_FILTER_DATA
    if _PROFILE.search(q):
        return DOC_PROFILE_DATA
    if _SCHEMA.search(q):
        return DOC_SCHEMA
    if _TABLE.search(q):
        return DOC_TABLE_EXTRACT
    if _EXTRACT.search(q):
        return DOC_EXTRACT
    if _SUM.search(q):
        return DOC_SUMMARIZE
    if _SEARCH.search(q):
        return DOC_SEARCH
    if _INSPECT.search(q):
        return DOC_INSPECT
    if _IDENTIFY.search(q):
        return DOC_IDENTIFY
    if _INGEST.search(q):
        return DOC_INGEST
    if _QA.search(q):
        return DOC_QA
    if _CITE.search(q):
        return DOC_CITATION
    if re.search(r"\b(document|pdf|csv|tsv|json|markdown|html|xlsx|file)\b",
                 q, re.I):
        return DOC_QA
    return DOC_NO_EVIDENCE
