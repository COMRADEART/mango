"""Deterministic profile / filter / aggregate / join. Source data is immutable."""
from __future__ import annotations

import statistics
from copy import deepcopy

from sciencemath.document.limits import DocumentLimits
from sciencemath.document.models import (
    BOOLEAN, DATE, DATETIME, FLOAT, INTEGER, MIXED, STRING, Dataset,
    content_sha,
)

NUMERIC = {INTEGER, FLOAT}


def profile_dataset(ds: Dataset) -> dict:
    cols = []
    for spec in ds.columns:
        vals = [row[spec.name] for row in ds.rows if spec.name in row]
        present = [c for c in vals
                   if c.missing_kind not in ("NULL", "EMPTY", "NOT_PRESENT")]
        numeric = [c.interpreted_value for c in present
                   if c.inferred_type in NUMERIC
                   and isinstance(c.interpreted_value, (int, float))
                   and not isinstance(c.interpreted_value, bool)]
        entry = {
            "name": spec.name,
            "inferred_type": spec.inferred_type,
            "null_count": spec.null_count,
            "row_count": ds.row_count,
            "unique_count": spec.unique_count,
            "type_distribution": _type_dist(vals),
        }
        if numeric and spec.inferred_type in NUMERIC:
            entry["min"] = min(numeric)
            entry["max"] = max(numeric)
            if _semantically_numeric(spec.name, spec.inferred_type):
                entry["mean"] = float(statistics.fmean(numeric))
                entry["median"] = float(statistics.median(numeric))
            else:
                entry["mean"] = None
                entry["median"] = None
                entry["mean_skipped"] = "not_semantically_numeric"
        else:
            entry["min"] = None
            entry["max"] = None
            entry["mean"] = None
            entry["median"] = None
        cols.append(entry)
    return {
        "dataset_id": ds.dataset_id,
        "row_count": ds.row_count,
        "column_count": ds.column_count,
        "columns": cols,
        "primary_key_candidate": ds.primary_key_candidate,
        "schema_hash": ds.schema_hash,
        "duplicates": detect_duplicates(ds),
        "derived": ds.derived,
        "source_row_ids": list(ds.source_row_ids),
    }


def _type_dist(vals) -> dict[str, int]:
    d: dict[str, int] = {}
    for c in vals:
        d[c.inferred_type] = d.get(c.inferred_type, 0) + 1
        d[c.missing_kind] = d.get(c.missing_kind, 0) + 1
    return d


def _semantically_numeric(name: str, inferred: str) -> bool:
    if inferred not in NUMERIC:
        return False
    n = name.lower()
    if n.endswith("id") or n in ("id", "pk", "zip", "year") or "code" in n:
        return False
    return True


def detect_duplicates(ds: Dataset) -> dict:
    seen: dict[tuple, list[int]] = {}
    for i, row in enumerate(ds.rows):
        key = tuple((k, row[k].raw_value, row[k].missing_kind) for k in sorted(row))
        seen.setdefault(key, []).append(i)
    dups = {str(v): v for v in seen.values() if len(v) > 1}
    return {"duplicate_groups": len(dups), "groups": list(dups.values())[:20]}


def _cmp(cell, op: str, value):
    if op == "null":
        return cell.missing_kind in ("NULL", "EMPTY", "NOT_PRESENT")
    if op == "not_null":
        return cell.missing_kind not in ("NULL", "EMPTY", "NOT_PRESENT")
    if cell.missing_kind in ("NULL", "NOT_PRESENT"):
        return False
    raw = cell.raw_value
    interp = cell.interpreted_value
    if op == "eq":
        return interp == value or raw == str(value) or str(raw) == str(value)
    if op == "neq":
        return not (interp == value or raw == str(value))
    if op == "contains":
        return str(value).lower() in str(raw).lower()
    if op in ("gt", "lt", "gte", "lte"):
        try:
            a = float(interp)
            b = float(value)
        except (TypeError, ValueError):
            a, b = str(raw), str(value)
        if op == "gt":
            return a > b
        if op == "lt":
            return a < b
        if op == "gte":
            return a >= b
        return a <= b
    if op == "date_range":
        lo, hi = value
        return str(lo) <= str(raw) <= str(hi)
    return False


def filter_dataset(ds: Dataset, clause: dict,
                   limits: DocumentLimits | None = None) -> Dataset:
    """clause: {column, op, value} or {and: [clauses]}."""
    limits = limits or DocumentLimits()
    kept = []
    ids = []
    for i, row in enumerate(ds.rows):
        if _match(row, clause):
            kept.append({k: deepcopy(v) for k, v in row.items()})
            rid = ds.source_row_ids[i] if i < len(ds.source_row_ids) else i
            ids.append(rid)
        if len(kept) >= limits.max_rows:
            break
    out = Dataset(
        dataset_id=f"{ds.dataset_id}:filter",
        source_document_id=ds.source_document_id,
        table_name=ds.table_name,
        columns=list(ds.columns),
        rows=kept,
        inferred_types=dict(ds.inferred_types),
        primary_key_candidate=ds.primary_key_candidate,
        derived=True,
        source_row_ids=ids,
        warnings=list(ds.warnings) + ["derived_view"],
    )
    return out


