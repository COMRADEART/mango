"""AST firewall for the real T21R13 blind builders and static auditors."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "evaluations" / "t21r13"
SCRIPTS = (
    "t21r13_world.py",
    "t21r13_build_suites.py",
    "t21r13_retrieval_mirror.py",
    "t21r13_construction_audit.py",
    "t21r13_construction_gate.py",
    "t21r13_static_semantics.py",
    "t21r13_static_gold_audit.py",
    "t21r13_uniqueness.py",
)
BUILDER_SCRIPTS = {"t21r13_world.py", "t21r13_build_suites.py"}
FORBIDDEN_MODULE_FRAGMENTS = (
    "sciencemath", "pipeline", "router", "retrieval", "evidence_paths",
    "relations", "conflicts", "citation", "injection", "run_eval",
)
ALLOWED_LOCAL_RETRIEVAL = "t21r13_retrieval_mirror"
FORBIDDEN_CALLS = {
    "answer_knowledge", "resolve_path", "retrieve_structured",
    "run_answer_row", "evaluate", "official_evaluation",
}


def audit_scripts(root: Path = ROOT) -> dict:
    violations: list[str] = []
    hashes: dict[str, str] = {}
    leakage = {
        "candidate_implementation": [],
        "historical_blind": [],
        "remediation_validation": [],
    }
    import hashlib
    for name in SCRIPTS:
        path = root / "scripts" / name
        if not path.is_file():
            violations.append(f"missing preregistered script: {name}")
            continue
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if name in BUILDER_SCRIPTS:
            lowered = source.casefold()
            checks = {
                "candidate_implementation": (
                    "src/sciencemath/knowledge", "answer_knowledge",
                    "decision_trace"),
                "historical_blind": (
                    "gk_holdout_t21r10", "evaluations/t21r10/suites",
                    "raw_results.jsonl"),
                "remediation_validation": (
                    "t21r13_diagnostics", "test_t21r13_remediation",
                    "after_validation"),
            }
            for category, markers in checks.items():
                for marker in markers:
                    if marker in lowered:
                        leakage[category].append(f"{name}:{marker}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            else:
                imports = []
            for imported in imports:
                if imported == ALLOWED_LOCAL_RETRIEVAL:
                    continue
                if any(fragment in imported
                       for fragment in FORBIDDEN_MODULE_FRAGMENTS):
                    violations.append(f"{name}: forbidden import {imported}")
            if isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else \
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if called in FORBIDDEN_CALLS:
                    violations.append(f"{name}: forbidden call {called}")
    for category, findings in leakage.items():
        violations.extend(f"{category} leakage: {value}"
                          for value in findings)
    return {
        "artifact": "T21R13_BLINDNESS_AUDIT",
        "status": "PASS" if not violations else "FAIL",
        "scripts": hashes,
        "forbidden_modules": list(FORBIDDEN_MODULE_FRAGMENTS),
        "forbidden_calls": sorted(FORBIDDEN_CALLS),
        "candidate_leakage": leakage["candidate_implementation"],
        "historical_blind_leakage": leakage["historical_blind"],
        "remediation_validation_leakage": leakage["remediation_validation"],
        "violations": violations,
        "runtime_execution_count": 0,
    }


def main() -> int:
    report = audit_scripts()
    path = OUT_DIR / "holdout_blindness.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

