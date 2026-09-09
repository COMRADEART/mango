"""T8S metric extraction - pure functions over raw prediction records.

Everything recomputes independently from the saved per-question records
(never from aggregate summaries alone). Denominators stay explicit.
"""
from __future__ import annotations

import statistics


def _read_jsonl(path):
    import json
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _pct(v):
    return round(v, 4) if v is not None else None


def t4_arm_metrics(predictions_path, *, arm: str,
                   suite_rows: list[dict] | None = None) -> dict:
    """STEP 3 per-arm T4 metrics recomputed from raw predictions.

    suite_rows (optional, the frozen suite) enable model-invocation
    routing precision/recall against the frozen per-question tool
    annotations (`correct_tools`)."""
    preds = _read_jsonl(predictions_path)
    n = len(preds)
    if not n:
        return {"arm": arm, "n": 0}
    suite_by_id = {r["eval_id"]: r for r in (suite_rows or [])}
    by_cat: dict[str, list[int]] = {}
    n_extracted = n_calls = n_ok_calls = n_err_calls = 0
    n_timeout_calls = 0
    err_codes: dict[str, int] = {}
    n_with_ok_call = n_with_ok_call_and_pass = 0
    n_with_any_call = n_with_any_call_and_pass = 0
    lat: list[float] = []
    tok_in = tok_out = 0
    route_tp = route_fp = route_fn = 0
    n_tool_eligible = 0
    for p in preds:
        by_cat.setdefault(p.get("category"), []).append(
            int(bool(p.get("correct"))))
        n_extracted += int(p.get("extracted_answer") is not None)
        calls = p.get("tool_calls") or []
        n_calls += len(calls)
        ok_calls = [c for c in calls if c.get("status") != "error"]
        n_ok_calls += len(ok_calls)
        for c in calls:
            if c.get("status") == "error":
                n_err_calls += 1
                code = c.get("error_code") or "UNKNOWN"
                err_codes[code] = err_codes.get(code, 0) + 1
                if "TIMEOUT" in str(code).upper():
                    n_timeout_calls += 1
        invoked = [c["tool"] for c in calls]
        ann = (suite_by_id.get(p["eval_id"], {}) or {}).get("correct_tools")
        ann = ann or []
        if ann:
            n_tool_eligible += 1
        ann_set, inv_set = set(ann), set(invoked)
        route_tp += len(inv_set & ann_set)
        route_fp += len(inv_set - ann_set)
        route_fn += len(ann_set - inv_set)
        if calls:
            n_with_any_call += 1
            n_with_any_call_and_pass += int(p.get("verdict") == "PASS")
        if ok_calls:
            n_with_ok_call += 1
            n_with_ok_call_and_pass += int(p.get("verdict") == "PASS")
        lat.append(float(p.get("latency_s") or 0.0))
        tok_in += int(p.get("input_tokens") or 0)
        tok_out += int(p.get("output_tokens") or 0)
    routing = {
        "definition": "model-invoked tools vs frozen per-question "
                      "correct_tools annotations (micro-averaged)",
        "precision": _pct(route_tp / (route_tp + route_fp))
        if (route_tp + route_fp) else None,
        "recall": _pct(route_tp / (route_tp + route_fn))
        if (route_tp + route_fn) else None,
        "tp": route_tp, "fp": route_fp, "fn": route_fn,
    }
    return {
        "arm": arm,
        "n": n,
        "correct": sum(bool(p.get("correct")) for p in preds),
        "overall_accuracy": _pct(sum(bool(p.get("correct"))
                                     for p in preds) / n),
        "by_category": {c: _pct(sum(v) / len(v))
                        for c, v in sorted(by_cat.items())},
        "extraction_rate": _pct(n_extracted / n),
        "tool_call_rate": _pct(n_with_any_call / n),
        "questions_tool_eligible": n_tool_eligible,
        "questions_invoking_tools": n_with_any_call,
        "total_tool_calls": n_calls,
        "valid_tool_calls": n_ok_calls,
        "valid_tool_call_rate": _pct(n_ok_calls / n_calls)
        if n_calls else None,
        "successful_tool_calls": n_ok_calls,
        "tool_engine_failures": n_err_calls,
        "tool_engine_error_codes": err_codes,
        "tool_timeouts": n_timeout_calls,
        "tool_routing": routing,
        "correct_use_of_tool_result": {
            "definition": "among questions with >=1 non-error tool "
                          "call, fraction whose final verdict is PASS",
            "n_questions_with_valid_call": n_with_ok_call,
            "n_pass_after_valid_call": n_with_ok_call_and_pass,
            "rate": _pct(n_with_ok_call_and_pass / n_with_ok_call)
            if n_with_ok_call else None,
        },
        "pass_rate_any_tool_call": _pct(
            n_with_any_call_and_pass / n_with_any_call)
        if n_with_any_call else None,
        "median_latency_s": round(statistics.median(lat), 3),
        "mean_latency_s": round(sum(lat) / len(lat), 3),
        "mean_input_tokens": round(tok_in / n, 1),
        "mean_output_tokens": round(tok_out / n, 1),
        "total_output_tokens": tok_out,
    }


