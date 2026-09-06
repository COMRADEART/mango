"""T4 failure-type classification (STEP 4 of the T4 closing protocol).

Classifies every non-PASS row of a tool-enabled predictions.jsonl into one
dominant failure type, from saved rows + the tool-call audit log ONLY
(no re-inference). Emits counts + per-case listing.

Usage:
    python scripts/classify_t4_failures.py [predictions.jsonl] [tool_calls.jsonl]
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_PRED = ROOT / "evaluations/tool-suite/v1/Qwen3-1.7B/tool/predictions.jsonl"
DEFAULT_CALLS = ROOT / "evaluations/tool-suite/v1/Qwen3-1.7B/tool/tool_calls.jsonl"


def classify_row(row: dict, calls: list[dict]) -> str:
    """Dominant failure type for one non-PASS tool-enabled row."""
    verdict = row.get("verdict")
    method = row.get("verdict_method") or ""
    errors = [c for c in calls if c.get("status") == "error"]
    oks = [c for c in calls if c.get("status") == "ok"]

    if row.get("error"):
        return "OTHER"

    if verdict == "UNKNOWN":
        if method in ("no_answer", "no_answer_extracted"):
            return "EXTRACTION_FAILURE"
        if method == "timeout":
            return "TOOL_TIMEOUT"
        if method == "mcq_parse":
            return "EXTRACTION_FAILURE"
        if errors:
            code = (errors[0].get("error") or {}).get("code", "")
            if code == "TIMEOUT":
                return "TOOL_TIMEOUT"
            return "TOOL_ENGINE_ERROR"
        return "VERIFIER_UNKNOWN"

    # verdict == FAIL
    if errors:
        code = (errors[0].get("error") or {}).get("code", "")
        if code == "TIMEOUT":
            return "TOOL_TIMEOUT"
        if code in ("INVALID_INPUT", "PARSE_ERROR",
                    "DISALLOWED_EXPRESSION"):
            return "TOOL_ARGUMENT_EXTRACTION"
        if code in ("UNKNOWN_UNIT", "INCOMPATIBLE_UNITS"):
            return "TOOL_UNSUPPORTED_OPERATION"
        return "TOOL_ENGINE_ERROR"
    if oks:
        # a deterministic tool succeeded; the final answer was still wrong
        return "MODEL_IGNORED_TOOL_RESULT"
    if method in ("numeric", "symbolic_equivalence", "equation",
                  "solution_set", "quantity", "text_match",
                  "normalized_string", "mcq_letter", "mcq_value"):
        return "MODEL_REASONING_FAILURE"
    return "OTHER"


def main() -> None:
    pred_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PRED
    calls_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CALLS

    calls_by_q: dict[str, list[dict]] = defaultdict(list)
    if calls_path.exists():
        for line in open(calls_path, encoding="utf-8"):
            if line.strip():
                c = json.loads(line)
                calls_by_q[c["question_id"]].append(c)

    rows = [json.loads(l) for l in open(pred_path, encoding="utf-8")
            if l.strip()]
    bad = [r for r in rows if r.get("verdict") != "PASS"]
    counts: Counter = Counter()
    detail: dict[str, list[str]] = defaultdict(list)
    for r in bad:
        t = classify_row(r, calls_by_q.get(r["eval_id"], []))
        counts[t] += 1
        detail[t].append(f"{r['eval_id']} [{r.get('category')}] "
                         f"exp={r.get('expected_answer')!r} "
                         f"got={r.get('extracted_answer')!r}")

    print(f"non-PASS rows: {len(bad)} / {len(rows)}")
    for t, n in counts.most_common():
        print(f"\n== {t}: {n}")
        for d in detail[t]:
            print("  ", d)


if __name__ == "__main__":
    main()