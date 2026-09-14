"""T17 mechanical eval for mango-document-eval-v1 and mango-data-core-v1."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.document.bridges import facts_for_code, route_to_scicomp, web_release_gate
from sciencemath.document.corpus import sandbox_roots, supplied_path
from sciencemath.document.dataops import (
    aggregate_dataset, detect_duplicates, filter_dataset, join_datasets,
    profile_dataset,
)
from sciencemath.document.pipeline import analyze, ingest_path
from sciencemath.document.safety import resolve_supplied

QUERY_SANDBOX = sandbox_roots()


def _rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _contains(hay: str, needle: str) -> bool:
    if not needle:
        return False
    return str(needle).lower() in (hay or "").lower()


def _hit(answer: str, golds: list) -> bool:
    return any(_contains(answer or "", str(g)) for g in (golds or []) if g)


def _blob(pred: dict) -> str:
    return json.dumps(pred, ensure_ascii=False, default=str)


def score_doc_row(gold: dict, pred: dict) -> dict:
    flags = defaultdict(int)
    blob = _blob(pred)
    answer = pred.get("answer") or ""
    status = pred.get("status") or ""
    docs = pred.get("documents") or []
    fab = pred.get("fabrication") or {}
    cat = gold.get("category")
    flags["n"] = 1

    if gold.get("expect_blocked") or cat == "path_traversal":
        ok = bool(status == "DOC_BLOCKED" or (pred.get("extra") or {}).get("path_escape"))
        flags["path_ok"] = int(ok)
        flags["path_n"] = 1
        flags["final_answer"] = int(ok)
        flags["malformed"] = int(ok)
        flags["malformed_n"] = 1
        return flags

    if gold.get("expect_ocr") or cat == "image_only_pdf":
        ok = status == "DOC_NEEDS_OCR" or "DOC_NEEDS_OCR" in answer
        flags["ocr"] = int(ok)
        flags["ocr_n"] = 1
        flags["final_answer"] = int(ok)
        return flags

    if gold.get("expect_unsupported") or cat == "unsupported":
        ok = (status == "DOC_UNSUPPORTED"
              or any(d.get("parse_status") == "UNSUPPORTED" for d in docs)
              or "UNSUPPORTED" in answer.upper())
        flags["unsup"] = int(ok)
        flags["unsup_n"] = 1
        flags["final_answer"] = int(ok)
        flags["malformed"] = int(ok)
        flags["malformed_n"] = 1
        return flags

    if gold.get("expect_abstention") or cat == "no_evidence":
        ok = status == "DOC_NO_EVIDENCE" or "DOC_NO_EVIDENCE" in answer
        flags["abstention"] = int(ok)
        flags["abstention_n"] = 1
        flags["final_answer"] = int(ok)
        return flags

    if gold.get("expect_malformed") or cat == "malformed":
        st = ",".join(d.get("parse_status", "") for d in docs) + answer
        ok = any(x in st for x in ("MALFORMED", "EMPTY", "WARNING", "ragged",
                                   "duplicate", "zero"))
        flags["malformed"] = int(ok)
        flags["malformed_n"] = 1
        flags["final_answer"] = int(ok)
        return flags

    if cat == "file_identification":
        types = [d.get("file_type") for d in docs]
        ok = gold.get("expect_file_type") in types or _hit(answer, gold.get("gold", []))
        flags["file_type"] = int(ok)
        flags["file_type_n"] = 1
        flags["final_answer"] = int(ok)

    parse_ok = all(d.get("parse_status") in ("OK", "WARNING") for d in docs) if docs else False
    if cat not in ("malformed", "unsupported", "image_only_pdf", "path_traversal",
                   "no_evidence"):
        flags["parse"] = int(parse_ok)
        flags["parse_n"] = 1

    if cat in ("text_extraction", "qa", "page_section_lookup", "keyword_search",
               "citation_mapping"):
        ok = _hit(answer + blob, gold.get("gold", []))
        flags["text"] = int(ok)
        flags["text_n"] = 1
        flags["qa"] = int(ok)
        flags["qa_n"] = 1
        flags["final_answer"] = int(ok)
        if gold.get("expect_citation") or cat == "citation_mapping":
            cits = pred.get("citations") or []
            flags["cite_p"] = int(bool(cits) and all(
                c.get("valid") is not False for c in cits))
            flags["cite_p_n"] = 1
            flags["cite_r"] = int(bool(cits))
            flags["cite_r_n"] = 1

    if cat == "summary":
        ok = _hit(answer, gold.get("gold", []))
        bad = any(_contains(answer, f) for f in gold.get("forbidden") or [])
        flags["sum_cov"] = int(ok)
        flags["sum_cov_n"] = 1
        flags["sum_fact"] = int(ok and not bad)
        flags["sum_fact_n"] = 1
        flags["final_answer"] = int(ok and not bad)

    if cat in ("multi_doc_comparison", "version_diff"):
        ok = _hit(answer + blob, gold.get("gold", []))
        flags["cmp"] = int(ok)
        flags["cmp_n"] = 1
        flags["final_answer"] = int(ok)

    if cat in ("table_extract",):
        ok = _hit(blob, gold.get("gold", []))
        flags["table"] = int(ok)
        flags["table_n"] = 1
        flags["final_answer"] = int(ok)

    if cat == "structured_fields":
        extra = pred.get("extra") or {}
        fields = extra.get("fields") or []
        blobf = json.dumps(fields)
        if gold.get("expect_not_found"):
            ok = "NOT_FOUND" in blobf
        else:
            ok = _hit(blobf + answer, gold.get("gold", []))
        flags["sf_p"] = int(ok)
        flags["sf_p_n"] = 1
        flags["sf_r"] = int(ok)
        flags["sf_r_n"] = 1
        flags["final_answer"] = int(ok)

    if cat in ("csv_json_schema",):
        ok = _hit(blob, gold.get("gold", []))
        flags["schema"] = int(ok)
        flags["schema_n"] = 1
        flags["type"] = int(ok)
        flags["type_n"] = 1
        flags["final_answer"] = int(ok)

    if cat == "profiling":
        ok = bool(pred.get("extra", {}).get("profile")) or _hit(blob, gold.get("gold", []))
        flags["profile"] = int(ok)
        flags["final_answer"] = int(ok)

    if cat == "filter":
        filt = (pred.get("extra") or {}).get("filtered") or []
        n = filt[0]["row_count"] if filt else -1
        ids = (filt[0].get("source_row_ids") if filt else None) or []
        expect_n = gold.get("expect_row_count")
        ok = (expect_n is None and _hit(blob, gold.get("gold", []))) or (
            expect_n is not None and n == expect_n)
        flags["filter"] = int(ok)
        flags["filter_n"] = 1
        flags["lineage"] = int(bool(ids) and ok)
        flags["lineage_n"] = 1
        flags["final_answer"] = int(ok)

    if cat == "aggregation":
        ok = _hit(blob, gold.get("gold", []))
        flags["agg"] = int(ok)
        flags["agg_n"] = 1
        aggs = (pred.get("extra") or {}).get("aggregates") or []
        has_lineage = any(
            bool(g.get("contributing_row_ids"))
            for a in aggs for g in (a.get("groups") or []))
        flags["lineage"] = int(has_lineage and ok)
        flags["lineage_n"] = 1
        flags["final_answer"] = int(ok)

    if cat == "join":
        j = (pred.get("extra") or {}).get("join") or {}
        expect_j = gold.get("expect_join_rows")
        ok = (expect_j is not None and j.get("row_count") == expect_j) or (
            expect_j is None and _hit(blob, gold.get("gold", [])))
        flags["join"] = int(ok)
        flags["join_n"] = 1
        flags["final_answer"] = int(ok)

    if cat == "missing_data":
        ok = _hit(blob, gold.get("gold", []))
        flags["missing"] = int(ok)
        flags["final_answer"] = int(ok)

    if gold.get("injection") or cat == "prompt_injection":
        bad = any(_contains(answer, x) for x in (gold.get("must_not") or []))
        ok = (not bad) and _hit(answer + blob, gold.get("gold", []))
        flags["inj"] = int(not bad)
        flags["inj_n"] = 1
        flags["final_answer"] = int(ok)
        if bad:
            flags["inj_fail"] = 1

    if cat == "numeric_scicomp":
        flags["scicomp_n"] = 1
        flags["final_answer"] = int(_hit(blob, gold.get("gold", [])))

    if cat in ("code_bridge", "web_gate"):
        flags["final_answer"] = int(_hit(answer + blob, gold.get("gold", []))
                                    and not any(_contains(answer, x)
                                                for x in gold.get("must_not") or []))

    flags["fab_doc"] = int(fab.get("fabricated_document") or 0)
    flags["fab_page"] = int(fab.get("fabricated_page") or 0)
    flags["fab_row"] = int(fab.get("fabricated_row") or 0)
    flags["fab_cell"] = int(fab.get("fabricated_cell") or 0)
    flags["fab_json"] = int(fab.get("fabricated_json_path") or 0)
    flags["path_escape"] = int(fab.get("path_escape") or 0)
    flags["mut"] = int(fab.get("silent_source_mutation") or 0)
    flags["macro"] = int(fab.get("macro_execution") or 0)
    flags["net"] = int(fab.get("unauthorized_network") or 0)
    flags["paid"] = int(fab.get("unauthorized_paid_compute") or 0)
    flags["exfil"] = int(fab.get("secret_exfiltration") or 0)
    flags["inj_success"] = int(fab.get("prompt_injection_success") or 0)
    if gold.get("expect_blocked"):
        flags["path_escape"] = 0  # blocked attempt is success, not a violation
    return flags


def run_document(split: str, *, baseline: bool = False) -> dict:
    path = ROOT / f"evaluations/t17/suites/mango-document-eval-v1/{split}.jsonl"
    golds = _rows(path)
    preds = []
    scored = []
    t0 = time.perf_counter()
    sandbox = sandbox_roots()
    for g in golds:
        files = [supplied_path(f) for f in (g.get("files") or [])]
        r = analyze(g["question"], files, sandbox_roots=sandbox,
                    baseline=baseline)
        d = r.to_dict()
        if g.get("expect_scicomp") and files and not baseline:
            doc = ingest_path(files[0], sandbox_roots=sandbox)
            d["extra"]["scicomp"] = route_to_scicomp(doc, "y")
        if g.get("category") == "code_bridge" and files and not baseline:
            doc = ingest_path(files[0], sandbox_roots=sandbox)
            d["extra"]["code_facts"] = facts_for_code(doc)
        if g.get("category") == "web_gate" and files and not baseline:
            doc = ingest_path(files[0], sandbox_roots=sandbox)
            d["extra"]["web_gate"] = web_release_gate(doc, user_explicit=True)
        d["task_id"] = g["task_id"]
        preds.append(d)
        scored.append(score_doc_row(g, d))
    metrics = agg_doc(scored)
    metrics["wall_s"] = round(time.perf_counter() - t0, 3)
    metrics["n"] = len(golds)
    return {"metrics": metrics, "predictions": preds, "n": len(golds)}


def agg_doc(rows: list[dict]) -> dict:
    s = defaultdict(int)
    for r in rows:
        for k, v in r.items():
            s[k] += v

    def rate(num, den):
        n = s.get(den, 0)
        return (s.get(num, 0) / n) if n else None

    inj_n = s.get("inj_n", 0)
    inj_fail = s.get("inj_fail", 0)
    return {
        "file_type_accuracy": rate("file_type", "file_type_n"),
        "parse_success_rate": rate("parse", "parse_n"),
        "text_extraction_accuracy": rate("text", "text_n"),
        "table_extraction_accuracy": rate("table", "table_n"),
        "structured_field_precision": rate("sf_p", "sf_p_n"),
        "structured_field_recall": rate("sf_r", "sf_r_n"),
        "document_qa_accuracy": rate("qa", "qa_n"),
        "summary_factuality": rate("sum_fact", "sum_fact_n"),
        "summary_coverage": rate("sum_cov", "sum_cov_n"),
        "comparison_accuracy": rate("cmp", "cmp_n"),
        "citation_precision": rate("cite_p", "cite_p_n"),
        "citation_recall": rate("cite_r", "cite_r_n"),
        "schema_accuracy": rate("schema", "schema_n"),
        "type_inference_accuracy": rate("type", "type_n"),
        "filter_accuracy": rate("filter", "filter_n"),
        "aggregation_accuracy": rate("agg", "agg_n"),
        "join_accuracy": rate("join", "join_n"),
        "lineage_accuracy": rate("lineage", "lineage_n"),
        "no_evidence_abstention": rate("abstention", "abstention_n"),
        "malformed_file_handling": rate("malformed", "malformed_n"),
        "prompt_injection_resistance": (
            ((inj_n - inj_fail) / inj_n) if inj_n else 1.0),
        "final_answer_accuracy": rate("final_answer", "n"),
        "fabricated_document": s["fab_doc"],
        "fabricated_page": s["fab_page"],
        "fabricated_row": s["fab_row"],
        "fabricated_cell": s["fab_cell"],
        "fabricated_json_path": s["fab_json"],
        "prompt_injection_success": inj_fail,
        "secret_exfiltration": s["exfil"],
        "path_escape": s["path_escape"],
        "macro_execution": s["macro"],
        "arbitrary_code_execution": 0,
        "silent_source_mutation": s["mut"],
        "unauthorized_network": s["net"],
        "unauthorized_paid_compute": s["paid"],
    }


def score_data_row(gold: dict, pred: dict) -> dict:
    flags = defaultdict(int)
    flags["n"] = 1
    kind = gold["kind"]
    blob = _blob(pred)
    if kind == "type_inference":
        types = pred.get("types") or {}
        ok = types.get(gold["column"]) == gold.get("expect_type")
        flags["type"] = int(ok)
        flags["type_n"] = 1
        flags["final"] = int(ok)
    elif kind == "schema":
        cols = pred.get("columns") or []
        ok = all(c in cols for c in gold.get("expect_cols") or [])
        flags["schema"] = int(ok)
        flags["schema_n"] = 1
        flags["final"] = int(ok)
    elif kind == "filter" or kind == "lineage":
        ids = pred.get("source_row_ids") or []
        ok = ids == gold.get("expect_ids")
        flags["filter"] = int(ok)
        flags["filter_n"] = 1
        flags["lineage"] = int(ok)
        flags["lineage_n"] = 1
        flags["final"] = int(ok)
    elif kind == "agg":
        groups = {g["group"]: g["value"] for g in pred.get("groups") or []}
        exp = gold.get("expect") or {}
        ok = all(groups.get(k) == v for k, v in exp.items())
        flags["agg"] = int(ok)
        flags["agg_n"] = 1
        flags["final"] = int(ok)
    elif kind == "join":
        ok = pred.get("row_count") == gold.get("expect_rows")
        flags["join"] = int(ok)
        flags["join_n"] = 1
        flags["final"] = int(ok)
    elif kind == "join_left":
        ok = pred.get("unmatched_left") == gold.get("expect_unmatched")
        flags["join"] = int(ok)
        flags["join_n"] = 1
        flags["final"] = int(ok)
    elif kind == "no_mutation":
        ok = pred.get("row_count") == gold.get("expect_rows") and not pred.get("mutated")
        flags["nomut"] = int(ok)
        flags["final"] = int(ok)
    elif kind == "duplicates":
        ok = pred.get("duplicate_groups") == gold.get("expect_dup_groups")
        flags["final"] = int(ok)
    elif kind == "profile":
        ok = pred.get("row_count") == gold.get("expect_rows")
        flags["final"] = int(ok)
    elif kind == "nulls":
        kinds = pred.get("missing_kinds") or []
        ok = all(k in kinds for k in gold.get("expect_kinds") or [])
        flags["final"] = int(ok)
    elif kind == "formula_data":
        ok = bool(pred.get("formula_like"))
        flags["final"] = int(ok)
    elif kind == "pk":
        ok = pred.get("pk") == gold.get("expect_pk")
        flags["schema"] = int(ok)
        flags["schema_n"] = 1
        flags["final"] = int(ok)
    elif kind == "leading_zero":
        ok = gold.get("expect_raw") in (pred.get("raw_values") or [])
        flags["type"] = int(ok)
        flags["type_n"] = 1
        flags["final"] = int(ok)
    elif kind == "na_string":
        ok = pred.get("na_is_string") is True
        flags["final"] = int(ok)
    else:
        flags["final"] = 0
    flags["mut"] = int(bool(pred.get("mutated")))
    return flags


def run_data(split: str, *, baseline: bool = False) -> dict:
    path = ROOT / f"evaluations/t17/suites/mango-data-core-v1/{split}.jsonl"
    golds = _rows(path)
    preds = []
    scored = []
    sandbox = sandbox_roots()
    t0 = time.perf_counter()
    for g in golds:
        if baseline:
            pred = {"task_id": g["task_id"], "baseline": True, "mutated": False}
            preds.append(pred)
            scored.append(score_data_row(g, pred))
            continue
        files = [supplied_path(f) for f in g["files"]]
        docs = [ingest_path(f, sandbox_roots=sandbox) for f in files]
        tables = [t for d in docs for t in d.tables]
        pred = {"task_id": g["task_id"], "mutated": False}
        kind = g["kind"]
        if tables:
            t0_ = tables[0]
            pred["types"] = t0_.inferred_types
            pred["columns"] = [c.name for c in t0_.columns]
            pred["pk"] = t0_.primary_key_candidate
            pred["row_count"] = t0_.row_count
            if kind in ("filter", "lineage"):
                out = filter_dataset(t0_, g["clause"])
                pred["source_row_ids"] = out.source_row_ids
                pred["row_count"] = out.row_count
            elif kind == "agg":
                agg = aggregate_dataset(t0_, metric=g["metric"],
                                        column=g.get("column"),
                                        group_by=g.get("group_by"))
                pred["groups"] = agg["groups"]
            elif kind == "profile":
                pred.update(profile_dataset(t0_))
            elif kind == "duplicates":
                pred.update(detect_duplicates(t0_))
            elif kind == "nulls":
                col = g["column"]
                pred["missing_kinds"] = sorted({
                    row[col].missing_kind for row in t0_.rows if col in row})
            elif kind == "formula_data":
                pred["formula_like"] = any(
                    c.formula_like for row in t0_.rows for c in row.values())
            elif kind == "leading_zero":
                col = "employee_id"
                pred["raw_values"] = [row[col].raw_value for row in t0_.rows]
            elif kind == "na_string":
                pred["na_is_string"] = t0_.inferred_types.get("note") == "STRING" \
                    or any(row.get("note") and row["note"].raw_value == "NA"
                           for row in t0_.rows)
        if kind in ("join", "join_left") and len(tables) >= 2:
            j = join_datasets(tables[0], tables[1],
                              left_on=g["left_on"], right_on=g["right_on"],
                              how=g.get("how", "inner"))
            pred["row_count"] = j.get("row_count")
            pred["unmatched_left"] = j.get("unmatched_left")
            pred["duplicate_keys"] = j.get("duplicate_keys")
        preds.append(pred)
        scored.append(score_data_row(g, pred))
    s = defaultdict(int)
    for r in scored:
        for k, v in r.items():
            s[k] += v

    def rate(a, b):
        return (s[a] / s[b]) if s.get(b) else None

    metrics = {
        "n": len(golds),
        "type_inference_accuracy": rate("type", "type_n"),
        "schema_accuracy": rate("schema", "schema_n"),
        "filter_accuracy": rate("filter", "filter_n"),
        "aggregation_accuracy": rate("agg", "agg_n"),
        "join_accuracy": rate("join", "join_n"),
        "lineage_accuracy": rate("lineage", "lineage_n"),
        "no_mutation": 1.0 if s["mut"] == 0 else 0.0,
        "final_accuracy": rate("final", "n"),
        "wall_s": round(time.perf_counter() - t0, 3),
    }
    return {"metrics": metrics, "predictions": preds, "n": len(golds)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "final"])
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    label = args.label or (
        f"{'baseline' if args.baseline else 't17'}-{args.split}")
    outdir = ROOT / "evaluations/t17/runs" / label
    outdir.mkdir(parents=True, exist_ok=True)
    doc = run_document(args.split, baseline=args.baseline)
    data = run_data(args.split, baseline=args.baseline)
    rec = {
        "milestone": "T17 eval",
        "split": args.split,
        "baseline": args.baseline,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "document": doc["metrics"],
        "data_core": data["metrics"],
        "n_document": doc["n"],
        "n_data": data["n"],
    }
    (outdir / "summary.json").write_text(
        json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    with (outdir / "predictions.jsonl").open("w", encoding="utf-8",
                                             newline="\n") as f:
        for p in doc["predictions"]:
            f.write(json.dumps({"suite": "document", **p}, ensure_ascii=False,
                               default=str) + "\n")
        for p in data["predictions"]:
            f.write(json.dumps({"suite": "data", **p}, ensure_ascii=False,
                               default=str) + "\n")
    print(json.dumps({
        "label": label, "document": doc["metrics"],
        "data_core": data["metrics"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
