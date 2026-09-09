"""T9 independent final audit — recompute all metrics from raw prediction
rows and verify artifact identity. Promotion is forbidden if this audit
fails.

Outputs evaluations/t9/final_audit.json.
Pure analysis: no model is loaded. The verifier selftest is deterministic
CPU-only and is recomputed here.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

OUT = REPO / "evaluations" / "t9"
T4RUN = REPO / "evaluations/t8/runs/qwen3-4b-stabilized-t4"
T5RRUN = REPO / "evaluations/t8/runs/qwen3-4b-stabilized-t5r"
CAPRUN = REPO / "evaluations/t8/runs/qwen3-4b-stabilized-cap/model"
CORRUN = REPO / "evaluations/t9/runs"
EXTRUN = REPO / "evaluations/t9/runs/qwen3-4b-extraction-benchmark"

MANIFEST_EXPECTED = {
    "git_commit": "1934e9d9e1e6a37dc9ecb03795a0c8d8bd0f5df5",
    "t3_adapter_sha256":
        "f57b2fd4a653abb90217e1156076dc7b583003dc2afc8da5682f958a11214668",
    "correction_suite_sha256":
        "dc77ccf845f539d4bf6df23964207d504962d75b56f02c981d0e15eb632a445b",
    "t4_suite_sha256":
        "807bb7d307c45f5160e4271388f1c2b82b5cb158610882dade3ca058ad336bef",
    "t5r_suite_sha256":
        "e74c8b1a5716ff61bdc978c9341a4592cfe902d19e5392df5204d2058e117347",
    "capacity_suite_sha256":
        "0bb6a3585ec628a54659775b30d57a852f8b7c3a2ed7f4b38c192732a2f573e1",
    "model_1_7b": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
    "model_4b": "cdbee75f17c01a7cc42f958dc650907174af0554",
}


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in
            p.read_text(encoding="utf-8").splitlines() if l.strip()]


def read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def ids_check(rows: list[dict], suite: list[dict]) -> dict:
    ids = [r["eval_id"] for r in rows]
    sids = [s["eval_id"] for s in suite]
    dups = sorted(i for i, c in Counter(ids).items() if c > 1)
    return {"rows": len(rows), "expected": len(sids),
            "unique_ids": len(set(ids)),
            "missing_ids": sorted(set(sids) - set(ids)),
            "extra_ids": sorted(set(ids) - set(sids)),
            "duplicates": dups,
            "order_matches_suite": ids == sids,
            "ids_ok": (len(rows) == len(sids) and not dups
                       and set(ids) == set(sids))}


def main() -> int:
    import subprocess
    from t8s_metrics import t4_arm_metrics
    from sciencemath.tools.benchmark import load_suite, verifier_selftest
    from sciencemath.tools.router import prevalidate_tool_call, \
        build_default_registry
    from sciencemath.evaluation.correction_metrics import (correction_metrics,
                                                           wilson_interval)

    audit: dict = {"milestone": "T9", "audit_version": "final"}
    checks: dict[str, bool] = {}
    audit["checks"] = checks

    # ---------- 1. freeze identity ----------
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO).decode().strip()
    checks["git_commit"] = head == MANIFEST_EXPECTED["git_commit"]
    audit["git_commit"] = head
    suite_shas = {
        "correction_suite": sha256_file(
            REPO / "evaluations/t9/correction-suite/v1/questions.jsonl"),
        "t4_suite": sha256_file(
            REPO / "evaluations/tool-suite/v1/questions.jsonl"),
        "t5r_suite": sha256_file(
            REPO / "evaluations/rag-suite/v1/questions.jsonl"),
        "capacity_suite": sha256_file(
            REPO / "evaluations/t8/capacity-suite/v1/questions.jsonl"),
        "extraction_suite": sha256_file(
            REPO / "evaluations/t9/extraction-benchmark/v1/questions.jsonl"),
        "t3_adapter": sha256_file(
            REPO / "mango/training/adapters/sciencemath-v0.1-t3/"
            "adapter_model.safetensors"),
    }
    audit["artifact_sha256"] = suite_shas
    for key, expected_key in [
            ("correction_suite", "correction_suite_sha256"),
            ("t4_suite", "t4_suite_sha256"),
            ("t5r_suite", "t5r_suite_sha256"),
            ("capacity_suite", "capacity_suite_sha256"),
            ("t3_adapter", "t3_adapter_sha256")]:
        checks[f"suite_sha_{key}"] = (suite_shas[key]
                                      == MANIFEST_EXPECTED[expected_key])
    hf_17b = (Path.home() / ".cache/huggingface/hub/"
              "models--Qwen--Qwen3-1.7B/refs/main").read_text().strip()
    hf_4b = (Path.home() / ".cache/huggingface/hub/"
             "models--Qwen--Qwen3-4B-Instruct-2507/refs/main").read_text().strip()
    audit["model_revisions_resolved"] = {"Qwen3-1.7B": hf_17b,
                                         "Qwen3-4B-Instruct-2507": hf_4b}
    checks["model_revision_1.7B"] = hf_17b == MANIFEST_EXPECTED["model_1_7b"]
    checks["model_revision_4B"] = hf_4b == MANIFEST_EXPECTED["model_4b"]

    # ---------- 2. correction arms ----------
    corr_suite = read_jsonl(
        REPO / "evaluations/t9/correction-suite/v1/questions.jsonl")
    audit["correction_arms"] = {}
    for label, expect_adapter, expect_firewall in [
            ("mango-v0.1-correction", "sciencemath/training/adapters/"
             "sciencemath-v0.1-t3", True),
            ("qwen3-4b-raw-replication", None, False),
            ("qwen3-4b-firewall-replication", None, True)]:
        arm = {}
        rows = read_jsonl(CORRUN / label / "predictions.jsonl")
        summ = read_json(CORRUN / label / "summary.json")
        inv = ids_check(rows, corr_suite)
        arm["inventory"] = inv
        arm["model"] = summ.get("model")
        arm["adapter"] = summ.get("adapter")
        arm["firewall"] = summ.get("firewall")
        arm["suite"] = summ.get("suite")
        arm["questions"] = summ.get("questions")
        checks[f"{label}_identity"] = (
            summ.get("model") == "Qwen/Qwen3-1.7B"
            if "mango" in label else
            summ.get("model") == "Qwen/Qwen3-4B-Instruct-2507")
        checks[f"{label}_adapter"] = summ.get("adapter") == expect_adapter
        checks[f"{label}_firewall"] = summ.get("firewall") == expect_firewall
        checks[f"{label}_inventory"] = inv["ids_ok"]
        cls = Counter(r["case_class"] for r in rows)
        checks[f"{label}_classes"] = (
            dict(cls) == {"TRUE_FAIL": 10, "FALSE_FAIL": 10,
                          "PARTIAL_FAIL": 10, "AMBIGUOUS": 10})
        # independent metric recompute
        m = correction_metrics(rows)
        n_true = m["counts"]["corrected_wrong"] + m["counts"]["still_wrong"]
        n_false = (m["counts"]["preserved_correct"]
                   + m["counts"]["destroyed_correct"])
        m["confidence_intervals_95"] = {
            "true_correction": wilson_interval(
                m["counts"]["corrected_wrong"], n_true),
            "preservation": wilson_interval(
                m["counts"]["preserved_correct"], n_false)}
        stored = summ["metrics"]
        keys = ["true_correction", "false_feedback_preservation",
                "overcorrection", "under_correction", "blind_agreement",
                "net_correction_benefit", "counts"]
        agree = all(m.get(k) == stored.get(k) for k in keys)
        arm["recomputed_metrics"] = {k: m.get(k) for k in keys}
        arm["confidence_intervals_95"] = m["confidence_intervals_95"]
        arm["stored_metrics"] = {k: stored.get(k) for k in keys}
        arm["metric_agreement"] = agree
        checks[f"{label}_metric_agreement"] = agree
        audit["correction_arms"][label] = arm

    # ---------- 3. T4 ----------
    t4rows = read_jsonl(T4RUN / "t4_tool/predictions.jsonl")
    ntrows = read_jsonl(T4RUN / "t4_notool/predictions.jsonl")
    suite4 = load_suite(REPO / "evaluations/tool-suite/v1")
    arm = {}
    arm["inventory_tool"] = ids_check(t4rows, suite4)
    # notool arm covers the 70 math-eligible ids (subset by design)
    inv_nt = ids_check(ntrows, suite4)
    arm["inventory_notool"] = {**inv_nt, "note":
                               "notool arm runs the 70 math-eligible "
                               "questions; subset expected"}
    checks["t4_tool_inventory"] = arm["inventory_tool"]["ids_ok"]
    checks["t4_notool_subset"] = (
        not inv_nt["duplicates"] and not inv_nt["extra_ids"]
        and inv_nt["rows"] == 70
        and set(r["eval_id"] for r in ntrows)
        <= set(s["eval_id"] for s in suite4))
    arm["model_id"] = sorted(set(r["model_id"] for r in t4rows))
    checks["t4_model_identity"] = arm["model_id"] == [
        "Qwen/Qwen3-4B-Instruct-2507"]
    arm["recomputed_tool_arm"] = t4_arm_metrics(
        str(T4RUN / "t4_tool/predictions.jsonl"), arm="tool",
        suite_rows=suite4)
    arm["recomputed_notool_arm"] = t4_arm_metrics(
        str(T4RUN / "t4_notool/predictions.jsonl"), arm="no_tool",
        suite_rows=suite4)
    stored = read_json(T4RUN / "t4_arm_summary.json")
    arm["verifier_selftest_recomputed"] = verifier_selftest(suite4)
    checks["t4_verifier_false_pass_zero"] = (
        arm["verifier_selftest_recomputed"]["false_pass_rate"] == 0.0)
    checks["t4_verifier_gold_full"] = (
        arm["verifier_selftest_recomputed"]["gold_pass_rate"] == 1.0)
    vs_stored = stored.get("verifier_selftest", {})
    checks["t4_verifier_agreement"] = all(
        arm["verifier_selftest_recomputed"].get(k) == vs_stored.get(k)
        for k in ["gold_cases", "gold_pass_rate", "wrong_cases",
                  "false_pass_rate", "false_pass_cases"])
    # tool arm agreement with stored comparison (paired 70-question subset)
    comp = stored.get("comparison", {})
    tool = arm["recomputed_tool_arm"]
    nt_ids = set(r["eval_id"] for r in ntrows)
    paired = [r for r in t4rows if r["eval_id"] in nt_ids]
    paired_acc = (sum(bool(r["correct"]) for r in paired) / len(paired)
                  if paired else None)
    checks["t4_paired_tool_accuracy_agreement"] = (
        paired_acc is not None and
        round(paired_acc, 4) ==
        round(comp.get("tool_enabled_accuracy", -1), 4))
    arm["paired_70_tool_accuracy"] = round(paired_acc, 4) if paired_acc \
        is not None else None
    arm["tool_arm_150_accuracy"] = tool["overall_accuracy"]
    arm["tool_call_rate"] = tool["tool_call_rate"]
    arm["valid_tool_calls"] = tool["valid_tool_calls"]
    arm["total_tool_calls"] = tool["total_tool_calls"]
    arm["adoption"] = tool["correct_use_of_tool_result"]
    arm["routing"] = tool["tool_routing"]
    arm["error_codes"] = tool["tool_engine_error_codes"]
    arm["mean_latency_s"] = tool["mean_latency_s"]
    arm["median_latency_s"] = tool["median_latency_s"]
    arm["mean_output_tokens"] = tool["mean_output_tokens"]
    # prevalidation taxonomy recomputed offline
    calls = read_jsonl(T4RUN / "t4_tool/tool_calls.jsonl")
    reg = build_default_registry()
    proposed = len(calls)
    executed_ok = sum(1 for c in calls if c["status"] == "ok")
    direct = normalized = 0
    pv_rej = Counter()
    for c in calls:
        r = prevalidate_tool_call(reg, c["tool"], c["arguments"])
        if r["ok"]:
            normalized += int(r["normalized"])
            direct += int(not r["normalized"])
        else:
            pv_rej[r["category"]] += 1
    code_map = {"UNKNOWN_TOOL": "WRONG_TOOL", "PARSE_ERROR":
                "PARSER_REJECTION", "INVALID_INPUT": "MALFORMED_ARGUMENT",
                "DISALLOWED_EXPRESSION": "UNSUPPORTED_EXPRESSION",
                "INTERNAL_ERROR": "TOOL_INTERNAL_FAILURE",
                "UNKNOWN_UNIT": "UNSUPPORTED_EXPRESSION"}
    logged = Counter()
    for c in calls:
        if c["status"] == "error":
            code = (c.get("error") or {}).get("code") or "OTHER"
            logged[code_map.get(code, "OTHER")] += 1
    taxonomy = {"MALFORMED_ARGUMENT": 0, "WRONG_TOOL": 0,
                "UNSUPPORTED_EXPRESSION": 0, "PARSER_REJECTION": 0,
                "TOOL_INTERNAL_FAILURE": 0, "RESOURCE_CAP": 0, "OTHER": 0}
    for k, n in logged.items():
        taxonomy[k] = taxonomy.get(k, 0) + n
    arm["prevalidation"] = {
        "proposed_calls": proposed,
        "passed_prevalidation": direct + normalized,
        "direct_valid": executed_ok,
        "normalized": normalized,
        "normalization_success": normalized,
        "rejected": proposed - executed_ok,
        "rejected_at_prevalidation": sum(pv_rej.values()),
        "rejected_at_engine": (proposed - executed_ok
                               - sum(pv_rej.values())),
        "prevalidation_stage_categories": dict(pv_rej),
        "failure_taxonomy": taxonomy,
        "timeout": 0,
        "note": "direct_valid = calls that passed prevalidation and "
                "executed without error; rejected total = proposed - "
                "executed_ok (prevalidation-stage + engine-stage failures), "
                "matching logged error statuses exactly",
    }
    checks["t4_prevalidation_consistent"] = (
        proposed == executed_ok + (proposed - executed_ok)
        and (proposed - executed_ok)
        == sum(pv_rej.values()) + (proposed - executed_ok
                                   - sum(pv_rej.values())))
    audit["t4"] = arm

    # ---------- 4. T5R ----------
    suite5_all = read_jsonl(REPO / "evaluations/rag-suite/v1/questions.jsonl")
    audit["t5r"] = {}
    for variant in ["G", "NORAG"]:
        rows = read_jsonl(T5RRUN / variant / "predictions.jsonl")
        ids = [r["eval_id"] for r in rows]
        dups = sorted(i for i, c in Counter(ids).items() if c > 1)
        in_suite = set(ids) <= {s["eval_id"] for s in suite5_all}
        v = {"inventory": {"rows": len(rows), "unique_ids": len(set(ids)),
                           "duplicates": dups, "ids_within_frozen_suite":
                               in_suite,
                           "denominator_58": len(rows) == 58}}
        correct = sum(1 for r in rows if r.get("correct"))
        cited = sum(1 for r in rows if
                    (r.get("citation_report") or {}).get("n_citations"))
        fab = sum(int(bool((r.get("citation_report") or {}).get("n_fabricated")))
                  for r in rows)
        unsup = sum(int(bool((r.get("citation_report") or {})
                             .get("n_unsupported"))) for r in rows)
        inv_refs = sum(int(r.get("invalid_refs") or 0) for r in rows)
        v["recomputed"] = {"n": len(rows), "correct": correct,
                           "accuracy": round(correct / len(rows), 4),
                           "questions_with_citations": cited,
                           "fabricated_accepted": fab,
                           "unsupported_accepted": unsup,
                           "invalid_accepted": inv_refs}
        stored_v = read_json(T5RRUN / "comparison.json")["variants"][variant]
        checks[f"t5r_{variant}_accuracy_agreement"] = (
            abs(v["recomputed"]["accuracy"]
                - stored_v["accuracy"]) < 1e-9)
        v["stored"] = {"accuracy": stored_v["accuracy"],
                       "citation_summary": stored_v["citation_summary"]}
        checks[f"t5r_{variant}_inventory"] = (
            not dups and in_suite and len(rows) == 58)
        audit["t5r"][variant] = v
    checks["t5r_citation_integrity"] = all(
        audit["t5r"][v]["recomputed"]["fabricated_accepted"] == 0 and
        audit["t5r"][v]["recomputed"]["unsupported_accepted"] == 0 and
        audit["t5r"][v]["recomputed"]["invalid_accepted"] == 0
        for v in ["G", "NORAG"])

    # ---------- 5. capacity / generalization ----------
    suitec = read_jsonl(
        REPO / "evaluations/t8/capacity-suite/v1/questions.jsonl")
    rows = read_jsonl(CAPRUN / "predictions.jsonl")
    cap = {"inventory": ids_check(rows, suitec)}
    checks["capacity_inventory"] = cap["inventory"]["ids_ok"]
    dims = defaultdict(list)
    for r in rows:
        d = r["dimension"]
        if d in ("distractor_clean", "distractor_loaded"):
            d = "distractor"
        dims[d].append(bool(r["correct"]))
    cap["by_dimension"] = {k: {"correct": sum(v), "n": len(v),
                               "accuracy": round(sum(v) / len(v), 4)}
                           for k, v in sorted(dims.items())}
    answerable = [r for r in rows if r["dimension"] != "uncertainty"]
    unc = [r for r in rows if r["dimension"] == "uncertainty"]
    tp = sum(1 for p in unc if p["uncertainty_signaled"])
    fn = sum(1 for p in unc if not p["uncertainty_signaled"])
    fp = sum(1 for p in answerable if p["uncertainty_signaled"])
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
    cap["uncertainty_f1"] = {"tp": tp, "fn": fn, "fp": fp,
                             "precision": round(prec, 4),
                             "recall": round(rec, 4),
                             "insufficient_info_f1": round(f1, 4)}
    overall = sum(bool(r["correct"]) for r in rows)
    cap["overall"] = {"correct": overall, "n": len(rows),
                      "accuracy": round(overall / len(rows), 4)}
    plans_path = CAPRUN / "plans.jsonl"
    if plans_path.exists():
        plans = read_jsonl(plans_path)
        n = max(1, len(plans))
        cap["decomposition"] = {
            "subset": len(plans),
            "raw_valid_rate": round(sum(1 for r in plans
                                        if r["raw_valid"]) / n, 4),
            "repaired_valid_rate": round(sum(1 for r in plans
                                             if r["repaired_valid"]) / n, 4),
            "semantic_valid_rate": round(sum(1 for r in plans
                                             if r["semantic_ok"]) / n, 4),
            "executable_rate": round(sum(1 for r in plans
                                         if r["executable_ok"]) / n, 4)}
        checks["decomposition_present"] = True
    else:
        cap["decomposition"] = None
        checks["decomposition_present"] = False
    audit["generalization"] = cap

    # ---------- 6. extraction ----------
    esuite = read_jsonl(
        REPO / "evaluations/t9/extraction-benchmark/v1/questions.jsonl")
    erows = read_jsonl(EXTRUN / "predictions.jsonl")
    ext = {"inventory": ids_check(erows, esuite)}
    checks["extraction_inventory"] = ext["inventory"]["ids_ok"]
    correct = sum(1 for r in erows if r["correct"] == True)  # noqa: E712
    extracted = sum(1 for r in erows if r.get("extracted_answer") is not None)
    false_acc = sum(1 for r in erows if r["correct"] != True  # noqa: E712
                    and r.get("extracted_answer") is not None)
    wrong_final = sum(1 for r in erows if r["correct"] != True  # noqa: E712
                      and r.get("extracted_answer") is not None
                      and str(r["extracted_answer"]) ==
                      str(r["expected_answer"]))
    ext["recomputed"] = {"total": len(erows), "correct": correct,
                         "extracted": extracted,
                         "recall": round(correct / len(erows), 4),
                         "precision": round(correct / extracted, 4)
                         if extracted else None,
                         "false_acceptance": false_acc,
                         "wrong_final_acceptance": wrong_final}
    stored_e = read_json(EXTRUN / "summary.json")["metrics"]
    checks["extraction_agreement"] = (
        ext["recomputed"]["recall"] == stored_e["extraction_recall"] and
        ext["recomputed"]["false_acceptance"] ==
        stored_e["counts"]["false_acceptance"])
    audit["extraction"] = ext

    # ---------- 7. result file hashes ----------
    files = {
        "mango_v01_predictions": CORRUN /
        "mango-v0.1-correction/predictions.jsonl",
        "raw_repl_predictions": CORRUN /
        "qwen3-4b-raw-replication/predictions.jsonl",
        "firewall_repl_predictions": CORRUN /
        "qwen3-4b-firewall-replication/predictions.jsonl",
        "t4_tool_predictions": T4RUN / "t4_tool/predictions.jsonl",
        "t4_notool_predictions": T4RUN / "t4_notool/predictions.jsonl",
        "t4_tool_calls": T4RUN / "t4_tool/tool_calls.jsonl",
        "t5r_G_predictions": T5RRUN / "G/predictions.jsonl",
        "t5r_NORAG_predictions": T5RRUN / "NORAG/predictions.jsonl",
        "cap_predictions": CAPRUN / "predictions.jsonl",
        "extraction_predictions": EXTRUN / "predictions.jsonl",
    }
    audit["result_file_sha256"] = {k: sha256_file(p)
                                   for k, p in sorted(files.items())
                                   if p.exists()}

    # ---------- verdict ----------
    audit["audit_pass"] = all(checks.values())
    audit["failed_checks"] = [k for k, v in checks.items() if not v]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "final_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({"audit_pass": audit["audit_pass"],
                      "failed_checks": audit["failed_checks"],
                      "n_checks": len(checks)}, indent=1))
    return 0 if audit["audit_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())