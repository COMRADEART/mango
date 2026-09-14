"""T17 data-core: types, nulls, lineage, joins, no mutation."""
from sciencemath.document.bridges import facts_for_code, route_to_scicomp, web_release_gate
from sciencemath.document.corpus import fixture_path, sandbox_roots
from sciencemath.document.dataops import (
    aggregate_dataset, detect_duplicates, filter_dataset, join_datasets,
    profile_dataset,
)
from sciencemath.document.models import BOOLEAN, DATE, FLOAT, INTEGER, STRING
from sciencemath.document.pipeline import ingest_path


def _t(name: str):
    d = ingest_path(str(fixture_path(name)), sandbox_roots=sandbox_roots())
    return d, d.tables[0]


def test_types_mixed():
    _, t = _t("types_mixed.csv")
    assert t.inferred_types["qty"] == INTEGER
    assert t.inferred_types["price"] == FLOAT
    assert t.inferred_types["shipped"] == BOOLEAN
    assert t.inferred_types["when"] == DATE
    assert t.inferred_types["sku"] == STRING


def test_null_empty_zero_nan_distinct():
    _, t = _t("nulls.csv")
    kinds = {row["score"].missing_kind for row in t.rows}
    assert "EMPTY" in kinds
    assert "ZERO" in kinds
    assert "NAN" in kinds
    # NA-like stays present string
    notes = [row["note"].raw_value for row in t.rows]
    assert "NA" in notes or "nalike" in str(notes)


def test_profile_lineage():
    _, t = _t("agg_sales.csv")
    p = profile_dataset(t)
    assert p["row_count"] == 5
    assert p["source_row_ids"] == [0, 1, 2, 3, 4]


def test_filter_preserves_ids():
    _, t = _t("filter_me.csv")
    out = filter_dataset(t, {"column": "region", "op": "eq", "value": "NA"})
    assert out.source_row_ids == [0, 3]
    assert t.row_count == 4


def test_join_left_unmatched():
    _, left = _t("join_left.csv")
    _, right = _t("join_right.csv")
    j = join_datasets(left, right, left_on="user_id", right_on="user_id",
                      how="left")
    assert j["unmatched_left"] == 1
    assert j["source_mutated"] is False


def test_duplicates_reported():
    _, t = _t("dup_rows.csv")
    d = detect_duplicates(t)
    assert d["duplicate_groups"] == 1
    assert t.row_count == 3


def test_mean_skipped_for_id_like():
    _, t = _t("ids_leading_zero.tsv")
    p = profile_dataset(t)
    emp = [c for c in p["columns"] if c["name"] == "employee_id"][0]
    assert emp["mean"] is None or emp.get("mean_skipped")


def test_document_to_scicomp():
    d, _ = _t("numeric_series.csv")
    out = route_to_scicomp(d, "y")
    assert out["document_overrides_scicomp"] is False
    assert out["status"] in ("PASS", "OK") or out.get("scicomp", {}).get("status") == "PASS"
    mean = (out.get("scicomp") or {}).get("result") or {}
    # describe result nested
    res = (out.get("scicomp") or {}).get("result")
    assert res is not None or out.get("adopted") is True or out["status"] == "PASS"


def test_document_to_code_not_executable():
    d = ingest_path(str(fixture_path("code_task.txt")),
                    sandbox_roots=sandbox_roots())
    facts = facts_for_code(d)
    assert facts["may_execute"] is False
    assert facts["instruction_authority"] == 0
    assert not any("delete" in f.lower() for f in facts["facts"])


def test_no_auto_upload():
    d = ingest_path(str(fixture_path("web_compare.txt")),
                    sandbox_roots=sandbox_roots())
    g = web_release_gate(d, user_explicit=True)
    assert g["may_upload"] is False
    assert g["text_released"] is False


def test_cache_invalidates_on_hash(tmp_path):
    from sciencemath.document.cache import DocumentCache
    from sciencemath.document.pipeline import ingest_path as ing
    cache = DocumentCache()
    d1 = ing(str(fixture_path("sci_helium.txt")), sandbox_roots=sandbox_roots(),
             cache=cache)
    d2 = ing(str(fixture_path("sci_helium.txt")), sandbox_roots=sandbox_roots(),
             cache=cache)
    assert d1.content_hash == d2.content_hash
    cache.invalidate(d1.content_hash)
    assert cache.get(d1.content_hash) is None


def test_agg_contributing_rows():
    _, t = _t("agg_sales.csv")
    agg = aggregate_dataset(t, metric="sum", column="amount", group_by="region")
    na = [g for g in agg["groups"] if g["group"] == "NA"][0]
    assert na["value"] == 15.0
    assert na["contributing_row_ids"] == [0, 1]
