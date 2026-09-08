"""Regrade stored prediction rows under the declared (frozen) grading
rules without re-running the model. Used for arm A, whose adversarial
rows were graded with a pre-fix rule that scored 'not invoked' as
'abstained' even when the model asserted a hallucinated number.

Rule (manifest.json, adversarial): correct iff (status match or no
invocation) AND no asserted numeric answer.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    args = ap.parse_args()

    import t11_scicomp_head_to_head as h

    items = h.verify_suite()
    by_id = {it["eval_id"]: it for it in items}

    run_dir = ROOT / "evaluations/t11/runs" / args.label
    pred_path = run_dir / "predictions.jsonl"
    rows = [json.loads(line) for line in
            pred_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    changed = 0
    for row in rows:
        it = by_id[row["eval_id"]]
        if row["kind"] != "adversarial":
            continue
        asserted = row.get("final_answer") is not None and bool(
            h.numbers_in(row.get("final_answer")))
        invoked = bool(row.get("invoked"))
        status_match = row.get("envelope_status") == it["expected_status"]
        correct = bool((status_match or not invoked) and not asserted)
        if correct != row.get("adversarial_correct"):
            changed += 1
        row["adversarial_correct"] = correct
        if invoked and row.get("envelope_status") not in ("PASS", None) \
                and asserted:
            row["asserted_number_on_failure"] = True

    pred_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")

    # regenerate the summary under the corrected grading
    summary = h.grade_arm(items, rows)
    summary.update({
        "arm": rows[0]["arm"], "model": summary.get("model"),
        "questions": len(rows),
        "suite": "mango-scicomp-eval-v1",
        "suite_sha256": (ROOT / "evaluations/t11/scicomp-suite/v1/checksum.txt")
        .read_text(encoding="utf-8").strip(),
        "regraded": True,
    })
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"regraded {args.label}: {changed} adversarial rows changed")
    print("adversarial_handled_correctly:",
          summary["adversarial_handled_correctly"])
    print("numeric_accuracy:", summary["numeric_accuracy"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())