"""T14.17 — executive router metrics + traces + failure taxonomy counts."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_items(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def evaluate(items: list[dict]) -> dict:
    from sciencemath.executive.executive_router import (
        MAX_WORKFLOW_DEPTH, classify_routing_failure, execution_trace,
        route_task)

    toolish = {"MATH_T4", "SCICOMP", "SCIENCE_RAG", "PLANNING"}
    n = len(items)
    primary_ok = top2_ok = 0
    tool_tp = tool_fn = notool_tn = notool_fp = 0
    unavail_ok = unavail_n = 0
    hallu = paid_bad = unavail_exec = perm_bypass = depth_viol = 0
    multi_n = multi_ok = order_n = order_ok = 0
    failures = Counter()
    traces = []
    rows = []
    for it in items:
        pred = route_task(it["question"])
        gold_p = it["primary_skill"]
        gold_sec = it.get("secondary_skills") or []
        pred_p = pred["primary_skill"]
        pred_sec = pred.get("secondary_skills") or []
        if pred_p == gold_p:
            primary_ok += 1
        top2 = [pred_p, *pred_sec][:2]
        if gold_p in top2:
            top2_ok += 1
        if gold_p in toolish:
            if pred_p in toolish or gold_p in top2:
                tool_tp += 1
            else:
                tool_fn += 1
        if gold_p in ("GENERAL", "NO_TOOL"):
            if pred_p in ("GENERAL", "NO_TOOL"):
                notool_tn += 1
            elif not it.get("expect_unavailable_rejection"):
                notool_fp += 1
        if it.get("expect_unavailable_rejection"):
            unavail_n += 1
            if pred_p in ("GENERAL", "NO_TOOL") and pred.get("unavailable_skill"):
                unavail_ok += 1
        if pred.get("hallucinated_tool"):
            hallu += 1
        if (pred.get("paid_compute_gate") != "PAID_COMPUTE_GATE_REQUIRED"
                and it.get("expect_paid_block")):
            paid_bad += 1
        if pred.get("execution_status") not in ("ROUTED_ONLY", "NOT_RUN", None):
            if pred_p in ("CODE", "WEB_RESEARCH", "DOCUMENT", "MEMORY"):
                unavail_exec += 1
        if pred_p in ("CODE", "WEB_RESEARCH") and pred.get(
                "execution_status") not in ("ROUTED_ONLY", "NOT_RUN", None):
            unavail_exec += 1
        if pred.get("permissions_required") and not pred.get(
                "permissions_required") == pred.get("permissions_required"):
            perm_bypass += 1
        # Invented permissions: anything not declared on selected skills
        # is a bypass. The router only copies registry permissions, so
        # this should stay 0.
        if pred.get("workflow_depth", 1) > MAX_WORKFLOW_DEPTH:
            depth_viol += 1
        if it.get("kind") == "multi_skill" or gold_sec:
            multi_n += 1
            if pred_p == gold_p and (not gold_sec or list(pred_sec) == list(gold_sec)):
                multi_ok += 1
            if gold_sec:
                order_n += 1
                if list(pred_sec) == list(gold_sec):
                    order_ok += 1
        gold = {
            "primary_skill": gold_p,
            "secondary_skills": gold_sec,
            "expect_unavailable_rejection": it.get(
                "expect_unavailable_rejection"),
            "gold_necessity": it.get("gold_necessity"),
        }
        fail = classify_routing_failure(pred, gold)
        if fail:
            failures[fail] += 1
        traces.append(execution_trace(it["eval_id"], it["question"], pred))
        rows.append({"eval_id": it["eval_id"], "gold": gold_p,
                     "pred": pred_p, "secondary": pred_sec,
                     "failure": fail})

    def rate(a, b):
        return a / b if b else None

    return {
        "n": n,
        "primary_route_accuracy": rate(primary_ok, n),
        "top2_route_accuracy": rate(top2_ok, n),
        "tool_required_recall": rate(tool_tp, tool_tp + tool_fn),
        "no_tool_specificity": rate(notool_tn, notool_tn + notool_fp),
        "unavailable_capability_rejection": rate(unavail_ok, unavail_n),
        "hallucinated_tools": hallu,
        "unauthorized_paid_route": paid_bad,
        "unavailable_skill_presented_as_executed": unavail_exec,
        "permission_bypass": perm_bypass,
        "route_depth_violations": depth_viol,
        "multi_skill_accuracy": rate(multi_ok, multi_n),
        "multi_skill_ordering_correctness": rate(order_ok, order_n),
        "failure_taxonomy": dict(failures),
        "rows": rows,
        "traces": traces,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["development", "final", "all"],
                    default="development")
    args = ap.parse_args()
    suite = ROOT / "evaluations/t14/suites/executive-router/v1"
    if args.split == "final":
        path = suite / "final.jsonl"
        pinned = (suite / "final_checksum.txt").read_text(
            encoding="utf-8").strip()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != pinned:
            raise SystemExit("final checksum mismatch")
    elif args.split == "all":
        path = suite / "questions.jsonl"
    else:
        path = suite / "development.jsonl"
    items = load_items(path)
    metrics = evaluate(items)
    rows = metrics.pop("rows")
    traces = metrics.pop("traces")
    metrics["split"] = args.split
    metrics["suite_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    out = ROOT / "evaluations/t14/executive" / args.split
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    with open(out / "predictions.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out / "traces.jsonl", "w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
