#!/usr/bin/env python3
"""T22 — preregistered temporal regression battery runner (non-blind).

Executes evaluations/t22/temporal_regressions/battery_spec.json against the
remediated candidate runtime and verifies the four section-38 qualification
gates plus every family's preregistered outcome.

Blindness rules (protocol sections 19/33):
- every battery row is project-owned fixture material with its own corpus
  record (the section-25 pairs share one corpus — that shared corpus is the
  discrimination proof);
- the runner passes only ``query`` and ``now`` (the request date) to the
  candidate runtime; battery rows never carry construction_tag, gold
  expected status, or floor identity;
- no wall-clock reads: every call receives the frozen request date.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from sciencemath.knowledge.corpus import build_corpus_files, load_corpus  # noqa: E402
from sciencemath.knowledge.pipeline import answer_knowledge  # noqa: E402
from sciencemath.knowledge.routing import ROUTE_WEB_RESEARCH  # noqa: E402
from sciencemath.knowledge.schema import (  # noqa: E402
    KnowledgeChunk,
    KnowledgeSourceRecord,
)

SPEC_PATH = ROOT / "evaluations" / "t22" / "temporal_regressions" / "battery_spec.json"
RESULTS_PATH = ROOT / "evaluations" / "t22" / "temporal_regressions" / "results.json"
CORPUS_ROOT = ROOT / "artifacts" / "t22_regression_battery_corpus"

FORBIDDEN_ROW_KEYS = ("construction_tag", "expect_status", "floor_id",
                      "blind_case_category")


def _sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record(source_id: str, chunk_text: str, freshness: str):
    src = KnowledgeSourceRecord(
        source_id=source_id,
        source_title="T22 regression battery record",
        source_type="fixture",
        source_uri_or_origin="project://t22/regression-battery",
        publisher_or_collection="mango-t22",
        license="CC0",
        revision_or_version="v1",
        retrieved_at_or_snapshot_date=SPEC["snapshot_date"],
        language="en",
        authority_class="GENERAL_REFERENCE",
        freshness_class=freshness,
        topic_tags=["cross_domain"],
        content_text=chunk_text,
    )
    chunk = KnowledgeChunk(
        chunk_id=f"{source_id}-001", source_id=source_id,
        section="main", ordinal=0, text=chunk_text,
        span=(0, len(chunk_text)))
    return src, chunk


def _run_query(corpus, query: str, request_date: str):
    result = answer_knowledge(query, corpus, now=request_date)
    return {
        "status": result.status,
        "answer": result.answer,
        "trace_tail": list(result.decision_trace)[-6:],
        "zero_tolerance": dict(result.zero_tolerance),
        "temporal_intent": (result.freshness or {}).get("temporal_intent"),
    }


def _expected_route(expected: str) -> bool:
    if expected == "ROUTE_WEB_RESEARCH":
        return True
    if expected == "NOT_ROUTE_WEB_RESEARCH":
        return False
    raise ValueError(f"unknown expected status {expected!r}")


def main() -> int:
    global SPEC
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    args = parser.parse_args()

    SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    request_date = SPEC["request_date"]
    snapshot_date = SPEC["snapshot_date"]

    # Materialize the battery deterministically -----------------------------
    if CORPUS_ROOT.exists():
        shutil.rmtree(CORPUS_ROOT)
    CORPUS_ROOT.mkdir(parents=True)

    battery_rows = []   # dicts: family, case_id, query, expected, corpus
    for family, fam in SPEC["families"].items():
        if family == "section25_discriminator_pairs":
            # One shared corpus: both sides present, only metadata differs.
            pair_dir = CORPUS_ROOT / "section25_pairs"
            sources, chunks = [], []
            for index in range(fam["count"]):
                for side, freshness in (("ts", "TIME_SENSITIVE"),
                                        ("static", "STATIC")):
                    case_id = f"t22reg-pairs-{index:02d}-{side}"
                    value = f"R22 {index:04d}"
                    chunk_text = fam["query_template"] and \
                        SPEC["chunk_text_template"].format(
                            case_id=case_id, value=value)
                    src, chunk = _record(f"gk-{case_id}", chunk_text,
                                         freshness)
                    sources.append(src)
                    chunks.append(chunk)
                    battery_rows.append({
                        "family": family, "side": side, "case_id": case_id,
                        "query": fam["query_template"].format(case_id=case_id),
                        "expected_status": (
                            fam["time_sensitive_side"]["expected_status"]
                            if side == "ts"
                            else fam["static_side"]["expected_status"]),
                        "expected_answer_value": None if side == "ts" else value,
                        "corpus_dir": str(pair_dir),
                    })
            build_corpus_files(pair_dir, sources, chunks,
                               snapshot_date=snapshot_date)
            continue

        rows = fam.get("rows")
        if rows is None:
            rows = [
                {"query_template": fam["query_template"]}
                for _ in range(fam["count"])
            ]
        elif fam["count"] > len(rows):
            # Declared shapes expand to the frozen family count (the
            # adversarial-spoof family declares 2 shapes over 8 rows).
            repeat = fam["count"] // len(rows)
            rows = [dict(row, _repeat=repeat) for row in rows]
            expanded = []
            for row in rows:
                expanded.extend(dict(row, _repeat_index=i)
                                for i in range(row.pop("_repeat")))
            rows = expanded
        for index, row in enumerate(rows):
            case_id = f"t22reg-{family}-{index:04d}"
            value = SPEC["value_template"].format(index=index)
            query_template = row.get("query_template",
                                     fam.get("query_template"))
            if query_template is None:
                query = row["query"]
            else:
                query = query_template.format(case_id=case_id)
            chunk_text = row.get("chunk_text")
            if chunk_text is None:
                chunk_text = SPEC["chunk_text_template"].format(
                    case_id=case_id, value=value)
            else:
                chunk_text = chunk_text.format(case_id=case_id, value=value)
            corpus_dir = CORPUS_ROOT / family / case_id
            src, chunk = _record(f"gk-{case_id}", chunk_text,
                                 fam["source_freshness_class"])
            build_corpus_files(corpus_dir, [src], [chunk],
                               snapshot_date=snapshot_date)
            battery_rows.append({
                "family": family,
                "case_id": case_id,
                "query": query,
                "expected_status": row.get(
                    "expected_status", fam.get("expected_status")),
                "expected_answer_value": (value
                                          if fam.get("expected_answer_match")
                                          or row.get("expected_answer_match")
                                          else None),
                "corpus_dir": str(corpus_dir),
            })

    # Structural blindness control: no gold-only fields on any row --------
    forbidden_present = [key for row in battery_rows
                         for key in FORBIDDEN_ROW_KEYS if key in row]

    # Execute --------------------------------------------------------------
    corpora = {}
    outcomes = []
    for row in battery_rows:
        corpus_dir = row["corpus_dir"]
        if corpus_dir not in corpora:
            corpora[corpus_dir] = load_corpus(Path(corpus_dir))
        outcome = _run_query(corpora[corpus_dir], row["query"], request_date)
        expected = row["expected_status"]
        if expected == "ANSWER":
            row_ok = outcome["status"] == "ANSWER"
            if row_ok and row["expected_answer_value"] is not None:
                row_ok = row["expected_answer_value"] in outcome["answer"]
        elif expected == "NOT_ROUTE_WEB_RESEARCH":
            row_ok = outcome["status"] != ROUTE_WEB_RESEARCH
        else:
            row_ok = outcome["status"] == expected
        outcomes.append({
            "family": row["family"],
            "side": row.get("side", ""),
            "case_id": row["case_id"],
            "expected_status": expected,
            "observed_status": outcome["status"],
            "answer_contains_expected_value": (
                row["expected_answer_value"] is None
                or row["expected_answer_value"] in outcome["answer"]),
            "temporal_intent": outcome["temporal_intent"],
            "trace_tail": outcome["trace_tail"],
            "zero_tolerance": outcome["zero_tolerance"],
            "row_ok": row_ok,
        })

    # Gates ----------------------------------------------------------------
    def _family_rows(family):
        return [o for o in outcomes if o["family"] == family]

    explicit_fams = ["explicit_current_direct_cue",
                     "explicit_current_lexicon_frame",
                     "explicit_current_metadata_only"]
    static_fams = ["historical_as_of", "stale_snapshot_record_pinned",
                   "static_unnecessary_web_timeless"]

    explicit = [o for f in explicit_fams for o in _family_rows(f)]
    static = [o for f in static_fams for o in _family_rows(f)]
    historical = _family_rows("historical_as_of")

    routed = sum(1 for o in explicit
                 if o["observed_status"] == ROUTE_WEB_RESEARCH)
    stale_answered = sum(1 for o in explicit
                         if o["observed_status"] == "ANSWER")
    static_routed = sum(1 for o in static
                        if o["observed_status"] == ROUTE_WEB_RESEARCH)
    historical_correct = sum(
        1 for o in historical
        if o["observed_status"] == "ANSWER"
        and o["answer_contains_expected_value"])

    explicit_total, static_total, historical_total = (
        len(explicit), len(static), len(historical))
    gates = {
        "explicit_current_routing_accuracy": {
            "observed": routed / explicit_total,
            "operator": "=", "threshold": 1.0,
            "pass": routed == explicit_total,
            "counts": {"routed": routed, "total": explicit_total},
        },
        "stale_snapshot_false_current_answers": {
            "observed": stale_answered,
            "operator": "=", "threshold": 0,
            "pass": stale_answered == 0,
            "counts": {"answered": stale_answered, "total": explicit_total},
        },
        "static_query_unnecessary_web_routing": {
            "observed": static_routed / static_total,
            "operator": "<=", "threshold": SPEC["gates"][
                "static_query_unnecessary_web_routing"]["threshold"],
            "pass": static_routed / static_total <= SPEC["gates"][
                "static_query_unnecessary_web_routing"]["threshold"],
            "counts": {"routed": static_routed, "total": static_total},
        },
        "historical_as_of_handling": {
            "observed": historical_correct / historical_total,
            "operator": ">=", "threshold": SPEC["gates"][
                "historical_as_of_handling"]["threshold"],
            "pass": historical_correct / historical_total >= SPEC["gates"][
                "historical_as_of_handling"]["threshold"],
            "counts": {"correct": historical_correct,
                       "total": historical_total},
        },
        "r17_shape_regression": {
            "observed": {"explicit_routed": routed,
                         "explicit_total": explicit_total,
                         "stale_answered": stale_answered},
            "pass": routed == explicit_total and stale_answered == 0,
        },
    }

    adversarial = _family_rows("adversarial_injection")
    adversarial_clean = all(
        o["observed_status"] == "ANSWER"
        and o["answer_contains_expected_value"]
        and not any(v for k, v in o["zero_tolerance"].items()
                    if k.endswith("_leak") or k.endswith("_miss"))
        for o in adversarial)

    all_rows_ok = all(o["row_ok"] for o in outcomes)
    all_gates_pass = all(g["pass"] for g in gates.values())
    battery_pass = (all_rows_ok and all_gates_pass
                    and adversarial_clean and not forbidden_present)

    results = {
        "schema_version": "t22-regression-battery-results-v1",
        "artifact": "T22_TEMPORAL_REGRESSION_BATTERY_RESULTS",
        "experiment": "t22",
        "spec_path": str(SPEC_PATH.relative_to(ROOT)),
        "spec_sha256": _sha256_text(SPEC_PATH.read_text(encoding="utf-8")),
        "request_date": request_date,
        "snapshot_date": snapshot_date,
        "row_count": len(outcomes),
        "blindness": {
            "forbidden_gold_only_keys_present": forbidden_present,
            "candidate_runtime_inputs": ["query", "now (request_date)"],
        },
        "gates": gates,
        "adversarial_injection_clean": adversarial_clean,
        "family_summary": {
            family: {
                "rows": sum(1 for o in outcomes if o["family"] == family),
                "ok": sum(1 for o in outcomes
                          if o["family"] == family and o["row_ok"]),
            }
            for family in SPEC["families"]
        },
        "outcomes": outcomes,
        "battery_pass": battery_pass,
    }
    results["results_sha256"] = _sha256_text(
        json.dumps({k: v for k, v in results.items()
                    if k != "results_sha256"},
                   sort_keys=True, separators=(",", ":")))
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(results, indent=2),
                            encoding="utf-8")

    print(f"battery rows={len(outcomes)} "
          f"rows_ok={all_rows_ok} gates_pass={all_gates_pass} "
          f"adversarial_clean={adversarial_clean} "
          f"battery_pass={battery_pass}")
    for name, gate in gates.items():
        observed = gate["observed"]
        if isinstance(observed, float):
            observed = round(observed, 6)
        print(f"  gate {name}: observed={observed} pass={gate['pass']}")
    if not battery_pass:
        for o in outcomes:
            if not o["row_ok"]:
                print(f"  FAIL row {o['case_id']} "
                      f"({o['family']}{'/' + o['side'] if o['side'] else ''}) "
                      f"expected={o['expected_status']} "
                      f"observed={o['observed_status']} "
                      f"trace={o['trace_tail']}")
    return 0 if battery_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())