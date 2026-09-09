"""T13.13 — measure the T13 classifier on the frozen
mango-scicomp-fidelity-transform-v1 benchmark (FINAL split only).

Metrics (T13.13):
* equivalent-case recall   — approved / declared-approved
* mutation rejection recall — rejected / declared-rejected
* false mutation acceptance — declared-rejected cases approved (must be 0)
* classifier exception rate — exceptions / cases (must be 0)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.fidelity import (  # noqa: E402
    FIDELITY_FAIL, check_fidelity, classify_transformation,
    validate_planner_request)

SUITE = ROOT / "evaluations/t13/suites/fidelity-transform/v1"
APPROVED_CLASSES = {"EXACT", "REPRESENTATION_EQUIVALENT",
                    "UNIT_EQUIVALENT", "STRUCTURE_EQUIVALENT"}


def measure(rows: list[dict]) -> dict:
    per_case = []
    exceptions = 0
    for row in rows:
        rec = {"case_id": row["case_id"], "expected": row["expected"]}
        try:
            if row["level"] == "transform":
                verdict = classify_transformation(
                    row["source"], row["compute"], row.get("role"))
                approved = verdict["semantic_equivalence_verified"]
                rec["t13_class"] = verdict.get("t13_class")
                rec["reason"] = verdict.get("reason")
            else:
                # pipeline order (matches t12_scicomp_eval.py): the schema
                # gate runs first; check_fidelity only sees schema-valid
                # requests.
                schema = validate_planner_request(row["request"])
                if not schema["ok"]:
                    approved = False
                    failures = [f"schema:{f}" for f in schema["failures"]]
                else:
                    fid = check_fidelity(row["request"], row["question"])
                    approved = fid.status != FIDELITY_FAIL
                    failures = fid.failures
                rec["failures"] = failures[:6]
                if row["expected"] == "INFORMATION_ADDED" and approved \
                        is False:
                    rec["class_hit"] = any(
                        f.startswith("no_source_input") for f in failures)
                elif row["expected"] == "INFORMATION_REMOVED" and \
                        approved is False:
                    rec["class_hit"] = any(
                        f.startswith("source_input_dropped")
                        for f in failures)
        except Exception as exc:  # exception rate must be 0
            exceptions += 1
            rec["exception"] = f"{type(exc).__name__}: {exc}"
            approved = None
        rec["approved"] = approved
        per_case.append(rec)

    declared_ok = [r for r in per_case
                   if r["expected"] in APPROVED_CLASSES or
                   r["expected"] == "FIDELITY_OK"]
    declared_rej = [r for r in per_case
                    if r["expected"] not in APPROVED_CLASSES and
                    r["expected"] != "FIDELITY_OK"]
    eq_recall = (sum(1 for r in declared_ok if r["approved"] is True)
                 / len(declared_ok)) if declared_ok else None
    mut_reject = (sum(1 for r in declared_rej if r["approved"] is False)
                  / len(declared_rej)) if declared_rej else None
    false_accept = [r for r in declared_rej if r["approved"] is True]
    false_reject = [r for r in declared_ok if r["approved"] is False]

    # class-level agreement on transform cases
    cls_mismatch = [r for r in per_case
                    if r["expected"] in APPROVED_CLASSES
                    and r["approved"] is True
                    and r.get("t13_class") != r["expected"]]

    return {
        "n_cases": len(per_case),
        "exceptions": exceptions,
        "equivalent_recall": eq_recall,
        "mutation_rejection_recall": mut_reject,
        "false_accepts": [r["case_id"] for r in false_accept],
        "false_rejects": [{"case": r["case_id"], "got": r.get("t13_class"),
                           "reason": r.get("reason"),
                           "failures": r.get("failures")}
                          for r in false_reject],
        "class_mismatches": [{"case": r["case_id"],
                              "expected": r["expected"],
                              "got": r.get("t13_class")}
                             for r in cls_mismatch],
        "per_case": per_case,
    }


def main() -> int:
    digest = hashlib.sha256(
        (SUITE / "questions.jsonl").read_bytes()).hexdigest()
    declared = (SUITE / "checksum.txt").read_text().strip()
    rows = [json.loads(l) for l in
            (SUITE / "questions.jsonl").read_text(encoding="utf-8")
            .splitlines() if l.strip()]
    final = [r for r in rows if r["split"] == "final"]
    result = measure(final)
    result["suite_sha256"] = digest
    result["checksum_matches_freeze"] = digest == declared
    out = ROOT / "evaluations/t13/transform_benchmark_results.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"checksum match: {digest == declared}  cases: {result['n_cases']}")
    print(f"exceptions: {result['exceptions']}")
    print(f"equivalent recall: {result['equivalent_recall']}")
    print(f"mutation rejection recall: {result['mutation_rejection_recall']}")
    print(f"false accepts: {result['false_accepts']}")
    print(f"false rejects: {json.dumps(result['false_rejects'], indent=1)}")
    print(f"class mismatches: {result['class_mismatches']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())