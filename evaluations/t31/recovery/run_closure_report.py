"""T31 closure: render the report, decide the gates, write everything.

Invocation (repo root, PYTHONPATH=src):
    python evaluations/t31/recovery/run_closure_report.py

This is the exact script that produced evaluations/t31/reports/ and
gates.json for the recovered run; it is kept inside the pack and hashed so
the report-rendering step is reproducible like every other step.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "src")

root = Path(".")
BASE = "d25d4574bcfe1634f91bce435efd75566fba8f7d"
FINAL = "58e911f484928e1e3da6d4fd9f888d96373af6df"

tests = {
    "passed": 4441, "failed": 51, "errors": 11, "skipped": 1,
    "suites": {
        "full battery (python -m pytest, repo root, unmodified)": (
            "4,504 tests: 4,441 passed, 51 failed, 11 errors, 1 skipped; "
            "log evaluations/t31/recovery/measured_tests.txt, junit "
            "evaluations/t31/recovery/t31_measured_tests_junit.xml"),
        "attribution of the 51 failures + 11 errors": (
            "23 legacy tracked suites, every failure reproduced in a "
            "pristine git worktree at the T31 base commit d25d457 - "
            "identical files, identical per-file counts; no failing test "
            "belongs to a T31-comparability module - see "
            "evaluations/t31/recovery/T31_TRACKED_SUITE_CLASSIFICATION.json"),
        "tests/test_t23_construction_remediation.py": (
            "11 errors at module-fixture setup: run_shadow_construction "
            "raises ValueError('historical T23 freeze changed') - a "
            "historical-identity recheck; pre-existing at d25d457"),
        "tests/test_t26_evaluation_v2.py": (
            "2 failures re-verifying the T26 V3 244-component byte freeze "
            "against the live repository: the pin was written by 9fdfe2a "
            "(2026-09-26) and one pinned file (integration runner) changed "
            "under 8caf8d0 (2026-09-27) - pre-existing at d25d457"),
        "tests/test_t31_concurrency.py": (
            "1 failure - untracked state-engine work-in-progress "
            "(StateStoreError under thread contention); outside this "
            "deliverable, has no baseline at the base commit, excluded "
            "from the regression record, disclosed"),
        "tests/test_t31_history.py": (
            "1 failure - untracked state-engine work-in-progress, "
            "order-dependent (passes in isolation); outside this "
            "deliverable, disclosed"),
        "tests/test_t31_comparability_*.py + resume suite": (
            "all green; the one skip is the T31_REAL_DATASETS=1 guard in "
            "test_t31_comparability_loading.py - verified green with the "
            "guard set"),
    },
}

regression = {
    "passed": 3221, "failed": 0, "skipped": 0,
    "note": (
        "Measured over the 128 tracked test modules (of the 151 tracked "
        "ones the battery collected) that were green in the battery, run "
        "unchanged against the T31 working tree: 3,221 tests, zero "
        "failures, zero errors. The 23 legacy suites whose 49 failures + "
        "11 setup errors pre-exist at the base commit d25d457 are not "
        "T31 regressions, proven by reproducing the identical per-file "
        "failure set in a pristine worktree at d25d457 (T31 files absent); "
        "their totals are recorded under Tests. The 34 new untracked T31 "
        "modules also have no baseline at the base commit and are "
        "excluded from the record but disclosed under Tests."),
}

AUDIT_RULE = (
    "The original T31 benchmark process was interrupted during the adapter "
    "SciQ arm after 320/1000 persisted rows. The remaining 680 adapter SciQ "
    "items were completed using the frozen configuration and a verified "
    "missing-ID-only resume path. Previously completed model outputs were "
    "not regenerated.")

limitations = [
    f"Interrupted run and resume, verbatim: {AUDIT_RULE} The recovery is "
    "documented in evaluations/t31/recovery/ "
    "(T31_PRERESUME_PRESERVATION.json, T31_RESUME_RECOVERY_RECORD.json "
    "with recovery_status ALL_DONE_AFTER_RESUME, six directed resume tests "
    "tests/test_t31_resume_recovery.py). The adapter SciQ arm is therefore "
    "not a single uninterrupted generation of 1,000 rows: 320 rows are "
    "from the original run, 680 from the resumed run, all under the "
    "verified frozen configuration (config hash unchanged, per-row prompt "
    "verification 12,054/12,054, adapter weights sha256 re-verified).",
    "The recovery directive stated 11,054 existing rows; its own per-file "
    "counts sum to 12,054 (6,367 base + 5,687 adapter), which the disk "
    "matched exactly. All rows the directive intended (all but the 680 "
    "missing adapter SciQ items) were present; 12,054 + 680 = 12,734. "
    "Disk evidence is authoritative.",
    "Scorer defect found and repaired BEFORE the scored layer existed: the "
    "first scoring run crashed on the first MATH-500 row when sympify of a "
    "bare word resolved a sympy namespace object (for example 'Ellipse' to "
    "a class) whose __eq__ raises TypeError. The comparison was wrapped in "
    "the same decide-or-fallback contract as the rest of the symbolic tier "
    "(an engine that raises cannot decide; the row falls back to string "
    "comparison and records the fallback tier). Two regression tests pin "
    "the repair; no previously scored artifact existed to regenerate "
    "because the interrupted session never reached scoring; raw "
    "generations are untouched; the rule is symmetric across both arms by "
    "construction.",
    "Environment drift since the frozen record is confined to the OS "
    "platform build string (Windows-11-10.0.26200 -> 10.0.26300). Python, "
    "torch, transformers, datasets, peft, CUDA runtime and GPU are "
    "identical to the frozen record.",
    "The full pytest battery contains 51 failures and 11 collection "
    "errors confined to legacy suites, all proven pre-existing at the T31 "
    "base commit by clean-worktree replication (identical files and "
    "per-file counts at d25d457 with zero T31 files in the tree); the "
    "regression gate is evaluated over the tracked-and-green record above "
    "instead of misattributing them to T31.",
    "The untracked state-engine work-in-progress (src/sciencemath/"
    "state_engine/ and its suites) is a separate work stream outside this "
    "deliverable; its two failing tests are disclosed under Tests and it "
    "is not committed with this closure.",
    "The Mango Integrated System was not re-run; the frozen T30 record's "
    "runtime figures are cited in the top-level README rather than "
    "re-measured here.",
    "Contamination is measured, not zero: 5 of the 12,734 evaluated items "
    "overlap the training corpus (1 sciq, 4 arc_easy); the disclosure "
    "table above carries the per-benchmark interpretation.",
]

commands = [
    "PYTHONPATH=src python -m sciencemath.comparability --root . run --arm both",
    "PYTHONPATH=src python -m sciencemath.comparability --root . run --arm adapter --benchmark sciq",
    "PYTHONPATH=src python -m sciencemath.comparability --root . score",
    "PYTHONPATH=src python -m sciencemath.comparability --root . analyse",
    "PYTHONPATH=src python -m sciencemath.comparability --root . contamination",
    ("PYTHONPATH=src python -m sciencemath.comparability --root . report "
     "--branch t31-public-comparability --base-commit d25d4574bcfe1634f91b"
     "ce435efd75566fba8f7d --final-commit 58e911f484928e1e3da6d4fd9f888d9"
     "6373af6df"),
    "PYTHONPATH=src python -m sciencemath.comparability --root . manifest",
    "PYTHONPATH=src python -m sciencemath.comparability --root . verify",
    ("PYTHONPATH=src python -m pytest tests/test_t31_comparability_runner.py"
     " tests/test_t31_comparability_rows.py tests/test_t31_comparability_"
     "pipeline.py tests/test_t31_resume_recovery.py"),
]


def main() -> int:
    from sciencemath.comparability import pipeline as P

    result = P.build_report(
        root, branch="t31-public-comparability", base_commit=BASE,
        final_commit=FINAL, tests=tests, regression=regression,
        limitations=limitations, commands=commands)
    print("STATUS:", result["status"])
    for gate in result["gates"]:
        print(f"  {gate['gate']:<9} {gate['status']:<14} {gate['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())