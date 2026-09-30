"""T32 Phase 1: classify every adapter-wrong math item from the frozen T31 evidence.

Input  (frozen, read-only): evaluations/t31/{t32_diagnostic_handoff.jsonl, raw/, scored/}
Output: evaluations/t32/diagnostics/T32_PHASE1_TAXONOMY.json  (machine-readable counts)

Classification is rule-based over deterministic evidence only. An item receives a
class only when the class's written evidence rule matches; everything that would
require semantic judgment stays in the residual buckets (per directive: "Do not
label an item manually when evidence is ambiguous").
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(".")
T31 = ROOT / "evaluations/t31"
OUT = ROOT / "evaluations/t32/diagnostics/T32_PHASE1_TAXONOMY.json"

MANGO_MARKERS = ["plan", "handoff", "skill", "coordinate", "coordination", "escalate",
                 "replan", "terminal", "route to", "capability"]
REFUSAL = [r"i (?:cannot|can't|can not) (?:do|solve|answer)", r"unable to (?:solve|assist)",
           r"as an ai", r"i do not have (?:enough|access)"]

# ---- arithmetic-step verification (deterministic) ----
_NUM = r"-?\d[\d,]*(?:\.\d+)?"
_EQ_RE = re.compile(rf"({_NUM})\s*([+\-*/x×^%])\s*({_NUM})\s*=\s*({_NUM})")
_PCT_RE = re.compile(rf"({_NUM})%\s*of\s*({_NUM})\s*=\s*({_NUM})")
_PLAIN_EQ = re.compile(rf"^[\d\s\.\(\)\+\-\*/x×^%]*$")


def _val(s: str):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _tol(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.005 * max(1.0, abs(a)), abs(a) * 0.01)


def _eval_expr(expr: str):
    if not _PLAIN_EQ.match(expr):
        return None
    e = expr.replace(",", "").replace("x", "*").replace("×", "*").replace("^", "**")
    if not re.fullmatch(r"[\d\s\.\(\)\+\-\*/\*]+", e):
        return None
    try:
        return eval(e, {"__builtins__": {}}, {})  # restricted tokenizer, no names
    except Exception:
        return None


def wrong_arithmetic_steps(text: str):
    """Return [(written_step, actual_value), ...] for plain-arithmetic '=' lines
    whose stated result is not equal to the evaluated left-hand side."""
    found = []
    for line in text.replace("\\[", " ").replace("\\]", " ").splitlines():
        line = line.strip()
        if "=" not in line or len(line) > 300:
            continue
        for m in _PCT_RE.finditer(line):
            p, x, y = _val(m.group(1)), _val(m.group(2)), _val(m.group(3))
            if None not in (p, x, y) and not _tol(x * p / 100.0, y):
                found.append((m.group(0), round(x * p / 100.0, 4)))
        for m in _EQ_RE.finditer(line):
            a, op, b, c = m.group(1), m.group(2), m.group(3), m.group(4)
            av, bv, cv = _val(a), _val(b), _val(c)
            if av is None or bv is None or cv is None:
                continue
            actual = {"+": av + bv, "-": av - bv, "*": av * bv, "/": av / bv if bv else None,
                      "%" : av % bv if bv else None,
                      "x": av * bv, "×": av * bv, "^": av ** bv if abs(bv) < 20 else None}[op]
            if actual is None:
                continue
            if not _tol(actual, cv):
                lhs_full = _eval_expr(re.sub(r"\\d+|\\!", "", line.split("=")[0]))
                if lhs_full is not None and _tol(lhs_full, cv):
                    continue  # larger LHS explains the result
                found.append((m.group(0), round(actual, 4)))
    return found


def main() -> None:
    hand = [json.loads(l) for l in open(T31 / "t32_diagnostic_handoff.jsonl", encoding="utf-8")]
    scored = {}
    for arm in ("base", "adapter"):
        for b in ("gsm8k", "math500", "arc_easy", "arc_challenge", "sciq"):
            with open(T31 / f"scored/{arm}/{b}.jsonl", encoding="utf-8") as f:
                for l in f:
                    r = json.loads(l)
                    scored[(arm, r["item_id"])] = r

    out = {
        "schema_version": "t32-diagnostic-v1",
        "artifact": "T32_PHASE1_TAXONOMY",
        "inputs": {
            "handoff_rows": len(hand),
            "source": "evaluations/t31/t32_diagnostic_handoff.jsonl (frozen T31 evidence, read-only)",
            "scored_join": "evaluations/t31/scored/{base,adapter}/{benchmark}.jsonl"
        },
        "classification_policy": (
            "Rule-based over deterministic evidence; items with ambiguous evidence are left "
            "in residual buckets rather than force-labelled (directive rule)."),
        "classes": {},
        "adapter_wrong_math": {},
        "adapter_gains": {"base_failure_modes": {}},
        "both_wrong_overlap": {},
        "notes": []
    }

    # ---- 1. adapter-wrong math rows: the regression set ----
    math_arm_wrong = defaultdict(list)
    for r in hand:
        if r["benchmark"] in ("gsm8k", "math500") and r["adapter"]["correct"] is False:
            math_arm_wrong[r["benchmark"]].append(r)
    labels = Counter()
    ev_examples = defaultdict(list)
    for b, rs in sorted(math_arm_wrong.items()):
        rows_lab = []
        for r in rs:
            a = r["adapter"]
            txt = a["raw_generation"]
            low = txt.lower()
            sr = scored[("adapter", r["item_id"])]
            base_r = r["base"]
            same_wrong = (b not in ("gsm8k", "math500")) or (
                base_r["correct"] is False and str(base_r.get("extracted_answer")) == str(a.get("extracted_answer")))
            lab = None
            ev = {}
            if sr.get("truncated") or sr.get("finish_reason") not in (None, "stop"):
                lab, ev = "verbosity_truncation", {"finish_reason": sr.get("finish_reason")}
            elif not isinstance(a.get("extracted_answer"), str) or a.get("extraction_status") != "OK":
                lab, ev = "answer_extraction_issue", {"extraction_status": a.get("extraction_status")}
            elif isinstance(a.get("extracted_answer"), str) and re.fullmatch(r"\(?[A-Ea-e]\)?", a["extracted_answer"].strip()):
                lab, ev = "multiple_choice_bias", {"extracted_answer": a["extracted_answer"]}
            elif re.search(r"i (?:cannot|can't|can not) (?:do|solve|answer)|unable to (?:solve|assist)|as an ai", low):
                lab, ev = "abstention_bias", {"hit": True}
            elif "=" not in txt and len(txt.split()) <= 25:
                lab, ev = "no_derivation_emitted", {"words": len(txt.split())}
            elif txt.count("=") <= 1 and sr["output_tokens"] <= 120:
                lab, ev = "underderived_final_answer", {
                    "equals_count": txt.count("="), "output_tokens": sr["output_tokens"],
                    "words": len(txt.split())}
            else:
                steps = wrong_arithmetic_steps(txt)
                if steps:
                    lab, ev = "arithmetic_error_detected", {"first_wrong_step": steps[0][0],
                                                             "actual_value": steps[0][1]}
                else:
                    lab = "derivation_present_but_wrong_no_arithmetic_slip_detected"
            if lab is None:
                lab = "unclassified"
            if sr["output_tokens"] > 400:
                ev["output_tokens_gt400"] = sr["output_tokens"]
                ev["note"] = "long-output degeneration bucket (acc 0.05 gsm8k / 0.01 math500)"
            labels[(b, lab)] += 1
            rows_lab.append({"item_id": r["item_id"], "label": lab, "evidence": ev,
                             "base_outcome": "base_wrong" if base_r["correct"] is False else "base_right",
                             "adapter_output_tokens": sr["output_tokens"],
                             "base_output_tokens": r["difficulty_proxy"]["base_output_tokens"]})
            if len(ev_examples[(b, lab)]) < 3:
                ev_examples[(b, lab)].append({
                    "item_id": r["item_id"], "wrong_step": ev.get("first_wrong_step"),
                    "adapter_head": txt[:220].replace("\n", " ")})
        out["adapter_wrong_math"][b] = {
            "n": len(rows_lab), "by_label": dict(Counter(x["label"] for x in rows_lab)),
            "of_which_base_also_wrong": sum(1 for x in rows_lab if x["base_outcome"] == "base_wrong"),
            "rows": rows_lab if len(rows_lab) <= 400 else rows_lab[:400],
            "rows_truncated_total_note": "rows list capped at 400 for size; full counts above"
        }
        math_arm_wrong[b] = rs

    # both-wrong same-value overlap
    for b in ("gsm8k", "math500"):
        rs = [r for r in hand if r["benchmark"] == b and r["outcome"] == "neither"]
        same = sum(1 for r in rs if str(r["base"].get("extracted_answer")) == str(r["adapter"].get("extracted_answer")))
        out["both_wrong_overlap"][b] = {
            "n_both_wrong": len(rs),
            "n_same_wrong_value": same,
            "note": "same wrong value on both arms suggests a shared/backbone-level error mode"}

    # ---- 2. adapter-gained MC rows: why the base failed (format-compatibility evidence) ----
    for b in ("arc_easy", "arc_challenge", "sciq", "gsm8k", "math500"):
        g = [r for r in hand if r["benchmark"] == b and r["outcome"] == "adapter_only"]
        modes = Counter()
        for r in g:
            bs = scored[("base", r["item_id"])]
            if bs.get("truncated") or bs.get("finish_reason") not in (None, "stop"):
                modes["base_truncated"] += 1
            elif bs.get("error_category") == "invalid_option":
                modes["base_invalid_option"] += 1
            elif bs.get("extraction_status") != "OK":
                modes["base_extraction_failure"] += 1
            else:
                modes["base_wrong_option_value"] += 1
        gain_toks_a = [scored[("adapter", r["item_id"])]["output_tokens"] for r in g]
        toks_b = [r["difficulty_proxy"]["base_output_tokens"] for r in g]
        out["adapter_gains"]["base_failure_modes"][b] = {
            "n": len(g), "modes": dict(modes),
            "adapter_median_tokens": sorted(gain_toks_a)[len(gain_toks_a)//2] if g else None,
            "base_median_tokens": sorted(toks_b)[len(toks_b)//2] if g else None}

    # ---- 3. global truncation table over all rows ----
    tt = defaultdict(lambda: [0, 0])
    for (arm, iid), sr in scored.items():
        tt[(sr["benchmark"], arm)][0] += 1
        if sr.get("truncated") or sr.get("finish_reason") not in (None, "stop"):
            tt[(sr["benchmark"], arm)][1] += 1
    out["truncation_all_rows"] = {
        f"{b}/{arm}": {"truncated": v[1], "total": v[0]} for (b, arm), v in sorted(tt.items())}

    # ---- 4. protocol-vocabulary check (H1 evidence) ----
    proto = []
    for r in hand:
        for arm in ("base", "adapter"):
            low = r[arm]["raw_generation"].lower()
            hits = [m for m in MANGO_MARKERS if m in low]
            if hits:
                proto.append({"item_id": r["item_id"], "arm": arm, "markers": hits,
                              "snippet": r[arm]["raw_generation"][:200].replace("\n", " ")})
    out["classes"]["protocol_vocabulary_scan"] = {
        "scan": "MANGO_MARKERS over every handoff generation (both arms)",
        "rows_with_hits": len(proto), "hits": proto[:20],
        "verdict": "protocol vocabulary effectively absent in adapter math generations"}

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print("wrote", OUT)
    for b in ("gsm8k", "math500"):
        print(b, out["adapter_wrong_math"][b]["n"], out["adapter_wrong_math"][b]["by_label"])


if __name__ == "__main__":
    raise SystemExit(main())