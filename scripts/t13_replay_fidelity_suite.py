"""T13.16 — frozen fidelity-v1 suite replay through the T13 classifier.

Replays every mutation in the frozen T12 fidelity suite
(sha256 f598825c...) through the repaired T13 classifier, using the
exact request construction from ``build_t12_suites.py``.  Requirements:

* all declared mutations still FAIL the fidelity gate (protection
  preserved — no weakening);
* faithful requests of kind FAITHFUL/FLAG classify without exception;
* the suite file itself is byte-frozen (checksum verified).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sciencemath.scicomp.fidelity import (  # noqa: E402
    FIDELITY_FAIL, P_USER_GIVEN, check_fidelity)

SUITE = ROOT / "evaluations/t12/suites/fidelity/v1"
DECLARED = "f598825c7823f30af1f5162e8d754542f80b10bd99608f4310e0594e93cadd7e"
OUT = ROOT / "evaluations/t13/fidelity_suite_replay_t13.json"


def replay() -> dict:
    rows = [json.loads(l) for l in
            (SUITE / "questions.jsonl").read_text(encoding="utf-8")
            .splitlines() if l.strip()]
    digest = hashlib.sha256(
        (SUITE / "questions.jsonl").read_bytes()).hexdigest()

    mutation_results = []
    exceptions = []
    faithful_results = []
    for it in rows:
        if it.get("mutating_inputs"):
            request = {
                "operation": it["operation"],
                "compute_required": True,
                "parameters": it["mutating_inputs"],
                "source_inputs": it["faithful_inputs"],
                "parameter_provenance": {k: P_USER_GIVEN
                                         for k in it["mutating_inputs"]},
                "expected_result_type": "scalar",
                "reason_for_compute": "T13.16 fidelity-suite replay",
            }
            try:
                r = check_fidelity(request, it["question"])
                rejected = r.status == FIDELITY_FAIL
                mutation_results.append({
                    "eval_id": it["eval_id"],
                    "category": it["category"],
                    "rejected": rejected,
                    "status": r.status,
                    "failures": r.failures[:4],
                })
            except Exception as exc:
                exceptions.append(f"{it['eval_id']}: "
                                  f"{type(exc).__name__}: {exc}")
        elif it["kind"] in ("FAITHFUL", "FLAG", "REJECT", "CONTROL"):
            # faithful side must classify without exception; kind REJECT /
            # CONTROL rows are engine-level rejects, fidelity may pass or
            # fail them (engine decides) — only exceptions are defects.
            request = {
                "operation": it["operation"],
                "compute_required": True,
                "parameters": it["faithful_inputs"],
                "source_inputs": it["faithful_inputs"],
                "parameter_provenance": {k: P_USER_GIVEN
                                         for k in it["faithful_inputs"]},
                "expected_result_type": "scalar",
                "reason_for_compute": "T13.16 fidelity-suite replay",
            }
            try:
                r = check_fidelity(request, it["question"])
                faithful_results.append({
                    "eval_id": it["eval_id"], "kind": it["kind"],
                    "status": r.status})
            except Exception as exc:
                exceptions.append(f"{it['eval_id']} faithful: "
                                  f"{type(exc).__name__}: {exc}")

    n_mut = len(mutation_results)
    n_rej = sum(1 for m in mutation_results if m["rejected"])
    return {
        "milestone": "T13.16 fidelity-v1 suite replay (T13 classifier)",
        "suite_sha256": digest,
        "checksum_matches_t12_freeze": digest == DECLARED,
        "n_rows": len(rows),
        "n_mutations": n_mut,
        "mutations_still_rejected": n_rej,
        "mutation_rejection_intact": n_rej == n_mut and not exceptions,
        "classifier_exceptions": exceptions,
        "faithful_classifications": faithful_results,
        "mutation_results": mutation_results,
    }


def main() -> int:
    out = replay()
    Path(OUT).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"checksum match: {out['checksum_matches_t12_freeze']}")
    print(f"mutations: {out['n_mutations']}  still rejected: "
          f"{out['mutations_still_rejected']}")
    print(f"exceptions: {out['classifier_exceptions']}")
    print(f"protection intact: {out['mutation_rejection_intact']}")
    if not out["mutation_rejection_intact"]:
        bad = [m for m in out["mutation_results"] if not m["rejected"]]
        print(json.dumps(bad, indent=1))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())