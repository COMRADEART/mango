"""T7.38 — Ablation analysis (arms B..G vs the matched E arm).

Reads the prediction files from one experiment label, computes per-class
accuracy per arm, and reports each ablation's delta against the full
executive arm (E) on the diagnostic subset. Cost columns (tokens,
latency, tool/retrieval/model calls) come along for the T7.39
cost-benefit table. Writes ablation_analysis.json next to the
predictions.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

ARMS = ("B_plan_only", "C_plan_tools", "D_plan_exec_verify",
        "E_full_executive", "F_no_distractor_filter",
        "G_no_correction_gate")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8")
            .splitlines() if l.strip()]


def normalize(v):
    if v is None:
        return None
    return str(v).strip().lower()


def is_correct(rec) -> bool:
    exp, got = rec["expected_answer"], rec["extracted_answer"]
    if got is None:
        return False
    if normalize(exp) == "insufficient":
        return False  # measured by the uncertainty metrics, not accuracy
    from sciencemath.evaluation.extraction import answers_match
    return bool(answers_match(str(exp), str(got)))


def summarize(records: list[dict]) -> dict:
    by_class: dict[str, list] = defaultdict(list)
    for r in records:
        by_class[r["class"]].append(r)
    insuf = [r for r in records if normalize(r["expected_answer"]) ==
             "insufficient"]
    non_insuf = [r for r in records if normalize(r["expected_answer"]) !=
                 "insufficient"]
    tp = sum(1 for r in insuf if r["declined"])
    fp = sum(1 for r in non_insuf if r["declined"])
    fn = len(insuf) - tp
    from sciencemath.evaluation.extraction import answers_match
    fixes = breaks = used = 0
    for r in records:
        if r.get("corrections_used"):
            used += 1
        ev = r.get("correction_event")
        if not ev:
            continue
        exp = str(r["expected_answer"])
        pre_ok = answers_match(exp, str(ev["pre_answer"]))
        post_ok = answers_match(exp, str(ev["post_answer"]))
        if not pre_ok and post_ok:
            fixes += 1
        elif pre_ok and not post_ok:
            breaks += 1
    return {
        "n": len(records),
        "accuracy": (sum(1 for r in records if is_correct(r)) /
                     len(records)) if records else None,
        "accuracy_by_class": {k: sum(1 for r in v if is_correct(r)) /
                              len(v) for k, v in sorted(by_class.items())},
        "uncertainty": {"precision": (tp / (tp + fp)) if (tp + fp) else None,
                        "recall": (tp / (tp + fn)) if (tp + fn) else None,
                        "tp": tp, "fp": fp, "fn": fn},
        "correction": {"used": used, "net_gain": fixes - breaks,
                       "fixes": fixes, "breaks": breaks},
        "citations_fabricated": sum(
            len(((r.get("citations") or {}).get("invalid_refs")) or [])
            for r in records if (r.get("supplied_chunks") or 0) > 0),
        "stalled_rate": (sum(1 for r in records
                             if r["termination_reason"] == "STALLED") /
                         len(records)) if records else None,
        "error_rate": (sum(1 for r in records
                           if r["termination_reason"] == "SYSTEM_ERROR") /
                       len(records)) if records else None,
        "avg_latency_s": round(sum(r.get("latency_s") or 0 for r in records)
                               / len(records), 1) if records else None,
        "avg_input_tokens": round(sum(r.get("input_tokens") or 0
                                      for r in records) / len(records), 1)
        if records else None,
        "avg_output_tokens": round(sum(r.get("output_tokens") or 0
                                       for r in records) / len(records), 1)
        if records else None,
        "total_model_calls": sum(r.get("model_calls") or 0 for r in records),
        "total_tool_calls": sum(r.get("tool_calls") or 0 for r in records),
        "total_retrievals": sum(r.get("retrievals") or 0 for r in records),
        "plan_first_attempt_validity": _plan_validity(records),
    }


def _plan_validity(records: list[dict]) -> float | None:
    attempted = [r for r in records
                 if r.get("first_attempt_plan_valid") is not None]
    if not attempted:
        return None
    return sum(1 for r in attempted if r["first_attempt_plan_valid"]) / \
        len(attempted)


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "mango-v0.1"
    results = REPO / "evaluations" / "t7" / "exec_results" / label
    arm_records: dict[str, list[dict]] = {}
    for arm in ARMS:
        recs = read_jsonl(results / f"{arm}_predictions.jsonl")
        # completeness: duplicate question ids corrupt every delta
        counts: dict[str, int] = defaultdict(int)
        for r in recs:
            counts[r["question_id"]] += 1
        dupes = sorted(q for q, c in counts.items() if c > 1)
        if dupes:
            print(f"WARNING [{arm}] duplicate question_ids, keeping "
                  f"first occurrence: {dupes}")
            seen, deduped = set(), []
            for r in recs:
                if r["question_id"] in seen:
                    continue
                seen.add(r["question_id"])
                deduped.append(r)
            recs = deduped
        arm_records[arm] = recs

    e_recs = arm_records.get("E_full_executive") or []
    if not e_recs:
        print("no E_full_executive predictions yet; nothing to compare")
        return 1
    e_summary_full = summarize(e_recs)

    report = {"label": label,
              "arms_present": [a for a in ARMS if arm_records.get(a)],
              "e_accuracy_by_class": e_summary_full["accuracy_by_class"],
              "ablations": {}}
    for arm in ARMS:
        recs = arm_records.get(arm) or []
        if not recs or arm == "E_full_executive":
            continue
        # subset-vs-full: ablation arms run the 72-item diagnostic
        # subset, E ran all 102 — restrict E to the SAME question ids
        # before comparing, otherwise the delta mixes different item
        # sets and is meaningless
        arm_ids = {r["question_id"] for r in recs}
        e_sub = [r for r in e_recs if r["question_id"] in arm_ids]
        if len(e_sub) != len(recs):
            print(f"WARNING [{arm}] coverage mismatch vs E: arm={len(recs)} "
                  f"e_subset={len(e_sub)} — comparing on the intersection")
        e_ids = {r["question_id"] for r in e_sub}
        recs = [r for r in recs if r["question_id"] in e_ids]
        s = summarize(recs)
        e = summarize(e_sub)
        acc_delta = None
        if s["accuracy"] is not None and e["accuracy"] is not None:
            acc_delta = round((s["accuracy"] - e["accuracy"]) * 100, 2)
        per_class_delta = {}
        for c, v in (s.get("accuracy_by_class") or {}).items():
            ev = e["accuracy_by_class"].get(c)
            if v is not None and ev is not None:
                per_class_delta[c] = round((v - ev) * 100, 2)
        report["ablations"][arm] = {
            "accuracy": s["accuracy"], "accuracy_delta_pp_vs_E": acc_delta,
            "per_class_accuracy_delta_pp_vs_E": per_class_delta,
            "uncertainty": s["uncertainty"],
            "correction": s["correction"],
            "citations_fabricated": s["citations_fabricated"],
            "n_compared": len(recs), "n_e_subset": len(e_sub),
            "plan_first_attempt_validity": s["plan_first_attempt_validity"],
            "cost": {"avg_latency_s": s["avg_latency_s"],
                     "avg_input_tokens": s["avg_input_tokens"],
                     "avg_output_tokens": s["avg_output_tokens"],
                     "total_model_calls": s["total_model_calls"],
                     "total_tool_calls": s["total_tool_calls"],
                     "total_retrievals": s["total_retrievals"]},
            "stalled_rate": s["stalled_rate"], "error_rate": s["error_rate"],
        }
    report["e_full_summary"] = {k: v for k, v in e_summary_full.items()}
    out = results / "ablation_analysis.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print("ablation analysis written:", out)
    for arm, a in report["ablations"].items():
        print(f"{arm:28s} acc={a['accuracy']} dE={a['accuracy_delta_pp_vs_E']}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())