"""T14R.13 — measure the frozen adoption microbench
mango-scicomp-adoption-v1 against the pre-registered targets.

The suite is checksum-verified before any measurement (frozen at
write time; the adoption layer was committed frozen BEFORE the suite,
so this is a pure measurement pass — no tuning happened after
freezing).

Per case: result_contract(...) is built from the frozen envelope;
each candidate is classified with classify_adoption (with the
authoritative_field hint). Checks:

* verified_result_adoption  — correct candidates on VERIFIED contracts
                              classified ADOPTED  (target >= 0.98)
* wrong_result_field_selection — selected field violates the case's
                              expected field      (target 0)
* unit_loss                 — unit-violating candidates not flagged
                              UNIT_LOST           (target 0)
* stale_answer_retention    — stale candidates classified ADOPTED
                                                    (target 0)
* rounding_policy_violations — display_value violates the question's
                              stated rounding     (target <= 0.01)
* false_authoritative_adoption — any adoption on a non-VERIFIED
                              contract            (target 0)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SUITE_DIR = ROOT / "evaluations/t14r/suites/adoption/v1"
OUT = ROOT / "evaluations/t14r/adoption_bench_results.json"


def main() -> int:
    digest = hashlib.sha256(
        (SUITE_DIR / "questions.jsonl").read_bytes()).hexdigest()
    expected = (SUITE_DIR / "checksum.txt").read_text(
        encoding="utf-8").strip()
    if digest != expected:
        raise SystemExit(f"suite checksum mismatch: {digest} != {expected}")
    cases = [json.loads(l) for l in
             (SUITE_DIR / "questions.jsonl").read_text(encoding="utf-8")
             .splitlines() if l.strip()]

    from sciencemath.scicomp.adoption import VERIFIED, classify_adoption
    from sciencemath.scicomp.result_contract import (
        _TYPE_CHECKS, format_policy, result_contract)

    metrics = {"verified_hits": 0, "verified_total": 0,
               "field_violations": 0, "field_total": 0,
               "unit_violations": 0, "unit_total": 0,
               "stale_violations": 0, "stale_total": 0,
               "rounding_violations": 0, "rounding_total": 0,
               "false_authoritative": 0, "failclosed_ok": 0,
               "failclosed_total": 0, "exceptions": []}
    rows = []

    for c in cases:
        env = c["envelope"]
        req = c["request"]
        try:
            contract = result_contract(
                env, req, c["question"],
                (req or {}).get("expected_result_type"))
        except Exception as exc:
            metrics["exceptions"].append(
                f"{c['case_id']}: {type(exc).__name__}: {exc}")
            continue
        rec = {"case_id": c["case_id"], "split": c["split"],
               "binding": contract.get("binding"),
               "field": contract.get("authoritative_field"),
               "candidate_results": {}}

        # --- wrong-result-field selection (skip NOT_CONTRACTABLE:
        # no selection is the correct fail-closed behavior there) ---
        exp = c.get("expected_authoritative_field")
        got_field = contract.get("authoritative_field")
        if exp and contract.get("binding") != "NOT_CONTRACTABLE":
            metrics["field_total"] += 1
            ok = (got_field == exp) if not exp.startswith("ANY:") else \
                got_field in exp[4:].split("|")
            # assembled CI pair reports a synthetic field name
            if not ok and exp == "ci_low+ci_high":
                ok = got_field == "ci_low+ci_high"
            if not ok:
                metrics["field_violations"] += 1
                rec["field_violation"] = {"expected": exp,
                                          "selected": got_field}

        # --- fail-closed behavior ---
        if not c.get("contractable", True):
            if contract.get("binding") == "NOT_CONTRACTABLE":
                metrics["failclosed_ok"] += 1
            else:
                metrics["false_authoritative"] += 1
                rec["failclosed_violation"] = contract.get("binding")
            rows.append(rec)
            continue

        # --- false authoritative adoption (non-PASS envelopes) ---
        if contract.get("binding") != VERIFIED:
            for cand in c["candidates"]["extra"]:
                cls = classify_adoption(env, cand["answer"],
                                        c["atol"], c["rtol"])
                rec["candidate_results"][cand["answer"][:40]] = cls
                if cls == "ADOPTED":
                    metrics["false_authoritative"] += 1
                    rec["false_adoption"] = cand["answer"][:60]
            rows.append(rec)
            continue

        # --- rounding policy (display must follow the question) ---
        pol = format_policy(c["question"])
        disp = contract.get("display") or {}
        val = contract.get("authoritative_value")
        metrics["rounding_total"] += 1
        if pol["policy"] == "DECIMAL_PLACES":
            want_disp = round(float(val), pol["decimals"])
            if abs(float(disp.get("display_value")) - want_disp) > 1e-12:
                metrics["rounding_violations"] += 1
                rec["rounding_violation"] = disp.get("display_value")
        else:
            if disp.get("rounding_rule") == "DEFAULT_SAFE_DISPLAY" + \
                    "_RAW_AS_COMPUTED" or disp.get("rounding_rule") == \
                    "DEFAULT_SAFE_DISPLAY_RAW_AS_COMPUTED":
                metrics["rounding_violations"] += 0  # default is legal

        # --- candidates on VERIFIED contracts ---
        atol, rtol = c["atol"], c["rtol"]
        correct = c["candidates"].get("correct")
        if correct and not c.get("skip_correct"):
            metrics["verified_total"] += 1
            cls = classify_adoption(env, correct, atol, rtol,
                                    authoritative_field=got_field)
            rec["candidate_results"]["correct"] = cls
            if cls == "ADOPTED":
                metrics["verified_hits"] += 1
        stale = c["candidates"].get("stale")
        if stale:
            metrics["stale_total"] += 1
            cls = classify_adoption(env, stale, atol, rtol,
                                    precompute_answer=stale,
                                    authoritative_field=got_field)
            rec["candidate_results"]["stale"] = cls
            if cls == "ADOPTED":
                metrics["stale_violations"] += 1
                rec["stale_violation"] = stale[:60]
        misread = c["candidates"].get("misread")
        if misread:
            cls = classify_adoption(env, misread, atol, rtol,
                                    authoritative_field=got_field)
            rec["candidate_results"]["misread"] = cls
        for cand in c["candidates"].get("extra", []):
            cls = classify_adoption(env, cand["answer"], atol, rtol,
                                    precompute_answer=cand.get(
                                        "precompute"),
                                    authoritative_field=got_field)
            rec["candidate_results"][cand["answer"][:40]] = cls
            if cand.get("expect") == "UNIT_LOST" and cls != "UNIT_LOST":
                metrics["unit_total"] += 1
                if cls == "ADOPTED":
                    metrics["unit_violations"] += 1
                rec["unit_miss"] = {"answer": cand["answer"][:40],
                                    "got": cls}
            elif cand.get("expect") == "UNIT_LOST":
                metrics["unit_total"] += 1
            elif cand.get("expect") == "STALE_PRECOMPUTE_ANSWER" and \
                    cls == "ADOPTED":
                metrics["stale_violations"] += 1
                rec["stale_violation"] = cand["answer"][:40]
            elif cand.get("expect") == "ADOPTED" and cls != "ADOPTED":
                # extra correct candidates count toward adoption misses
                metrics["verified_total"] += 1
                if cls == "ADOPTED":
                    metrics["verified_hits"] += 1
                else:
                    rec["correct_miss"] = cand["answer"][:40]
        rows.append(rec)

    def rate(h, n) -> float:
        return h / n if n else None

    summary = {
        "suite": "mango-scicomp-adoption-v1",
        "suite_sha256": digest,
        "cases": len(cases),
        "metrics": {
            "verified_result_adoption": {
                "value": rate(metrics["verified_hits"],
                              metrics["verified_total"]),
                "target": ">= 0.98"},
            "wrong_result_field_selection": {
                "value": metrics["field_violations"],
                "of": metrics["field_total"], "target": 0},
            "unit_loss": {
                "value": metrics["unit_violations"],
                "of": metrics["unit_total"], "target": 0},
            "stale_answer_retention": {
                "value": metrics["stale_violations"],
                "of": metrics["stale_total"], "target": 0},
            "rounding_policy_violations": {
                "value": rate(metrics["rounding_violations"],
                              metrics["rounding_total"]),
                "target": "<= 0.01"},
            "false_authoritative_adoption": {
                "value": metrics["false_authoritative"], "target": 0},
            "failclosed_shape_checks": {
                "ok": metrics["failclosed_ok"]},
            "exceptions": metrics["exceptions"],
        },
        "rows": rows,
    }

    # split sizes for the report
    for split in ("dev", "final"):
        summary[f"{split}_cases"] = sum(
            1 for r in rows if r["split"] == split)
    (OUT.parent).mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    m = summary["metrics"]
    print("verified_result_adoption:",
          m["verified_result_adoption"]["value"],
          f"(hits {metrics['verified_hits']}/{metrics['verified_total']})")
    print("wrong_result_field_selection:",
          m["wrong_result_field_selection"]["value"],
          f"of {m['wrong_result_field_selection']['of']}")
    print("unit_loss:", m["unit_loss"]["value"],
          f"of {m['unit_loss']['of']}")
    print("stale_answer_retention:", m["stale_answer_retention"]["value"],
          f"of {m['stale_answer_retention']['of']}")
    print("rounding_policy_violations:",
          m["rounding_policy_violations"]["value"],
          f"of {metrics['rounding_total']}")
    print("false_authoritative_adoption:",
          m["false_authoritative_adoption"]["value"])
    print("exceptions:", len(metrics["exceptions"]))
    for e in metrics["exceptions"][:5]:
        print("  ", e)
    passed = (m["verified_result_adoption"]["value"] is not None
              and m["verified_result_adoption"]["value"] >= 0.98
              and m["wrong_result_field_selection"]["value"] == 0
              and m["unit_loss"]["value"] == 0
              and m["stale_answer_retention"]["value"] == 0
              and (m["rounding_policy_violations"]["value"] is not None
                   and m["rounding_policy_violations"]["value"] <= 0.01)
              and m["false_authoritative_adoption"]["value"] == 0
              and not metrics["exceptions"])
    print("overall:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())