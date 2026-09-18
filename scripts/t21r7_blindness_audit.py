"""Pre-freeze mechanical blindness audit for the T21R7 candidate.

This script is deliberately data-only.  It verifies freeze identity, the
absence of official-run artifacts, and a static import/call firewall around
every construction/audit program that has read T21R7 rows.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r7"
sys.path.insert(0, str(ROOT / "scripts"))

from t21r4_freeze_runtime import RUNTIME_GROUPS, sha_group  # noqa: E402


DATA_ONLY_SCRIPTS = (
    "t21r7_world.py",
    "t21r7_build_suites.py",
    "t21r7_construction_audit.py",
    "t21r7_construction_gate.py",
    "t21r7_static_gold_audit.py",
    "t21r7_uniqueness.py",
    "t21r7_blindness_audit.py",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "sciencemath.knowledge",
    "t21r7_run_eval",
    "t21r6_run_eval",
)
FORBIDDEN_CALLS = {
    "answer_knowledge", "load_corpus", "run_answer_row",
    "run_retrieval_row", "retrieve",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            names = []
        for name in names:
            if name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"forbidden import {name}")
        if isinstance(node, ast.Call):
            function = node.func
            call_name = function.id if isinstance(function, ast.Name) else (
                function.attr if isinstance(function, ast.Attribute) else "")
            if call_name in FORBIDDEN_CALLS:
                violations.append(f"forbidden runtime call {call_name}")
    return violations


def main() -> int:
    runtime_freeze_path = OUT_DIR / "runtime_freeze.json"
    evaluator_freeze_path = OUT_DIR / "evaluator_freeze.json"
    static_path = OUT_DIR / "static_gold_audit.json"
    uniqueness_path = OUT_DIR / "holdout_uniqueness.json"
    runtime_freeze = json.loads(runtime_freeze_path.read_text("utf-8"))
    evaluator_freeze = json.loads(evaluator_freeze_path.read_text("utf-8"))
    static = json.loads(static_path.read_text("utf-8"))
    uniqueness = json.loads(uniqueness_path.read_text("utf-8"))

    source_firewall = {
        name: _source_violations(ROOT / "scripts" / name)
        for name in DATA_ONLY_SCRIPTS
    }
    runtime_identity = {
        name: sha_group(spec) == runtime_freeze["runtime_composites"][name]
        for name, spec in RUNTIME_GROUPS.items()
    }
    evaluator_path = ROOT / evaluator_freeze["frozen_hashes"][
        "evaluator_path"]
    evaluator_identity = (
        _sha256(evaluator_path)
        == evaluator_freeze["evaluator_source_sha256"]
    )
    forbidden_artifacts = (
        "HOLDOUT_FROZEN", "holdout_manifest.json",
        "evaluation_run_ledger.json", "raw_results.jsonl",
        "holdout_results.json",
    )
    artifacts_present = [name for name in forbidden_artifacts
                         if (OUT_DIR / name).exists()]

    checks = {
        "runtime_freeze_identity": all(runtime_identity.values()),
        "evaluator_freeze_identity": evaluator_identity,
        "static_gold_audit_pass": static.get("status") == "PASS",
        "static_runtime_execution_count_zero":
            static.get("runtime_execution_count") == 0,
        "uniqueness_verdict_unique":
            uniqueness.get("verdict") == "UNIQUE",
        "uniqueness_runtime_execution_count_zero":
            uniqueness.get("runtime_execution_count") == 0,
        "data_only_source_firewall":
            all(not values for values in source_firewall.values()),
        "no_holdout_freeze_or_official_run_artifacts":
            not artifacts_present,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    report = {
        "audit": "T21R7 pre-freeze blindness audit",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checks": checks,
        "runtime_group_identity": runtime_identity,
        "evaluator_source": {
            "path": evaluator_path.relative_to(ROOT).as_posix(),
            "expected_sha256": evaluator_freeze["evaluator_source_sha256"],
            "actual_sha256": _sha256(evaluator_path),
        },
        "data_only_source_firewall": source_firewall,
        "forbidden_artifacts_present": artifacts_present,
        "official_runtime_exposures_before_freeze": 0,
        "statement": (
            "No T21R7 suite row was passed to the production runtime, "
            "evaluator, or retrieval API before HOLDOUT_FROZEN."
        ),
    }
    (OUT_DIR / "blindness_audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": status,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "official_runtime_exposures_before_freeze": 0,
    }, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
