"""T17 unit tests: parsers, QA, tables, schema, search, citations."""
from __future__ import annotations

from pathlib import Path

from sciencemath.document.contract import (
    DOC_IDENTIFY, DOC_JOIN, DOC_NO_EVIDENCE, DOC_QA, DOC_SUMMARIZE,
    classify_request, needs_document,
)
from sciencemath.document.corpus import fixture_path, sandbox_roots
from sciencemath.document.models import PARSE_NEEDS_OCR, PARSE_OK, STRING
from sciencemath.document.pipeline import analyze, ingest_path
from sciencemath.document.search import lookup_page, search_document


SANDBOX = None


def _sb():
    global SANDBOX
    if SANDBOX is None:
        SANDBOX = sandbox_roots()
    return SANDBOX


def _p(name: str) -> str:
    return str(fixture_path(name))


def test_no_document_for_arithmetic():
    assert classify_request("What is 2+2?") == DOC_NO_EVIDENCE
    assert not needs_document("What is 2+2?")
    r = analyze("What is 2+2?", [])
    assert r.status == "DOC_NO_EVIDENCE"


def test_identify_ops():
    assert classify_request("Identify this file type and parser.") == DOC_IDENTIFY
    assert classify_request("Summarize this document.") == DOC_SUMMARIZE
    assert classify_request("Inner join the tables on user_id") == DOC_JOIN


def test_txt_helium_qa():
    r = analyze("According to the document, what is the boiling point of helium?",
                [_p("sci_helium.txt")], sandbox_roots=_sb())
    assert "4.22" in r.answer
    assert r.documents[0].parse_status in (PARSE_OK, "WARNING")
    assert r.documents[0].page_count == "UNKNOWN"


def test_markdown_table_and_headings():
    d = ingest_path(_p("policy_retention.md"), sandbox_roots=_sb())
    assert "Retention window" in d.sections or any(
        b.block_type == "heading" for b in d.blocks)
    assert d.tables
    assert any("90" in str(c.raw_value) for row in d.tables[0].rows for c in row.values())


def test_pdf_pages():
    d = ingest_path(_p("multi_page.pdf"), sandbox_roots=_sb())
    assert d.page_count == 3 or d.page_count == 4  # writer count
    assert "HX-441" in d.text
    hits = lookup_page(d, 2)
    assert hits
    r = analyze("What is on page 2 of the document?",
                [_p("multi_page.pdf")], sandbox_roots=_sb())
    assert "2026-01-15" in r.answer or "Calibration" in r.answer


def test_image_only_pdf_needs_ocr():
    r = analyze("What does this pdf say?",
                [_p("image_only.pdf")], sandbox_roots=_sb())
    assert r.status == "DOC_NEEDS_OCR"
    assert r.documents[0].parse_status == PARSE_NEEDS_OCR
    assert not (r.documents[0].text or "").strip()


def test_csv_schema_and_leading_zeros():
    d = ingest_path(_p("ids_leading_zero.tsv"), sandbox_roots=_sb())
    t = d.tables[0]
    assert t.inferred_types["employee_id"] == STRING
    assert t.rows[0]["employee_id"].raw_value == "00123"


def test_json_path_and_missing_field():
    r = analyze("Extract field timeout_ms from this file.",
                [_p("api_widgets.json")], sandbox_roots=_sb(),
                extract_keys=["timeout_ms", "nope"])
    fields = r.extra["fields"][0]["fields"]
    assert fields["timeout_ms"]["status"] == "OK"
    assert fields["nope"]["status"] == "NOT_FOUND"


def test_html_strips_script():
    d = ingest_path(_p("tech_config.html"), sandbox_roots=_sb())
    assert "worker" in d.text.lower() or "8" in d.text
    assert "document.cookie" not in d.text


def test_filter_and_agg():
    r = analyze("Filter rows where region eq NA",
                [_p("filter_me.csv")], sandbox_roots=_sb())
    filt = r.extra["filtered"][0]
    assert filt["row_count"] == 2
    r_pad = analyze("Filter rows where region eq NA exactly",
                    [_p("filter_me.csv")], sandbox_roots=_sb())
    assert r_pad.extra["filtered"][0]["row_count"] == 2
    assert r_pad.extra["filtered"][0]["source_row_ids"] == [0, 3]
    r2 = analyze("Sum of amount group by region",
                 [_p("agg_sales.csv")], sandbox_roots=_sb())
    groups = {g["group"]: g["value"] for g in r2.extra["aggregates"][0]["groups"]}
    assert groups["NA"] == 15.0
    assert groups["EU"] == 10.0


