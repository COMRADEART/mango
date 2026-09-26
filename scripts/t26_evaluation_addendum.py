"""Build and reproduce the public-safe T26 evaluation addendum.

No code path in this script opens the real T26 store.  Every evaluation uses
an isolated disposable V3-seal/V4-manifest store under a temporary directory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from t26_protocol.evaluation_v2 import (
    SYNTHETIC_TOKEN, build_addendum_document,
    build_addendum_freeze, build_disposable_sealed_store,
    disposable_runner_factory, load_evaluation_ledger,
    run_disposable_evaluation, run_negative_controls,
    run_public_addendum_leak_scan, semantic_evaluation_view,
    verify_addendum_document, verify_addendum_freeze,
    verify_original_v3_components,
)
from t26_protocol.lifecycle import T26PrivateStore

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluations/t26"
ADDENDUM = OUT / "T26_EVALUATION_PROTOCOL_ADDENDUM.json"
REHEARSAL = OUT / "T26_EVALUATION_REHEARSAL_REPORT.json"
NEGATIVE = OUT / "T26_EVALUATION_NEGATIVE_CONTROLS.json"
FREEZE = OUT / "T26_EVALUATION_ADDENDUM_FREEZE.json"


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def run_pair(*, verify_freeze_document: bool) -> dict:
    runs = []
    for run_index, variant in enumerate((101, 102), start=1):
        with TemporaryDirectory(prefix=f"t26-evaluation-v2-{run_index}-") as tmp:
            store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
            construction = build_disposable_sealed_store(ROOT, store, variant)
            result = run_disposable_evaluation(
                ROOT, store, token=SYNTHETIC_TOKEN,
                runner_factory=disposable_runner_factory(variant),
                verify_freeze_document=verify_freeze_document)
            view = semantic_evaluation_view(result)
            runs.append({
                "run": run_index,
                "construction_manifest_schema":
                    construction["seal"]["schema_version"].replace(
                        "t26-holdout-seal-v3", "t26-private-manifest-v4"),
                "construction_seal_schema": construction["seal"]["schema_version"],
                "semantic": view,
            })
    first = dict(runs[0]["semantic"])
    second = dict(runs[1]["semantic"])
    reproducible = first == second
    return {
        "schema_version": "t26-evaluation-v2-rehearsal-pair-v1",
        "artifact": "T26_EVALUATION_V2_REHEARSAL_PAIR",
        "status": "PASS" if reproducible and all(
            run["semantic"]["status"] == "COMPLETE" for run in runs) else "FAIL",
        "run_count": 2,
        "scenario_count_per_run": 512,
        "total_synthetic_candidate_executions": 1024,
        "semantic_reproducibility": reproducible,
        "runs": runs,
        "real_private_rows_read": 0,
        "real_candidate_executions": 0,
        "official_evaluator_invocations": 0,
    }


def run_failure(*, verify_freeze_document: bool) -> dict:
    with TemporaryDirectory(prefix="t26-evaluation-v2-failure-") as tmp:
        store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
        build_disposable_sealed_store(ROOT, store, 103)
        injected = False
        try:
            run_disposable_evaluation(
                ROOT, store, token=SYNTHETIC_TOKEN,
                runner_factory=disposable_runner_factory(103),
                inject_failure_after_ledger=True,
                verify_freeze_document=verify_freeze_document)
        except RuntimeError:
            injected = True
        ledger = load_evaluation_ledger(store)
        verification = ledger.verify()
        retry_refused = False
        try:
            run_disposable_evaluation(
                ROOT, store, token=SYNTHETIC_TOKEN,
                runner_factory=disposable_runner_factory(103),
                verify_freeze_document=verify_freeze_document)
        except Exception:
            retry_refused = True
        passed = (injected and ledger.state == "FAILED" and
                  ledger.document["attempt"] == 1 and retry_refused and
                  verification["status"] == "PASS")
        return {
            "schema_version": "t26-evaluation-v2-failure-rehearsal-v1",
            "artifact": "T26_EVALUATION_V2_FAILURE_REHEARSAL",
            "status": "PASS" if passed else "FAIL",
            "state": ledger.state,
            "attempt": ledger.document["attempt"],
            "event_count": ledger.document["event_count"],
            "event_types": [event["event_type"]
                            for event in ledger.document["events"]],
            "failure_phase": ledger.document["failure"]["failure_phase"],
            "failure_class": ledger.document["failure"]["failure_class"],
            "retry_count": 0,
            "second_evaluation_refused": retry_refused,
            "candidate_executions": 0,
            "real_private_rows_read": 0,
        }


def build() -> dict:
    _write(ADDENDUM, build_addendum_document(ROOT))
    rehearsal = {
        "schema_version": "t26-evaluation-v2-rehearsal-report-v1",
        "artifact": "T26_EVALUATION_V2_REHEARSAL_REPORT",
        "classification": "PUBLIC_SAFE",
        "status": "PASS",
        "pair": run_pair(verify_freeze_document=False),
        "failure": run_failure(verify_freeze_document=False),
        "real_private_rows_read": 0,
        "real_evaluation_ledger_created": False,
        "real_evaluation_attempts": 0,
        "official_evaluator_invocations": 0,
    }
    if rehearsal["pair"]["status"] != "PASS" or rehearsal["failure"]["status"] != "PASS":
        rehearsal["status"] = "FAIL"
    _write(REHEARSAL, rehearsal)
    negative = run_negative_controls(ROOT)
    _write(NEGATIVE, negative)
    _write(FREEZE, build_addendum_freeze(ROOT))
    original = verify_original_v3_components(ROOT)
    frozen = verify_addendum_freeze(ROOT)
    return {"status": "PASS" if rehearsal["status"] == negative["status"] ==
            original["status"] == frozen["status"] == "PASS" else "FAIL",
            "rehearsal": rehearsal, "negative_controls": negative,
            "original_freeze": original, "addendum_freeze": frozen}


def reproduce() -> dict:
    verify_addendum_document(ROOT)
    original = verify_original_v3_components(ROOT)
    frozen = verify_addendum_freeze(ROOT)
    expected_rehearsal = json.loads(REHEARSAL.read_text(encoding="utf-8"))
    current_rehearsal = {
        "schema_version": "t26-evaluation-v2-rehearsal-report-v1",
        "artifact": "T26_EVALUATION_V2_REHEARSAL_REPORT",
        "classification": "PUBLIC_SAFE",
        "status": "PASS",
        "pair": run_pair(verify_freeze_document=True),
        "failure": run_failure(verify_freeze_document=True),
        "real_private_rows_read": 0,
        "real_evaluation_ledger_created": False,
        "real_evaluation_attempts": 0,
        "official_evaluator_invocations": 0,
    }
    if current_rehearsal["pair"]["status"] != "PASS" or current_rehearsal["failure"]["status"] != "PASS":
        current_rehearsal["status"] = "FAIL"
    expected_negative = json.loads(NEGATIVE.read_text(encoding="utf-8"))
    current_negative = run_negative_controls(ROOT)
    leak = run_public_addendum_leak_scan(ROOT)
    rehearsal_exact = current_rehearsal == expected_rehearsal
    negative_exact = current_negative == expected_negative
    status = "PASS" if (rehearsal_exact and negative_exact and
                         original["status"] == frozen["status"] ==
                         leak["status"] == "PASS") else "FAIL"
    return {"status": status, "rehearsal_exact": rehearsal_exact,
            "negative_controls_exact": negative_exact,
            "original_freeze": original, "addendum_freeze": frozen,
            "publication_scan": leak,
            "real_private_rows_read": 0,
            "real_candidate_executions": 0,
            "official_evaluator_invocations": 0,
            "real_evaluation_ledger_created": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "reproduce"))
    args = parser.parse_args()
    result = build() if args.mode == "build" else reproduce()
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
