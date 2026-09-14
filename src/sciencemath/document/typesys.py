"""Conservative type inference. Raw values are never mutated."""
from __future__ import annotations

import re
from datetime import datetime

from sciencemath.document.models import (
    BOOLEAN, DATE, DATETIME, FLOAT, INTEGER, MIXED, NULLABLE, NULL_TYPE,
    STRING, UNKNOWN, CellValue, ColumnSpec, Dataset, content_sha,
)
from sciencemath.document.safety import formula_like

_INT = re.compile(r"^-?(0|[1-9]\d*)$")
_LEAD0 = re.compile(r"^-?0\d+")
_FLOAT = re.compile(r"^-?(?:0|[1-9]\d*)\.\d+(?:[eE][+-]?\d+)?$")
_SCI = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?[eE][+-]?\d+$")
_BOOL = {"true": True, "false": False}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?$")
_NA = {"na", "n/a", "none", "#n/a"}


def classify_raw(value, *, not_present_token: str | None = None) -> CellValue:
    if value is not None and not_present_token is not None and value == not_present_token:
        return CellValue(raw_value=None, interpreted_value=None,
                         inferred_type=UNKNOWN, missing_kind="NOT_PRESENT")
    if value is None:
        return CellValue(raw_value=None, interpreted_value=None,
                         inferred_type=NULL_TYPE, missing_kind="NULL")
    if isinstance(value, bool):
        return CellValue(raw_value="true" if value else "false",
                         interpreted_value=value, inferred_type=BOOLEAN,
                         missing_kind="FALSE" if value is False else "PRESENT")
    if isinstance(value, int) and not isinstance(value, bool):
        mk = "ZERO" if value == 0 else "PRESENT"
        return CellValue(raw_value=str(value), interpreted_value=value,
                         inferred_type=INTEGER, missing_kind=mk)
    if isinstance(value, float):
        import math
        if math.isnan(value):
            return CellValue(raw_value="NaN", interpreted_value=None,
                             inferred_type=STRING, missing_kind="NAN")
        mk = "ZERO" if value == 0.0 else "PRESENT"
        return CellValue(raw_value=repr(value), interpreted_value=value,
                         inferred_type=FLOAT, missing_kind=mk)
    raw = str(value)
    fl = formula_like(raw)
    if raw == "":
        return CellValue(raw_value="", interpreted_value="",
                         inferred_type=STRING, missing_kind="EMPTY",
                         formula_like=fl)
    if raw.lower() in ("null",):
        return CellValue(raw_value=raw, interpreted_value=None,
                         inferred_type=NULL_TYPE, missing_kind="NULL",
                         formula_like=fl)
    if raw.lower() in ("nan",):
        return CellValue(raw_value=raw, interpreted_value=raw,
                         inferred_type=STRING, missing_kind="NAN",
                         formula_like=fl)
    if raw.lower() in _NA:
        return CellValue(raw_value=raw, interpreted_value=raw,
                         inferred_type=STRING, missing_kind="PRESENT",
                         formula_like=fl)
    if _LEAD0.match(raw):
        return CellValue(raw_value=raw, interpreted_value=raw,
                         inferred_type=STRING, missing_kind="PRESENT",
                         formula_like=fl)
    low = raw.lower()
    if low in _BOOL:
        val = _BOOL[low]
        return CellValue(raw_value=raw, interpreted_value=val,
                         inferred_type=BOOLEAN,
                         missing_kind="FALSE" if val is False else "PRESENT",
                         formula_like=fl)
    if _INT.match(raw):
        iv = int(raw)
        return CellValue(raw_value=raw, interpreted_value=iv,
                         inferred_type=INTEGER,
                         missing_kind="ZERO" if iv == 0 else "PRESENT",
                         formula_like=fl)
    if _FLOAT.match(raw) or _SCI.match(raw):
        fv = float(raw)
        return CellValue(raw_value=raw, interpreted_value=fv,
                         inferred_type=FLOAT,
                         missing_kind="ZERO" if fv == 0.0 else "PRESENT",
                         formula_like=fl)
    if _DATE.match(raw):
        try:
            datetime.strptime(raw, "%Y-%m-%d")
            return CellValue(raw_value=raw, interpreted_value=raw,
                             inferred_type=DATE, missing_kind="PRESENT",
                             formula_like=fl)
        except ValueError:
            pass
    if _DT.match(raw):
        return CellValue(raw_value=raw, interpreted_value=raw,
                         inferred_type=DATETIME, missing_kind="PRESENT",
                         formula_like=fl)
    return CellValue(raw_value=raw, interpreted_value=raw,
                     inferred_type=STRING, missing_kind="PRESENT",
                     formula_like=fl)


def column_type(cells: list[CellValue]) -> tuple[str, bool, int]:
    present = [c for c in cells
               if c.missing_kind not in ("NULL", "EMPTY", "NOT_PRESENT")]
    nulls = sum(1 for c in cells
                if c.missing_kind in ("NULL", "EMPTY", "NOT_PRESENT"))
    types = {c.inferred_type for c in present}
    if not present:
        return (NULLABLE if nulls else UNKNOWN, True, nulls)
    if len(types) == 1:
        t = next(iter(types))
        return (NULLABLE if nulls and t != NULL_TYPE else t, nulls > 0, nulls)
    if types <= {INTEGER, FLOAT}:
        return (NULLABLE if nulls else FLOAT, nulls > 0, nulls)
    return (MIXED, nulls > 0, nulls)


def dataset_from_rows(doc_id: str, table_name: str, headers: list,
                      body: list, filename: str,
                      *, not_present_token: str | None = None,
                      original_headers: list | None = None) -> Dataset:
    headers = [str(h) for h in headers]
    cols_cells: dict[str, list[CellValue]] = {h: [] for h in headers}
    rows: list[dict[str, CellValue]] = []
    source_ids = []
    for ri, raw_row in enumerate(body):
        rec = {}
        source_ids.append(ri)
        for ci, h in enumerate(headers):
            val = raw_row[ci] if ci < len(raw_row) else not_present_token
            cell = classify_raw(val, not_present_token=not_present_token)
            cell.source = filename
            cell.row = ri
            cell.column = h
            rec[h] = cell
            cols_cells[h].append(cell)
        rows.append(rec)
    columns = []
    inferred = {}
    nulls = {}
    for h in headers:
        t, nullable, nc = column_type(cols_cells[h])
        uniques = len({(c.raw_value, c.missing_kind) for c in cols_cells[h]})
        columns.append(ColumnSpec(
            name=h, inferred_type=t, nullable=nullable, null_count=nc,
            unique_count=uniques,
            original_name=(original_headers[headers.index(h)]
                           if original_headers and h in headers else h),
        ))
        inferred[h] = t
        nulls[h] = nc
    pk = None
    for c in columns:
        if c.unique_count == len(rows) and len(rows) > 0 and c.inferred_type in (
                STRING, INTEGER):
            if re.search(r"id$", c.name, re.I) or c.name.lower() in ("id", "pk"):
                pk = c.name
                break
    if pk is None and columns:
        c0 = columns[0]
        if c0.unique_count == len(rows) and len(rows) > 0:
            pk = c0.name
    ds = Dataset(
        dataset_id=f"{doc_id}:{table_name}",
        source_document_id=doc_id,
        table_name=table_name,
        columns=columns,
        rows=rows,
        inferred_types=inferred,
        null_counts=nulls,
        primary_key_candidate=pk,
        source_row_ids=source_ids,
        derived=False,
    )
    ds.schema_hash = content_sha(
        "|".join(f"{c.name}:{c.inferred_type}" for c in columns))
    return ds