def test_join_tracks_duplicates():
    r = analyze("Inner join the tables on user_id",
                [_p("join_left.csv"), _p("join_right.csv")],
                sandbox_roots=_sb())
    j = r.extra["join"]
    assert j["row_count"] == 3
    assert "u1" in j["duplicate_keys"]


def test_version_diff():
    r = analyze("What changed between these version documents?",
                [_p("policy_v1.txt"), _p("policy_v2.txt")],
                sandbox_roots=_sb())
    blob = str(r.extra.get("diff"))
    assert "15" in blob or "15" in r.answer
    assert r.extra["diff"]["newer_not_automatically_correct"] is True


def test_compare_contradiction():
    r = analyze("Compare these two documents on vaccine efficacy.",
                [_p("contradict_a.md"), _p("contradict_b.md")],
                sandbox_roots=_sb())
    blob = r.answer + str(r.extra)
    assert "72" in blob and "90" in blob


def test_search_keyword():
    d = ingest_path(_p("policy_retention.md"), sandbox_roots=_sb())
    hits = search_document(d, "90 days", mode="phrase")
    assert hits


def test_duplicates_not_removed():
    d = ingest_path(_p("dup_rows.csv"), sandbox_roots=_sb())
    assert d.tables[0].row_count == 3


def test_citations_resolve():
    r = analyze("According to the document, what is the boiling point of helium?",
                [_p("sci_helium.txt")], sandbox_roots=_sb())
    assert r.citations
    assert all(c.get("valid") for c in r.citations)
    assert r.fabrication["fabricated_document"] == 0


def test_unsupported_zip():
    r = analyze("Parse this file.", [_p("zip_bomb.zip")], sandbox_roots=_sb())
    assert r.documents[0].parse_status == "UNSUPPORTED"


def test_malformed_json():
    d = ingest_path(_p("bad.json"), sandbox_roots=_sb())
    assert d.parse_status == "MALFORMED"


def test_raw_immutable_filter_is_derived():
    d = ingest_path(_p("filter_me.csv"), sandbox_roots=_sb())
    n = d.tables[0].row_count
    r = analyze("Filter rows where region eq NA",
                [_p("filter_me.csv")], sandbox_roots=_sb())
    d2 = ingest_path(_p("filter_me.csv"), sandbox_roots=_sb())
    assert d2.tables[0].row_count == n
    assert r.extra["filtered"][0]["derived"] is True


def test_ragged_csv_warns():
    d = ingest_path(_p("ragged.csv"), sandbox_roots=_sb())
    assert d.parse_status in ("WARNING", "MALFORMED", "OK")
    assert d.parse_warnings or d.tables


def test_duplicate_headers_reported():
    d = ingest_path(_p("dup_headers.csv"), sandbox_roots=_sb())
    blob = " ".join(d.parse_warnings).lower()
    assert "duplicate" in blob or d.parse_status in ("WARNING", "MALFORMED")


def test_bad_utf8_warns_not_silent():
    d = ingest_path(_p("bad_utf8.txt"), sandbox_roots=_sb())
    assert d.parse_status == "WARNING" or "replace" in (d.encoding or "")
    assert any("utf8" in w.lower() or "bad" in w.lower()
               for w in d.parse_warnings)


def test_truncated_pdf_fail_closed():
    d = ingest_path(_p("truncated.pdf"), sandbox_roots=_sb())
    assert d.parse_status in ("WARNING", "MALFORMED", "NEEDS_OCR", "OK")
    assert "truncated_pdf" in d.parse_warnings or d.parse_status == "MALFORMED"


def test_fabricated_row_and_json_path_counted():
    from sciencemath.document.citations import cite, fabrication_counts
    d = ingest_path(_p("finance_q2.csv"), sandbox_roots=_sb())
    bad_row = cite(d, "no such row", row=9999, column="region")
    assert bad_row.valid is False
    counts = fabrication_counts([bad_row])
    assert counts["fabricated_row"] == 1
    assert counts["fabricated_cell"] == 1
    djson = ingest_path(_p("api_widgets.json"), sandbox_roots=_sb())
    bad_path = cite(djson, "no such path", json_path="$.does.not.exist")
    assert bad_path.valid is False
    jcounts = fabrication_counts([bad_path])
    assert jcounts["fabricated_json_path"] == 1
