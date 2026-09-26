"""Build/reproduce the additive T26 production-runner binding package.

Only disposable synthetic stores are constructed.  No code path opens the
real T26 private store or invokes the official real-evaluation entrypoint.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from t26_protocol.evaluation_v2 import (
    run_public_addendum_leak_scan, verify_addendum_document,
    verify_addendum_freeze, verify_original_v3_components,
)
from t26_protocol.evaluation_v3 import (
    ADDENDUM_PATH, FREEZE_PATH, NEGATIVE_PATH, REHEARSAL_PATH,
    SYNTHETIC_TOKEN, build_addendum_document, build_addendum_freeze,
    build_production_disposable_store, load_ledger,
    run_negative_controls, run_production_disposable_evaluation,
    semantic_view, verify_addendum_document_v2, verify_addendum_freeze_v2,
)
from t26_protocol.lifecycle import T26PrivateStore
from t26_protocol.official_runner import (
    IDENTITY_PATH, build_runner_identity_document,
    verify_runner_identity_document,
)

ROOT = Path(__file__).resolve().parents[1]


def _write(relative: str, value: dict) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def run_pair(*, verify_freeze_document: bool) -> dict:
    runs = []
    for run_index, variant in enumerate((201, 202), start=1):
        with TemporaryDirectory(
                prefix=f"t26-production-runner-{run_index}-") as tmp:
            store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
            construction = build_production_disposable_store(
                ROOT, store, variant)
            result = run_production_disposable_evaluation(
                ROOT, store, token=SYNTHETIC_TOKEN,
                verify_freeze_document=verify_freeze_document)
            runs.append({
                "run": run_index,
                "construction_manifest_schema": "t26-private-manifest-v4",
                "construction_seal_schema":
                    construction["seal"]["schema_version"],
                "semantic": semantic_view(result),
            })
    reproducible = runs[0]["semantic"] == runs[1]["semantic"]
    return {
        "schema_version": "t26-production-runner-rehearsal-pair-v1",
        "artifact": "T26_PRODUCTION_RUNNER_REHEARSAL_PAIR",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if reproducible and all(
            run["semantic"]["status"] == "COMPLETE" for run in runs) else "FAIL",
        "run_count": 2, "scenario_count_per_run": 512,
        "total_synthetic_candidate_executions": 1024,
        "semantic_reproducibility": reproducible, "runs": runs,
        "production_adapter_registry_used": True,
        "integrated_runner_used": True,
        "t25_production_router_provider_used": True,
        "t26_firewall_used": True,
        "external_authority": False, "gold_exposure": 0,
        "real_private_rows_read": 0, "real_candidate_executions": 0,
        "official_evaluator_invocations": 0,
    }


def run_failure(*, verify_freeze_document: bool) -> dict:
    with TemporaryDirectory(prefix="t26-production-runner-failure-") as tmp:
        store = T26PrivateStore(Path(tmp) / "T26-STORE-01", ROOT)
        build_production_disposable_store(ROOT, store, 203)
        injected = False
        try:
            run_production_disposable_evaluation(
                ROOT, store, token=SYNTHETIC_TOKEN,
                inject_failure_after_ledger=True,
                verify_freeze_document=verify_freeze_document)
        except RuntimeError:
            injected = True
        ledger = load_ledger(store)
        verification = ledger.verify()
        retry_refused = False
        try:
            run_production_disposable_evaluation(
                ROOT, store, token=SYNTHETIC_TOKEN,
                verify_freeze_document=verify_freeze_document)
        except Exception:
            retry_refused = True
        passed = (injected and ledger.state == "FAILED" and
                  ledger.document["attempt"] == 1 and retry_refused and
                  verification["status"] == "PASS")
        return {
            "schema_version": "t26-production-runner-failure-rehearsal-v1",
            "artifact": "T26_PRODUCTION_RUNNER_FAILURE_REHEARSAL",
            "classification": "PUBLIC_SAFE",
            "status": "PASS" if passed else "FAIL",
            "state": ledger.state, "attempt": ledger.document["attempt"],
            "event_count": ledger.document["event_count"],
            "event_types": [event["event_type"]
                            for event in ledger.document["events"]],
            "failure_phase": ledger.document["failure"]["failure_phase"],
            "failure_class": ledger.document["failure"]["failure_class"],
            "retry_count": 0, "second_evaluation_refused": retry_refused,
            "candidate_executions": 0, "real_private_rows_read": 0,
        }


def _report(*, verify_freeze_document: bool) -> dict:
    pair = run_pair(verify_freeze_document=verify_freeze_document)
    failure = run_failure(verify_freeze_document=verify_freeze_document)
    return {
        "schema_version": "t26-production-runner-rehearsal-report-v1",
        "artifact": "T26_PRODUCTION_RUNNER_REHEARSAL_REPORT",
        "classification": "PUBLIC_SAFE",
        "status": "PASS" if pair["status"] == failure["status"] == "PASS"
        else "FAIL",
        "pair": pair, "failure": failure,
        "predecessor_mechanics_rehearsals_preserved": True,
        "real_private_rows_read": 0, "real_evaluation_ledger_created": False,
        "real_evaluation_attempts": 0, "real_candidate_executions": 0,
        "official_evaluator_invocations": 0,
    }


def build() -> dict:
    _write(IDENTITY_PATH, build_runner_identity_document(ROOT))
    _write(ADDENDUM_PATH, build_addendum_document(ROOT))
    rehearsal = _report(verify_freeze_document=False)
    _write(REHEARSAL_PATH, rehearsal)
    negative = run_negative_controls(ROOT)
    _write(NEGATIVE_PATH, negative)
    _write(FREEZE_PATH, build_addendum_freeze(ROOT))
    original = verify_original_v3_components(ROOT)
    predecessor_addendum = verify_addendum_document(ROOT)
    predecessor_freeze = verify_addendum_freeze(ROOT)
    identity = verify_runner_identity_document(ROOT)
    addendum = verify_addendum_document_v2(ROOT)
    freeze = verify_addendum_freeze_v2(ROOT)
    status = "PASS" if (
        rehearsal["status"] == negative["status"] == original["status"] ==
        predecessor_freeze["status"] == freeze["status"] == "PASS") else "FAIL"
    return {"status": status, "original_freeze": original,
            "predecessor_addendum_sha256":
                predecessor_addendum["evaluation_implementation_sha256"],
            "predecessor_freeze": predecessor_freeze,
            "runner_factory_identity_root": identity["identity_root"],
            "addendum_evaluation_sha256":
                addendum["evaluation_implementation_sha256"],
            "new_freeze": freeze, "rehearsal": rehearsal,
            "negative_controls": negative}


def reproduce() -> dict:
    original = verify_original_v3_components(ROOT)
    verify_addendum_document(ROOT)
    predecessor = verify_addendum_freeze(ROOT)
    identity = verify_runner_identity_document(ROOT)
    verify_addendum_document_v2(ROOT)
    freeze = verify_addendum_freeze_v2(ROOT)
    expected_rehearsal = json.loads((ROOT / REHEARSAL_PATH)
                                    .read_text(encoding="utf-8"))
    current_rehearsal = _report(verify_freeze_document=True)
    expected_negative = json.loads((ROOT / NEGATIVE_PATH)
                                   .read_text(encoding="utf-8"))
    current_negative = run_negative_controls(ROOT)
    leak = run_public_addendum_leak_scan(ROOT)
    rehearsal_exact = current_rehearsal == expected_rehearsal
    negative_exact = current_negative == expected_negative
    status = "PASS" if (
        original["status"] == predecessor["status"] == freeze["status"] ==
        leak["status"] == "PASS" and rehearsal_exact and negative_exact
    ) else "FAIL"
    return {"status": status, "original_freeze": original,
            "predecessor_freeze": predecessor,
            "runner_factory_identity_root": identity["identity_root"],
            "new_freeze": freeze, "rehearsal_exact": rehearsal_exact,
            "negative_controls_exact": negative_exact,
            "publication_scan": leak, "real_private_rows_read": 0,
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
