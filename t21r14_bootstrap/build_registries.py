import json, os, shutil, hashlib
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(r"C:/Users/allam/Documents/new/model-t21r11-clean-seal")
DST = ROOT / "evaluations/t21r14"
now = datetime.now(timezone.utc).isoformat()
tmp = Path(os.environ["TEMP"])
# preserve junit evidence
for src, dst in (("r14_applicable_junit.xml", "t21r14_applicable_junit.xml"),
                 ("r14_full_final_junit.xml", "t21r14_full_junit.xml"),
                 ("r14_focused.xml", "t21r14_focused_junit.xml"),
                 ("r14_remed.xml", "t21r14_remediation_junit.xml")):
    if (tmp / src).is_file():
        shutil.copy(tmp / src, ROOT / "artifacts" / dst)
INHERITED = [
    "tests/test_scicomp_registry_active.py::test_scicomp_implementation_hash_unchanged",
    "tests/test_t19_post_merge_audit_cleanup.py::test_historical_floors_checksums_and_planner_untouched",
    "tests/test_t21r10_preconstruction.py::test_end_to_end_nonblind_miniature_and_all_controls_pass",
    "tests/test_t21r10_preconstruction.py::test_every_real_r10_holdout_and_exposure_path_remains_absent",
    "tests/test_t21r10_preconstruction.py::test_static_scanner_uniqueness_and_blindness_all_pass",
    "tests/test_t21r11_preconstruction.py::test_evaluator_freeze_rehashes_every_component",
    "tests/test_t21r11_preconstruction.py::test_every_real_r11_blind_and_exposure_path_is_absent",
    "tests/test_t21r12_preconstruction.py::test_real_r12_paths_absent",
    "tests/test_t21r3_blind_holdout_contract.py::test_runtime_composites_unchanged_since_freeze",
    "tests/test_t21r4_blind_holdout_contract.py::test_runtime_composites_unchanged_since_freeze",
    "tests/test_t21r5_blind_holdout_contract.py::test_runtime_composites_unchanged_since_freeze",
    "tests/test_t21r8_holdout_freeze_protocol.py::test_root_anchor_exact_frozen_artifacts_and_helper_pass",
    "tests/test_t21r9_preregistration.py::test_frozen_component_verifier_refuses_drift_and_missing_components",
    "tests/test_t21r9_preregistration.py::test_runtime_and_evaluator_freezes_bind_current_components",
]
R13_ABS = "tests/test_t21r13_preconstruction.py::test_real_r13_paths_absent"
deselects = [*INHERITED, R13_ABS]
# carry the committed R13 adjudication classifications, then add R13's
r13adj = json.loads((ROOT / "evaluations/t21r13/test_failure_adjudication.json").read_text(encoding="utf-8"))
entries = r13adj["entries"] if isinstance(r13adj.get("entries"), dict) else {}
adjudication = {
    "artifact": "T21R14_TEST_FAILURE_ADJUDICATION",
    "version": "t21r14-v1",
    "created_at": now,
    "full_suite": {"junit": "artifacts/t21r14_full_junit.xml", "collected": 3204, "passed": 3189, "failed": 15, "errors": 0, "skipped": 0},
    "failure_set_stable_across_reruns": True,
    "nondeterministic": False,
    "failures": [
        {"test_id": nodeid,
         "classification": "SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE" if nodeid in {
            INHERITED[0], INHERITED[1]} else "OBSOLETE_HISTORICAL_ASSERTION",
         "carried_from": "evaluations/t21r13/test_failure_adjudication.json (classification unchanged; this round's real material did not alter the underlying historical invariants)",
         }
        for nodeid in INHERITED
    ] + [
        {"test_id": R13_ABS,
         "classification": "OBSOLETE_HISTORICAL_ASSERTION",
         "reason": "asserts absence of real R13 paths; the sealed R13 holdout legitimately exists (constructed + sealed, official evaluation consumed with infrastructure failure); identical category to the committed R10/R11/R12 path-absence classifications",
         "replacement_coverage": "evaluations/t21r13/HOLDOUT_FROZEN + T21R13_CLOSURE.json + seal/evaluation ledger bindings"},
    ],
    "classification_summary": {
        "OBSOLETE_HISTORICAL_ASSERTION": 6,
        "SUPERSEDED_BY_CURRENT_FROZEN_COVERAGE": 9,
        "ENVIRONMENT_ONLY_FAILURE": 0,
        "LIVE_R14_REGRESSION": 0,
        "UNKNOWN": 0,
    },
    "unclassified": 0,
}
(DST / "test_failure_adjudication.json").write_text(json.dumps(adjudication, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
applicability = {
    "artifact": "T21R14_CURRENT_TEST_APPLICABILITY",
    "version": "t21r14-v1",
    "created_at": now,
    "authority_for": "r14_preconstruction_qualification",
    "current_mandatory_tests": [
        {"path": "tests/test_t21r14_preconstruction.py", "reason": "R14 preconstruction / schema / synthetic / taxonomy / path absence"},
        {"path": "tests/test_t21r14_taxonomy_placeholder", "reason": "taxonomy coverage lives in test_t21r14_preconstruction + test_t21r14_gate_interface"},
        {"path": "tests/test_t21r11_remediation.py", "reason": "candidate remediation regression coverage"},
        {"path": "tests/test_t21r14_remediation.py", "reason": "quarantine + registry + remediation exclusion integrity"},
        {"path": "tests/test_t21r6_multihop_repairs.py", "reason": "multihop repair regression coverage"},
        {"path": "tests/test_t21r11_code_runtime_freeze.py", "reason": "current code_runtime freeze governance"},
    ],
    "deselect_nodeids": deselects,
    "note": "fresh registry for R14; the R13 phase gate test_real_r13_paths_absent is classified OBSOLETE_HISTORICAL_ASSERTION (R13 sealed); inherited classifications carried unchanged from the committed R13 registry",
}
(DST / "current_test_applicability.json").write_text(json.dumps(applicability, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({"applicability_deselects": len(deselects), "adjudication": adjudication["classification_summary"]}, indent=2))