def t4_pair_metrics(notool: dict, tool: dict) -> dict:
    """Combine the two arms of one system (A2-A1 / B2-B1)."""
    return {
        "no_tool": notool,
        "tool": tool,
        "tool_gain_pp": _pp_delta(notool.get("overall_accuracy"),
                                  tool.get("overall_accuracy")),
        "matched_questions": min(notool.get("n", 0), tool.get("n", 0)),
        "note": "both arms run on the identical frozen suite "
                "(mango-tool-eval-v1); questions matched by eval_id",
    }


def t5r_variant_metrics(predictions_path, *, variant: str) -> dict:
    """STEP 6 per-arm T5R metrics recomputed from raw predictions.
    Citation COVERAGE and citation INTEGRITY are separate measures."""
    preds = _read_jsonl(predictions_path)
    n = len(preds)
    if not n:
        return {"variant": variant, "n": 0}
    by_cat: dict[str, list[int]] = {}
    n_cited = n_fab = n_unsup = n_invalid = n_valid_refs = 0
    n_emitted = 0
    lat: list[float] = []
    tok_in = tok_out = 0
    n_retrieval = 0
    n_chunks = 0
    n_src_attr = n_src_attr_ok = 0
    # categories whose ground truth expects retrieval (=> citation-bearing
    # evidence flow) per the frozen T5R.6 invocation mapping
    CITATION_REQUIRING = {
        "factual_science_qa", "multi_hop_science_qa",
        "insufficient_evidence", "distractor_retrieval",
        "conflicting_evidence", "source_attribution",
    }
    n_requiring = 0
    for p in preds:
        by_cat.setdefault(p.get("category"), []).append(
            int(bool(p.get("correct"))))
        if p.get("category") in CITATION_REQUIRING:
            n_requiring += 1
        if p.get("category") == "source_attribution":
            n_src_attr += 1
            n_src_attr_ok += int(bool(p.get("correct")))
        rep = p.get("citation_report") or {}
        n_emitted += int(rep.get("n_citations") or 0)
        if rep.get("n_citations"):
            n_cited += 1
        n_fab += int(rep.get("n_fabricated") or 0)
        n_unsup += int(rep.get("n_unsupported") or 0)
        n_invalid += len(rep.get("invalid_refs") or [])
        n_valid_refs += int(rep.get("n_valid") or 0)
        lat.append(float(p.get("latency_s") or 0.0))
        tok_in += int(p.get("input_tokens") or 0)
        tok_out += int(p.get("output_tokens") or 0)
        n_retrieval += int(bool(p.get("retrieval_used")))
        n_chunks += len(p.get("retrieved_chunk_ids") or [])
    integrity_ok = (n_fab == 0 and n_unsup == 0 and n_invalid == 0)
    graded = n_valid_refs + n_fab + n_unsup + n_invalid
    return {
        "variant": variant,
        "n": n,
        "correct": sum(bool(p.get("correct")) for p in preds),
        "overall_accuracy": _pct(sum(bool(p.get("correct"))
                                     for p in preds) / n),
        "by_category": {c: _pct(sum(v) / len(v))
                        for c, v in sorted(by_cat.items())},
        "extraction_rate": _pct(
            sum(1 for p in preds if p.get("extracted_answer") is not None)
            / n),
        "retrieval_used_rate": _pct(n_retrieval / n),
        "retrieved_context": {
            "mean_chunks_per_question": round(n_chunks / n, 3),
            "questions_with_retrieval": n_retrieval,
        },
        "citation": {
            "coverage": {
                "definition": "questions with >=1 attached citation / "
                              "questions whose category requires "
                              "citation-bearing evidence",
                "questions_requiring_citation": n_requiring,
                "questions_with_citation": n_cited,
                "coverage_rate": _pct(n_cited / n_requiring)
                if n_requiring else None,
                "coverage_rate_all_questions": _pct(n_cited / n),
            },
            "integrity": {
                "emitted_citations": n_emitted,
                "valid_accepted_refs": n_valid_refs,
                "fabricated_accepted": n_fab,
                "unsupported_accepted": n_unsup,
                "invalid_accepted_refs": n_invalid,
                "correctness_among_emitted": _pct(
                    n_valid_refs / graded) if graded else None,
                "integrity_ok": integrity_ok,
                "note": "zero citations does NOT imply integrity or "
                        "coverage; the two are reported separately",
            },
        },
        "source_attribution": {
            "n": n_src_attr,
            "accuracy": _pct(n_src_attr_ok / n_src_attr)
            if n_src_attr else None,
        },
        "median_latency_s": round(statistics.median(lat), 3),
        "mean_latency_s": round(sum(lat) / len(lat), 3),
        "mean_input_tokens": round(tok_in / n, 1),
        "mean_output_tokens": round(tok_out / n, 1),
    }


def _pp_delta(old, new):
    if old is None or new is None:
        return None
    return round(100 * (new - old), 2)
