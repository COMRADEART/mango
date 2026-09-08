"""Collect T10.18–T10.21 protection battery outputs into
evaluations/t10/protection/ in the shape scripts/t10_final_audit.py reads.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROT = ROOT / "evaluations/t10/protection"


def main() -> int:
    PROT.mkdir(parents=True, exist_ok=True)

    # T10.18 — T4 arm summary (verifier selftest false-PASS gate)
    t4 = ROOT / "evaluations/t8/runs/t10-protect-t4/t4_arm_summary.json"
    if t4.exists():
        (PROT / "t4_arm_summary.json").write_text(t4.read_text(encoding="utf-8"),
                                                  encoding="utf-8")
        print("t4: copied")

    # T10.19 — T5R frozen comparison -> citation integrity + accuracy
    t5r = PROT / "t5r" / "comparison.json"
    if t5r.exists():
        c = json.loads(t5r.read_text(encoding="utf-8"))
        g = c["variants"]["G"]
        cs = g["citation_summary"]
        (PROT / "t5r_audit.json").write_text(json.dumps({
            "citation_integrity": {
                "fabricated": cs.get("n_fabricated"),
                "unsupported": cs.get("n_unsupported"),
                "invalid": cs.get("n_invalid_refs"),
            },
            "accuracy_G": g.get("accuracy"),
            "accuracy_NORAG": c["variants"]["NORAG"].get("accuracy"),
        }, indent=2) + "\n", encoding="utf-8")
        print("t5r: written")

    # T10.20 — capacity overall accuracy from predictions
    cap_preds = PROT / "cap" / "predictions.jsonl"
    if cap_preds.exists():
        rows = [json.loads(l) for l in cap_preds.read_text(encoding="utf-8")
                .splitlines() if l]
        n = len(rows)
        correct = sum(1 for r in rows if r.get("correct"))
        overall = correct / n if n else 0.0
        decomp = {}
        decomp_path = PROT / "cap" / "decomposition.json"
        if decomp_path.exists():
            d = json.loads(decomp_path.read_text(encoding="utf-8"))
            decomp = {k: d.get(k) for k in
                      ("raw_valid_rate", "repaired_valid_rate",
                       "semantic_valid_rate", "executable_rate")
                      if k in d}
        (PROT / "capacity_summary.json").write_text(json.dumps({
            "overall_accuracy": overall, "n": n, "correct": correct,
            "decomposition": decomp,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"capacity: overall={overall:.4f} (n={n})")

    # T10.21 — extraction benchmark
    ext = ROOT / "evaluations/t9/runs/t10-protect-ext/summary.json"
    if ext.exists():
        s = json.loads(ext.read_text(encoding="utf-8"))
        m = s["metrics"]
        (PROT / "extraction_summary.json").write_text(json.dumps({
            "wrong_final_acceptance": m["wrong_final_answer_acceptance"],
            "extraction_recall": m["extraction_recall"],
            "extraction_precision": m["extraction_precision"],
            "false_extraction_acceptance": m["false_extraction_acceptance"],
        }, indent=2) + "\n", encoding="utf-8")
        print("extraction: written")
    return 0


if __name__ == "__main__":
    sys.exit(main())