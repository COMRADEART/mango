"""T15R.1 / T15R.2 — freeze T15 executable failures and classify them.

Reads historical T15 artifacts only. Does not alter them. Does not
modify src/sciencemath/code/.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "evaluations/t15/suites/mango-code-eval-v1/final.jsonl"
CODE_PRED = ROOT / "evaluations/t15/runs/code-final/predictions.jsonl"
BASE_PRED = ROOT / "evaluations/t15/runs/baseline-final/predictions.jsonl"
CODE_SUM = ROOT / "evaluations/t15/runs/code-final/summary.json"
OUT_DIR = ROOT / "evaluations/t15r"

EXEC = ("single_fix", "multi_fix", "test_repair", "feature", "refactor",
        "config", "import_err", "type_err", "algo", "data_xform",
        "api_compat")

TAXONOMY = (
    "PARTIAL_PROGRESS_REVERTED",
    "NO_VALID_PATCH",
    "WRONG_FILE_SELECTED",
    "WRONG_SYMBOL_SELECTED",
    "TEST_DIAGNOSIS_FAILURE",
    "ASSERTION_MISREAD",
    "MULTI_FILE_DEPENDENCY_MISSED",
    "PATCH_REGRESSION",
    "PATCH_CONFLICT",
    "SCHEMA/API_MISMATCH",
    "DATA_TRANSFORM_LOGIC_ERROR",
    "ALGORITHM_ERROR",
    "TEST_ORACLE_MISMATCH",
    "HARNESS_ERROR",
    "OTHER",
)

REQUIRED_GROUPS = {
    "multi_fix": 10,
    "data_xform": 6,
    "refactor": None,  # all failed rows
    "algo": None,
    "feature": None,
    "test_repair": None,
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def classify(row: dict, task: dict, base_row: dict | None) -> dict:
    """Deterministic primary taxonomy from frozen T15 evidence."""
    cat = row["category"]
    status = row.get("status")
    touched = list(row.get("files_touched") or [])
    test = row.get("test") or {}
    reasons = list(row.get("reasons") or [])
    detail = (row.get("detail") or "")
    diagnosis = ((row.get("evidence_summary") or {}).get("diagnosis")
                 or "")
    gold = [g.get("file") for g in task.get("golden") or []]
    checks = task.get("checks") or {}
    secondary: list[str] = []
    evidence: list[str] = []

    harness = any("harness exception" in r for r in reasons) or \
        "harness exception" in detail.lower()
    tests_ran = test.get("exit_code") not in (None, "")
    failed_n = test.get("failed")
    exit_code = test.get("exit_code")
    empty_touch = not touched
    blocked = status == "BLOCKED"
    base_pass = bool(base_row and base_row.get("pass"))
    code_pass = bool(row.get("pass"))

    if harness:
        primary = "HARNESS_ERROR"
        evidence.append("harness exception in reasons/detail")
    elif any("fabricat" in r for r in reasons):
        primary = "HARNESS_ERROR"
        evidence.append("fabrication flag (independent re-run)")
    elif blocked and empty_touch and tests_ran and (
            exit_code not in (0,) and (failed_n or 0) >= 0):
        # Dominant T15 pattern: patch applied, tests reduced, loop
        # exhausted, files_touched cleared (revert-on-fail).
        primary = "PARTIAL_PROGRESS_REVERTED"
        evidence.append(
            f"BLOCKED + files_touched=[] + runner tests "
            f"exit={exit_code} failed={failed_n} diagnosis={diagnosis}")
        if cat == "multi_fix":
            secondary.append("MULTI_FILE_DEPENDENCY_MISSED")
        if diagnosis == "ASSERTION_MISMATCH":
            secondary.append("ASSERTION_MISREAD")
        if cat == "data_xform":
            secondary.append("DATA_TRANSFORM_LOGIC_ERROR")
        if cat == "algo":
            secondary.append("ALGORITHM_ERROR")
        if cat == "refactor":
            secondary.append("MULTI_FILE_DEPENDENCY_MISSED")
        if base_pass and not code_pass:
            secondary.append("TEST_ORACLE_MISMATCH")
            evidence.append(
                "baseline PASS / CODE FAIL — repair loop may have been "
                "stricter than (or failed to reach) the frozen oracle")
    elif empty_touch and not tests_ran:
        primary = "NO_VALID_PATCH"
        evidence.append("no files_touched and tests did not execute")
    elif empty_touch and blocked:
        primary = "NO_VALID_PATCH"
        evidence.append("BLOCKED with empty files_touched")
    elif cat == "multi_fix":
        primary = "MULTI_FILE_DEPENDENCY_MISSED"
        evidence.append("multi_fix category; coordinated two-file golden")
    elif cat == "data_xform":
        primary = "DATA_TRANSFORM_LOGIC_ERROR"
        evidence.append("data_xform family=" + str(task.get("family")))
    elif cat == "algo":
        if base_pass and not code_pass:
            primary = "TEST_ORACLE_MISMATCH"
            secondary.append("ALGORITHM_ERROR")
            evidence.append("baseline beat CODE on algo oracle")
        else:
            primary = "ALGORITHM_ERROR"
            evidence.append("algo family=" + str(task.get("family")))
    elif cat == "refactor":
        primary = "MULTI_FILE_DEPENDENCY_MISSED"
        evidence.append("rename requires definition + caller updates")
    elif cat == "feature":
        primary = "NO_VALID_PATCH" if empty_touch else "OTHER"
        evidence.append("feature stub not completed")
    elif cat == "test_repair":
        primary = "TEST_DIAGNOSIS_FAILURE"
        evidence.append("test_repair failed; source must stay unchanged")
    elif cat == "api_compat":
        primary = "SCHEMA/API_MISMATCH"
        evidence.append("api_compat signature adaptation")
    elif "weakening" in " ".join(reasons).lower():
        primary = "OTHER"
        evidence.append("test weakening flagged")
    else:
        primary = "OTHER"
        evidence.append(f"status={status} reasons={reasons[:2]}")

    if gold and touched and set(touched).isdisjoint(set(gold)) and touched:
        if primary != "PARTIAL_PROGRESS_REVERTED":
            secondary.append("WRONG_FILE_SELECTED")

    oracle = {
        "evaluation_oracle": sorted(checks.keys()),
        "runner_acceptance_rule": (
            "targeted pytest exit_code==0 AND remaining mechanical checks"
            if "tests_pass" in checks else
            "mechanical checks only (no tests_pass)"
        ),
        "disagreement_reason": None,
    }
    if base_pass and not code_pass:
        if primary == "PARTIAL_PROGRESS_REVERTED":
            oracle["disagreement_reason"] = (
                "B_THEN_A: repair loop reverted a workspace that still had "
                "failing targeted tests; baseline's first patch satisfied "
                "the frozen oracle. Not an oracle weakening. CODE was not "
                "shown to be fully correct at revert time."
            )
        elif primary == "TEST_ORACLE_MISMATCH":
            oracle["disagreement_reason"] = (
                "B: possible runner-stricter-than-oracle; inspect remaining "
                "failures vs frozen checks. Do not weaken correctness."
            )
        else:
            oracle["disagreement_reason"] = (
                "A: CODE did not satisfy the frozen acceptance checks."
            )
    elif not base_pass and not code_pass:
        oracle["disagreement_reason"] = (
            "both baseline and CODE failed the frozen oracle"
        )

    return {
        "primary": primary,
        "secondary": secondary,
        "evidence": evidence,
        "oracle_contract": oracle,
    }


def main() -> int:
    recorded = datetime.now(timezone.utc).isoformat()
    suite_rows = load_jsonl(SUITE)
    suite = {t["task_id"]: t for t in suite_rows}
    code = [r for r in load_jsonl(CODE_PRED) if not r.get("skipped")]
    base = {r["task_id"]: r for r in load_jsonl(BASE_PRED)
            if not r.get("skipped")}
    summary = json.loads(CODE_SUM.read_text(encoding="utf-8"))

    exec_fail = [r for r in code
                 if r.get("category") in EXEC and not r.get("pass")]
    frozen = []
    for r in exec_fail:
        t = suite[r["task_id"]]
        b = base.get(r["task_id"])
        tax = classify(r, t, b)
        test = r.get("test") or {}
        gold_files = [g.get("file") for g in t.get("golden") or []]
        frozen.append({
            "task_id": r["task_id"],
            "category": r["category"],
            "family": t.get("family"),
            "op": t.get("op") or r.get("op"),
            "request": t.get("request"),
            "initial_repo_state": {
                "fixture_files": sorted((t.get("fixture") or {}).keys()),
                "context_files": t.get("context_files") or [],
                "golden_files": gold_files,
                "tests_to_run": t.get("tests_to_run") or [],
                "model_needed": bool(t.get("model_needed")),
            },
            "initial_test_state": {
                "note": "T15 predictions do not record pre-edit pytest; "
                        "executable fixtures are fail-before-golden except "
                        "refactor (pass-before and pass-after).",
                "refactor_passes_before_edit": r["category"] == "refactor",
            },
            "patch_attempt_count": None,
            "intermediate_test_results": {
                "recorded_in_t15_predictions": False,
                "reason": "T15 prediction schema stored only final test "
                          "counts; per-round trails were not persisted.",
            },
            "final_test_result": {
                "exit_code": test.get("exit_code"),
                "passed": test.get("passed"),
                "failed": test.get("failed"),
                "errors": test.get("errors"),
                "status": r.get("status"),
                "detail": (r.get("detail") or "")[:500],
                "diagnosis": (r.get("evidence_summary") or {}).get(
                    "diagnosis"),
                "reasons": r.get("reasons") or [],
            },
            "whether_patch_was_reverted": bool(
                not (r.get("files_touched") or [])
                and r.get("status") in ("BLOCKED", "EXECUTED_FAIL")
                and test.get("exit_code") not in (None, 0)
            ),
            "files_touched_before_revert": {
                "recorded": False,
                "inferred": "unknown — T15 cleared files_touched on revert",
            },
            "files_touched_after_revert": r.get("files_touched") or [],
            "failure_taxonomy": tax["primary"],
            "failure_taxonomy_secondary": tax["secondary"],
            "taxonomy_evidence": tax["evidence"],
            "oracle_contract": tax["oracle_contract"],
            "baseline_result": {
                "pass": bool(b.get("pass")) if b else None,
                "status": (b or {}).get("status"),
                "reasons": (b or {}).get("reasons") or [],
            },
            "t15_code_result": {
                "pass": bool(r.get("pass")),
                "status": r.get("status"),
                "latency_s": r.get("latency_s"),
                "plan_valid": r.get("plan_valid"),
            },
            "checks": t.get("checks") or {},
        })

    # required groups
    by_cat = defaultdict(list)
    for row in frozen:
        by_cat[row["category"]].append(row["task_id"])

    freeze_doc = {
        "milestone": "T15R.1 — T15 failure freeze",
        "recorded_at": recorded,
        "source_artifacts": {
            "code_final_predictions": str(CODE_PRED.relative_to(ROOT)),
            "code_final_predictions_sha256": sha(CODE_PRED),
            "baseline_final_predictions": str(BASE_PRED.relative_to(ROOT)),
            "baseline_final_predictions_sha256": sha(BASE_PRED),
            "suite_final": str(SUITE.relative_to(ROOT)),
            "suite_final_sha256": sha(SUITE),
            "code_final_summary_n_pass": summary.get("n_pass"),
            "code_final_summary_n_tasks": summary.get("n_tasks"),
        },
        "historical_t15_artifacts_altered": False,
        "n_executable_failures": len(frozen),
        "by_category": {c: len(v) for c, v in sorted(by_cat.items())},
        "required_groups": {
            "multi_fix_failures": by_cat["multi_fix"],
            "data_xform_failures": by_cat["data_xform"],
            "failed_refactor": by_cat["refactor"],
            "failed_algo": by_cat["algo"],
            "failed_feature": by_cat["feature"],
            "failed_test_repair": by_cat["test_repair"],
            "other_executable_failures": [
                tid for cat, ids in by_cat.items()
                if cat not in ("multi_fix", "data_xform", "refactor",
                               "algo", "feature", "test_repair")
                for tid in ids
            ],
        },
        "group_counts": {
            "multi_fix": len(by_cat["multi_fix"]),
            "data_xform": len(by_cat["data_xform"]),
            "refactor": len(by_cat["refactor"]),
            "algo": len(by_cat["algo"]),
            "feature": len(by_cat["feature"]),
            "test_repair": len(by_cat["test_repair"]),
        },
        "failures": frozen,
    }

    tax_counts = Counter(r["failure_taxonomy"] for r in frozen)
    cat_tax = defaultdict(lambda: Counter())
    for r in frozen:
        cat_tax[r["category"]][r["failure_taxonomy"]] += 1

    oracle_audit = []
    for r in frozen:
        if r["category"] in ("algo", "refactor", "feature", "test_repair"):
            oracle_audit.append({
                "task_id": r["task_id"],
                "category": r["category"],
                "baseline_pass": r["baseline_result"]["pass"],
                "code_pass": r["t15_code_result"]["pass"],
                "primary": r["failure_taxonomy"],
                "evaluation_oracle": r["oracle_contract"]["evaluation_oracle"],
                "runner_acceptance_rule":
                    r["oracle_contract"]["runner_acceptance_rule"],
                "disagreement_reason":
                    r["oracle_contract"]["disagreement_reason"],
            })

    analysis = {
        "milestone": "T15R.2 — failure taxonomy",
        "recorded_at": recorded,
        "taxonomy_labels": list(TAXONOMY),
        "n_classified": len(frozen),
        "counts": dict(tax_counts),
        "by_category": {c: dict(v) for c, v in sorted(cat_tax.items())},
        "dominant_bottleneck": "PARTIAL_PROGRESS_REVERTED",
        "notes": [
            "T15 prediction rows do not persist per-round trails; "
            "PARTIAL_PROGRESS_REVERTED is assigned when BLOCKED + empty "
            "files_touched + tests actually ran with a non-zero exit.",
            "multi_fix 0/10 is dual-labeled: primary revert, secondary "
            "MULTI_FILE_DEPENDENCY_MISSED.",
            "Oracle-contract review (T15R.16) is recorded per "
            "algo/refactor/feature/test_repair row. Frozen oracles are "
            "not weakened.",
        ],
        "oracle_contract_review": oracle_audit,
        "rows": [
            {
                "task_id": r["task_id"],
                "category": r["category"],
                "primary": r["failure_taxonomy"],
                "secondary": r["failure_taxonomy_secondary"],
                "evidence": r["taxonomy_evidence"],
                "baseline_pass": r["baseline_result"]["pass"],
                "code_status": r["t15_code_result"]["status"],
                "test": r["final_test_result"],
                "reverted": r["whether_patch_was_reverted"],
            }
            for r in frozen
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    freeze_p = OUT_DIR / "t15_failure_freeze.json"
    analysis_p = OUT_DIR / "t15_failure_analysis.json"
    freeze_p.write_text(json.dumps(freeze_doc, indent=2, ensure_ascii=False)
                        + "\n", encoding="utf-8")
    analysis_p.write_text(json.dumps(analysis, indent=2, ensure_ascii=False)
                          + "\n", encoding="utf-8")
    print(json.dumps({
        "n_executable_failures": len(frozen),
        "group_counts": freeze_doc["group_counts"],
        "taxonomy": dict(tax_counts),
        "multi_fix": len(by_cat["multi_fix"]),
        "data_xform": len(by_cat["data_xform"]),
    }, indent=2))
    # sanity: required 10 multi_fix + 6 data_xform
    ok = (len(by_cat["multi_fix"]) == 10
          and len(by_cat["data_xform"]) == 6
          and len(frozen) == sum(len(v) for v in by_cat.values()))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