def _match(row: dict, clause: dict) -> bool:
    if "and" in clause:
        return all(_match(row, c) for c in clause["and"])
    if "or" in clause:
        return any(_match(row, c) for c in clause["or"])
    col = clause.get("column")
    if col not in row:
        return False
    return _cmp(row[col], clause.get("op", "eq"), clause.get("value"))


def aggregate_dataset(ds: Dataset, *, metric: str, column: str | None = None,
                      group_by: str | None = None) -> dict:
    groups: dict[str, list] = {}
    contrib: dict[str, list[int]] = {}
    if group_by:
        for i, row in enumerate(ds.rows):
            if group_by not in row:
                continue
            key = str(row[group_by].raw_value)
            groups.setdefault(key, []).append(row)
            rid = ds.source_row_ids[i] if i < len(ds.source_row_ids) else i
            contrib.setdefault(key, []).append(rid)
    else:
        groups["all"] = list(ds.rows)
        contrib["all"] = list(ds.source_row_ids or range(len(ds.rows)))

    results = []
    for key, rows in groups.items():
        values = []
        if column:
            for row in rows:
                cell = row.get(column)
                if cell is None:
                    continue
                if cell.missing_kind in ("NULL", "EMPTY", "NOT_PRESENT", "NAN"):
                    continue
                if metric in ("sum", "mean", "median", "min", "max"):
                    if cell.inferred_type not in NUMERIC:
                        continue
                    if isinstance(cell.interpreted_value, (int, float)) and \
                            not isinstance(cell.interpreted_value, bool):
                        values.append(float(cell.interpreted_value))
                else:
                    values.append(cell.interpreted_value)
        n = len(rows)
        entry = {"group": key, "count": n,
                 "contributing_row_ids": contrib.get(key, [])[:200],
                 "contributing_row_count": len(contrib.get(key, []))}
        if metric == "count":
            entry["value"] = n
        elif metric == "sum":
            entry["value"] = float(sum(values)) if values else None
        elif metric == "mean":
            entry["value"] = (float(statistics.fmean(values)) if values else None)
        elif metric == "median":
            entry["value"] = (float(statistics.median(values)) if values else None)
        elif metric == "min":
            entry["value"] = min(values) if values else None
        elif metric == "max":
            entry["value"] = max(values) if values else None
        else:
            entry["value"] = None
            entry["error"] = "unknown_metric"
        results.append(entry)
    return {
        "metric": metric, "column": column, "group_by": group_by,
        "groups": results, "source_dataset_id": ds.dataset_id,
        "derived": True, "source_mutated": False,
    }


def join_datasets(left: Dataset, right: Dataset, *,
                  left_on: str, right_on: str, how: str = "inner",
                  limits: DocumentLimits | None = None) -> dict:
    limits = limits or DocumentLimits()
    how = how.lower()
    if how not in ("inner", "left"):
        return {"status": "BLOCKED", "reason": "unsupported_join",
                "how": how}
    rindex: dict[str, list[int]] = {}
    for i, row in enumerate(right.rows):
        if right_on not in row:
            continue
        k = str(row[right_on].raw_value)
        rindex.setdefault(k, []).append(i)
    dup_keys = [k for k, v in rindex.items() if len(v) > 1]
    out_rows = []
    matched_l = unmatched_l = 0
    expansion_blocked = False
    l_ids = []
    for i, lrow in enumerate(left.rows):
        if left_on not in lrow:
            unmatched_l += 1
            continue
        k = str(lrow[left_on].raw_value)
        hits = rindex.get(k, [])
        if len(hits) > limits.max_join_expansion:
            expansion_blocked = True
            hits = hits[: limits.max_join_expansion]
        if not hits:
            unmatched_l += 1
            if how == "left":
                merged = {f"L.{c}": deepcopy(lrow[c]) for c in lrow}
                out_rows.append(merged)
                l_ids.append(left.source_row_ids[i] if i < len(left.source_row_ids) else i)
            continue
        matched_l += 1
        for j in hits:
            rrow = right.rows[j]
            merged = {f"L.{c}": deepcopy(lrow[c]) for c in lrow}
            for c, v in rrow.items():
                merged[f"R.{c}"] = deepcopy(v)
            out_rows.append(merged)
            l_ids.append(left.source_row_ids[i] if i < len(left.source_row_ids) else i)
            if len(out_rows) >= limits.max_join_output_rows:
                expansion_blocked = True
                break
        if len(out_rows) >= limits.max_join_output_rows:
            break
    cols = []
    if out_rows:
        from sciencemath.document.models import ColumnSpec
        names = list(out_rows[0].keys())
        cols = [ColumnSpec(name=n, inferred_type=out_rows[0][n].inferred_type)
                for n in names]
    joined = Dataset(
        dataset_id=f"{left.dataset_id}+{right.dataset_id}",
        source_document_id=left.source_document_id,
        table_name="join",
        columns=cols,
        rows=out_rows,
        derived=True,
        source_row_ids=l_ids,
        warnings=["derived_view"] + (
            ["join_expansion_bounded"] if expansion_blocked else []),
    )
    return {
        "status": "OK",
        "how": how,
        "left_on": left_on,
        "right_on": right_on,
        "matched_left": matched_l,
        "unmatched_left": unmatched_l,
        "duplicate_keys": dup_keys[:20],
        "duplicate_key_count": len(dup_keys),
        "expansion_blocked": expansion_blocked,
        "row_count": joined.row_count,
        "dataset": joined,
        "source_mutated": False,
    }
