"""Build and freeze mango-correction-eval-v1 before any T9 tuning."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations" / "t9" / "correction-suite" / "v1"

DOMAINS = [
    ("arithmetic", "What is 17 + 19?", "36", "42", "numeric_result", "MATH_TOOL"),
    ("algebra", "Simplify 2(x + 3).", "2x + 6", "2x + 3", "symbolic_result", "T4_VERIFIER"),
    ("equations", "Solve x + 7 = 12.", "5", "7", "solution", "T4_VERIFIER"),
    ("calculus", "Differentiate x^3.", "3x^2", "x^2", "derivative", "MATH_TOOL"),
    ("units", "Convert 2 km to metres.", "2000 m", "200 m", "unit_value", "UNIT_CHECK"),
    ("physics", "At 3 m/s for 4 s, how far?", "12 m", "7 m", "numeric_result", "UNIT_CHECK"),
    ("chemistry", "What is the formula of water?", "H2O", "CO2", "claim", "RETRIEVAL_EVIDENCE"),
    ("biology", "Which organelle produces most ATP?", "mitochondrion", "ribosome", "claim", "RETRIEVAL_EVIDENCE"),
    ("mixed_math_science", "Two 3 V cells in series give what voltage?", "6 V", "3 V", "numeric_result", "UNIT_CHECK"),
    ("retrieval_science", "At sea level, water boils at what Celsius temperature?", "100 C", "90 C", "claim", "RETRIEVAL_EVIDENCE"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    classes = ["TRUE_FAIL", "FALSE_FAIL", "PARTIAL_FAIL", "AMBIGUOUS"]
    for i, (domain, question, correct, wrong, component, source) in enumerate(DOMAINS):
        case = classes[i % 4]
        initial = wrong if case == "TRUE_FAIL" else correct
        if case == "PARTIAL_FAIL":
            initial = f"Method is valid; final answer is {wrong}."
        feedback_source = source if case != "AMBIGUOUS" else "UNVERIFIED_MODEL_FEEDBACK"
        rows.append({
            "eval_id": f"mcor-v1-{i + 1:03d}", "case_class": case,
            "domain": domain, "question": question, "initial_answer": initial,
            "expected_answer": correct, "feedback": "The answer failed checking.",
            "feedback_source": feedback_source, "failed_component": component,
            "expected_behavior": ("CHANGE_ANSWER" if case == "TRUE_FAIL" else
                                  "PRESERVE_ANSWER" if case in {"FALSE_FAIL", "AMBIGUOUS"}
                                  else "TARGETED_REPAIR"),
            "mechanical_label": case != "AMBIGUOUS",
        })
    # Rotate the same balanced domains across all four classes (40 total).
    seed = list(rows)
    rows = []
    for cidx, case in enumerate(classes):
        for i, base in enumerate(seed):
            row = dict(base)
            row["eval_id"] = f"mcor-v1-{cidx * 10 + i + 1:03d}"
            row["case_class"] = case
            row["initial_answer"] = (base["initial_answer"] if case == "PARTIAL_FAIL"
                                     else base["expected_answer"] if case != "TRUE_FAIL"
                                     else DOMAINS[i][3])
            row["feedback_source"] = ("UNVERIFIED_MODEL_FEEDBACK" if case == "AMBIGUOUS"
                                      else DOMAINS[i][5])
            row["expected_behavior"] = ("CHANGE_ANSWER" if case == "TRUE_FAIL" else
                                        "TARGETED_REPAIR" if case == "PARTIAL_FAIL"
                                        else "PRESERVE_ANSWER")
            row["mechanical_label"] = case != "AMBIGUOUS"
            rows.append(row)
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=True) for r in rows]
    payload = ("\n".join(lines) + "\n").encode()
    (OUT / "questions.jsonl").write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()
    manifest = {"name": "mango-correction-eval-v1", "frozen": True,
                "questions": len(rows), "class_counts": {c: 10 for c in classes},
                "domains": [d[0] for d in DOMAINS], "sha256": checksum,
                "tuning_performed_before_freeze": False}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (OUT / "checksum.json").write_text(json.dumps({"questions.jsonl": checksum}, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
